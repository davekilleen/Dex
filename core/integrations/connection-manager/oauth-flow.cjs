'use strict';
/**
 * oauth-flow.cjs — The OAuth2 runtime Dex owns. Catalog-driven (config comes from
 * catalog.cjs), local-first (callback is a localhost HTTP server with dynamic port).
 *
 * Implements authorization-code + PKCE, token exchange, and refresh using only Node
 * built-ins (crypto, http, fetch) — no heavy OAuth dependency. Honors the per-provider
 * quirks the Nango catalog encodes: scope_separator, disable_pkce, body_format,
 * token_request_auth_method, and extra authorization/token params.
 */

const http = require('http');
const crypto = require('crypto');

const CALLBACK_PORTS = [3847, 3848, 3849, 3850, 3851, 3852, 3853, 3854, 3855, 3860];

// ---- PKCE -------------------------------------------------------------------

function base64url(buf) {
  return buf.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function makePkce() {
  const verifier = base64url(crypto.randomBytes(32));
  const challenge = base64url(crypto.createHash('sha256').update(verifier).digest());
  return { verifier, challenge };
}

// ---- Localhost callback server ---------------------------------------------

function listenOnFirstFreePort(ports, createServer) {
  return new Promise((resolve, reject) => {
    const tryPort = (i) => {
      if (i >= ports.length) return reject(new Error(`No free port in ${ports[0]}..${ports[ports.length - 1]}`));
      const server = createServer();
      server.once('error', (err) => {
        if (err && err.code === 'EADDRINUSE') tryPort(i + 1);
        else reject(err);
      });
      server.listen(ports[i], '127.0.0.1', () => resolve({ server, port: server.address().port }));
    };
    tryPort(0);
  });
}

/**
 * Start a localhost callback server. Returns:
 *   { redirectUri, waitForCode(): Promise<{code,state}>, close() }
 * waitForCode resolves when the provider redirects back with ?code=...&state=...
 */
async function startCallbackServer({
  ports = CALLBACK_PORTS,
  path = '/callback',
  timeoutMs = 5 * 60 * 1000,
  createServer = () => http.createServer(),
} = {}) {
  const { server, port } = await listenOnFirstFreePort(ports, createServer);
  // Loopback host literal in the redirect_uri. Defaults to 127.0.0.1 (what Google's
  // desktop client is registered with). Salesforce rejects http://127.0.0.1 callbacks
  // ("Cannot be an HTTP URL") and only allows 'localhost', so set
  // DEX_OAUTH_CALLBACK_HOST=localhost for it. The server still binds 127.0.0.1; the
  // browser resolves localhost → 127.0.0.1 so the loopback still hits us.
  const host = process.env.DEX_OAUTH_CALLBACK_HOST || '127.0.0.1';
  const redirectUri = `http://${host}:${port}${path}`;

  const waitForCode = ({ expectedState } = {}) =>
    new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        server.close();
        reject(new Error(`OAuth callback timed out after ${timeoutMs}ms.`));
      }, timeoutMs);

      server.on('request', (req, res) => {
        const url = new URL(req.url, redirectUri);
        if (url.pathname !== path) {
          res.writeHead(404).end();
          return;
        }
        const error = url.searchParams.get('error');
        const code = url.searchParams.get('code');
        const state = url.searchParams.get('state');
        const stateMismatch = expectedState !== undefined && state !== expectedState;
        res.writeHead(stateMismatch ? 400 : 200, { 'Content-Type': 'text/html' });
        res.end(
          stateMismatch
            ? '<html><body style="font-family:system-ui;padding:3rem;text-align:center"><h2>Connection aborted</h2><p>OAuth state mismatch.</p></body></html>'
            : error
            ? `<html><body style="font-family:system-ui;padding:3rem;text-align:center"><h2>Connection failed</h2><p>${error}</p><p>You can close this tab and return to Dex.</p></body></html>`
            : `<html><body style="font-family:system-ui;padding:3rem;text-align:center"><h2>✅ Connected</h2><p>You can close this tab and return to Dex.</p></body></html>`
        );
        clearTimeout(timeout);
        server.close();
        if (stateMismatch) reject(new Error('OAuth state mismatch — possible CSRF, aborting.'));
        else if (error) reject(new Error(`Provider returned error: ${error}`));
        else resolve({ code, state });
      });
    });

  return { redirectUri, waitForCode, close: () => server.listening && server.close() };
}

// ---- Authorization URL ------------------------------------------------------

