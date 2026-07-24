'use strict';
/**
 * catalog.cjs — Provider configuration layer (the "hybrid" in catalog-hybrid).
 *
 * Sources per-provider OAuth config from Nango's open-source provider catalog
 * (`@nangohq/providers`, ~831 providers). We consume it as DATA only — Dex owns
 * the OAuth runtime (oauth-flow.cjs) and the on-device token store (token-store.cjs).
 *
 * Nango's catalog is Elastic License 2.0 (source-available). We embed it as an
 * npm dependency (not vendored source) and never re-expose it as a managed service.
 */

let providers;
try {
  providers = require('@nangohq/providers');
} catch (err) {
  throw new Error(
    "Missing dependency '@nangohq/providers'. Run `npm install @nangohq/providers` in dex-core. " +
      'It supplies the provider OAuth catalog for the connection manager.'
  );
}

const DEX_UNFILLED = '<<dex:unfilled>>';

/**
 * Resolve `${connectionConfig.x}` templating and Nango's `a || b` fallback syntax.
 * Used for multi-tenant hosts, e.g. Salesforce:
 *   "https://${connectionConfig.hostname} || https://login.salesforce.com"
 * Picks the first `||` candidate whose placeholders are all satisfied.
 */
function resolveTemplate(value, connectionConfig = {}) {
  if (typeof value !== 'string') return value;
  const candidates = value.split('||').map((s) => s.trim());
  for (const candidate of candidates) {
    const substituted = candidate.replace(/\$\{connectionConfig\.([^}]+)\}/g, (_, key) => {
      const v = connectionConfig[key.trim()];
      return v === undefined || v === null ? DEX_UNFILLED : String(v);
    });
    if (!substituted.includes(DEX_UNFILLED)) return substituted; // all placeholders filled
  }
  // None fully satisfied — return the last candidate with whatever we have (lets caller see the gap).
  return candidates[candidates.length - 1].replace(
    /\$\{connectionConfig\.([^}]+)\}/g,
    (_, key) => String(connectionConfig[key.trim()] ?? '')
  );
}

const CONNECTABLE_OAUTH_MODES = new Set(['OAUTH2', 'MCP_OAUTH2']);
const BROWSE_OAUTH_MODES = new Set(['OAUTH2', 'MCP_OAUTH2', 'OAUTH1', 'OAUTH2_CC', 'TBA']);
const VERIFIED_PROVIDERS = Object.freeze(['google', 'slack', 'linear']);

// Class-B "paste a secret" auth modes. These don't run an OAuth dance — the user
// pastes a long-lived secret (API key, or a username/password pair for HTTP Basic),
// which we store encrypted and replay into request headers/query at call time.
const KEY_MODES = new Set(['API_KEY', 'BASIC']);

// Per-provider header overrides for catalog quirks the proxy block gets wrong or
// omits. Merged OVER raw.proxy.headers (case-insensitive on header name). Example:
// Linear's personal API key goes in a raw `Authorization: <key>` header with NO
// `Bearer` scheme — the opposite of the usual convention.
const KEY_HEADER_OVERRIDES = {
  linear: { authorization: '${apiKey}' },
};

// Providers usable via a paste-in API key even though Nango's catalog only encodes
// their OAuth config (many tools support BOTH OAuth and a personal API key/PAT).
// An entry here forces Class-B key mode for that provider id and supplies the
// request scheme verbatim. ${apiKey} is substituted by renderAuthHeaders.
const KEY_PROVIDER_OVERRIDES = {
  linear: {
    displayName: 'Linear (API key)',
    proxyBaseUrl: 'https://api.linear.app',
    // Linear personal API keys go in a RAW Authorization header — no "Bearer".
    requestHeaders: { Authorization: '${apiKey}' },
    verification: { method: 'POST', endpoint: '/graphql' },
  },
};

