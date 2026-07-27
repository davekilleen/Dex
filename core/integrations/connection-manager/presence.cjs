'use strict';

const { spawn } = require('node:child_process');
const fs = require('node:fs');

const DEFAULT_TTL_MS = 60_000;
const DEFAULT_TIMEOUT_MS = 30_000;
const STANDALONE_PROVIDER = Object.freeze({ kind: 'standalone', standalone: true });
const grants = new Map();
const inFlightChecks = new Map();
let injectedProvider = null;

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
  const error = new Error(
    'User presence is required for this operation, which only the Dex desktop app can provide — it cannot be completed from the command line.'
  );
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
    return unavailableProvider('DEX_CM_PRESENCE_CMD could not be parsed into a command.');
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

async function detectHostBroker() {
  // Lazy requires avoid presence.cjs <-> broker.cjs initialization cycles.
  const broker = require('./broker.cjs');
  const socketPresent = fs.existsSync(broker.socketPath());
  const identityPresent = fs.existsSync(broker.serverIdentityPath());
  if (!socketPresent && !identityPresent) {
    return { reachable: false, authenticated: false };
  }
  if (!socketPresent || !identityPresent) {
    return { reachable: true, authenticated: false };
  }
  try {
    // brokerRequest authenticates serverAuth before returning. The filesystem
    // checks above prevent this probe from starting a broker for a clean,
    // genuinely hostless CLI.
    await require('./broker-client.cjs').brokerRequest({ op: 'status' });
    return { reachable: true, authenticated: true };
  } catch {
    // Runtime evidence exists but cannot be authenticated. This is ambiguous,
    // not proof that no host exists, so the caller must remain fail-closed.
    return { reachable: true, authenticated: false };
  }
}

/**
 * This module cannot honestly create a Touch ID prompt by itself: macOS
 * requires an OS-bound signed application/helper to make that claim meaningful.
 * The desktop host may inject its own in-process provider. Standalone Core can
 * still use DEX_CM_PRESENCE_CMD, whose environment seam is same-user-
 * controllable and therefore carries the documented CLI-only security ceiling.
 *
 * DEX_CM_PRESENCE_OPTIONAL is deliberately NOT a production runtime bypass. It
 * is honored only under the Node test runner, or when the explicit
 * DEX_CM_ALLOW_INSECURE_PRESENCE=1 build/development flag is set. That flag is
 * non-production and must never be enabled in a shipped runtime.
 *
 * Precedence is security policy: injected provider, command provider,
 * authenticated/ambiguous host (fail closed), then explicit standalone.
 */
function resolveProvider({ detectHostBroker: detect = detectHostBroker } = {}) {
  if (injectedProvider) return injectedProvider;
  if (process.env.DEX_CM_PRESENCE_CMD) return commandProvider(process.env.DEX_CM_PRESENCE_CMD);
  return Promise.resolve()
    .then(() => detect())
    .then((host) => {
      if (host && host.reachable === false) return STANDALONE_PROVIDER;
      if (host && host.authenticated === true) {
        return unavailableProvider(
          'A desktop-owned credential broker is reachable, so its user-presence provider is required.'
        );
      }
      return unavailableProvider(
        'Dex could not safely prove that no desktop-owned credential broker is present.'
      );
    })
    .catch(() =>
      unavailableProvider('Dex could not safely determine whether a desktop-owned broker is present.')
    );
}

function setPresenceProvider(provider) {
  if (provider === null) {
    injectedProvider = null;
    return;
  }
  injectedProvider =
    provider && provider.available === true && typeof provider.verify === 'function'
      ? provider
      : unavailableProvider('Injected presence provider is unavailable or malformed.');
}

function grantKey(connId, op) {
  return `${connId}\0${op}`;
}

function optionalPresenceAllowed() {
  return (
    process.env.DEX_CM_PRESENCE_OPTIONAL === '1' &&
    (Boolean(process.env.NODE_TEST_CONTEXT) || process.env.DEX_CM_ALLOW_INSECURE_PRESENCE === '1')
  );
}

async function assertPresence(connId, op, { provider, now, detectHostBroker: detect } = {}) {
  if (!requiresPresence(op)) return;
  const key = grantKey(connId, op);
  const cacheable = op !== 'full';
  if (cacheable) {
    const checkedAt = currentTime(now);
    const grantExpiresAt = grants.get(key);
    if (Number.isFinite(grantExpiresAt) && checkedAt < grantExpiresAt) return;
  }
  grants.delete(key);

  // Tests and the desktop host may inject a provider directly. Standalone Core
  // otherwise uses the command or fail-closed fallbacks described above.
  provider = provider || (await module.exports.resolveProvider({ detectHostBroker: detect }));
  if (provider === STANDALONE_PROVIDER) return;
  if (!provider || provider.available !== true || typeof provider.verify !== 'function') {
    if (optionalPresenceAllowed()) {
      console.error(
        `warning: user presence was NOT verified for ${connId}; ` +
          'DEX_CM_PRESENCE_OPTIONAL=1 allowed this test/development operation.'
      );
      return;
    }
    throw presenceRequiredError();
  }
  if (cacheable && inFlightChecks.has(key)) return inFlightChecks.get(key);

  const check = (async () => {
    let approved = false;
    try {
      approved = (await provider.verify({ connId, op })) === true;
    } catch {
      approved = false;
    }
    if (!approved) throw presenceRequiredError();
    if (cacheable) grants.set(key, currentTime(now) + DEFAULT_TTL_MS);
  })();
  if (!cacheable) return check;

  inFlightChecks.set(key, check);
  try {
    return await check;
  } finally {
    if (inFlightChecks.get(key) === check) inFlightChecks.delete(key);
  }
}

module.exports = { requiresPresence, assertPresence, resolveProvider, setPresenceProvider };
