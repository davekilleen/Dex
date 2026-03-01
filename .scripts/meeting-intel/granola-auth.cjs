#!/usr/bin/env node

/**
 * Dex Meeting Intel — Granola MCP OAuth 2.0 Authentication
 *
 * Handles the full OAuth 2.0 flow for Granola's official MCP server:
 *   1. OAuth metadata discovery (RFC 8414)
 *   2. Dynamic Client Registration (DCR)
 *   3. Browser-based user authorization with PKCE (RFC 7636)
 *   4. Token exchange and persistent storage
 *   5. Token refresh
 *
 * CLI:
 *   node granola-auth.cjs              # Run full OAuth flow
 *   node granola-auth.cjs --setup      # Run full OAuth flow
 *   node granola-auth.cjs --status     # Check if tokens exist and are valid
 *   node granola-auth.cjs --refresh    # Force token refresh
 *   node granola-auth.cjs --revoke     # Delete stored tokens
 *
 * Uses ONLY Node.js built-in modules — no npm dependencies.
 */

'use strict';

const https = require('https');
const http = require('http');
const crypto = require('crypto');
const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');
const url = require('url');

// ─── Constants ───────────────────────────────────────────────────────────────

const MCP_ORIGIN = 'https://mcp.granola.ai';
const OAUTH_METADATA_PATH = '/.well-known/oauth-authorization-server';
const OPENID_CONFIG_PATH = '/.well-known/openid-configuration';
const CALLBACK_PORT = 8914;
const CALLBACK_URI = `http://localhost:${CALLBACK_PORT}/callback`;
const AUTH_TIMEOUT_MS = 120_000; // 2 minutes
const CLIENT_NAME = 'Dex Meeting Intel';

const TOKEN_DIR = path.join(os.homedir(), '.config', 'dex');
const TOKEN_FILE = path.join(TOKEN_DIR, 'granola-tokens.json');

// ─── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Make an HTTPS GET request and return the parsed JSON body.
 */
function httpsGetJSON(targetUrl) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(targetUrl);
    const options = {
      hostname: parsed.hostname,
      port: parsed.port || 443,
      path: parsed.pathname + parsed.search,
      method: 'GET',
      headers: { 'Accept': 'application/json' },
    };
    const req = https.request(options, (res) => {
      let body = '';
      res.on('data', (chunk) => { body += chunk; });
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try { resolve(JSON.parse(body)); }
          catch (e) { reject(new Error(`Invalid JSON from ${targetUrl}: ${e.message}`)); }
        } else {
          reject(new Error(`HTTP ${res.statusCode} from ${targetUrl}: ${body.slice(0, 200)}`));
        }
      });
    });
    req.on('error', reject);
    req.setTimeout(15_000, () => { req.destroy(); reject(new Error(`Timeout fetching ${targetUrl}`)); });
    req.end();
  });
}

/**
 * Make an HTTPS POST request with a URL-encoded or JSON body and return parsed JSON.
 */
function httpsPost(targetUrl, body, contentType) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(targetUrl);
    const payload = typeof body === 'string' ? body : JSON.stringify(body);
    const ct = contentType || (typeof body === 'string'
      ? 'application/x-www-form-urlencoded'
      : 'application/json');

    const options = {
      hostname: parsed.hostname,
      port: parsed.port || 443,
      path: parsed.pathname + parsed.search,
      method: 'POST',
      headers: {
        'Content-Type': ct,
        'Content-Length': Buffer.byteLength(payload),
        'Accept': 'application/json',
      },
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try { resolve(JSON.parse(data)); }
          catch (e) { reject(new Error(`Invalid JSON response: ${e.message}`)); }
        } else {
          reject(new Error(`HTTP ${res.statusCode} from POST ${targetUrl}: ${data.slice(0, 300)}`));
        }
      });
    });
    req.on('error', reject);
    req.setTimeout(15_000, () => { req.destroy(); reject(new Error(`Timeout posting to ${targetUrl}`)); });
    req.write(payload);
    req.end();
  });
}

/**
 * Generate a cryptographically random string of the given byte length, base64url-encoded.
 */