// Per-provider OAuth config overrides for when Dex's *registered* app differs from the
// assumption baked into Nango's catalog. Merged OVER the derived OAuth descriptor.
//
// microsoft: Nango sets `disable_pkce: true` because it assumes a CONFIDENTIAL client
// (one shipping a client_secret). Dex registers a PUBLIC client (PKCE, no secret) so a
// distributed local-first app never has to embed a real secret on every user's machine
// — and Azure then REQUIRES PKCE, so force it on. Also request explicit Graph delegated
// scopes (exactly the ones the Entra app "Dex Connection Manager", appId
// 8ae475ca-929f-4bbe-861d-4a5468996069, is configured for) instead of Nango's `.default`,
// which is unreliable across the personal + work-account audience on the /common endpoint.
const OAUTH_PROVIDER_OVERRIDES = {
  // google: Nango ships empty default_scopes, and Google hard-fails authorization
  // requests with no scope. Dex deliberately defaults to least-privilege Calendar
  // read-only instead of the broad catalogScopes map; --scopes remains the explicit override.
  google: {
    defaultScopes: [
      'https://www.googleapis.com/auth/calendar.readonly',
    ],
  },
  microsoft: {
    usePkce: true,
    defaultScopes: [
      'offline_access',
      'https://graph.microsoft.com/Mail.Read',
      'https://graph.microsoft.com/Mail.Send',
      'https://graph.microsoft.com/Calendars.ReadWrite',
      'https://graph.microsoft.com/Chat.Read',
    ],
  },
};

function providerSupport(providerId, raw) {
  const verified = VERIFIED_PROVIDERS.includes(providerId);
  if (raw.auth_mode === 'OAUTH1') {
    return { supported: false, verified, reason: 'OAuth 1 is not implemented by the Dex connection manager.' };
  }
  if (raw.auth_mode === 'OAUTH2_CC') {
    return {
      supported: false,
      verified,
      reason: 'OAuth 2 client-credentials is not implemented by the Dex connection manager.',
    };
  }
  if (raw.auth_mode === 'TBA') {
    return {
      supported: false,
      verified,
      reason: 'Token-based authentication (TBA) is not implemented by the Dex connection manager.',
    };
  }
  if (raw.post_connection_script) {
    return {
      supported: false,
      verified,
      reason: 'This provider depends on a Nango post-connection server script that Dex does not run.',
    };
  }
  if (raw.client_registration === 'dynamic') {
    return {
      supported: false,
      verified,
      reason: 'This provider requires dynamic client registration, which the Dex connection manager does not implement.',
    };
  }
  if (!CONNECTABLE_OAUTH_MODES.has(raw.auth_mode) && !KEY_MODES.has(raw.auth_mode)) {
    return {
      supported: false,
      verified,
      reason: `Auth mode ${raw.auth_mode} is not implemented by the Dex connection manager.`,
    };
  }
  return { supported: true, verified, reason: null };
}

/**
 * Return a normalized, Dex-facing descriptor for a provider id (e.g. "google",
 * "google-calendar", "slack"). `connectionConfig` fills any `${connectionConfig.*}`
 * template variables (subdomain, hostname, instance_url, ...).
 *
 * OAuth-family providers get the OAuth descriptor (authorizationUrl, tokenUrl, …).
 * API_KEY/BASIC providers get a "key descriptor" (proxyBaseUrl, requestHeaders, …)
 * for the paste-a-key path. Throws only if the provider is unknown or uses an
 * auth_mode in neither family.
 */
