'use strict';
/**
 * connection-manager.test.cjs — repeatable smoke tests for the local connection
 * manager. Runs against a throwaway DEX_VAULT under the OS temp dir, so it never
 * touches your real credentials. Run with: npm run test:cm
 *
 * Covers the catalog (OAuth + Class-B descriptors, renderAuthHeaders), the
 * encrypted token store (OAuth tokens + paste-a-key secrets, touchUsed), the
 * health state machine, and the two CLIs end-to-end via subprocess
 * (connect.cjs set-key → status → get-token.cjs), proving the cross-process read
 * path the Python MCP servers rely on.
 */

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

// Point everything at a throwaway vault BEFORE requiring the store modules.
const TMP_VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-test-'));
process.env.DEX_VAULT = TMP_VAULT;

const catalog = require('./catalog.cjs');
const store = require('./token-store.cjs');
const health = require('./health.cjs');
const cli = require('./connect.cjs'); // buildProbeTarget / classifyProbeStatus (pure probe policy)
const dexcall = require('./dex-call.cjs'); // buildRequest / parseArgs (generic floor caller)
const authctx = require('./auth-context.cjs'); // resolveAuthContext (shared auth seam)

const DIR = __dirname;
const childEnv = { ...process.env, DEX_VAULT: TMP_VAULT };

// Pick a real paste-a-key provider for the Class-B path. Prefer one that needs ONLY an
// API key (no connection_config) so the single-secret round-trip tests stay simple; the
// field-requiring providers get their own dedicated tests below.
const KEY_PROVIDERS = catalog.listKeyProviders();
const KEY_PROV = (
  KEY_PROVIDERS.find((p) => p.authMode === 'API_KEY' && catalog.requiredConnectionConfig(p.id).length === 0) ||
  KEY_PROVIDERS[0] ||
  {}
).id;
// A provider that requires connection_config (e.g. subdomain/hostname), for validation tests.
const FIELD_PROV = KEY_PROVIDERS.find(
  (p) => p.authMode === 'API_KEY' && catalog.requiredConnectionConfig(p.id).length > 0
);
// An API_KEY provider whose probe target builds to null (e.g. unresolvable base) so the
// default-on probe is skipped WITHOUT any network — used to prove set-key never blocks/throws.
const NULL_TARGET_PROV = KEY_PROVIDERS.find(
  (p) =>
    p.authMode === 'API_KEY' &&
    catalog.requiredConnectionConfig(p.id).length === 0 &&
    cli.buildProbeTarget(catalog.getProviderConfig(p.id), { apiKey: 'k' }) === null
);

test.after(() => fs.rmSync(TMP_VAULT, { recursive: true, force: true }));

// ---- catalog ----------------------------------------------------------------

