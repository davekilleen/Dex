'use strict';
/**
 * health.cjs — Local equivalent of Nango's connection `errors[]` health model,
 * plus the refresh state machine. This is what lets Dex "monitor what's working /
 * what's broken and re-authenticate when needed."
 *
 * Status values: connected | expiring | expired | needs_reauth | not_connected
 * Multi-account aware: every entry point resolves a bare/aliased id to a concrete connId.
 */

const store = require('./token-store.cjs');
const catalog = require('./catalog.cjs');
const path = require('path');
const connectorModel = require('./lib/connector-model.js');
const { createConnectorLedger } = require('./lib/connector-ledger.js');
const { createConnectorVerify, CATEGORY } = require('./lib/connector-verify.js');
const { createSingleFlight, refreshOAuthToken } = require('./lib/oauth-refresh.js');

const EXPIRY_SKEW_MS = 5 * 60 * 1000; // treat tokens expiring within 5 min as "expiring"
const runSingleFlight = createSingleFlight();
const ledger = createConnectorLedger({
  stateDir: () => path.join(store.credentialsDir(), 'ledger'),
});

function connectionLedger() {
  return ledger;
}

function evidenceFor(connId) {
  return ledger.rollup(connId);
}

/** True if this connection is a paste-a-key (Class B) connection (registry mode or stored kind). */
function isKeyBased(reg, token) {
  if (reg && reg.authMode && catalog.KEY_MODES.has(reg.authMode)) return true;
  if (token && token.kind === 'api_key') return true;
  return false;
}

/** Pure status read — does NOT attempt a refresh. Cheap; safe to call in a sweep. */
function connectionHealth(service) {
  const connId = store.resolveConnId(service);
  const reg = store.readRegistry()[connId];
  const provider = (reg && reg.provider) || store.parseConnectionId(connId).provider;
  let token;
  try {
    token = store.loadToken(connId); // a corrupt file is quarantined + stamped here, never thrown
  } catch (err) {
    if (err && err.code === 'DEX_CM_KEY_LOST') {
      // Computed at read time and never persisted, so a transient keychain
      // blip self-heals completely the moment the key is readable again.
      return {
        service: connId,
        provider,
        alias: reg && reg.alias,
        status: 'needs_reauth',
        expiresAt: null,
        hasRefreshToken: false,
        scopes: (reg && reg.scopes) || [],
        lastRefreshedAt: reg && reg.lastRefreshedAt,
        error: 'encryption_key_lost',
        message: err.message,
      };
    }
    throw err;
  }
  if (!token) {
    // Re-read: loadToken may just have stamped a corruption reason on the entry.
    const reg2 = store.readRegistry()[connId] || reg;
    if (reg2 && reg2.error) {
      return {
        service: connId,
        provider: reg2.provider || provider,
        alias: reg2.alias,
        status: 'needs_reauth',
        expiresAt: null,
        hasRefreshToken: false,
        scopes: reg2.scopes || [],
        lastRefreshedAt: reg2.lastRefreshedAt,
        error: reg2.error,
      };
    }
    return {
      service: connId,
      status: 'not_connected',
      provider,
      alias: reg && reg.alias,
      ...connectorModel.deriveVerification(evidenceFor(connId)),
    };
  }

  const keyBased = isKeyBased(reg, token);
  const expiresAt = keyBased ? null : token.expires_at || (reg && reg.expiresAt) || null;
  const status = connectorModel.deriveStatus({
    credentialPresent: true,
    registryError: reg && reg.error,
    expiresAt,
    hasRefreshToken: Boolean(token.refresh_token),
  });

  return {
    service: connId,
    provider,
    alias: reg && reg.alias,
    status,
    expiresAt,
    hasRefreshToken: keyBased ? false : Boolean(token.refresh_token),
    scopes: (reg && reg.scopes) || [],
    lastRefreshedAt: reg && reg.lastRefreshedAt,
    error: reg && reg.error,
    ...connectorModel.deriveVerification(evidenceFor(connId)),
  };
}

/** Sweep every known connection (the monitoring view). One broken connection must never kill the sweep. */
function allConnectionsHealth() {
  return store.listConnections().map((c) => {
    try {
      return connectionHealth(c.service);
    } catch (err) {
      return {
        service: c.service,
        provider: c.provider,
        alias: c.alias,
        status: 'needs_reauth',
        error: err && err.code === 'DEX_CM_KEY_LOST' ? 'encryption_key_lost' : `health_check_failed: ${err.message}`,
      };
    }
  });
}