function getProviderConfig(providerId, connectionConfig = {}) {
  // Forced paste-a-key override wins, even if the catalog classifies this
  // provider as OAuth (it returns a Class-B key descriptor).
  const keyOverride = KEY_PROVIDER_OVERRIDES[providerId];
  if (keyOverride) {
    return {
      supported: true,
      verified: VERIFIED_PROVIDERS.includes(providerId),
      reason: null,
      authMode: 'API_KEY',
      id: providerId,
      displayName: keyOverride.displayName || providerId,
      proxyBaseUrl: keyOverride.proxyBaseUrl || null,
      requestHeaders: keyOverride.requestHeaders || {},
      requestQuery: keyOverride.requestQuery || {},
      verification: keyOverride.verification || null,
      credentialsSchema: null,
      connectionConfigSchema: null,
      raw: { __keyOverride: true },
    };
  }

  const raw = providers.getProvider(providerId);
  if (!raw) {
    throw new Error(`Unknown provider '${providerId}'. See listOAuthProviders() / listKeyProviders() for available ids.`);
  }
  const authMode = raw.auth_mode;
  const support = providerSupport(providerId, raw);

  // Class B: paste-a-key (API_KEY / BASIC). Return a key descriptor instead of throwing.
  if (KEY_MODES.has(authMode)) {
    const baseHeaders = (raw.proxy && raw.proxy.headers) || {};
    const override = KEY_HEADER_OVERRIDES[providerId] || {};
    return {
      ...support,
      authMode,
      id: providerId,
      displayName: raw.display_name || providerId,
      docs: raw.docs || null,
      credentialsSchema: raw.credentials || null,
      proxyBaseUrl: raw.proxy && raw.proxy.base_url ? resolveTemplate(raw.proxy.base_url, connectionConfig) : null,
      requestHeaders: { ...baseHeaders, ...override },
      requestQuery: (raw.proxy && raw.proxy.query) || {},
      verification: (raw.proxy && raw.proxy.verification) || null,
      connectionConfigSchema: raw.connection_config || null,
      raw,
    };
  }

  const scopes = (() => {
    try {
      return providers.getProviderScopes ? providers.getProviderScopes(providerId) || [] : [];
    } catch {
      return [];
    }
  })();

  const config = {
    ...support,
    id: providerId,
    displayName: raw.display_name || providerId,
    authMode,
    authorizationUrl: resolveTemplate(raw.authorization_url, connectionConfig),
    tokenUrl: resolveTemplate(raw.token_url, connectionConfig),
    refreshUrl: raw.refresh_url ? resolveTemplate(raw.refresh_url, connectionConfig) : null,
    authorizationParams: raw.authorization_params || {},
    tokenParams: raw.token_params || {},
    refreshParams: raw.refresh_params || {},
    scopeSeparator: raw.scope_separator || ' ',
    // Nango: PKCE is ON by default unless a provider opts out via disable_pkce: true.
    usePkce: raw.disable_pkce !== true && (authMode === 'OAUTH2' || authMode === 'MCP_OAUTH2'),
    // 'basic' => HTTP Basic header; 'request_body' (default) => client creds in the body.
    tokenRequestAuthMethod: raw.token_request_auth_method || 'request_body',
    bodyFormat: raw.body_format || 'form', // 'form' (x-www-form-urlencoded) or 'json'
    defaultScopes: raw.default_scopes || [],
    catalogScopes: scopes,
    connectionConfigSchema: raw.connection_config || null,
    tokenResponseMetadata: raw.token_response_metadata || null,
    alternateAccessTokenResponsePath: raw.alternate_access_token_response_path || null,
    proxyBaseUrl: raw.proxy && raw.proxy.base_url ? resolveTemplate(raw.proxy.base_url, connectionConfig) : null,
    // Imperative quirks that live in Nango's SERVER, not the catalog — flagged so callers
    // know a given provider may need bespoke handling we haven't implemented.
    serverSideScripts: {
      postConnection: raw.post_connection_script || null,
      credentialsVerification: raw.credentials_verification_script || null,
      webhookRouting: raw.webhook_routing_script || null,
    },
    docs: raw.docs || null,
    raw,
  };
  // Apply any Dex-registered-app override (e.g. microsoft: force PKCE for our public client).
  const oauthOverride = OAUTH_PROVIDER_OVERRIDES[providerId];
  return oauthOverride ? { ...config, ...oauthOverride } : config;
}

/** List all OAuth-family providers as { id, displayName, authMode }. */
function listOAuthProviders() {
  const all = providers.getProviders();
  return Object.entries(all)
    .filter(([id, p]) => BROWSE_OAUTH_MODES.has(p.auth_mode) && !KEY_PROVIDER_OVERRIDES[id])
    .map(([id, p]) => ({
      id,
      displayName: p.display_name || id,
      authMode: p.auth_mode,
      ...providerSupport(id, p),
    }))
    .sort((a, b) => a.displayName.localeCompare(b.displayName));
}

/** List all paste-a-key (API_KEY / BASIC) providers as { id, displayName, authMode }. */
function listKeyProviders() {
  const all = providers.getProviders();
  const fromCatalog = Object.entries(all)
    .filter(([, p]) => KEY_MODES.has(p.auth_mode))
    .map(([id, p]) => ({
      id,
      displayName: p.display_name || id,
      authMode: p.auth_mode,
      ...providerSupport(id, p),
    }));
  const fromOverrides = Object.entries(KEY_PROVIDER_OVERRIDES)
    .filter(([id]) => !(all[id] && KEY_MODES.has(all[id].auth_mode)))
    .map(([id, o]) => ({
      id,
      displayName: o.displayName || id,
      authMode: 'API_KEY',
      supported: true,
      verified: VERIFIED_PROVIDERS.includes(id),
      reason: null,
    }));
  return [...fromCatalog, ...fromOverrides].sort((a, b) => a.displayName.localeCompare(b.displayName));
}

