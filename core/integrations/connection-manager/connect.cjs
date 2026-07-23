#!/usr/bin/env node
'use strict';
/**
 * connect.cjs — CLI orchestration for the connection manager. Backs the future
 * `/connect` skill and the health checks in `/daily-plan`.
 *
 *   node connect.cjs connect <provider> [--scopes a,b,c] [--as <alias>] [--default]
 *                                                           run OAuth, store token (--as = 2nd account)
 *   node connect.cjs set-key <provider> [--username <u>] [--as <alias>] [--default]
 *                                                           paste-a-key (Class B); secret via stdin only
 *   node connect.cjs register-app <provider> [--client-id ID]
 *                                                           save an OAuth app; secret via stdin only
 *   node connect.cjs status                                 health sweep (monitor view)
 *   node connect.cjs refresh <conn> [--force]               refresh if needed; --force always calls provider
 *   node connect.cjs disconnect <conn>                      delete local token (conn = provider or provider:alias)
 *   node connect.cjs providers [filter] [--keys]            list OAuth (or paste-a-key) providers
 *   node connect.cjs describe <provider>                    show what's needed to connect it
 *   node connect.cjs coverage                               paste-a-key coverage tiering (counts)
 *   node connect.cjs authurl <provider> [--scopes ...]      print auth URL only (dry, no browser)
 */

const fs = require('fs');
const catalog = require('./catalog.cjs');
const store = require('./token-store.cjs');
const oauth = require('./oauth-flow.cjs');
const health = require('./health.cjs');

function parseFlags(args) {
  const flags = {};
  const positional = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i].startsWith('--')) {
      const key = args[i].slice(2);
      const val = args[i + 1] && !args[i + 1].startsWith('--') ? args[++i] : 'true';
      flags[key] = val;
    } else positional.push(args[i]);
  }
  return { flags, positional };
}

function openBrowser(url) {
  const { spawn } = require('child_process');
  const cmd = process.platform === 'darwin' ? 'open' : process.platform === 'win32' ? 'start' : 'xdg-open';
  spawn(cmd, [url], { stdio: 'ignore', detached: true }).unref();
}

async function cmdConnect(provider, flags) {
  if (!provider) throw new Error('Usage: node connect.cjs connect <provider> [--scopes a,b,c] [--as <alias>]');
  const providerConfig = catalog.getProviderConfig(provider);
  if (!providerConfig.supported) {
    throw new Error(`'${provider}' is not connectable yet: ${providerConfig.reason} It remains available to browse in providers.`);
  }
  if (!providerConfig.verified) {
    console.log('Unverified provider — advanced tier, expect quirks.');
  }
  // Multi-account: `--as <alias>` connects a second account (provider:alias); bare = the default.
  const { connId, alias } = store.parseConnectionId(flags.as ? `${provider}:${flags.as}` : provider);
  const app = store.getOAuthApp(provider); // OAuth app is shared across a provider's accounts
  if (!app || !app.clientId) {
    // Non-technical ICP: the user never hand-edits a file. The /connect skill captures the
    // client id/secret in chat and runs `register-app` to write them — this error just routes there.
    console.error(
      `'${provider}' has no OAuth app registered yet.\n` +
        `Dex can set this up with you — no file editing. It will ask for the client id and secret\n` +
        `from ${provider}'s developer console and save them for you:\n` +
        `  node connect.cjs register-app ${provider}      (paste client id, then secret, on stdin)\n` +
        `Then: node connect.cjs connect ${provider}`
    );
    process.exit(1);
  }
  const scopes = catalog.normalizeScopes(provider, flags.scopes ? flags.scopes.split(',') : []);

  const cb = await oauth.startCallbackServer();
  const { url, codeVerifier, state } = oauth.buildAuthorizationUrl(providerConfig, {
    clientId: app.clientId,
    scopes,
    redirectUri: cb.redirectUri,
  });

  console.log(`\nOpening browser to connect ${providerConfig.displayName}${alias ? ` (as ${alias})` : ''}…`);
  console.log(`(If it doesn't open, visit:)\n${url}\n`);
  openBrowser(url);

  const { code } = await cb.waitForCode({ expectedState: state });

  const token = await oauth.exchangeCodeForToken(providerConfig, {
    code,
    codeVerifier,
    clientId: app.clientId,
    clientSecret: app.clientSecret,
    redirectUri: cb.redirectUri,
  });
  store.saveToken(connId, token, { provider: providerConfig.id });
  if (flags.default) store.setDefault(provider, alias);
  console.log(`✅ Connected ${providerConfig.displayName}${alias ? ` (${connId})` : ''}. Token stored (encrypted) in ${store.credentialsDir()}/tokens/.`);
}

