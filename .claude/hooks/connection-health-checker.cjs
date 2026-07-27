#!/usr/bin/env node
'use strict';
/**
 * Connection Health Checker
 *
 * Runs at session start at most once per day. Reads the connection manager's
 * local-only health sweep, silently repairs refreshable expired OAuth
 * connections, and surfaces a short note only for connections still expired
 * or needing reauthentication.
 *
 * ALWAYS exits 0. Missing vaults, missing engine files, and read/write errors
 * are silent so this can never block a session start.
 *
 * Throttle state: {DEX_VAULT}/System/integrations/.connection-health-state.json
 */

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const CM_DIR = path.resolve(__dirname, '..', '..', 'core', 'integrations', 'connection-manager');
const STATUSES_TO_SURFACE = new Set(['needs_reauth', 'expired']);
const REPAIR_PASS_BUDGET_MS = 2_000;
const REFRESH_REQUEST_TIMEOUT_MS = 1_500;
const REFRESH_WORKER_ARG = '--connection-health-refresh-worker';

function configuredPaths() {
  const configuredVault = process.env.DEX_VAULT || process.env.VAULT_PATH;
  if (!configuredVault) return null;

  try {
    // Keep vault discovery aligned with the neighbouring hooks. DEX_VAULT is
    // also accepted by the connection manager, so mirror it into VAULT_PATH
    // for paths.cjs when that is the only configured name.
    if (!process.env.VAULT_PATH) process.env.VAULT_PATH = configuredVault;
    const { loadPaths } = require('./paths.cjs');
    const loaded = loadPaths();
    const vaultRoot = path.resolve(configuredVault);
    return {
      vaultRoot,
      systemDir:
        path.resolve(loaded.VAULT_ROOT) === vaultRoot
          ? loaded.SYSTEM_DIR
          : path.join(vaultRoot, 'System'),
    };
  } catch {
    return null;
  }
}

function stateFile(paths) {
  return path.join(paths.systemDir, 'integrations', '.connection-health-state.json');
}

function shouldCheck(file) {
  try {
    const state = JSON.parse(fs.readFileSync(file, 'utf8'));
    return state.lastCheck !== new Date().toISOString().slice(0, 10);
  } catch {
    return true;
  }
}

function saveCheckState(file, needsAttention) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(
      file,
      JSON.stringify(
        {
          lastCheck: new Date().toISOString().slice(0, 10),
          needsAttention,
        },
        null,
        2,
      ),
    );
  } catch {
    // The throttle is best-effort; a state write must never block startup.
  }
}

function isRefreshableExpired(row) {
  // health.cjs reports hasRefreshToken=false for every paste-a-key connection,
  // so this only selects expired OAuth entries with a usable refresh token.
  return Boolean(
    row &&
      row.status === 'expired' &&
      row.hasRefreshToken === true &&
      typeof row.service === 'string' &&
      row.service,
  );
}

async function refreshWorker(service) {
  const healthPath = path.join(CM_DIR, 'health.cjs');
  let health;
  let ok = false;
  try {
    health = require(healthPath);
    await health.refreshToken(service);
    ok = true;
  } catch {
    // The parent reports the connection's health; worker errors stay silent.
  }

  let rows = null;
  try {
    const refreshedRows = health && health.allConnectionsHealth();
    if (Array.isArray(refreshedRows)) rows = refreshedRows;
  } catch {
    // A failed post-refresh read falls back to the parent's previous rows.
  }

  try {
    process.stdout.write(JSON.stringify({ ok, rows }));
  } catch {
    // The parent treats missing worker output as a report-only fallback.
  }
}

function refreshInWorker(service, timeoutMs) {
  return new Promise((resolve) => {
    let settled = false;
    let timer;
    let stdout = '';
    let child;

    const finish = (result) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      resolve(result);
    };

    try {
      child = spawn(process.execPath, [__filename, REFRESH_WORKER_ARG, service], {
        cwd: process.cwd(),
        env: process.env,
        stdio: ['ignore', 'pipe', 'ignore'],
      });
    } catch {
      finish({ ok: false, rows: null });
      return;
    }

    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });
    child.once('error', () => finish({ ok: false, rows: null }));
    child.once('close', () => {
      try {
        const result = JSON.parse(stdout);
        finish({
          ok: result.ok === true,
          rows: Array.isArray(result.rows) ? result.rows : null,
        });
      } catch {
        finish({ ok: false, rows: null });
      }
    });

    timer = setTimeout(() => {
      try {
        child.kill('SIGKILL');
        child.stdout.destroy();
        child.unref();
      } catch {
        // The worker may already have exited between the timer and the kill.
      }
      finish({ ok: false, rows: null });
    }, timeoutMs);
  });
}

async function attemptAutoRepair(rows) {
  let currentRows = rows;
  const deadline = Date.now() + REPAIR_PASS_BUDGET_MS;
  const candidates = rows.filter(isRefreshableExpired);

  for (const candidate of candidates) {
    const remainingMs = deadline - Date.now();
    if (remainingMs <= 0) break;

    const result = await refreshInWorker(
      candidate.service,
      Math.min(REFRESH_REQUEST_TIMEOUT_MS, remainingMs),
    );

    if (result.rows) {
      currentRows = result.rows;
    } else if (result.ok) {
      // Guarded refresh completed, but the follow-up local sweep failed.
      // Silence the repaired row without making assumptions about any others.
      currentRows = currentRows.filter((row) => row.service !== candidate.service);
    }

    // A rejected, broken, or timed-out repair degrades to report-only. Do not
    // spend more of the session-start budget trying other connections.
    if (!result.ok) break;
  }

  return currentRows;
}

async function main() {
  const paths = configuredPaths();
  if (!paths) return;

  const healthPath = path.join(CM_DIR, 'health.cjs');
  if (!fs.existsSync(healthPath)) return;

  const file = stateFile(paths);
  if (!shouldCheck(file)) return;

  // Claim today's attempt before loading the engine. Even a damaged local
  // connection record must not make every session repeat the sweep.
  saveCheckState(file, false);

  let rows;
  try {
    const health = require(healthPath);
    rows = health.allConnectionsHealth() || [];
  } catch {
    return;
  }

  try {
    rows = await attemptAutoRepair(rows);
  } catch {
    // Any repair failure falls back to the original report-only rows.
  }

  const attention = rows.filter((row) => STATUSES_TO_SURFACE.has(row.status));
  if (attention.length) {
    console.log('--- Connections Need Attention ---');
    for (const row of attention) {
      const reason = row.status === 'expired' ? 'expired' : 'needs re-authentication';
      console.log(`${row.service} — ${reason}. Run /connect ${row.service} to reconnect.`);
    }
    console.log('---\n');
  }

  saveCheckState(file, attention.length > 0);
}

async function run() {
  try {
    if (process.argv[2] === REFRESH_WORKER_ARG) {
      await refreshWorker(process.argv[3]);
      return;
    }
    await main();
  } catch {
    // SessionStart hooks are advisory. Fail open and stay silent.
  }
}

run().finally(() => {
  process.exitCode = 0;
});
