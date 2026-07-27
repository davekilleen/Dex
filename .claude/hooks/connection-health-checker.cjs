#!/usr/bin/env node
'use strict';
/**
 * Connection Health Checker
 *
 * Runs at session start at most once per day. Reads the connection manager's
 * local-only health sweep and surfaces a short note only when a connection is
 * expired or needs reauthentication.
 *
 * ALWAYS exits 0. Missing vaults, missing engine files, and read/write errors
 * are silent so this can never block a session start.
 *
 * Throttle state: {DEX_VAULT}/System/integrations/.connection-health-state.json
 */

const fs = require('fs');
const path = require('path');

const CM_DIR = path.resolve(__dirname, '..', '..', 'core', 'integrations', 'connection-manager');
const STATUSES_TO_SURFACE = new Set(['needs_reauth', 'expired']);

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

function main() {
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

try {
  main();
} catch {
  // SessionStart hooks are advisory. Fail open and stay silent.
}
process.exitCode = 0;