/**
 * Register a provider's OAuth app (client id + secret) WITHOUT the user opening any file.
 * The /connect skill drives this conversationally: it asks for each value and pipes it here.
 * Reads the client id from `--client-id` or stdin. The secret always comes from
 * stdin so it never appears in process listings or shell history.
 * Public clients (PKCE, no secret) pass an empty secret.
 */
function cmdRegisterApp(provider, flags) {
  if (!provider) throw new Error('Usage: node connect.cjs register-app <provider> [--client-id ID] (secret via stdin)');
  if (flags['client-secret'] !== undefined) {
    throw new Error('--client-secret is not accepted; pipe the client secret on stdin.');
  }
  let clientId = flags['client-id'];
  const piped = (readStdin() || '').split(/\r?\n/).map((s) => s.trim());
  const clientSecret = clientId === undefined ? piped[1] || '' : piped[0] || '';
  if (clientId === undefined) clientId = piped[0] || '';
  if (!clientId) throw new Error(`No client id provided for '${provider}'. Pass --client-id or pipe it on stdin.`);
  store.setOAuthApp(provider, { clientId, clientSecret: clientSecret || '' });
  console.log(`✅ Registered OAuth app for ${provider} (saved to ${store.credentialsDir()}/oauth-apps.json). Now: node connect.cjs connect ${provider}`);
}

/** Read a secret from stdin (the default for set-key). Returns undefined if nothing is piped. */
function readStdin() {
  try {
    const data = fs.readFileSync(0, 'utf8'); // fd 0; '' immediately on empty pipe, blocks on a TTY until EOF
    return data.trim() || undefined;
  } catch {
    return undefined;
  }
}

// Status codes that — ONLY at a Nango-authored verification endpoint — definitively mean
// "this credential was rejected", the sole basis for marking a key needs_reauth. 403 is
// deliberately excluded: it's overloaded (WAF, geo, missing User-Agent, plan/scope limits,
// account state), so a perfectly valid key 403s for many non-auth reasons.
const AUTH_REJECT_STATUSES = new Set([401, 407]);

/**
 * Classify a probe HTTP status into an outcome. PURE (no I/O) so the whole condemnation
 * policy is unit-testable. Two probe classes carry different rights:
 *   - 'catalog' — a real endpoint Nango authored to return 401 on bad auth; may CONDEMN.
 *   - 'generic' — a bare base_url root we picked ourselves; CONFIRM-ONLY, never condemns
 *     (a good key can legitimately 401 at a root it was never designed to answer).
 * Only a clean 2xx confirms; for 'catalog' a 401/407 condemns; everything else (403, 404,
 * 405, 429, 5xx, 3xx) is inconclusive and never penalizes the key.
 */
function classifyProbeStatus(klass, status) {
  if (status >= 200 && status < 300) return 'ok';
  if (klass === 'catalog' && AUTH_REJECT_STATUSES.has(status)) return 'failed';
  return 'skipped';
}

/**
 * Decide WHERE and HOW to probe a paste-a-key connection — or null to skip. PURE (it builds
 * the request, sends nothing), reusing the same auth-rendering seam as get-token.cjs.
 *   - catalog class: the catalog's proxy.verification endpoint, plus its own headers/body
 *     (161/238 verification blocks carry headers; a few POST a body — dropping these would
 *     turn a good key's probe into a spurious 400/415).
 *   - generic class: GET the resolved base_url root — the confirm-only fallback for the
 *     ~111 providers Nango ships no verification block for.
 * Returns null (→ caller skips) whenever we can't build a trustworthy request: an unresolved
 * ${...} anywhere in the URL/headers/query (e.g. AWS ${awsSigV4(...)} computed auth, or an
 * unfilled connection field), or a base with no host. A request we can't authenticate
 * correctly would look exactly like a bad key — so we don't fire it.
 */