/**
 * Render the concrete request auth for a Class-B (API_KEY / BASIC) connection by
 * substituting the user's secret into the catalog's header/query templates VERBATIM.
 *
 * The catalog encodes each provider's real scheme — never assume `Bearer`:
 *   - "authorization": "Bearer ${apiKey}"   → Bearer scheme (openai, github-pat)
 *   - "authorization": "${apiKey}"           → no scheme, raw key (clay, linear override)
 *   - "x-api-key": "${apiKey}"               → custom header (anthropic)
 *   - proxy.query { key: "${apiKey}" }       → query-param key (google-maps)
 * For BASIC providers that declare no authorization header, synthesize
 *   "Authorization: Basic base64(username:password)"
 * reusing the exact pattern from oauth-flow.cjs buildTokenAuth.
 *
 * @param descriptor key descriptor from getProviderConfig() (authMode in KEY_MODES)
 * @param secret { apiKey, username, password, connectionConfig }
 * @returns { headers: {...}, query: {...} } with all ${...} placeholders resolved
 */
function renderAuthHeaders(descriptor, { apiKey, username, password, connectionConfig = {} } = {}) {
  const subst = (tpl) =>
    String(tpl)
      .replace(/\$\{apiKey\}/g, apiKey == null ? '' : String(apiKey))
      .replace(/\$\{connectionConfig\.([^}]+)\}/g, (_, key) => {
        const v = connectionConfig[key.trim()];
        return v === undefined || v === null ? '' : String(v);
      });

  const headers = {};
  for (const [name, tpl] of Object.entries(descriptor.requestHeaders || {})) {
    headers[name] = subst(tpl);
  }
  const query = {};
  for (const [name, tpl] of Object.entries(descriptor.requestQuery || {})) {
    query[name] = subst(tpl);
  }

  // BASIC with no authorization header declared → synthesize one. Same shape as
  // oauth-flow.cjs buildTokenAuth: 'Basic ' + base64(user:pass).
  const hasAuthHeader = Object.keys(headers).some((h) => h.toLowerCase() === 'authorization');
  if (descriptor.authMode === 'BASIC' && !hasAuthHeader) {
    headers.Authorization = 'Basic ' + Buffer.from(`${username || ''}:${password || ''}`).toString('base64');
  }

  return { headers, query };
}

// Google requires FULLY-QUALIFIED scope URLs at its auth endpoint (e.g.
// "https://www.googleapis.com/auth/gmail.readonly"); most other providers use
// bare scope names (GitHub "repo", Slack "channels:read"). Map a provider's
// auth host to the URL prefix its short scope names expand to.
const SCOPE_URL_PREFIX_BY_HOST = {
  'accounts.google.com': 'https://www.googleapis.com/auth/',
};
// Bare scopes that must never be URL-expanded for any provider.
const BARE_SCOPES = new Set(['openid', 'email', 'profile', 'offline_access']);

/**
 * Expand shorthand scopes into the form a provider's auth endpoint expects, so
 * callers can write `--scopes gmail.readonly,calendar.readonly` instead of the
 * full googleapis URLs. Idempotent and safe to call for any provider:
 *   - anything already a URL (contains "://") is left untouched
 *   - bare OIDC scopes (openid/email/profile/offline_access) are left untouched
 *   - for Google-family providers, "gmail.readonly" →
 *     "https://www.googleapis.com/auth/gmail.readonly"
 *   - for bare-scope providers (GitHub, Slack, …) scopes pass through unchanged
 */
const CONN_FIELD_RE = /\$\{connectionConfig\.([^}]+)\}/g;

/** Pull `${connectionConfig.x}` field names out of a template string. */
function extractConnFields(tpl) {
  const out = [];
  if (typeof tpl !== 'string') return out;
  let m;
  CONN_FIELD_RE.lastIndex = 0;
  while ((m = CONN_FIELD_RE.exec(tpl))) out.push(m[1].trim());
  return out;
}

/**
 * The connection_config fields a paste-a-key provider REQUIRES before its base_url
 * (and auth headers/query) can resolve — e.g. Zendesk needs `subdomain`, NetSuite an
 * `accountId`. Returns [] when a single pasted key is enough. Derived from the catalog's
 * own templates so it stays correct across all 349 Class-B providers without per-provider
 * config. A `${cc.x} || https://static.fallback` base_url counts as NOT required (the
 * fallback resolves with no extra input).
 */