function providerRefreshFetch(providerConfig) {
  return async (url, options) => {
    const params = new URLSearchParams(options.body);
    const headers = { Accept: 'application/json', ...(options.headers || {}) };
    let body;
    if (providerConfig.tokenRequestAuthMethod === 'basic') {
      const clientId = params.get('client_id') || '';
      const clientSecret = params.get('client_secret') || '';
      params.delete('client_id');
      params.delete('client_secret');
      headers.Authorization = 'Basic ' + Buffer.from(`${clientId}:${clientSecret}`).toString('base64');
    }
    if (providerConfig.bodyFormat === 'json') {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(Object.fromEntries(params));
    } else {
      headers['Content-Type'] = 'application/x-www-form-urlencoded';
      body = params.toString();
    }
    const response = await globalThis.fetch(url, { ...options, headers, body });
    if (response && typeof response.json !== 'function' && typeof response.text === 'function') {
      return {
        ...response,
        json: async () => JSON.parse(await response.text()),
      };
    }
    return response;
  };
}

function normalizeRefreshResult(result, previous) {
  const raw = result.raw && typeof result.raw === 'object' ? result.raw : {};
  const nested = raw.authed_user && typeof raw.authed_user === 'object' ? raw.authed_user : {};
  return {
    ...previous,
    access_token: result.accessToken,
    refresh_token: result.refreshToken || previous.refresh_token || null,
    token_type: nested.token_type || raw.token_type || previous.token_type || 'Bearer',
    scope: nested.scope || raw.scope || previous.scope || null,
    expires_at: result.expiresAt || previous.expires_at || null,
    obtained_at: Date.now(),
    ...(raw.instance_url || nested.instance_url || previous.instance_url
      ? { instance_url: raw.instance_url || nested.instance_url || previous.instance_url }
      : {}),
    ...(raw.id || nested.id || previous.id ? { id: raw.id || nested.id || previous.id } : {}),
    raw,
  };
}

function recordConnectionEvent(connId, op, row = {}) {
  return ledger.append(connId, { op, ...row });
}

/**
 * Return a valid access token for `service`, refreshing if expired/expiring.
 * With { force:true }, perform the provider refresh even when the token is fresh.
 * On refresh failure (e.g. revoked refresh token) marks the connection
 * needs_reauth and throws — the caller surfaces a "Reconnect" prompt.
 *
 * Concurrency: the actual refresh runs under store.withRefreshLock(connId), a
 * cross-process lock held across the network call. After acquiring it we
 * RE-CHECK freshness, so when two processes race, the loser reuses the
 * winner's stored token instead of burning the refresh token a second time
 * (providers with refresh-token rotation invalidate one side otherwise).
 */
