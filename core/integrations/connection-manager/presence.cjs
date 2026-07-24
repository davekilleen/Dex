'use strict';

const { spawn } = require('node:child_process');

const DEFAULT_TTL_MS = 60_000;
const DEFAULT_TIMEOUT_MS = 30_000;
const grants = new Map();
const inFlightChecks = new Map();

/**
 * B1 user-presence policy.
 *
 * `connect` is the synthetic operation used by connect.cjs for the first
 * credential save. Rendered credentials and default token access deliberately
 * remain silent so background sync keeps working.
 */
function requiresPresence(op) {
  return op === 'access-token' || op === 'full' || op === 'connect';
}

function presenceRequiredError() {
  const error = new Error('User presence is required for this credential operation.');
  error.code = 'DEX_CM_PRESENCE_REQUIRED';
  error.category = 'presence_required';
  return error;
}

function configuredMs(name, fallback) {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function currentTime(now) {
  return typeof now === 'function' ? now() : now == null ? Date.now() : Number(now);
}

function splitCommand(value) {
  const argv = [];
  let current = '';
  let quote = null;
  let escaped = false;
  let started = false;
  for (const char of String(value || '')) {
    if (escaped) {
      current += char;
      escaped = false;
      started = true;
    } else if (char === '\\' && quote !== "'") {
      escaped = true;
      started = true;
    } else if (quote) {
      if (char === quote) quote = null;
      else current += char;
      started = true;
    } else if (char === '"' || char === "'") {
      quote = char;
      started = true;
    } else if (/\s/.test(char)) {
      if (started) {
        argv.push(current);
        current = '';
        started = false;
      }
    } else {
      current += char;
      started = true;
    }
  }
  if (escaped || quote) return [];
  if (started) argv.push(current);
  return argv;
}

function commandProvider(commandValue) {
  const argv = splitCommand(commandValue);
  if (!argv.length || !argv[0]) {
    return { available: false, reason: 'DEX_CM_PRESENCE_CMD could not be parsed into a command.' };
  }
  return {
    available: true,
    kind: 'command',
    verify() {
      return new Promise((resolve) => {
        let settled = false;
        let timer;
        let child;
        const finish = (approved) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          resolve(approved);
        };
        try {
          child = spawn(argv[0], argv.slice(1), {
            shell: false,
            stdio: 'ignore',
          });
        } catch {
          finish(false);
          return;
        }
        child.once('error', () => finish(false));
        child.once('exit', (code) => finish(code === 0));
        timer = setTimeout(() => {
          child.kill('SIGKILL');
          finish(false);
        }, configuredMs('DEX_CM_PRESENCE_TIMEOUT_MS', DEFAULT_TIMEOUT_MS));
      });
    },
  };
}

function unavailableProvider(reason) {
  return { available: false, kind: 'unavailable', reason };
}

/**
 * This module cannot honestly create a Touch ID prompt by itself: macOS
 * requires an OS-signed application/helper to make that claim meaningful. The
 * desktop app supplies that helper through DEX_CM_PRESENCE_CMD. A plain dialog
 * would be theatre, so the built-in Darwin adapter is deliberately unavailable.
 */
function resolveProvider() {
  if (process.env.DEX_CM_PRESENCE_CMD) return commandProvider(process.env.DEX_CM_PRESENCE_CMD);
  if (process.platform === 'darwin') {
    return unavailableProvider(
      'Real biometric presence requires the Dex-signed helper configured by DEX_CM_PRESENCE_CMD.'
    );
  }
  return unavailableProvider('OS user presence is unavailable on this platform without DEX_CM_PRESENCE_CMD.');
}

async function assertPresence(connId, op, { provider, now } = {}) {
  if (!requiresPresence(op)) return;
  const checkedAt = currentTime(now);
  const grantExpiresAt = grants.get(connId);
  if (Number.isFinite(grantExpiresAt) && checkedAt < grantExpiresAt) return;
  grants.delete(connId);

  provider = provider || resolveProvider();
  if (!provider || provider.available === false || typeof provider.verify !== 'function') {
    if (process.env.DEX_CM_PRESENCE_OPTIONAL === '1') {
      console.error(
        `warning: user presence was NOT verified for ${connId}; ` +
          'DEX_CM_PRESENCE_OPTIONAL=1 explicitly allowed this headless/CI operation.'
      );
      return;
    }
    throw presenceRequiredError();
  }
  if (inFlightChecks.has(connId)) return inFlightChecks.get(connId);

  const check = (async () => {
    let approved = false;
    try {
      approved = (await provider.verify({ connId, op })) === true;
    } catch {
      approved = false;
    }
    if (!approved) throw presenceRequiredError();
    grants.set(connId, currentTime(now) + configuredMs('DEX_CM_PRESENCE_TTL_MS', DEFAULT_TTL_MS));
  })();
  inFlightChecks.set(connId, check);
  try {
    return await check;
  } finally {
    if (inFlightChecks.get(connId) === check) inFlightChecks.delete(connId);
  }
}

module.exports = { requiresPresence, assertPresence, resolveProvider };
