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
  const token = store.loadToken(connId);
  const provider = (reg && reg.provider) || store.parseConnectionId(connId).provider;
  if (!token) return { service: connId, status: 'not_connected', provider, alias: reg && reg.alias };

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

/** Sweep every known connection (the monitoring view). */
function allConnectionsHealth() {
  return store.listConnections().map((c) => connectionHealth(c.service));
}

// Simple per-process refresh lock so concurrent callers don't double-refresh.
const _inFlight = new Map();

/**
 * Return a valid access token for `service`, refreshing if expired/expiring.
 * On refresh failure (e.g. revoked refresh token) marks the connection
 * needs_reauth and throws — the caller surfaces a "Reconnect" prompt.
 */
async function ensureFreshToken(service) {
  const connId = store.resolveConnId(service);
  const token = store.loadToken(connId);
  if (!token) throw new Error(`${connId} is not connected.`);

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
    const reg = store.readRegistry()[connId] || {};
    const provider = reg.provider || store.parseConnectionId(connId).provider;
    const app = store.getOAuthApp(provider); // OAuth app is shared per provider, not per account
    if (!app) throw new Error(`No OAuth app credentials for '${provider}'. Add them to oauth-apps.json.`);
    const providerConfig = catalog.getProviderConfig(provider, reg.connectionConfig || {});
    try {
      const fresh = await refreshAccessToken(providerConfig, {
        refreshToken: token.refresh_token,
        clientId: app.clientId,
        clientSecret: app.clientSecret,
        previous: token,
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
    } finally {
      _inFlight.delete(connId);
    }
  })();

  _inFlight.set(connId, promise);
  return promise;
}

module.exports = { connectionHealth, allConnectionsHealth, ensureFreshToken, EXPIRY_SKEW_MS };