function requiredConnectionConfig(providerId) {
  const override = KEY_PROVIDER_OVERRIDES[providerId];
  if (override) {
    const blobs = [override.proxyBaseUrl, ...Object.values(override.requestHeaders || {}), ...Object.values(override.requestQuery || {})];
    return [...new Set(blobs.flatMap(extractConnFields))];
  }
  let raw;
  try {
    raw = providers.getProvider(providerId);
  } catch {
    return [];
  }
  if (!raw || !raw.proxy) return [];
  const fields = new Set();
  if (raw.proxy.base_url) {
    const candidates = String(raw.proxy.base_url).split('||').map((s) => s.trim());
    const hasStaticFallback = candidates.some((c) => !c.includes('${'));
    if (!hasStaticFallback) extractConnFields(candidates[0]).forEach((f) => fields.add(f));
  }
  for (const v of Object.values(raw.proxy.headers || {})) extractConnFields(v).forEach((f) => fields.add(f));
  for (const v of Object.values(raw.proxy.query || {})) extractConnFields(v).forEach((f) => fields.add(f));
  return [...fields];
}

/**
 * Honest coverage tiering for the paste-a-key (Class-B) universe — what the engine can
 * actually connect today, for website claims and gap-tracking. Buckets every API_KEY /
 * BASIC provider:
 *   - singleKeyReady : paste one key, works now (base_url + auth template, no extra fields)
 *   - needsFields    : works once the user supplies connection_config (subdomain, region…)
 *   - needsOverride  : KEY mode but catalog doesn't say where the secret goes (manual override)
 *   - withVerification: has a proxy.verification endpoint → can confirm AND condemn a key live
 *   - genericProbeable : no verification block, but a clean static base + auth template + no
 *                        unmet fields → the connection manager can attempt a CONFIRM-ONLY live
 *                        check (it can go green, but never condemns). Distinct from withVerification.
 * `reachable` = singleKeyReady + needsFields (the defensible "tools you can connect" number).
 */
function keyProviderCoverage() {
  const all = providers.getProviders();
  const buckets = { singleKeyReady: [], needsFields: [], needsOverride: [] };
  let withVerification = 0;
  let genericProbeable = 0;
  for (const [id, p] of Object.entries(all)) {
    if (!KEY_MODES.has(p.auth_mode)) continue;
    const hasVerification = !!(p.proxy && p.proxy.verification);
    if (hasVerification) withVerification++;
    const base = p.proxy && p.proxy.base_url;
    const isBasic = p.auth_mode === 'BASIC';
    const authBlob = JSON.stringify((p.proxy && p.proxy.headers) || {}) + JSON.stringify((p.proxy && p.proxy.query) || {});
    const hasAuthTemplate = isBasic || /\$\{apiKey\}|\$\{api_key\}|\$\{secret\}|\$\{token\}/i.test(authBlob) || /\$\{apiKey\}/.test(String(base || ''));
    if (!base || !hasAuthTemplate) {
      buckets.needsOverride.push(id);
    } else if (requiredConnectionConfig(id).length) {
      buckets.needsFields.push(id);
    } else {
      buckets.singleKeyReady.push(id);
      // A clean single-key provider with no catalog verification → the generic confirm-only probe.
      if (!hasVerification) genericProbeable++;
    }
  }
  const total = buckets.singleKeyReady.length + buckets.needsFields.length + buckets.needsOverride.length;
  return {
    total,
    singleKeyReady: buckets.singleKeyReady.length,
    needsFields: buckets.needsFields.length,
    needsOverride: buckets.needsOverride.length,
    withVerification,
    genericProbeable,
    reachable: buckets.singleKeyReady.length + buckets.needsFields.length,
    buckets,
  };
}

function normalizeScopes(providerId, scopes = []) {
  let host = '';
  try {
    const raw = providers.getProvider(providerId);
    host = new URL(resolveTemplate(raw && raw.authorization_url, {})).host;
  } catch {
    /* unknown provider or templated/missing auth URL → no expansion */
  }
  const prefix = SCOPE_URL_PREFIX_BY_HOST[host];
  if (!prefix) return scopes.map((s) => String(s).trim()).filter(Boolean);
  return scopes
    .map((s) => String(s).trim())
    .filter(Boolean)
    .map((scope) => (scope.includes('://') || BARE_SCOPES.has(scope) ? scope : prefix + scope.replace(/^\/+/, '')));
}

module.exports = {
  getProviderConfig,
  listOAuthProviders,
  listKeyProviders,
  renderAuthHeaders,
  requiredConnectionConfig,
  keyProviderCoverage,
  normalizeScopes,
  resolveTemplate,
  KEY_MODES,
  KEY_HEADER_OVERRIDES,
  VERIFIED_PROVIDERS,
};