function randomBase64url(byteLength) {
  return crypto.randomBytes(byteLength)
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

/**
 * Compute the PKCE code_challenge from a code_verifier (S256).
 */
function pkceChallenge(verifier) {
  return crypto
    .createHash('sha256')
    .update(verifier)
    .digest('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

/**
 * URL-encode an object as application/x-www-form-urlencoded.
 */
function urlEncode(obj) {
  return Object.entries(obj)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&');
}

/**
 * Open a URL in the user's default browser (cross-platform).
 */
function openBrowser(targetUrl) {
  return new Promise((resolve, reject) => {
    const platform = process.platform;
    let cmd;
    if (platform === 'darwin') cmd = `open "${targetUrl}"`;
    else if (platform === 'win32') cmd = `start "" "${targetUrl}"`;
    else cmd = `xdg-open "${targetUrl}"`;

    exec(cmd, (err) => {
      if (err) reject(new Error(`Failed to open browser: ${err.message}`));
      else resolve();
    });
  });
}

/**
 * Read stored tokens from disk. Returns null if not found or unreadable.
 */
function readTokens() {
  try {
    if (!fs.existsSync(TOKEN_FILE)) return null;
    const raw = fs.readFileSync(TOKEN_FILE, 'utf-8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Write tokens to disk, creating the directory if needed.
 */
function writeTokens(tokens) {
  if (!fs.existsSync(TOKEN_DIR)) {
    fs.mkdirSync(TOKEN_DIR, { recursive: true });
  }
  fs.writeFileSync(TOKEN_FILE, JSON.stringify(tokens, null, 2), 'utf-8');
}

// ─── OAuth Flow Steps ────────────────────────────────────────────────────────

/**
 * Step 1 — Discover OAuth metadata from the MCP server.
 * Tries RFC 8414 first, falls back to OpenID Connect discovery.
 */
async function discoverOAuthMetadata() {
  console.log('  Discovering OAuth metadata...');
  try {
    const meta = await httpsGetJSON(`${MCP_ORIGIN}${OAUTH_METADATA_PATH}`);
    console.log('  Found OAuth Authorization Server metadata.');
    return meta;
  } catch (err1) {
    console.log(`  RFC 8414 discovery failed (${err1.message}), trying OpenID Configuration...`);
    try {
      const meta = await httpsGetJSON(`${MCP_ORIGIN}${OPENID_CONFIG_PATH}`);
      console.log('  Found OpenID Configuration metadata.');
      return meta;
    } catch (err2) {
      throw new Error(
        `Could not discover OAuth metadata from ${MCP_ORIGIN}.\n` +
        `  RFC 8414: ${err1.message}\n` +
        `  OpenID:   ${err2.message}`
      );
    }
  }
}

/**
 * Step 2 — Dynamic Client Registration.
 * Registers this application with the authorization server.
 */
async function registerClient(registrationEndpoint) {
  console.log('  Registering client with Granola...');
  const registration = await httpsPost(registrationEndpoint, {
    client_name: CLIENT_NAME,
    redirect_uris: [CALLBACK_URI],
    grant_types: ['authorization_code', 'refresh_token'],
    response_types: ['code'],
    token_endpoint_auth_method: 'client_secret_post',
  });

  if (!registration.client_id) {
    throw new Error('Dynamic Client Registration did not return a client_id');
  }

  console.log(`  Client registered: ${registration.client_id.slice(0, 12)}...`);
  return registration;
}

/**
 * Step 3 — User Authorization.
 * Opens the browser and waits for the OAuth callback on a local HTTP server.
 * Returns the authorization code.
 */
async function authorizeUser(authorizationEndpoint, clientId, codeVerifier) {
  const state = randomBase64url(16);
  const codeChallenge = pkceChallenge(codeVerifier);

  const params = urlEncode({
    response_type: 'code',
    client_id: clientId,
    redirect_uri: CALLBACK_URI,
    scope: 'openid',
    state: state,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
  });

  const authUrl = `${authorizationEndpoint}?${params}`;

  return new Promise((resolve, reject) => {
    let settled = false;

    const callbackHTML = `<!DOCTYPE html>
<html>
<head><title>Dex - Authorization Complete</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         display: flex; justify-content: center; align-items: center; height: 100vh;
         margin: 0; background: #f9fafb; color: #1a1a1a; }
  .card { text-align: center; padding: 3rem; background: white; border-radius: 12px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.08); max-width: 400px; }
  h1 { font-size: 1.4rem; margin-bottom: 0.5rem; }
  p { color: #6b7280; font-size: 0.95rem; }
</style>
</head>
<body>
  <div class="card">
    <h1>Authorization complete!</h1>
    <p>You can close this tab and return to your terminal.</p>
  </div>
</body>
</html>`;

    const server = http.createServer((req, res) => {
      if (settled) { res.end(); return; }

      const parsed = url.parse(req.url, true);
      if (parsed.pathname !== '/callback') {
        res.writeHead(404);
        res.end('Not found');
        return;
      }

      const { code, state: returnedState, error, error_description } = parsed.query;

      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(callbackHTML);

      settled = true;
      server.close();

      if (error) {
        reject(new Error(`Authorization denied: ${error} — ${error_description || 'no details'}`));
        return;
      }

      if (returnedState !== state) {
        reject(new Error('OAuth state mismatch — possible CSRF. Please try again.'));
        return;
      }

      if (!code) {
        reject(new Error('No authorization code received in callback.'));
        return;
      }

      resolve(code);
    });

    server.on('error', (err) => {
      if (!settled) {
        settled = true;
        reject(new Error(`Callback server error: ${err.message}. Is port ${CALLBACK_PORT} in use?`));
      }
    });

    server.listen(CALLBACK_PORT, '127.0.0.1', async () => {
      console.log('  Opening browser for authorization...');
      try {
        await openBrowser(authUrl);
        console.log('  Waiting for authorization (up to 2 minutes)...');
      } catch (browserErr) {
        console.log(`  Could not open browser automatically: ${browserErr.message}`);
        console.log('');
        console.log('  Please open this URL manually:');
        console.log(`  ${authUrl}`);
        console.log('');
      }
    });

    // Timeout after AUTH_TIMEOUT_MS
    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true;
        server.close();
        reject(new Error('Authorization timed out after 2 minutes. Please try again.'));
      }
    }, AUTH_TIMEOUT_MS);

    // Clean up timeout when server closes
    server.on('close', () => clearTimeout(timeout));
  });
}

/**
 * Step 4 — Exchange authorization code for tokens.
 */
async function exchangeCode(tokenEndpoint, code, clientId, clientSecret, codeVerifier) {
  console.log('  Exchanging authorization code for tokens...');
  const body = urlEncode({
    grant_type: 'authorization_code',
    code: code,
    redirect_uri: CALLBACK_URI,
    client_id: clientId,
    client_secret: clientSecret,
    code_verifier: codeVerifier,
  });

  const tokenResponse = await httpsPost(tokenEndpoint, body);

  if (!tokenResponse.access_token) {
    throw new Error('Token exchange did not return an access_token');
  }

  return tokenResponse;
}

// ─── Exported Functions ──────────────────────────────────────────────────────

/**
 * Run the full OAuth 2.0 authentication flow (interactive, opens browser).
 */
async function authenticate() {
  console.log('');
  console.log('Granola MCP — OAuth Authentication');
  console.log('──────────────────────────────────');
  console.log('');

  // Step 1: Discover metadata
  const metadata = await discoverOAuthMetadata();

  const {
    authorization_endpoint,
    token_endpoint,
    registration_endpoint,
  } = metadata;

  if (!authorization_endpoint || !token_endpoint) {
    throw new Error('OAuth metadata missing authorization_endpoint or token_endpoint');
  }

  // Step 2: Dynamic Client Registration
  let clientId, clientSecret;
  const existingTokens = readTokens();

  if (existingTokens && existingTokens.client_id && existingTokens.client_secret) {
    // Reuse existing client registration
    console.log('  Reusing existing client registration.');
    clientId = existingTokens.client_id;
    clientSecret = existingTokens.client_secret;
  } else if (registration_endpoint) {
    const reg = await registerClient(registration_endpoint);
    clientId = reg.client_id;
    clientSecret = reg.client_secret || '';
  } else {
    throw new Error(
      'No registration_endpoint in OAuth metadata and no existing client_id. ' +
      'Cannot proceed without client credentials.'
    );
  }

  // Step 3: PKCE + User Authorization
  const codeVerifier = randomBase64url(32);
  const code = await authorizeUser(authorization_endpoint, clientId, codeVerifier);
  console.log('  Authorization code received.');

  // Step 4: Token Exchange
  const tokenResponse = await exchangeCode(
    token_endpoint, code, clientId, clientSecret, codeVerifier
  );

  // Step 5: Store tokens
  const now = Date.now();
  const expiresIn = tokenResponse.expires_in || 3600;
  const tokens = {
    access_token: tokenResponse.access_token,
    refresh_token: tokenResponse.refresh_token || null,
    expires_at: Math.floor(now / 1000) + expiresIn,
    client_id: clientId,
    client_secret: clientSecret,
    token_endpoint: token_endpoint,
    authorization_endpoint: authorization_endpoint,
    created_at: new Date(now).toISOString(),
  };

  writeTokens(tokens);
  console.log('');
  console.log(`  Tokens saved to ${TOKEN_FILE}`);
  console.log('  Expires in: ' + formatDuration(expiresIn));
  console.log('');
  console.log('Done! Granola MCP authentication is ready.');
  console.log('');

  return tokens;
}

/**
 * Refresh the access token using the stored refresh_token.
 * Returns the new access_token.
 */
async function refreshToken() {
  const tokens = readTokens();
  if (!tokens) {
    throw new Error('No stored tokens found. Run authentication first.');
  }
  if (!tokens.refresh_token) {
    throw new Error('No refresh_token stored. Re-authenticate with: node granola-auth.cjs --setup');
  }
  if (!tokens.token_endpoint) {
    throw new Error('No token_endpoint stored. Re-authenticate with: node granola-auth.cjs --setup');
  }

  console.log('  Refreshing access token...');

  const body = urlEncode({
    grant_type: 'refresh_token',
    refresh_token: tokens.refresh_token,
    client_id: tokens.client_id,
    client_secret: tokens.client_secret,
  });

  const response = await httpsPost(tokens.token_endpoint, body);

  if (!response.access_token) {
    throw new Error('Token refresh did not return an access_token. Re-authenticate.');
  }

  const now = Date.now();
  const expiresIn = response.expires_in || 3600;

  tokens.access_token = response.access_token;
  if (response.refresh_token) {
    tokens.refresh_token = response.refresh_token;
  }
  tokens.expires_at = Math.floor(now / 1000) + expiresIn;

  writeTokens(tokens);
  console.log('  Token refreshed. Expires in: ' + formatDuration(expiresIn));

  return tokens.access_token;
}

/**
 * Get the current access token, refreshing automatically if expired.
 * Returns the access_token string.
 */
async function getAccessToken() {
  const tokens = readTokens();
  if (!tokens || !tokens.access_token) {
    throw new Error('No stored tokens. Run: node granola-auth.cjs --setup');
  }

  const now = Math.floor(Date.now() / 1000);
  const bufferSeconds = 60; // refresh 60s before actual expiry

  if (tokens.expires_at && now >= (tokens.expires_at - bufferSeconds)) {
    if (tokens.refresh_token) {
      console.log('  Access token expired, refreshing...');
      return await refreshToken();
    } else {
      throw new Error('Access token expired and no refresh_token available. Re-authenticate.');
    }
  }

  return tokens.access_token;
}

/**
 * Check if valid (non-expired) tokens exist.
 * Returns true/false without throwing.
 */
function isAuthenticated() {
  const tokens = readTokens();
  if (!tokens || !tokens.access_token) return false;

  const now = Math.floor(Date.now() / 1000);
  // Consider authenticated if token hasn't expired OR we have a refresh token
  if (tokens.expires_at && now >= tokens.expires_at) {
    return !!tokens.refresh_token;
  }
  return true;
}

/**
 * Returns the path to the tokens file.
 */
function getTokenPath() {
  return TOKEN_FILE;
}

/**
 * Delete stored tokens.
 */
function revokeTokens() {
  if (fs.existsSync(TOKEN_FILE)) {
    fs.unlinkSync(TOKEN_FILE);
    console.log(`  Tokens deleted: ${TOKEN_FILE}`);
    return true;
  }
  console.log('  No tokens file found — nothing to revoke.');
  return false;
}

// ─── Utilities ───────────────────────────────────────────────────────────────

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

// ─── CLI ─────────────────────────────────────────────────────────────────────

async function cli() {
  const arg = process.argv[2] || '--setup';

  switch (arg) {
    case '--setup':
      try {
        await authenticate();
        process.exit(0);
      } catch (err) {
        console.error('');
        console.error(`Authentication failed: ${err.message}`);
        process.exit(1);
      }
      break;

    case '--status': {
      console.log('');
      console.log('Granola MCP — Auth Status');
      console.log('─────────────────────────');
      const tokens = readTokens();
      if (!tokens) {
        console.log('  Status: Not authenticated');
        console.log(`  Tokens file: ${TOKEN_FILE} (not found)`);
        console.log('');
        console.log('  Run: node granola-auth.cjs --setup');
        process.exit(1);
      }

      const now = Math.floor(Date.now() / 1000);
      const expired = tokens.expires_at && now >= tokens.expires_at;
      const hasRefresh = !!tokens.refresh_token;
      const ttl = tokens.expires_at ? tokens.expires_at - now : 0;

      console.log(`  Status: ${expired ? (hasRefresh ? 'Expired (refresh available)' : 'Expired') : 'Active'}`);
      console.log(`  Tokens file: ${TOKEN_FILE}`);
      console.log(`  Client ID: ${tokens.client_id ? tokens.client_id.slice(0, 16) + '...' : 'none'}`);
      console.log(`  Access token: ${tokens.access_token ? tokens.access_token.slice(0, 12) + '...' : 'none'}`);
      console.log(`  Refresh token: ${hasRefresh ? 'present' : 'none'}`);
      if (!expired && ttl > 0) {
        console.log(`  Expires in: ${formatDuration(ttl)}`);
      } else if (expired) {
        console.log(`  Expired: ${formatDuration(Math.abs(ttl))} ago`);
      }
      console.log(`  Created: ${tokens.created_at || 'unknown'}`);
      console.log(`  Token endpoint: ${tokens.token_endpoint || 'unknown'}`);
      console.log('');
      process.exit(expired && !hasRefresh ? 1 : 0);
      break;
    }

    case '--refresh':
      try {
        console.log('');
        const newToken = await refreshToken();
        console.log(`  New access token: ${newToken.slice(0, 12)}...`);
        console.log('');
        process.exit(0);
      } catch (err) {
        console.error(`Refresh failed: ${err.message}`);
        process.exit(1);
      }
      break;

    case '--revoke':
      console.log('');
      console.log('Granola MCP — Revoking Tokens');
      console.log('─────────────────────────────');
      revokeTokens();
      console.log('');
      process.exit(0);
      break;

    default:
      console.log('Usage:');
      console.log('  node granola-auth.cjs              Run full OAuth flow');
      console.log('  node granola-auth.cjs --setup      Run full OAuth flow');
      console.log('  node granola-auth.cjs --status     Check token status');
      console.log('  node granola-auth.cjs --refresh    Force token refresh');
      console.log('  node granola-auth.cjs --revoke     Delete stored tokens');
      process.exit(1);
  }
}

// ─── Module Exports ──────────────────────────────────────────────────────────

module.exports = {
  authenticate,
  getAccessToken,
  refreshToken,
  isAuthenticated,
  getTokenPath,
  revokeTokens,
};

// ─── Run CLI if executed directly ────────────────────────────────────────────

if (require.main === module) {
  cli();
}