async function refreshToken(service, { force = false } = {}) {
  const connId = store.resolveConnId(service);
  let token;
  try {
    token = store.loadToken(connId);
  } catch (err) {
    // Key loss: the only fix is reconnecting, so flag it as a re-auth with the
    // explicit message rather than letting a raw decrypt error escape.
    if (err && err.code === 'DEX_CM_KEY_LOST') throw Object.assign(err, { needsReauth: true });
    throw err;
  }
  if (!token) {
    // Distinguish "never connected" from "stored credential unreadable" (a
    // corrupt token file was just quarantined); the latter is a reconnect.
    const reg = store.readRegistry()[connId];
    if (reg && reg.error) {
      throw Object.assign(new Error(`${connId} needs re-authentication (${reg.error}).`), { needsReauth: true });
    }
    throw new Error(`${connId} is not connected.`);
  }

  // Class B (paste-a-key): the stored secret is the credential — never expires,
  // no refresh dance. Return it directly (apiKey, or BASIC password).
  const reg0 = store.readRegistry()[connId];
  if (isKeyBased(reg0, token)) return token.apiKey || token.password || null;

  const h = connectionHealth(connId);
  if (!force && h.status === 'connected') return token.access_token;

  if (!token.refresh_token) {
    store.upsertConnection(connId, { status: 'needs_reauth', error: 'no_refresh_token' });
    recordConnectionEvent(connId, 'break', {
      ok: false,
      error: { category: 'auth_permanent', code: 'no_refresh_token', message: 'No refresh token on file' },
    });
    throw Object.assign(new Error(`${connId} needs re-authentication (no refresh token).`), { needsReauth: true });
  }

  return runSingleFlight(connId, async () =>
    store.withRefreshLock(connId, async () => {
      // Double-check under the lock: another process may have refreshed while
      // we waited. If the stored token is fresh now, use it: no network call.
      const current = store.loadToken(connId) || token;
      if (!force && connectionHealth(connId).status === 'connected') return current.access_token;

      const reg = store.readRegistry()[connId] || {};
      const provider = reg.provider || store.parseConnectionId(connId).provider;
      const app = store.getOAuthApp(provider); // OAuth app is shared per provider, not per account
      if (!app) throw new Error(`No OAuth app credentials for '${provider}'. Add them to oauth-apps.json.`);
      const providerConfig = catalog.getProviderConfig(provider, reg.connectionConfig || {});
      try {
        const result = await refreshOAuthToken({
          tokenUrl: providerConfig.refreshUrl || providerConfig.tokenUrl,
          refreshToken: current.refresh_token || token.refresh_token,
          clientId: app.clientId,
          clientSecret: app.clientSecret,
          extraParams: providerConfig.refreshParams || {},
          fetchImpl: providerRefreshFetch(providerConfig),
          retryDelayMs: Number.isFinite(providerConfig.refreshRetryDelayMs)
            ? providerConfig.refreshRetryDelayMs
            : undefined,
        });
        const fresh = normalizeRefreshResult(result, current);
        store.saveToken(connId, fresh, { provider: providerConfig.id, connectedAt: reg.connectedAt });
        recordConnectionEvent(connId, 'refresh', { ok: true, httpStatus: 200 });
        return fresh.access_token;
      } catch (err) {
        const needsReauth = err && err.permanent === true;
        const code = String((err && err.message) || 'refresh_failed').slice(0, 200);
        recordConnectionEvent(connId, 'refresh', {
          ok: false,
          error: { category: needsReauth ? 'auth_permanent' : 'transient', code, message: code },
        });
        if (needsReauth) {
          store.upsertConnection(connId, { status: 'needs_reauth', error: code });
          recordConnectionEvent(connId, 'break', {
            ok: false,
            error: { category: 'auth_permanent', code, message: code },
          });
        }
        throw Object.assign(err, { needsReauth });
      }
    })
  );
}

async function ensureFreshToken(service) {
  return refreshToken(service);
}

async function probeConnection(service, options = {}) {
  const connId = store.resolveConnId(service);
  const reg = store.readRegistry()[connId] || {};
  const provider = reg.provider || store.parseConnectionId(connId).provider;
  const token = store.loadToken(connId);
  if (!token) throw new Error(`${connId} is not connected.`);
  const credential = isKeyBased(reg, token)
    ? token.apiKey || token.password || null
    : await ensureFreshToken(connId);
  const verifier = createConnectorVerify(options);
  const result = await verifier.verify(connId, { provider, token: credential });
  recordConnectionEvent(connId, 'probe', verifier.toLedgerRow(connId, result));
  if (result.error && result.error.category === CATEGORY.AUTH_PERMANENT) {
    const code = String(result.error.code || result.error.message || 'authentication_failed');
    store.upsertConnection(connId, { status: 'needs_reauth', error: code });
    recordConnectionEvent(connId, 'break', {
      ok: false,
      httpStatus: result.httpStatus,
      error: result.error,
    });
  }
  return result;
}

async function probeConnections(service, options = {}) {
  const targets = service ? [store.resolveConnId(service)] : store.listConnections().map((entry) => entry.service);
  const results = [];
  for (const connId of targets) {
    try {
      const result = await probeConnection(connId, options);
      results.push({ service: connId, ...result, status: connectionHealth(connId).status });
    } catch (error) {
      results.push({
        service: connId,
        ok: false,
        status: connectionHealth(connId).status,
        error: { category: 'probe_failed', message: error.message },
      });
    }
  }
  return results;
}

module.exports = {
  connectionHealth,
  allConnectionsHealth,
  ensureFreshToken,
  refreshToken,
  probeConnection,
  probeConnections,
  recordConnectionEvent,
  connectionLedger,
  EXPIRY_SKEW_MS,
};
