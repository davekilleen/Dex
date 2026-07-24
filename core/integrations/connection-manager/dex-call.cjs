#!/usr/bin/env node
'use strict';
/**
 * dex-call.cjs — the generic "floor": make an authenticated request to any connected app,
 * using a fresh token + the catalog's auth scheme.
 *
 *   node dex-call.cjs <service> [METHOD] <path|url> \
 *        [--query k=v]… [--header "K: V"]… [--body '<json>' | --body-file <f>] [--status] [--raw]
 *
 *   # examples
 *   node dex-call.cjs linear POST /graphql --body '{"query":"{ viewer { name } }"}'
 *   node dex-call.cjs active-campaign /3/contacts --query limit=5
 *
 * Exit codes: 0 ok · 2 not connected · 3 needs re-auth · 4 HTTP 4xx/5xx · 1 other error.
 */

const { resolveAuthContext, secretsOf, redactSecrets } = require('./auth-context.cjs');

const HTTP_VERBS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']);

function hostOf(u) {
  try {
    return new URL(u).host;
  } catch {
    return '';
  }
}

/**
 * Build the concrete request from an auth context + the user's method/path/query/headers/body.
 * PURE (constructs, sends nothing) so it's unit-testable offline.
 *
 * Auth-leak guard: the service's rendered credential is attached ONLY when the target is the
 * service's own host (a relative path, or a full URL on the same host). A full URL pointing at
 * a DIFFERENT host gets no secret — the caller must pass it explicitly via --header. Returns
 * `authAttached` so the CLI can warn.
 */
function buildRequest(ctx, method, pathOrUrl, { query = {}, headers = {}, body } = {}) {
  // Any scheme://… counts as absolute so non-http schemes (file://, ftp://, …) are caught by
  // the protocol guard below rather than silently appended to the base as if they were a path.
  const absolute = /^[a-z][a-z0-9+.-]*:\/\//i.test(pathOrUrl || '');
  let urlStr;
  if (absolute) {
    urlStr = pathOrUrl;
  } else {
    if (!ctx.baseUrl) {
      const e = new Error("No base URL known for this service — pass a full https:// URL as the path.");
      e.exitCode = 1;
      throw e;
    }
    urlStr = ctx.baseUrl.replace(/\/+$/, '') + '/' + String(pathOrUrl || '').replace(/^\/+/, '');
  }
  let url;
  try {
    url = new URL(urlStr);
  } catch {
    const e = new Error(`Invalid URL: ${urlStr}`);
    e.exitCode = 1;
    throw e;
  }
  if (!/^https?:$/.test(url.protocol)) {
    const e = new Error('Only http/https URLs are allowed.');
    e.exitCode = 1;
    throw e;
  }

  const baseHost = ctx.baseUrl ? hostOf(ctx.baseUrl) : '';
  const sameHost = !absolute || (!!baseHost && url.host === baseHost);
  const authHeaders = sameHost ? ctx.headers || {} : {};
  const authQuery = sameHost ? ctx.query || {} : {};

  for (const [k, v] of Object.entries(authQuery)) url.searchParams.set(k, v);
  for (const [k, v] of Object.entries(query)) url.searchParams.set(k, v);
  const finalHeaders = { ...authHeaders, ...headers };

  return {
    url: url.toString(),
    method: (method || (body != null ? 'POST' : 'GET')).toUpperCase(),
    headers: finalHeaders,
    body,
    authAttached: sameHost,
  };
}

function parseArgs(argv) {
  const positional = [];
  const query = {};
  const headers = {};
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--query') {
      const kv = argv[++i] || '';
      const j = kv.indexOf('=');
      if (j > 0) query[kv.slice(0, j)] = kv.slice(j + 1);
    } else if (a === '--header') {
      const h = argv[++i] || '';
      const j = h.indexOf(':');
      if (j > 0) headers[h.slice(0, j).trim()] = h.slice(j + 1).trim();
    } else if (a === '--body') {
      flags.body = argv[++i];
    } else if (a === '--body-file') {
      flags.bodyFile = argv[++i];
    } else if (a === '--status') {
      flags.status = true;
    } else if (a === '--raw') {
      flags.raw = true;
    } else if (a.startsWith('--')) {
      flags[a.slice(2)] = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
    } else {
      positional.push(a);
    }
  }
  const service = positional[0];
  let method;
  let path;
  if (positional[1] && HTTP_VERBS.has(positional[1].toUpperCase())) {
    method = positional[1].toUpperCase();
    path = positional[2];
  } else {
    path = positional[1];
  }
  return { service, method, path, query, headers, flags };
}

/**
 * Send an authenticated request without allowing fetch to replay credentials
 * to a redirect target. Kept injectable for the network-boundary tests.
 */
function fetchAuthenticated(url, options, fetchImpl = globalThis.fetch) {
  return fetchImpl(url, { ...options, redirect: 'error' });
}

async function main() {
  const { service, method, path, query, headers, flags } = parseArgs(process.argv.slice(2));
  if (!service || !path) {
    console.error(
      'Usage: node dex-call.cjs <service> [METHOD] <path|url> [--query k=v]… [--header "K: V"]… [--body <json> | --body-file <f>] [--status] [--raw]'
    );
    process.exit(1);
  }

  let body = flags.body;
  if (flags.bodyFile) body = require('fs').readFileSync(flags.bodyFile, 'utf8');

  let ctx;
  try {
    ctx = await resolveAuthContext(service);
  } catch (e) {
    console.error(e.message);
    process.exit(e.exitCode || 1);
  }

  let req;
  try {
    req = buildRequest(ctx, method, path, { query, headers, body });
  } catch (e) {
    console.error(e.message);
    process.exit(e.exitCode || 1);
  }

  const reqHeaders = { ...req.headers };
  if (req.body != null && !Object.keys(reqHeaders).some((h) => h.toLowerCase() === 'content-type')) {
    reqHeaders['content-type'] = 'application/json';
  }
  if (!req.authAttached) {
    console.error(`note: ${service}'s credential was NOT attached (target host differs from the service base). Add --header if this call needs auth.`);
  }

  // Diagnostics must never echo the credential: the URL can EMBED it (key-in-URL
  // providers like Telegram, or query-param auth), so anything printed about the
  // request goes through redaction first. The response BODY is the user's data
  // and is printed as-is (that is this tool's job).
  const secrets = secretsOf(ctx);

  let res;
  try {
    res = await fetchAuthenticated(req.url, {
      method: req.method,
      headers: reqHeaders,
      body: req.body != null ? req.body : undefined,
      signal: AbortSignal.timeout(30000),
    });
  } catch (e) {
    console.error(redactSecrets(`request failed: ${e.message}`, secrets));
    process.exit(1);
  }

  const text = await res.text();
  if (flags.status) console.error(redactSecrets(`${res.status} ${res.statusText}  ${req.method} ${req.url}`, secrets));
  if (!flags.raw) {
    try {
      process.stdout.write(JSON.stringify(JSON.parse(text), null, 2) + '\n');
    } catch {
      process.stdout.write(text);
    }
  } else {
    process.stdout.write(text);
  }
  if (!res.ok) process.exit(4);
}

if (require.main === module) main();

module.exports = { buildRequest, parseArgs, fetchAuthenticated };
