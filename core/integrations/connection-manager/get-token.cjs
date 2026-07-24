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

const { brokerRequest, exitCodeForError } = require('./broker-client.cjs');
const { GET_TOKEN_EXIT_CODES } = require('./contract.cjs');

async function main() {
  const service = process.argv[2];
  const accessOnly = process.argv.includes('--access-token-only');
  const full = process.argv.includes('--full');
  if (!service) {
    console.error('Usage: node get-token.cjs <service> [--full | --access-token-only]');
    process.exit(GET_TOKEN_EXIT_CODES.error);
  }
  const op = accessOnly ? 'access-token' : full ? 'full' : 'get-token-default';
  let response;
  try {
    response = await brokerRequest({
      op,
      connId: service,
      ...(accessOnly || full ? { privileged: true } : {}),
    });
  } catch (err) {
    console.error(err.message);
    process.exit(GET_TOKEN_EXIT_CODES.error);
  }
  if (!response.ok) {
    const error = response.error || {};
    console.error(
      error.message ||
        (error.category === 'not_connected'
          ? `${service} is not connected.`
          : error.category === 'needs_reauth'
            ? `${service} needs re-authentication. Run: node connect.cjs connect ${service}`
            : 'Credential broker request failed.')
    );
    process.exit(exitCodeForError(error.category));
  }
  if (accessOnly) process.stdout.write(response.value);
  else process.stdout.write(JSON.stringify(full ? response.token : response.value));
}

main();
