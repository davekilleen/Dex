'use strict';
/**
 * auth-context.cjs — the one place that turns a stored connection into everything needed
 * to make an authenticated request: { kind, baseUrl, headers, query }.
 *
 * Shared by get-token.cjs (the accessor other runtimes read) and dex-call.cjs (the generic
 * caller), so per-provider auth is rendered in exactly one place.
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
    // apiKey rides along so CLIs can REDACT it from anything they print (the
    // envelope itself is secret-bearing by contract: headers/baseUrl carry it).
    const context = {
      kind: 'api_key',
      baseUrl: baseUrl || null,
      headers,
      query,
      ...(token.apiKey ? { apiKey: token.apiKey } : {}),
    };
    // Internal routing metadata for dex-call's origin policy. Keep it
    // non-enumerable so the published get-token response contract stays v1.
    Object.defineProperty(context, 'provider', { value: provider });
    return context;
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
    // loadToken quarantines corrupt token files and stamps the reason; surface
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
    const reg = store.getConnection(service);
    if (reg && reg.status === 'needs_reauth') {
      const e = new Error(`${service} needs re-authentication. Run: node connect.cjs set-key ${service}`);
      e.exitCode = 3;
      throw e;
    }
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
  const reg = store.getConnection(service) || {};
  const provider = reg.provider || store.parseConnectionId(service).provider;
  const context = { kind: 'oauth', baseUrl, headers: { Authorization: `Bearer ${accessToken}` }, query: {} };
  Object.defineProperty(context, 'provider', { value: provider });
  return context;
}

/**
 * Every secret string carried by an auth context: header values (and the token
 * part after a Bearer/Basic/Token scheme), auth query values, and the raw
 * apiKey (which can be embedded in the base URL, e.g. Telegram's /bot<key>).
 * Used to REDACT diagnostics, never to print. Short values (<4 chars) are
 * skipped so redaction can't shred ordinary text.
 */
function secretsOf(ctx) {
  const out = new Set();
  const add = (v) => {
    if (typeof v === 'string' && v.length >= 4) out.add(v);
  };
  for (const v of Object.values((ctx && ctx.headers) || {})) {
    add(v);
    const m = typeof v === 'string' && v.match(/^(?:Bearer|Basic|Token)\s+(.+)$/i);
    if (m) add(m[1]);
  }
  for (const v of Object.values((ctx && ctx.query) || {})) add(v);
  if (ctx && ctx.apiKey) add(ctx.apiKey);
  // Broker-rendered contexts deliberately omit the raw apiKey field. Recover
  // only the credential-shaped portion of catalog URLs such as Telegram's
  // .../bot${apiKey}, so dex-call diagnostics retain their pre-broker
  // redaction without widening the broker response.
  if (ctx && ctx.provider && ctx.baseUrl) {
    try {
      const template = catalog.getProviderConfig(ctx.provider).proxyBaseUrl || '';
      const marker = '${apiKey}';
      const markerAt = template.indexOf(marker);
      if (markerAt !== -1) {
        const prefix = template.slice(0, markerAt);
        const suffix = template.slice(markerAt + marker.length);
        if (
          !prefix.includes('${') &&
          !suffix.includes('${') &&
          ctx.baseUrl.startsWith(prefix) &&
          ctx.baseUrl.endsWith(suffix)
        ) {
          const end = suffix ? ctx.baseUrl.length - suffix.length : undefined;
          add(ctx.baseUrl.slice(prefix.length, end));
        }
      }
    } catch {
      /* header/query forms above still redact when catalog lookup is unavailable */
    }
  }
  // Longest first so overlapping values redact fully.
  return [...out].sort((a, b) => b.length - a.length);
}

function encodedSecretForms(secret) {
  const forms = new Set([secret, Buffer.from(secret, 'utf8').toString('base64')]);
  try {
    const percentEncoded = encodeURIComponent(secret);
    forms.add(percentEncoded);
    forms.add(percentEncoded.replace(/%[0-9A-F]{2}/g, (hex) => hex.toLowerCase()));
  } catch {
    /* malformed surrogate: raw + base64 forms still redact */
  }
  const formEncoded = new URLSearchParams({ value: secret }).toString().slice('value='.length);
  forms.add(formEncoded);
  forms.add(formEncoded.replace(/%[0-9A-F]{2}/g, (hex) => hex.toLowerCase()));
  return forms;
}

/** Replace every raw, URL/form-encoded, or base64 occurrence of each secret in `text` with '***'. */
function redactSecrets(text, secrets) {
  let s = String(text);
  const forms = new Set();
  for (const secret of secrets || []) {
    if (typeof secret !== 'string' || secret.length < 4) continue;
    for (const form of encodedSecretForms(secret)) {
      if (form.length >= 4) forms.add(form);
    }
  }
  for (const form of [...forms].sort((a, b) => b.length - a.length)) {
    s = s.split(form).join('***');
  }
  return s;
}

module.exports = { apiKeyContext, resolveAuthContext, secretsOf, redactSecrets };
