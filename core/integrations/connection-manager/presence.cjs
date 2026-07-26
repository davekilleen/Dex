'use strict';

const DEFAULT_TTL_MS = 60_000;
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

function currentTime(now) {
  return typeof now === 'function' ? now() : now == null ? Date.now() : Number(now);
}

function unavailableProvider(reason) {
  return { available: false, kind: 'unavailable', reason };
}

/**
 * This module cannot honestly create a Touch ID prompt by itself: macOS
 * requires an OS-bound signed application/helper to make that claim meaningful.
 * A caller-controlled command or "optional" environment flag is not evidence
 * of user presence, so Core deliberately has no production environment adapter.
 * The signed host must inject a provider in-process at its trusted boundary.
 */
function resolveProvider() {
  if (process.platform === 'darwin') {
    return unavailableProvider(
      'Real biometric presence requires an OS-bound Dex-signed host; environment commands are not trusted.'
    );
  }
  return unavailableProvider('OS-bound user presence is unavailable on this platform.');
}

function grantKey(connId, op) {
  return `${connId}\0${op}`;
}

async function assertPresence(connId, op, { provider, now } = {}) {
  if (!requiresPresence(op)) return;
  const key = grantKey(connId, op);
  const checkedAt = currentTime(now);
  const grantExpiresAt = grants.get(key);
  if (Number.isFinite(grantExpiresAt) && checkedAt < grantExpiresAt) return;
  grants.delete(key);

  // The signed desktop host can replace this exported seam in-process. Core
  // itself never accepts presence approval from caller-controlled environment.
  provider = provider || module.exports.resolveProvider();
  if (!provider || provider.available === false || typeof provider.verify !== 'function') {
    throw presenceRequiredError();
  }
  if (inFlightChecks.has(key)) return inFlightChecks.get(key);

  const check = (async () => {
    let approved = false;
    try {
      approved = (await provider.verify({ connId, op })) === true;
    } catch {
      approved = false;
    }
    if (!approved) throw presenceRequiredError();
    grants.set(key, currentTime(now) + DEFAULT_TTL_MS);
  })();
  inFlightChecks.set(key, check);
  try {
    return await check;
  } finally {
    if (inFlightChecks.get(key) === check) inFlightChecks.delete(key);
  }
}

module.exports = { requiresPresence, assertPresence, resolveProvider };