/**
 * Build the provider authorization URL.
 * @param providerConfig from catalog.getProviderConfig()
 * @param opts { clientId, scopes:[], redirectUri }
 * @returns { url, codeVerifier, state }
 */
function buildAuthorizationUrl(providerConfig, { clientId, scopes = [], redirectUri }) {
  const url = new URL(providerConfig.authorizationUrl);
  const params = url.searchParams;

  // Defaults + catalog-declared authorization_params (response_type, access_type, prompt, ...)
  params.set('response_type', 'code');
  for (const [k, v] of Object.entries(providerConfig.authorizationParams || {})) params.set(k, String(v));

  params.set('client_id', clientId);
  params.set('redirect_uri', redirectUri);

  const allScopes = scopes.length ? scopes : providerConfig.defaultScopes || [];
  if (allScopes.length) params.set('scope', allScopes.join(providerConfig.scopeSeparator || ' '));

  const state = base64url(crypto.randomBytes(16));
  params.set('state', state);

  let codeVerifier = null;
  if (providerConfig.usePkce) {
    const pkce = makePkce();
    codeVerifier = pkce.verifier;
    params.set('code_challenge', pkce.challenge);
    params.set('code_challenge_method', 'S256');
  }

  return { url: url.toString(), codeVerifier, state };
}

// ---- Token exchange / refresh ----------------------------------------------

function buildTokenAuth(providerConfig, clientId, clientSecret, body) {
  const headers = { Accept: 'application/json' };
  if (providerConfig.tokenRequestAuthMethod === 'basic') {
    headers.Authorization = 'Basic ' + Buffer.from(`${clientId}:${clientSecret}`).toString('base64');
  } else {
    body.client_id = clientId;
    if (clientSecret) body.client_secret = clientSecret;
  }
  return headers;
}

async function postToken(providerConfig, body, headers) {
  let payload;
  if (providerConfig.bodyFormat === 'json') {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  } else {
    headers['Content-Type'] = 'application/x-www-form-urlencoded';
    payload = new URLSearchParams(body).toString();
  }
  const res = await fetch(providerConfig.tokenUrl, { method: 'POST', headers, body: payload });
  const text = await res.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = { raw: text };
  }
  if (!res.ok) {
    const err = new Error(`Token endpoint ${res.status}: ${json.error || text.slice(0, 200)}`);
    err.status = res.status;
    err.body = json;
    throw err;
  }
  return json;
}

function valueAtPath(value, dottedPath) {
  if (!dottedPath) return undefined;
  return String(dottedPath)
    .split('.')
    .reduce((current, key) => (current && typeof current === 'object' ? current[key] : undefined), value);
}

function normalizeToken(json, previous = {}, providerConfig = {}) {
  const expiresInMs = json.expires_in ? Number(json.expires_in) * 1000 : null;
  return {
    access_token: valueAtPath(json, providerConfig.alternateAccessTokenResponsePath) || json.access_token,
    // Some providers don't return a new refresh_token on refresh — keep the old one.
    refresh_token: json.refresh_token || previous.refresh_token || null,
    token_type: json.token_type || 'Bearer',
    scope: json.scope || previous.scope || null,
    expires_at: expiresInMs ? Date.now() + expiresInMs : previous.expires_at || null,
    obtained_at: Date.now(),
    // Provider-specific fields some APIs require to make calls (e.g. Salesforce's
    // per-org instance_url and identity id). Surfaced at the top level and kept
    // across refreshes via `previous` (Salesforce returns them on refresh too).
    ...(json.instance_url || previous.instance_url ? { instance_url: json.instance_url || previous.instance_url } : {}),
    ...(json.id || previous.id ? { id: json.id || previous.id } : {}),
    raw: json,
  };
}

/** Exchange an authorization code for tokens. */
async function exchangeCodeForToken(providerConfig, { code, codeVerifier, clientId, clientSecret, redirectUri }) {
  const body = {
    grant_type: 'authorization_code',
    code,
    redirect_uri: redirectUri,
    ...providerConfig.tokenParams,
  };
  if (codeVerifier) body.code_verifier = codeVerifier;
  const headers = buildTokenAuth(providerConfig, clientId, clientSecret, body);
  return normalizeToken(await postToken(providerConfig, body, headers), {}, providerConfig);
}

module.exports = {
  startCallbackServer,
  buildAuthorizationUrl,
  exchangeCodeForToken,
  makePkce,
  CALLBACK_PORTS,
};
