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
const { refreshAccessToken } = require('./oauth-flow.cjs');

const EXPIRY_SKEW_MS = 5 * 60 * 1000; // treat tokens expiring within 5 min as "expiring"

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
  const token = store.loadToken(connId); // a corrupt file is quarantined + stamped here, never thrown
  const provider = (reg && reg.provider) || store.parseConnectionId(connId).provider;
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
    return { service: connId, status: 'not_connected', provider, alias: reg && reg.alias };
  }

  // Class B (paste-a-key): no expiry, no refresh state machine. A bad key only
  // surfaces if a probe stamped reg.error → needs_reauth; otherwise connected.
  if (isKeyBased(reg, token)) {
    return {
      service: connId,
      provider,
      alias: reg && reg.alias,
      status: reg && reg.error ? 'needs_reauth' : 'connected',
      expiresAt: null,
      hasRefreshToken: false,
      scopes: (reg && reg.scopes) || [],
      lastRefreshedAt: reg && reg.lastRefreshedAt,
      error: reg && reg.error,
    };
  }

  const expiresAt = token.expires_at || (reg && reg.expiresAt) || null;
  let status = 'connected';
  if (reg && reg.error) status = 'needs_reauth';
  else if (expiresAt && Date.now() >= expiresAt) status = token.refresh_token ? 'expired' : 'needs_reauth';
  else if (expiresAt && Date.now() >= expiresAt - EXPIRY_SKEW_MS) status = 'expiring';

  return {
    service: connId,
    provider,
    alias: reg && reg.alias,
    status,
    expiresAt,
    hasRefreshToken: Boolean(token.refresh_token),
    scopes: (reg && reg.scopes) || [],
    lastRefreshedAt: reg && reg.lastRefreshedAt,
    error: reg && reg.error,
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
        error: `health_check_failed: ${err.message}`,
      };
    }
  });
}

// Per-process refresh dedup so concurrent callers in ONE process share a refresh.
// Cross-process exclusion is the store's refresh lock (see below).
const _inFlight = new Map();

/**
 * Return a valid access token for `service`, refreshing if expired/expiring.
 * On refresh failure (e.g. revoked refresh token) marks the connection
 * needs_reauth and throws — the caller surfaces a "Reconnect" prompt.
 *
 * Concurrency: the actual refresh runs under store.withRefreshLock(connId), a
 * cross-process lock held across the network call. After acquiring it we
 * RE-CHECK freshness, so when two processes race, the loser reuses the
 * winner's stored token instead of burning the refresh token a second time
 * (providers with refresh-token rotation invalidate one side otherwise).
 */
async function ensureFreshToken(service) {
  const connId = store.resolveConnId(service);
  const token = store.loadToken(connId);
  if (!token) {
    // Distinguish "never connected" from "stored credential unreadable" (a
    // corrupt token file was just quarantined) — the latter is a reconnect.
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
  if (h.status === 'connected') return token.access_token;

  if (!token.refresh_token) {
    store.upsertConnection(connId, { status: 'needs_reauth', error: 'no_refresh_token' });
    throw Object.assign(new Error(`${connId} needs re-authentication (no refresh token).`), { needsReauth: true });
  }

  if (_inFlight.has(connId)) return _inFlight.get(connId);

  const promise = (async () => {
    try {
      return await store.withRefreshLock(connId, async () => {
        // Double-check under the lock: another process may have refreshed while
        // we waited. If the stored token is fresh now, use it — no network call.
        const current = store.loadToken(connId) || token;
        if (connectionHealth(connId).status === 'connected') return current.access_token;

        const reg = store.readRegistry()[connId] || {};
        const provider = reg.provider || store.parseConnectionId(connId).provider;
        const app = store.getOAuthApp(provider); // OAuth app is shared per provider, not per account
        if (!app) throw new Error(`No OAuth app credentials for '${provider}'. Add them to oauth-apps.json.`);
        const providerConfig = catalog.getProviderConfig(provider, reg.connectionConfig || {});
        try {
          const fresh = await refreshAccessToken(providerConfig, {
            refreshToken: current.refresh_token || token.refresh_token,
            clientId: app.clientId,
            clientSecret: app.clientSecret,
            previous: current,
          });
          store.saveToken(connId, fresh, { provider: providerConfig.id, connectedAt: reg.connectedAt });
          return fresh.access_token;
        } catch (err) {
          // Refresh-token revoked / invalid_grant → needs re-auth (the break→detect→reconnect signal).
          const needsReauth = err.status === 400 || err.status === 401;
          store.upsertConnection(connId, {
            status: needsReauth ? 'needs_reauth' : 'error',
            error: (err.body && err.body.error) || err.message,
          });
          throw Object.assign(err, { needsReauth });
        }
      });
    } finally {
      _inFlight.delete(connId);
    }
  })();

  _inFlight.set(connId, promise);
  return promise;
}

module.exports = { connectionHealth, allConnectionsHealth, ensureFreshToken, EXPIRY_SKEW_MS };