function buildProbeTarget(descriptor, secret) {
  if (!descriptor) return null;
  const { headers, query } = catalog.renderAuthHeaders(descriptor, secret || {});
  const apiKey = (secret && secret.apiKey) || '';
  // Resolve ${apiKey} in the base (Telegram-style key-in-URL), mirroring get-token.cjs.
  const base = String(descriptor.proxyBaseUrl || '').replace(/\$\{apiKey\}/g, apiKey);

  const v = descriptor.verification;
  let urlStr, method, reqHeaders, data, klass;
  if (v) {
    const ep = v.endpoint || (Array.isArray(v.endpoints) && v.endpoints[0] && (v.endpoints[0].endpoint || v.endpoints[0]));
    const vbase = v.base_url_override || base;
    if (!ep || !vbase) return null;
    urlStr = String(ep).startsWith('http') ? String(ep) : vbase.replace(/\/$/, '') + '/' + String(ep).replace(/^\//, '');
    method = (v.method || 'GET').toUpperCase();
    reqHeaders = { ...(v.headers || {}), ...headers }; // auth headers win over verification headers
    data = v.data;
    klass = 'catalog';
  } else {
    if (!base) return null;
    urlStr = base;
    method = 'GET';
    reqHeaders = headers;
    klass = 'generic';
  }

  let url;
  try {
    url = new URL(urlStr);
  } catch {
    return null;
  }
  if (!url.host) return null;
  for (const [k, val] of Object.entries(query)) url.searchParams.set(k, val);

  // Any leftover ${...} in the URL or headers means the auth/template couldn't be built —
  // skip rather than send a request that's guaranteed to look unauthenticated.
  if ((url.toString() + JSON.stringify(reqHeaders)).includes('${')) return null;

  return { url: url.toString(), method, headers: reqHeaders, data, klass };
}

/**
 * Best-effort live validity probe for a paste-a-key connection. Never throws and never blocks
 * the save. A definitive auth rejection at a real verification endpoint stamps reg.error
 * (→ needs_reauth in the health sweep); a bare-root generic probe can only ever CONFIRM, never
 * condemn; everything inconclusive (network error, timeout, 403, 404, 5xx, redirect) is 'skipped'.
 */
async function probeKey(service, descriptor, secret) {
  const t = buildProbeTarget(descriptor, secret);
  if (!t) return 'skipped';
  try {
    const res = await fetch(t.url, {
      method: t.method,
      headers: t.headers,
      body: t.data ? JSON.stringify(t.data) : undefined,
      redirect: 'manual', // a root 302→login→200 HTML would falsely confirm; treat 3xx as inconclusive
      signal: AbortSignal.timeout(8000),
    });
    const outcome = classifyProbeStatus(t.klass, res.status);
    if (outcome === 'failed') store.upsertConnection(service, { error: `probe_http_${res.status}` });
    return outcome;
  } catch {
    return 'skipped'; // network/timeout/unsupported — inconclusive, don't penalize the key
  }
}

async function cmdSetKey(service, flags) {
  if (!service) throw new Error('Usage: node connect.cjs set-key <provider> [--username <u>] [--<field> <value> …] [--no-probe] (secret via stdin)');
  if (flags.key !== undefined || flags.password !== undefined) {
    throw new Error('Secret flags are not accepted; pipe the API key or password on stdin.');
  }
  // Connection details: explicit --connectionConfig JSON, plus any required field passed
  // as its own flag (e.g. `--subdomain acme` for Zendesk — friendlier than JSON).
  // Multi-account: the positional is a provider (optionally provider:alias); `--as` adds an alias.
  // Catalog lookups go by PROVIDER (the auth scheme); the key is SAVED under the connId.
  const parsed = store.parseConnectionId(service);
  const provider = parsed.provider;
  const alias = flags.as || parsed.alias || null;
  const connId = alias ? `${provider}:${alias}` : provider;

  const connectionConfig = flags.connectionConfig ? JSON.parse(flags.connectionConfig) : {};
  const required = catalog.requiredConnectionConfig(provider);
  for (const f of required) {
    if ((connectionConfig[f] == null || connectionConfig[f] === '') && flags[f] != null && flags[f] !== 'true') {
      connectionConfig[f] = flags[f];
    }
  }
  const descriptor = catalog.getProviderConfig(provider, connectionConfig);
  if (!descriptor.supported) {
    throw new Error(`'${provider}' is not connectable yet: ${descriptor.reason} It remains available to browse in providers.`);
  }
  if (!catalog.KEY_MODES.has(descriptor.authMode)) {
    throw new Error(`'${provider}' uses ${descriptor.authMode} (OAuth) — use: node connect.cjs connect ${provider}`);
  }
  // Many paste-a-key providers are host-scoped (Zendesk subdomain, NetSuite accountId, …):
  // without these the base_url can't resolve and every call would silently 404/timeout.
  // Fail loudly with exactly what's missing instead of saving a dead connection.
  const missing = required.filter((f) => connectionConfig[f] == null || connectionConfig[f] === '');
  if (missing.length) {
    const schema = descriptor.connectionConfigSchema || {};
    const lines = missing.map((f) => {
      const meta = schema[f] || {};
      const hint = meta.title || meta.description;
      const eg = meta.example ? ` (e.g. ${meta.example})` : '';
      return `    --${f} <value>${hint ? `   # ${hint}${eg}` : eg}`;
    });
    throw new Error(
      `${descriptor.displayName} needs connection detail${missing.length > 1 ? 's' : ''}: ${missing.join(', ')}.\n` +
        `${lines.join('\n')}\n` +
        `e.g. printf '%s\\n' '<secret>' | node connect.cjs set-key ${provider} ${missing.map((f) => `--${f} <value>`).join(' ')}`
    );
  }

  let secret;
  if (descriptor.authMode === 'BASIC') {
    const username = flags.username;
    const password = readStdin();
    if (!username || !password) throw new Error('BASIC auth needs --username and a password piped on stdin.');
    secret = { username, password };
  } else {
    const apiKey = readStdin();
    if (!apiKey) throw new Error('No key provided. Pipe it on stdin.');
    secret = { apiKey };
  }
  if (Object.keys(connectionConfig).length) secret.connectionConfig = connectionConfig;

  store.saveApiKey(connId, secret, { provider: descriptor.id, authMode: descriptor.authMode });
  if (flags.default) store.setDefault(provider, alias);
  if (!descriptor.verified) {
    console.log('Unverified provider — advanced tier, expect quirks.');
  }

  const probe = flags['no-probe'] === undefined && flags.probe !== 'false' ? await probeKey(connId, descriptor, secret) : 'skipped';
  const note = probe === 'ok' ? ' Verified live.' : probe === 'failed' ? ' (probe failed — marked needs_reauth)' : '';
  console.log(`✅ Stored ${descriptor.displayName}${alias ? ` (${connId})` : ''} key (encrypted) in ${store.credentialsDir()}/tokens/.${note}`);
}

function cmdStatus() {
  const meta = store.readRegistry()._meta;
  if (meta && meta.notice === 'registry_rebuilt') {
    console.log(
      `\n⚠️  Dex's connection list was damaged (${meta.reason}) and was rebuilt from your saved tokens on ${meta.rebuiltAt}: ` +
        `${meta.recovered} recovered, ${meta.unreadable} unreadable.` +
        `${meta.quarantinedRegistry ? ` The damaged list was kept as ${meta.quarantinedRegistry} in ${store.credentialsDir()}.` : ''}` +
        ' Check the list below and reconnect anything missing or red.'
    );
  }
  const rows = health.allConnectionsHealth();
  if (!rows.length) {
    console.log('No connections yet. Run: node connect.cjs connect <provider>');
    return;
  }
  if (rows.some((r) => r.error === 'encryption_key_lost')) {
    console.log(
      "\n🔑 Dex's encryption key is missing or unreadable, so the saved connections below can't be unlocked. " +
        'Reconnect each tool (node connect.cjs connect <provider>); reconnecting issues a fresh key and preserves the old token files.'
    );
  }
  const icon = { connected: '🟢', expiring: '🟡', expired: '🟠', needs_reauth: '🔴', error: '🔴', not_connected: '⚪' };
  console.log('\nConnection status:\n');
  for (const r of rows) {
    const exp = r.expiresAt ? new Date(r.expiresAt).toISOString() : '—';
    console.log(`  ${icon[r.status] || '•'} ${r.service.padEnd(18)} ${r.status.padEnd(13)} expires ${exp}${r.error ? '  (' + r.error + ')' : ''}`);
  }
  console.log('');
}

async function cmdRefresh(service, flags = {}) {
  if (!service) throw new Error('Usage: node connect.cjs refresh <conn> [--force]');
  // No token material in output, not even a prefix: logs and transcripts of this
  // command must stay credential-free. get-token is the sanctioned accessor.
  await health.refreshToken(service, { force: flags.force !== undefined });
  console.log(`✅ ${service}: token valid (${flags.force !== undefined ? 'forced refresh complete' : 'refreshed if needed'}).`);
}

function cmdProviders(filter, flags = {}) {
  const keys = flags.keys !== undefined;
  const list = keys ? catalog.listKeyProviders() : catalog.listOAuthProviders();
  const filtered = filter ? list.filter((p) => (p.id + ' ' + p.displayName).toLowerCase().includes(filter.toLowerCase())) : list;
  const label = keys ? 'paste-a-key providers' : 'OAuth providers';
  console.log(`\n${filtered.length} ${label}${filter ? ` matching "${filter}"` : ''} (of ${list.length}):\n`);
  for (const p of filtered.slice(0, 60)) {
    const tier = p.supported === false ? '; browse-only' : p.verified ? '; verified' : '; advanced';
    console.log(`  ${p.id.padEnd(28)} ${p.displayName}  [${p.authMode}${tier}]`);
  }
  if (filtered.length > 60) console.log(`  …and ${filtered.length - 60} more`);
  console.log('');
}

/** Show exactly what's needed to connect a provider: secret + any required fields. */
function cmdDescribe(service) {
  if (!service) throw new Error('Usage: node connect.cjs describe <provider>');
  const descriptor = catalog.getProviderConfig(service);
  const isKey = catalog.KEY_MODES.has(descriptor.authMode);
  const required = isKey ? catalog.requiredConnectionConfig(service) : [];
  console.log(`\n${descriptor.displayName}  [${descriptor.authMode}]  (${descriptor.id})`);
  if (!descriptor.supported) {
    console.log(`  Connect:      browse-only — ${descriptor.reason}`);
  } else if (!isKey) {
    console.log(`  Connect:      node connect.cjs connect ${descriptor.id}`);
  } else {
    console.log(`  Connect:      pipe the secret to: node connect.cjs set-key ${descriptor.id}${required.map((f) => ` --${f} <value>`).join('')}`);
  }
  // Show the RAW base template (e.g. https://${connectionConfig.subdomain}.zendesk.com) so the
  // field's role is obvious — descriptor.proxyBaseUrl is resolved against empty config here and
  // would render a blank host (https:///api).
  const rawBase = (descriptor.raw && descriptor.raw.proxy && descriptor.raw.proxy.base_url) || descriptor.proxyBaseUrl;
  if (rawBase) console.log(`  API base:     ${rawBase}`);
  const schema = descriptor.connectionConfigSchema || {};
  if (required.length) {
    console.log('  Needs fields:');
    for (const f of required) {
      const meta = schema[f] || {};
      const hint = meta.title || meta.description;
      console.log(`     - ${f}${hint ? `  — ${hint}` : ''}${meta.example ? `  (e.g. ${meta.example})` : ''}`);
    }
  } else if (isKey) {
    console.log('  Needs fields: none — a single API key is enough.');
  }
  const creds = descriptor.credentialsSchema || (descriptor.raw && descriptor.raw.credentials) || null;
  if (creds && typeof creds === 'object') {
    console.log(`  Secret:       ${Object.entries(creds).map(([k, v]) => `${k}${v && v.title ? ` (${v.title})` : ''}`).join(', ')}`);
  }
  if (isKey) console.log(`  Verify:       ${descriptor.verification ? 'live probe on connect' : 'no probe endpoint — validated on first use'}`);
  if (descriptor.docs) console.log(`  Docs:         ${descriptor.docs}`);
  console.log('');
}

/** Honest paste-a-key coverage tiering — the "how many tools" number for the website. */
function cmdCoverage() {
  const c = catalog.keyProviderCoverage();
  console.log('\nPaste-a-key (Class-B) coverage:\n');
  console.log(`  Total API_KEY / BASIC providers : ${c.total}`);
  console.log(`  Connect with one key            : ${c.singleKeyReady}`);
  console.log(`  Connect with key + fields       : ${c.needsFields}`);
  console.log(`  Need a manual override          : ${c.needsOverride}`);
  console.log(`  Live-verified on connect        : ${c.withVerification}  (catalog endpoint — can confirm + flag bad keys)`);
  console.log(`  Generic confirm-only check      : ${c.genericProbeable}  (no catalog endpoint — can go green, never falsely flags)`);
  console.log('  ──────────────────────────────────');
  console.log(`  Reachable today                 : ${c.reachable}  ← "tools you can connect with an API key"`);
  if (c.buckets.needsOverride.length) console.log(`\n  needsOverride (long tail): ${c.buckets.needsOverride.join(', ')}`);
  console.log('');
}

function cmdAuthUrl(provider, flags) {
  const app = store.getOAuthApp(provider) || { clientId: 'YOUR_CLIENT_ID' };
  const scopes = catalog.normalizeScopes(provider, flags.scopes ? flags.scopes.split(',') : []);
  const providerConfig = catalog.getProviderConfig(provider);
  if (!providerConfig.supported) throw new Error(`'${provider}' is browse-only: ${providerConfig.reason}`);
  const { url, state, codeVerifier } = oauth.buildAuthorizationUrl(providerConfig, {
    clientId: app.clientId,
    scopes,
    redirectUri: 'http://127.0.0.1:3847/callback',
  });
  console.log(JSON.stringify({ provider: providerConfig.id, usePkce: providerConfig.usePkce, state, codeVerifierPresent: Boolean(codeVerifier), url }, null, 2));
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const { flags, positional } = parseFlags(rest);
  try {
    switch (cmd) {
      case 'connect':
        await cmdConnect(positional[0], flags);
        break;
      case 'set-key':
        await cmdSetKey(positional[0], flags);
        break;
      case 'register-app':
        cmdRegisterApp(positional[0], flags);
        break;
      case 'status':
        cmdStatus();
        break;
      case 'refresh':
        await cmdRefresh(positional[0], flags);
        break;
      case 'disconnect':
        store.deleteToken(positional[0]);
        console.log(`Disconnected ${positional[0]}.`);
        break;
      case 'providers':
        cmdProviders(positional[0], flags);
        break;
      case 'describe':
        cmdDescribe(positional[0]);
        break;
      case 'coverage':
        cmdCoverage();
        break;
      case 'authurl':
        cmdAuthUrl(positional[0], flags);
        break;
      default:
        console.log('Usage: node connect.cjs <connect|set-key|register-app|status|refresh|disconnect|providers|describe|coverage|authurl> [args]');
    }
  } catch (err) {
    console.error(`Error: ${err.message}`);
    process.exit(1);
  }
}

if (require.main === module) main();
module.exports = { main, buildProbeTarget, classifyProbeStatus, probeKey, cmdRefresh };
