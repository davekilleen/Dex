#!/usr/bin/env node
'use strict';
/**
 * get-token.cjs — Accessor for OTHER runtimes (the Python FastMCP servers).
 * Refreshes if needed, then prints the fresh token JSON to stdout. This is how
 * Python reads credentials without needing the encryption key:
 *
 *   token = json.loads(subprocess.check_output(
 *       ["node", "get-token.cjs", "google", "--access-token-only"]))
 *
 * Output asymmetry (by auth class):
 *   OAuth, no flag      → least-privilege JSON { access_token, expires_at }.
 *   OAuth, --full       → full stored token JSON, including refresh_token.
 *   Class-B, no flag    → request envelope { kind:'api_key', baseUrl, headers, query } with the
 *                         auth scheme already rendered (NOT the raw key).
 *   any, --access-token-only → the raw bearer token (OAuth) or raw secret (Class-B).
 * The service id may be `provider` or `provider:alias` (multi-account); bare ids resolve to the default.
 *
 * Exit codes: 0 ok · 2 not connected · 3 needs re-auth · 1 other error.
 */

const health = require('./health.cjs');
const store = require('./token-store.cjs');
const { apiKeyContext } = require('./auth-context.cjs');
const { GET_TOKEN_EXIT_CODES } = require('./contract.cjs');

async function main() {
  const service = process.argv[2];
  const accessOnly = process.argv.includes('--access-token-only');
  const full = process.argv.includes('--full');
  if (!service) {
    console.error('Usage: node get-token.cjs <service> [--full | --access-token-only]');
    process.exit(GET_TOKEN_EXIT_CODES.error);
  }
  let token;
  try {
    token = store.loadToken(service);
  } catch (err) {
    console.error(err.message);
    process.exit(err.code === 'DEX_CM_KEY_LOST' ? GET_TOKEN_EXIT_CODES.needs_reauth : GET_TOKEN_EXIT_CODES.error);
  }
  if (!token) {
    // A corrupt token file was quarantined and stamped by loadToken; that is a
    // reconnect (exit 3 with the reason), not a plain "not connected" (exit 2).
    const reg = store.getConnection(service);
    if (reg && reg.error) {
      console.error(`${service} needs re-authentication (${reg.error}). Run: node connect.cjs connect ${service}`);
      process.exit(GET_TOKEN_EXIT_CODES.needs_reauth);
    }
    console.error(`${service} is not connected.`);
    process.exit(GET_TOKEN_EXIT_CODES.not_connected);
  }
  try {
    // Class B (paste-a-key): no refresh. Emit the raw secret (--access-token-only)
    // or a JSON envelope with the catalog's auth scheme already rendered, so the
    // consumer never re-implements per-provider header/query placement.
    if (token.kind === 'api_key') {
      store.touchUsed(service);
      if (accessOnly) {
        process.stdout.write(token.apiKey || token.password || '');
        return;
      }
      // Render the auth scheme via the shared seam (same context dex-call uses).
      const { apiKey: _rawSecret, ...rendered } = apiKeyContext(token, service);
      process.stdout.write(JSON.stringify(rendered));
      return;
    }

    const accessToken = await health.ensureFreshToken(service);
    store.touchUsed(service);
    if (accessOnly) {
      process.stdout.write(accessToken);
    } else {
      const fresh = store.loadToken(service);
      process.stdout.write(
        JSON.stringify(full ? fresh : { access_token: fresh.access_token, expires_at: fresh.expires_at || null })
      );
    }
  } catch (err) {
    if (err.needsReauth) {
      console.error(`${service} needs re-authentication. Run: node connect.cjs connect ${service}`);
      process.exit(GET_TOKEN_EXIT_CODES.needs_reauth);
    }
    console.error(err.message);
    process.exit(GET_TOKEN_EXIT_CODES.error);
  }
}

main();
