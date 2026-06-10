'use strict';
/**
 * auth-context.cjs — the one place that turns a stored connection into everything needed
 * to make an authenticated request: { kind, baseUrl, headers, query }.
 *
 * Shared by get-token.cjs (the accessor other runtimes read) and dex-call.cjs (the generic
 * "floor" caller), so per-provider auth is rendered in exactly one place. See CONSUMPTION-LAYER.md.
 */

const health = require('./health.cjs');
const store = require('./token-store.cjs');
const catalog = require('./catalog.cjs');

/**
 * Request context for a Class-B (paste-a-key) token: base URL + auth headers/query with the
 * secret already placed per the catalog's scheme (Bearer / x-api-key / raw / query param /
 * key-in-URL / Basic). Falls back to the raw secret if the provider isn't in the catalog.
 */
function apiKeyContext(token, service) {
  try {
    const reg = store.getConnection(service) || {}; // resolves bare/aliased ids to the connection
    const provider = reg.provider || store.parseConnectionId(service).provider;
    const descriptor = catalog.getProviderConfig(provider, token.connectionConfig || {});
    const { headers, query } = catalog.renderAuthHeaders(descriptor, {
      apiKey: token.apiKey,
      username: token.username,
      password: token.password,
      connectionConfig: token.connectionConfig || {},
    });
    // A few providers embed the secret IN the base_url path (Telegram: …/bot${apiKey}).
    const baseUrl = (descriptor.proxyBaseUrl || '').replace(/\$\{apiKey\}/g, token.apiKey || '');
    return { kind: 'api_key', baseUrl: baseUrl || null, headers, query };
  } catch {
    // Not in catalog (or BASIC-only) — hand back the raw secret with no scheme; a caller can
    // still hit a full URL and supply its own header.
    return { kind: 'api_key', baseUrl: null, headers: {}, query: {}, apiKey: token.apiKey };
  }
}

/**
 * Resolve everything needed to make an authenticated request to a connected service.
 * For OAuth this refreshes the token if stale. Returns { kind, baseUrl, headers, query }.
 * Throws an Error with `.exitCode` (2 = not connected, 3 = needs re-auth) so CLIs map exit codes.
 */
async function resolveAuthContext(service) {
  let token;
  try {
    token = store.loadToken(service);
  } catch (err) {
    if (err.code === 'DEX_CM_KEY_LOST') {
      err.exitCode = 3;
      throw err;
    }
    throw err;
  }
  if (!token) {
    // loadToken quarantines corrupt token files and stamps the reason — surface
    // that as "reconnect" (exit 3) rather than a misleading "not connected".
    const reg = store.getConnection(service);
    if (reg && reg.error) {
      const e = new Error(`${service} needs re-authentication (${reg.error}). Run: node connect.cjs connect ${service}`);
      e.exitCode = 3;
      throw e;
    }
    const e = new Error(`${service} is not connected.`);
    e.exitCode = 2;
    throw e;
  }
  if (token.kind === 'api_key') {
    store.touchUsed(service);
    return apiKeyContext(token, service);
  }
  // OAuth: ensure a fresh access token (auto-refresh), then Bearer it.
  let accessToken;
  try {
    accessToken = await health.ensureFreshToken(service);
  } catch (err) {
    if (err.needsReauth) {
      const e = new Error(`${service} needs re-authentication. Run: node connect.cjs connect ${service}`);
      e.exitCode = 3;
      throw e;
    }
    throw err;
  }
  store.touchUsed(service);
  let baseUrl = null;
  try {
    const reg = store.getConnection(service) || {};
    const provider = reg.provider || store.parseConnectionId(service).provider;
    baseUrl = catalog.getProviderConfig(provider).proxyBaseUrl || null;
  } catch {
    /* no catalog base — caller must pass a full URL */
  }
  return { kind: 'oauth', baseUrl, headers: { Authorization: `Bearer ${accessToken}` }, query: {} };
}

module.exports = { apiKeyContext, resolveAuthContext };
