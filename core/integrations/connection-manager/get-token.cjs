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
 *   OAuth, no flag      → full token JSON (contains `access_token`, refresh_token, expiry…).
 *                         pp-gmail and other consumers rely on `access_token` being present.
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

async function main() {
  const service = process.argv[2];
  const accessOnly = process.argv.includes('--access-token-only');
  if (!service) {
    console.error('Usage: node get-token.cjs <service> [--access-token-only]');
    process.exit(1);
  }
  const token = store.loadToken(service);
  if (!token) {
    console.error(`${service} is not connected.`);
    process.exit(2);
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
      process.stdout.write(JSON.stringify(apiKeyContext(token, service)));
      return;
    }

    const accessToken = await health.ensureFreshToken(service);
    store.touchUsed(service);
    if (accessOnly) {
      process.stdout.write(accessToken);
    } else {
      process.stdout.write(JSON.stringify(store.loadToken(service)));
    }
  } catch (err) {
    if (err.needsReauth) {
      console.error(`${service} needs re-authentication. Run: node connect.cjs connect ${service}`);
      process.exit(3);
    }
    console.error(err.message);
    process.exit(1);
  }
}

main();