test('catalog: google resolves to an OAuth descriptor', () => {
  const g = catalog.getProviderConfig('google');
  assert.ok(catalog.KEY_MODES.has(g.authMode) === false, 'google is OAuth, not a key mode');
  assert.match(g.authorizationUrl, /^https:\/\//);
  assert.match(g.tokenUrl, /^https:\/\//);
});

test('catalog: unknown provider throws', () => {
  assert.throws(() => catalog.getProviderConfig('definitely-not-a-provider-xyz'), /Unknown provider/);
});

test('catalog: there are paste-a-key providers', () => {
  assert.ok(KEY_PROVIDERS.length > 0, 'expected at least one API_KEY/BASIC provider in the catalog');
});

test('catalog: renderAuthHeaders injects the secret verbatim', { skip: KEY_PROV ? false : 'no key provider' }, () => {
  const desc = catalog.getProviderConfig(KEY_PROV);
  const { headers, query } = catalog.renderAuthHeaders(desc, { apiKey: 'SEKRET-123' });
  const blob = JSON.stringify({ headers, query });
  assert.ok(blob.includes('SEKRET-123'), `secret should land in a header or query param for ${KEY_PROV}: ${blob}`);
  assert.ok(!blob.includes('${apiKey}'), 'no unresolved ${apiKey} placeholder should remain');
});

test('catalog: normalizeScopes expands Google shorthand to full URLs', () => {
  assert.deepEqual(
    catalog.normalizeScopes('google', ['gmail.readonly', 'calendar.readonly']),
    ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/calendar.readonly']
  );
  // idempotent: full URLs and bare OIDC scopes pass through untouched
  assert.deepEqual(
    catalog.normalizeScopes('google', ['https://www.googleapis.com/auth/drive.file', 'openid', 'email']),
    ['https://www.googleapis.com/auth/drive.file', 'openid', 'email']
  );
});

test('catalog: normalizeScopes leaves bare-scope (non-Google) providers untouched', () => {
  const nonGoogle = catalog.listOAuthProviders().find((p) => !/^google/.test(p.id));
  if (!nonGoogle) return; // catalog always has these, but stay defensive
  assert.deepEqual(catalog.normalizeScopes(nonGoogle.id, ['read', 'write']), ['read', 'write']);
});

test('catalog: requiredConnectionConfig finds host-scoping fields (and none for key-only)', () => {
  // active-campaign's base_url is https://${connectionConfig.hostname}, so hostname is required.
  assert.deepEqual(catalog.requiredConnectionConfig('active-campaign'), ['hostname']);
  // A single-key provider needs nothing extra.
  if (KEY_PROV) assert.deepEqual(catalog.requiredConnectionConfig(KEY_PROV), []);
  // A `${cc.x} || static-fallback` base_url is NOT required (the fallback resolves).
  assert.equal(catalog.requiredConnectionConfig('unknown-provider-xyz').length, 0);
});

test('catalog: keyProviderCoverage tiers add up and reachable is the bulk', () => {
  const c = catalog.keyProviderCoverage();
  assert.equal(c.singleKeyReady + c.needsFields + c.needsOverride, c.total);
  assert.equal(c.reachable, c.singleKeyReady + c.needsFields);
  assert.ok(c.total > 300, `expected 300+ Class-B providers, got ${c.total}`);
  assert.ok(c.reachable / c.total > 0.95, 'the vast majority should be reachable');
  // genericProbeable: confirm-only providers with no catalog endpoint, a subset of singleKeyReady.
  assert.equal(typeof c.genericProbeable, 'number');
  assert.ok(c.genericProbeable > 0 && c.genericProbeable <= c.singleKeyReady, 'genericProbeable ⊆ singleKeyReady');
});

// ---- probe policy (PURE — the false-negative safety net) ---------------------

test('probe: classifyProbeStatus — only catalog 401/407 condemns; 403 never does', () => {
  const C = cli.classifyProbeStatus;
  assert.equal(C('catalog', 200), 'ok');
  assert.equal(C('generic', 204), 'ok');
  assert.equal(C('catalog', 401), 'failed');
  assert.equal(C('catalog', 407), 'failed');
  assert.equal(C('catalog', 403), 'skipped'); // 403 is overloaded — never condemn
  for (const s of [400, 404, 405, 429, 500, 503, 302]) assert.equal(C('catalog', s), 'skipped');
});

test('probe: generic class is CONFIRM-ONLY — never returns failed for any status', () => {
  const C = cli.classifyProbeStatus;
  assert.equal(C('generic', 401), 'skipped'); // even a 401 at a bare root must not condemn
  for (let s = 100; s <= 599; s++) {
    assert.notEqual(C('generic', s), 'failed', `generic must never condemn (status ${s})`);
  }
});

test('probe: buildProbeTarget skips computed/unresolvable auth (no false condemnation)', () => {
  // aws-iam uses ${awsSigV4(...)} — renderAuthHeaders leaves it literal → must skip, not probe.
  assert.equal(cli.buildProbeTarget(catalog.getProviderConfig('aws-iam'), { username: 'u', password: 'p' }), null);
  // An unresolved ${connectionConfig.*} in the base → null (can't build a real host).
  const templated = { authMode: 'API_KEY', proxyBaseUrl: 'https://${connectionConfig.subdomain}.zendesk.com', requestHeaders: { authorization: 'Bearer ${apiKey}' }, requestQuery: {}, verification: null };
  assert.equal(cli.buildProbeTarget(templated, { apiKey: 'k' }), null);
});

test('probe: buildProbeTarget — catalog vs generic class, headers merged, key-in-URL resolved', () => {
  // Linear override: POST /graphql, raw Authorization, catalog class.
  const lin = cli.buildProbeTarget(catalog.getProviderConfig('linear'), { apiKey: 'lin_x' });
  assert.equal(lin.klass, 'catalog');
  assert.equal(lin.method, 'POST');
  assert.ok(lin.url.endsWith('/graphql'));
  assert.equal(lin.headers.Authorization, 'lin_x');

  // Telegram: key-in-URL resolved, verification /getMe, content-type header preserved.
  const tg = cli.buildProbeTarget(catalog.getProviderConfig('telegram'), { apiKey: 'BOTKEY' });
  assert.equal(tg.klass, 'catalog');
  assert.ok(tg.url.includes('botBOTKEY') && !tg.url.includes('${'), `telegram key must be in the URL: ${tg.url}`);
  assert.equal(tg.headers['content-type'], 'application/json');

  // active-campaign + hostname: catalog headers (content-type) merged WITH the auth header.
  const ac = cli.buildProbeTarget(catalog.getProviderConfig('active-campaign', { hostname: 'acme.api-us1.com' }), { apiKey: 'k', connectionConfig: { hostname: 'acme.api-us1.com' } });
  assert.equal(ac.klass, 'catalog');
  assert.ok(ac.url.includes('acme.api-us1.com'));
  assert.equal(ac.headers['content-type'], 'application/json');
  assert.equal(ac.headers['api-token'], 'k');

  // A no-verification single-key provider → generic class, GET, base root.
  const gen = cli.buildProbeTarget({ authMode: 'API_KEY', proxyBaseUrl: 'https://api.airtable.com', requestHeaders: { authorization: 'Bearer ${apiKey}' }, requestQuery: {}, verification: null }, { apiKey: 'k' });
  assert.equal(gen.klass, 'generic');
  assert.equal(gen.method, 'GET');
  assert.ok(gen.url.startsWith('https://api.airtable.com'));
  assert.equal(gen.headers.authorization, 'Bearer k');
});

// ---- dex-call (generic floor caller) ----------------------------------------

test('dex-call: buildRequest joins base + relative path and attaches the rendered auth', () => {
  const ctx = { kind: 'api_key', baseUrl: 'https://api.acme.com', headers: { authorization: 'Bearer K' }, query: {} };
  const r = dexcall.buildRequest(ctx, 'GET', '/v1/contacts', {});
  assert.equal(r.url, 'https://api.acme.com/v1/contacts');
  assert.equal(r.method, 'GET');
  assert.equal(r.headers.authorization, 'Bearer K');
  assert.equal(r.authAttached, true);
});

test('dex-call: buildRequest NEVER leaks the secret to a different host', () => {
  const ctx = { kind: 'api_key', baseUrl: 'https://api.acme.com', headers: { authorization: 'Bearer K' }, query: {} };
  const same = dexcall.buildRequest(ctx, 'GET', 'https://api.acme.com/x', {}); // same host → auth ok
  assert.equal(same.authAttached, true);
  assert.equal(same.headers.authorization, 'Bearer K');
  const diff = dexcall.buildRequest(ctx, 'GET', 'https://evil.example.com/x', {}); // other host → no secret
  assert.equal(diff.authAttached, false);
  assert.equal(diff.headers.authorization, undefined);
});

test('dex-call: buildRequest merges query, defaults method by body, rejects bad input', () => {
  const ctx = { kind: 'api_key', baseUrl: 'https://api.acme.com', headers: {}, query: { api_key: 'K' } };
  const r = dexcall.buildRequest(ctx, undefined, '/x', { query: { limit: '5' }, body: '{"a":1}' });
  const u = new URL(r.url);
  assert.equal(u.searchParams.get('api_key'), 'K'); // ctx query (auth)
  assert.equal(u.searchParams.get('limit'), '5'); // user query
  assert.equal(r.method, 'POST'); // body present → POST
  assert.equal(dexcall.buildRequest(ctx, undefined, '/x', {}).method, 'GET'); // no body → GET
  assert.throws(() => dexcall.buildRequest({ baseUrl: null, headers: {}, query: {} }, 'GET', '/x', {})); // no base + relative
  assert.throws(() => dexcall.buildRequest(ctx, 'GET', 'file:///etc/passwd', {})); // non-http blocked
});

test('dex-call: parseArgs detects optional METHOD, query, header, body', () => {
  const a = dexcall.parseArgs(['svc', 'POST', '/p', '--query', 'k=v', '--header', 'X-Y: z', '--body', '{"a":1}']);
  assert.equal(a.service, 'svc');
  assert.equal(a.method, 'POST');
  assert.equal(a.path, '/p');
  assert.equal(a.query.k, 'v');
  assert.equal(a.headers['X-Y'], 'z');
  assert.equal(a.flags.body, '{"a":1}');
  const b = dexcall.parseArgs(['svc', '/p']); // no method → GET-by-default path only
  assert.equal(b.method, undefined);
  assert.equal(b.path, '/p');
});

test('dex-call: resolveAuthContext + buildRequest sign a request from a stored key (offline)', { skip: FIELD_PROV ? false : 'no field provider' }, async () => {
  const field = catalog.requiredConnectionConfig(FIELD_PROV.id)[0];
  // Store under a DISTINCT connection name (provider via meta) so we don't pollute FIELD_PROV's
  // own slot, which a later test asserts is empty.
  store.saveApiKey('dexcall-signed-test', { apiKey: 'sek', connectionConfig: { [field]: 'acme.api-us1.com' } }, { provider: FIELD_PROV.id, authMode: 'API_KEY' });
  const ctx = await authctx.resolveAuthContext('dexcall-signed-test');
  assert.equal(ctx.kind, 'api_key');
  const r = dexcall.buildRequest(ctx, 'GET', '/3/contacts', {});
  assert.ok(r.url.includes('acme'), `url should use the stored connection field: ${r.url}`);
  assert.ok(JSON.stringify(r.headers).includes('sek'), 'the stored secret should ride in the auth header');
  // Tear down: loadToken resolves by provider too, so leaving this mapped to FIELD_PROV's
  // provider would make a later "is it empty?" test see a phantom connection.
  store.deleteToken('dexcall-signed-test');
});

// ---- token store ------------------------------------------------------------

test('store: OAuth token encrypt/decrypt roundtrip', () => {
  const tok = { access_token: 'at-1', refresh_token: 'rt-1', expires_at: Date.now() + 3600_000, scope: 'a b' };
  store.saveToken('demo-oauth', tok, { provider: 'google' });
  const back = store.loadToken('demo-oauth');
  assert.equal(back.access_token, 'at-1');
  assert.equal(back.refresh_token, 'rt-1');
  const reg = store.readRegistry()['demo-oauth'];
  assert.equal(reg.status, 'connected');
  assert.deepEqual(reg.scopes, ['a', 'b']);
});

test('store: raw encrypt/decrypt is reversible', () => {
  const env = store.encrypt('hello-world');
  assert.notEqual(env.data, 'hello-world');
  assert.equal(store.decrypt(env), 'hello-world');
});

test('store: saveApiKey roundtrip + registry shape', () => {
  store.saveApiKey('demo-key', { apiKey: 'k-abc' }, { provider: KEY_PROV || 'demo-key', authMode: 'API_KEY' });
  const back = store.loadToken('demo-key');
  assert.equal(back.kind, 'api_key');
  assert.equal(back.apiKey, 'k-abc');
  const reg = store.readRegistry()['demo-key'];
  assert.equal(reg.authMode, 'API_KEY');
  assert.equal(reg.status, 'connected');
  assert.equal(reg.expiresAt, null);
});

test('store: touchUsed stamps lastUsedAt (and no-ops for unknown service)', () => {
  assert.equal(store.touchUsed('nope-not-here'), null);
  store.saveApiKey('demo-touch', { apiKey: 'k' }, { provider: 'demo-touch' });
  const r = store.touchUsed('demo-touch');
  assert.ok(r.lastUsedAt, 'lastUsedAt should be set');
});

// ---- health -----------------------------------------------------------------

test('health: key connection reads connected, flips to needs_reauth on error', () => {
  store.saveApiKey('demo-health', { apiKey: 'k' }, { provider: 'demo-health', authMode: 'API_KEY' });
  assert.equal(health.connectionHealth('demo-health').status, 'connected');
  store.upsertConnection('demo-health', { error: 'bad_key' });
  assert.equal(health.connectionHealth('demo-health').status, 'needs_reauth');
});

test('health: ensureFreshToken returns the raw key for a Class-B connection', async () => {
  store.saveApiKey('demo-fresh', { apiKey: 'the-key' }, { provider: 'demo-fresh', authMode: 'API_KEY' });
  assert.equal(await health.ensureFreshToken('demo-fresh'), 'the-key');
});

// ---- CLIs end-to-end (subprocess) ------------------------------------------

test('cli: set-key (stdin) → status → get-token roundtrip', { skip: KEY_PROV ? false : 'no key provider' }, () => {
  // set-key reads the secret from stdin; --no-probe keeps the test offline.
  execFileSync('node', [path.join(DIR, 'connect.cjs'), 'set-key', KEY_PROV, '--no-probe'], {
    input: 'cli-secret-xyz\n',
    env: childEnv,
  });

  const status = execFileSync('node', [path.join(DIR, 'connect.cjs'), 'status'], { env: childEnv }).toString();
  assert.match(status, new RegExp(KEY_PROV), 'status should list the new key connection');

  const raw = execFileSync('node', [path.join(DIR, 'get-token.cjs'), KEY_PROV, '--access-token-only'], { env: childEnv }).toString();
  assert.equal(raw, 'cli-secret-xyz', 'get-token --access-token-only returns the stored secret');

  const json = JSON.parse(execFileSync('node', [path.join(DIR, 'get-token.cjs'), KEY_PROV], { env: childEnv }).toString());
  assert.equal(json.kind, 'api_key');
  assert.ok(JSON.stringify(json).includes('cli-secret-xyz'), 'rendered headers/query carry the secret');
});

test('cli: get-token exits 2 when service is not connected', () => {
  let code = 0;
  try {
    execFileSync('node', [path.join(DIR, 'get-token.cjs'), 'never-connected-svc'], { env: childEnv, stdio: 'ignore' });
  } catch (err) {
    code = err.status;
  }
  assert.equal(code, 2);
});

test('cli: set-key on a host-scoped provider FAILS without the field (no dead connection)', { skip: FIELD_PROV ? false : 'no field provider' }, () => {
  const field = catalog.requiredConnectionConfig(FIELD_PROV.id)[0];
  let err;
  try {
    execFileSync('node', [path.join(DIR, 'connect.cjs'), 'set-key', FIELD_PROV.id, '--key', 'k', '--no-probe'], {
      env: childEnv,
      stdio: 'pipe',
    });
  } catch (e) {
    err = e;
  }
  assert.ok(err, 'set-key should reject when a required field is missing');
  assert.match(err.stderr.toString(), new RegExp(field), 'error should name the missing field');
  // and nothing was stored
  let code = 0;
  try {
    execFileSync('node', [path.join(DIR, 'get-token.cjs'), FIELD_PROV.id], { env: childEnv, stdio: 'ignore' });
  } catch (e) {
    code = e.status;
  }
  assert.equal(code, 2, 'no connection should have been saved');
});

test('cli: set-key with --<field> resolves the templated base_url end-to-end', { skip: FIELD_PROV ? false : 'no field provider' }, () => {
  const field = catalog.requiredConnectionConfig(FIELD_PROV.id)[0];
  execFileSync(
    'node',
    [path.join(DIR, 'connect.cjs'), 'set-key', FIELD_PROV.id, '--key', 'sek', `--${field}`, 'acme', '--no-probe'],
    { env: childEnv }
  );
  const json = JSON.parse(execFileSync('node', [path.join(DIR, 'get-token.cjs'), FIELD_PROV.id], { env: childEnv }).toString());
  assert.equal(json.kind, 'api_key');
  assert.ok(json.baseUrl && json.baseUrl.includes('acme'), `base_url should embed the field value: ${json.baseUrl}`);
  assert.ok(!json.baseUrl.includes('${'), 'no unresolved template should remain in base_url');
});

test('cli: coverage reports reachable + generic-probeable counts', () => {
  const out = execFileSync('node', [path.join(DIR, 'connect.cjs'), 'coverage'], { env: childEnv }).toString();
  assert.match(out, /Reachable today\s*:\s*\d{3}/, 'coverage prints a 3-digit reachable count');
  assert.match(out, /Generic confirm-only check\s*:\s*\d+/, 'coverage prints the generic-probeable count');
});

test('cli: default-on probe never blocks the save (null-target provider stays green, offline)', { skip: NULL_TARGET_PROV ? false : 'no null-target provider' }, () => {
  // No --no-probe here: the probe runs, but buildProbeTarget is null → skipped → zero network.
  const out = execFileSync('node', [path.join(DIR, 'connect.cjs'), 'set-key', NULL_TARGET_PROV.id, '--key', 'k'], {
    env: childEnv,
  }).toString();
  assert.match(out, /Stored/, 'set-key should report success even when the probe is skipped');
  assert.ok(!/probe failed/.test(out), 'a null-target probe must never report a failure');
  const status = execFileSync('node', [path.join(DIR, 'connect.cjs'), 'status'], { env: childEnv }).toString();
  assert.match(status, new RegExp(`${NULL_TARGET_PROV.id}\\s+connected`), 'connection should be green, not needs_reauth');
});

test('cli: describe shows required fields for a host-scoped provider', { skip: FIELD_PROV ? false : 'no field provider' }, () => {
  const field = catalog.requiredConnectionConfig(FIELD_PROV.id)[0];
  const out = execFileSync('node', [path.join(DIR, 'connect.cjs'), 'describe', FIELD_PROV.id], { env: childEnv }).toString();
  assert.match(out, /Needs fields:/);
  assert.match(out, new RegExp(field));
});

test('cli: dex-call exits 2 for a service that is not connected (offline)', () => {
  let code = 0;
  try {
    execFileSync('node', [path.join(DIR, 'dex-call.cjs'), 'never-connected-xyz', '/x'], { env: childEnv, stdio: 'ignore' });
  } catch (e) {
    code = e.status;
  }
  assert.equal(code, 2);
});

// ---- multi-account (blocker #1) ---------------------------------------------

test('store: a second account does NOT clobber the first (the blocker-#1 guarantee)', () => {
  store.saveToken('google', { access_token: 'PERSONAL', refresh_token: 'rp' }, { provider: 'google' });
  store.saveToken('google:work', { access_token: 'WORK', refresh_token: 'rw' }, { provider: 'google' });
  const tdir = path.join(TMP_VAULT, 'System', 'credentials', 'tokens');
  assert.ok(fs.existsSync(path.join(tdir, 'google.json')), 'default token file untouched');
  assert.ok(fs.existsSync(path.join(tdir, 'google__work.json')), 'aliased token file created (colon → __)');
  assert.equal(store.loadToken('google').access_token, 'PERSONAL', 'bare id still returns the original');
  assert.equal(store.loadToken('google:work').access_token, 'WORK', 'aliased id returns the second account');
  assert.equal(store.resolveConnId('google'), 'google', 'exact match wins for a bare id');
  const ids = store.listConnections().map((c) => c.service);
  assert.ok(ids.includes('google') && ids.includes('google:work'));
  store.deleteToken('google');
  store.deleteToken('google:work');
});

test('store: resolveConnId falls back to sole account / default, throws on ambiguity', () => {
  store.saveApiKey('ma-prov:main', { apiKey: 'k' }, { provider: 'ma-prov', authMode: 'API_KEY' });
  assert.equal(store.resolveConnId('ma-prov'), 'ma-prov:main', 'sole account resolves');
  store.saveApiKey('ma-prov:alt', { apiKey: 'k2' }, { provider: 'ma-prov', authMode: 'API_KEY' });
  assert.throws(() => store.resolveConnId('ma-prov'), /Multiple 'ma-prov' accounts/, 'ambiguous bare id throws');
  store.setDefault('ma-prov', 'alt');
  assert.equal(store.resolveConnId('ma-prov'), 'ma-prov:alt', 'explicit default resolves');
  store.deleteToken('ma-prov:main');
  store.deleteToken('ma-prov:alt');
});

test('store: refresh looks up the OAuth app by PROVIDER, not connId (latent-bug fix)', () => {
  // The OAuth app is shared across a provider's accounts: google:work must use the `google` app.
  store.setOAuthApp('gprov', { clientId: 'CID', clientSecret: 'CS' });
  assert.equal(store.getOAuthApp('gprov').clientId, 'CID');
  // a connId for that provider has no app of its own — health.ensureFreshToken resolves provider first
  assert.equal(store.getOAuthApp('gprov:work'), null, 'no app keyed by the aliased connId');
});

// ---- credentials gitignore (blocker #2) -------------------------------------

test('store: credentials dir gets a "*" .gitignore on first write (blocker #2)', () => {
  store.saveApiKey('gi-test', { apiKey: 'k' }, { provider: 'gi-test', authMode: 'API_KEY' });
  const gi = path.join(TMP_VAULT, 'System', 'credentials', '.gitignore');
  assert.ok(fs.existsSync(gi), '.gitignore should exist in the credentials dir');
  assert.match(fs.readFileSync(gi, 'utf8'), /^\*$/m, 'it should ignore everything');
  store.deleteToken('gi-test');
});

test('store: a NARROWER existing .gitignore is UPGRADED to ignore everything (red-team gap)', () => {
  const credDir = path.join(TMP_VAULT, 'System', 'credentials');
  fs.mkdirSync(credDir, { recursive: true });
  // legacy/narrow rule that would leak the fallback key (.dex-cm.key isn't *.json)
  fs.writeFileSync(path.join(credDir, '.gitignore'), '# legacy narrow rule\n*.json\n!README.md\n');
  store.saveApiKey('gi-upgrade', { apiKey: 'k' }, { provider: 'gi-upgrade', authMode: 'API_KEY' });
  const gi = fs.readFileSync(path.join(credDir, '.gitignore'), 'utf8');
  assert.match(gi, /^\*\s*$/m, 'a bare * line must now be present (so .dex-cm.key is ignored too)');
  assert.match(gi, /!README\.md/, 'README.md stays tracked');
  store.deleteToken('gi-upgrade');
});

// ---- conversational OAuth-app onboarding (should-fix #3) --------------------

test('store: setOAuthApp / getOAuthApp roundtrip (Dex writes the file, user never edits it)', () => {
  store.setOAuthApp('demo-prov', { clientId: 'CID', clientSecret: 'CSECRET' });
  const app = store.getOAuthApp('demo-prov');
  assert.equal(app.clientId, 'CID');
  assert.equal(app.clientSecret, 'CSECRET');
});

test('cli: register-app writes OAuth creds from stdin (no hand-editing)', () => {
  execFileSync('node', [path.join(DIR, 'connect.cjs'), 'register-app', 'demo-oauth-prov'], {
    input: 'MYID\nMYSECRET\n',
    env: childEnv,
  });
  const app = store.getOAuthApp('demo-oauth-prov');
  assert.equal(app.clientId, 'MYID');
  assert.equal(app.clientSecret, 'MYSECRET');
});

test('cli: set-key --as adds a second paste-key account without clobbering the first (offline)', { skip: KEY_PROV ? false : 'no key provider' }, () => {
  execFileSync('node', [path.join(DIR, 'connect.cjs'), 'set-key', KEY_PROV, '--no-probe'], { input: 'first-key\n', env: childEnv });
  execFileSync('node', [path.join(DIR, 'connect.cjs'), 'set-key', KEY_PROV, '--as', 'work', '--no-probe'], { input: 'work-key\n', env: childEnv });
  const first = execFileSync('node', [path.join(DIR, 'get-token.cjs'), KEY_PROV, '--access-token-only'], { env: childEnv }).toString();
  const work = execFileSync('node', [path.join(DIR, 'get-token.cjs'), `${KEY_PROV}:work`, '--access-token-only'], { env: childEnv }).toString();
  assert.equal(first, 'first-key', 'bare id still returns the original account');
  assert.equal(work, 'work-key', 'aliased id returns the second account');
  store.deleteToken(`${KEY_PROV}:work`);
});

// ---- get-token output contract (low) ----------------------------------------

test('cli: get-token OAuth no-flag returns full JSON with access_token (locks pp-gmail contract)', () => {
  store.saveToken('oauth-contract', { access_token: 'AT', refresh_token: 'RT', expires_at: Date.now() + 3600_000, scope: 'a b' }, { provider: 'google' });
  const json = JSON.parse(execFileSync('node', [path.join(DIR, 'get-token.cjs'), 'oauth-contract'], { env: childEnv }).toString());
  assert.equal(json.access_token, 'AT', 'OAuth no-flag output must contain access_token');
  store.deleteToken('oauth-contract');
});
