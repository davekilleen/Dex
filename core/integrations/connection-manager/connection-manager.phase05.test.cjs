'use strict';

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const { EventEmitter } = require('node:events');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const TMP_VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-phase05-'));
const TMP_RUNTIME = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-phase05-runtime-'));
process.env.DEX_VAULT = TMP_VAULT;
process.env.DEX_CM_RUNTIME_DIR = TMP_RUNTIME;
process.env.DEX_CM_BROKER_IDLE_MS = '100';
process.env.DEX_CM_NO_KEYCHAIN = '1';

const catalog = require('./catalog.cjs');
const store = require('./token-store.cjs');
const health = require('./health.cjs');
const oauth = require('./oauth-flow.cjs');
const cli = require('./connect.cjs');

const DIR = __dirname;
const CRED_DIR = path.join(TMP_VAULT, 'System', 'credentials');
const TOKENS_DIR = path.join(CRED_DIR, 'tokens');
const childEnv = {
  ...process.env,
  DEX_VAULT: TMP_VAULT,
  DEX_CM_NO_KEYCHAIN: '1',
  DEX_CM_ALLOW_UNVETTED: '1',
  DEX_CM_PRESENCE_OPTIONAL: '1',
};

test.after(() => {
  fs.rmSync(TMP_VAULT, { recursive: true, force: true });
  fs.rmSync(TMP_RUNTIME, { recursive: true, force: true });
});

function callbackHarness({ busyPorts = [] } = {}) {
  const servers = [];
  const createServer = () => {
    const server = new EventEmitter();
    server.listening = false;
    server.listen = (port, _host, onListening) => {
      server.port = port;
      if (busyPorts.includes(port)) {
        queueMicrotask(() => server.emit('error', Object.assign(new Error('busy'), { code: 'EADDRINUSE' })));
      } else {
        server.listening = true;
        queueMicrotask(onListening);
      }
    };
    server.address = () => ({ port: server.port });
    server.close = () => {
      server.listening = false;
    };
    servers.push(server);
    return server;
  };
  const request = (server, url) => {
    const response = {
      writeHead(status, headers = {}) {
        response.status = status;
        response.headers = headers;
        return response;
      },
      end(body) {
        response.body = body;
      },
    };
    server.emit('request', { url }, response);
    return response;
  };
  return { createServer, servers, request };
}

function tokenEndpointMock() {
  const requests = [];
  const fetch = async (_url, options) => {
    const params = new URLSearchParams(options.body);
    requests.push(Object.fromEntries(params));
    const n = requests.length + 1;
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ access_token: `AT-${n}`, refresh_token: `RT-${n}`, expires_in: 3600 }),
    };
  };
  return { fetch, requests };
}

function run(args, input) {
  return spawnSync('node', args, { env: childEnv, input, encoding: 'utf8' });
}

test('catalog source is UTF-8 text with no NUL sentinel and template fallback behavior is unchanged', () => {
  const source = fs.readFileSync(path.join(DIR, 'catalog.cjs'), 'utf8');
  assert.ok(!source.includes('\0'));
  assert.equal(
    catalog.resolveTemplate('https://${connectionConfig.host}/x || https://fallback.example/x', {}),
    'https://fallback.example/x'
  );
});

test('refresh --force hits the token endpoint for a fresh token; default refresh does not', async () => {
  const { fetch, requests } = tokenEndpointMock();
  const originalFetch = global.fetch;
  global.fetch = fetch;
  const originalGetProviderConfig = catalog.getProviderConfig;
  catalog.getProviderConfig = () => ({
    ...originalGetProviderConfig('google'),
    tokenUrl: 'https://oauth2.googleapis.com/token',
    refreshUrl: null,
  });
  try {
    store.setOAuthApp('google', { clientId: 'CID', clientSecret: 'CSECRET' });
    store.saveToken(
      'force-fresh',
      { access_token: 'AT-1', refresh_token: 'RT-1', expires_at: Date.now() + 3600_000 },
      { provider: 'google' }
    );

    await cli.cmdRefresh('force-fresh', {});
    assert.equal(requests.length, 0, 'default refresh keeps the freshness short-circuit');

    await cli.cmdRefresh('force-fresh', { force: 'true' });
    assert.equal(requests.length, 1, '--force performs the network refresh');
    assert.equal(requests[0].refresh_token, 'RT-1');
    assert.equal(store.loadToken('force-fresh').refresh_token, 'RT-2');
  } finally {
    global.fetch = originalFetch;
    catalog.getProviderConfig = originalGetProviderConfig;
    store.deleteToken('force-fresh');
  }
});

test('rotating refresh tokens persist and the next refresh uses the newest token', async () => {
  const { fetch, requests } = tokenEndpointMock();
  const originalFetch = global.fetch;
  global.fetch = fetch;
  const originalGetProviderConfig = catalog.getProviderConfig;
  catalog.getProviderConfig = () => ({
    ...originalGetProviderConfig('google'),
    tokenUrl: 'https://oauth2.googleapis.com/token',
    refreshUrl: null,
  });
  try {
    store.setOAuthApp('google', { clientId: 'CID', clientSecret: 'CSECRET' });
    store.saveToken(
      'rotating',
      { access_token: 'AT-1', refresh_token: 'RT-1', expires_at: Date.now() + 3600_000 },
      { provider: 'google' }
    );

    await health.refreshToken('rotating', { force: true });
    assert.equal(store.loadToken('rotating').refresh_token, 'RT-2');
    await health.refreshToken('rotating', { force: true });
    assert.deepEqual(
      requests.map((r) => r.refresh_token),
      ['RT-1', 'RT-2']
    );
    assert.equal(store.loadToken('rotating').refresh_token, 'RT-3');
  } finally {
    global.fetch = originalFetch;
    catalog.getProviderConfig = originalGetProviderConfig;
    store.deleteToken('rotating');
  }
});

test('macOS Keychain receives the master key on stdin, never in process arguments', () => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-keychain-argv-'));
  const storePath = path.join(DIR, 'token-store.cjs');
  const script = `
    Object.defineProperty(process, 'platform', { value: 'darwin' });
    const childProcess = require('node:child_process');
    const calls = [];
    childProcess.execFileSync = (file, args, options) => {
      calls.push({ file, args, input: options && options.input });
      if (file === 'git' && args.includes('rev-parse')) return process.env.DEX_VAULT + '\\n';
      if (file === 'git' && args.includes('ls-files')) return '';
      if (args[0] === 'find-generic-password') throw new Error('not found');
      return Buffer.alloc(0);
    };
    const store = require(${JSON.stringify(storePath)});
    store.saveApiKey('keychain-argv', { apiKey: 'API-KEY' }, { provider: 'linear' });
    process.stdout.write(JSON.stringify(calls));
  `;
  const env = { ...childEnv, DEX_VAULT: vault };
  delete env.DEX_CM_NO_KEYCHAIN;
  const result = spawnSync('node', ['-e', script], { env, encoding: 'utf8' });
  try {
    assert.equal(result.status, 0, result.stderr);
    const add = JSON.parse(result.stdout).find((call) => call.args[0] === 'add-generic-password');
    assert.ok(add, 'the test reaches the Keychain write');
    const keyArg = add.args.find((arg) => /^[A-Za-z0-9+/]{43}=$/.test(arg));
    assert.equal(keyArg, undefined, 'the base64 master key is absent from argv');
    assert.match(add.input, /^([A-Za-z0-9+/]{43}=)\n\1\n$/);
    assert.equal(add.args.at(-1), '-w');
  } finally {
    fs.rmSync(vault, { recursive: true, force: true });
  }
});

test('callback server escapes provider errors before rendering HTML', async () => {
  const harness = callbackHarness();
  const cb = await oauth.startCallbackServer({ ports: [3847], timeoutMs: 1000, createServer: harness.createServer });
  const pending = cb.waitForCode({ expectedState: 'expected-state' }).catch((error) => error);
  const response = harness.request(
    harness.servers[0],
    `/callback?error=${encodeURIComponent('<img src=x onerror=alert(1)>')}&state=expected-state`
  );
  assert.equal(response.status, 200);
  assert.doesNotMatch(response.body, /<img/i);
  assert.match((await pending).message, /provider returned error/i);
});

test('callback server ignores a mismatched state and still accepts the real callback', async () => {
  const harness = callbackHarness();
  const cb = await oauth.startCallbackServer({ ports: [3847], timeoutMs: 1000, createServer: harness.createServer });
  const pending = cb.waitForCode({ expectedState: 'expected-state' });
  let settled = false;
  pending.then(
    () => {
      settled = true;
    },
    () => {
      settled = true;
    }
  );
  const wrong = harness.request(harness.servers[0], '/callback?code=wrong-code&state=wrong-state');
  assert.equal(wrong.status, 400);
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(settled, false);

  const correct = harness.request(harness.servers[0], '/callback?code=right-code&state=expected-state');
  assert.equal(correct.status, 200);
  assert.deepEqual(await pending, { code: 'right-code', state: 'expected-state' });
});

test('callback server times out and closes cleanly', async () => {
  const harness = callbackHarness();
  const cb = await oauth.startCallbackServer({ ports: [3847], timeoutMs: 30, createServer: harness.createServer });
  const guarded = Promise.race([
    cb.waitForCode({ expectedState: 'expected-state' }),
    new Promise((_, reject) => setTimeout(() => reject(new Error('test guard expired')), 500)),
  ]);
  await assert.rejects(guarded, /timed out/i);
  cb.close();
});

test('callback server skips a contended port and completes on the next one', async () => {
  const firstPort = 3847;
  const secondPort = 3848;
  const harness = callbackHarness({ busyPorts: [firstPort] });
  const cb = await oauth.startCallbackServer({
    ports: [firstPort, secondPort],
    timeoutMs: 1000,
    createServer: harness.createServer,
  });
  try {
    assert.equal(new URL(cb.redirectUri).port, String(secondPort));
    const pending = cb.waitForCode({ expectedState: 'right-state' });
    const response = harness.request(harness.servers[1], '/callback?code=good-code&state=right-state');
    assert.equal(response.headers['Content-Type'], 'text/html; charset=utf-8');
    assert.match(response.body, /✅ Connected/);
    assert.deepEqual(await pending, { code: 'good-code', state: 'right-state' });
  } finally {
    cb.close();
  }
});

test('GCM AAD rejects an envelope copied to a different connection id without crashing', () => {
  store.saveToken('aad-source', { access_token: 'AT-A', refresh_token: 'RT-A' }, { provider: 'google' });
  store.saveToken('aad-target', { access_token: 'AT-B', refresh_token: 'RT-B' }, { provider: 'google' });
  fs.copyFileSync(path.join(TOKENS_DIR, 'aad-source.json'), path.join(TOKENS_DIR, 'aad-target.json'));

  const result = health.connectionHealth('aad-target');
  assert.equal(result.status, 'needs_reauth');
  assert.equal(result.error, 'token_envelope_account_mismatch');
  assert.equal(store.loadToken('aad-target'), null);
  store.deleteToken('aad-source');
  store.deleteToken('aad-target');
});

test('OAuth app client secrets are encrypted at rest and decrypt transparently', () => {
  store.setOAuthApp('secret-at-rest', { clientId: 'VISIBLE-ID', clientSecret: 'MUST-NOT-BE-PLAINTEXT' });
  const raw = fs.readFileSync(path.join(CRED_DIR, 'oauth-apps.json'), 'utf8');
  assert.match(raw, /VISIBLE-ID/);
  assert.ok(!raw.includes('MUST-NOT-BE-PLAINTEXT'));
  const parsed = JSON.parse(raw);
  assert.equal(parsed['secret-at-rest'].clientSecret.v, 2);
  assert.equal(store.getOAuthApp('secret-at-rest').clientSecret, 'MUST-NOT-BE-PLAINTEXT');
});

test('OAuth app secrets surface the same explicit key-loss state as tokens', () => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-app-keyloss-'));
  const env = { ...process.env, DEX_VAULT: vault, DEX_CM_NO_KEYCHAIN: '1' };
  const storePath = path.join(DIR, 'token-store.cjs');
  const save = spawnSync(
    'node',
    ['-e', `require(${JSON.stringify(storePath)}).setOAuthApp('app-only',{clientId:'ID',clientSecret:'SECRET'})`],
    { env, encoding: 'utf8' }
  );
  assert.equal(save.status, 0, save.stderr);
  fs.rmSync(path.join(vault, 'System', 'credentials', '.dex-cm.key'));

  const read = spawnSync(
    'node',
    [
      '-e',
      `try { require(${JSON.stringify(storePath)}).getOAuthApp('app-only') } catch (e) { console.error(e.code); process.exit(e.code === 'DEX_CM_KEY_LOST' ? 3 : 1) }`,
    ],
    { env, encoding: 'utf8' }
  );
  assert.equal(read.status, 3);
  assert.match(read.stderr, /DEX_CM_KEY_LOST/);
  assert.ok(fs.existsSync(path.join(vault, 'System', 'credentials', 'oauth-apps.json')));
  fs.rmSync(vault, { recursive: true, force: true });
});

test('status reports file custody when the macOS Keychain is disabled', () => {
  store.saveApiKey('custody-status', { apiKey: 'FAKE-custody-key' }, { provider: 'linear' });
  try {
    const result = run([path.join(DIR, 'connect.cjs'), 'status']);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /Encryption key: stored in your vault folder/i);
    assert.match(result.stdout, /anyone with a copy of that folder can read these credentials/i);
  } finally {
    store.deleteToken('custody-status');
  }
});

test('disconnect explains that provider access must still be revoked', () => {
  store.saveApiKey('disconnect-wording', { apiKey: 'FAKE-disconnect-key' }, { provider: 'linear' });
  const result = run([path.join(DIR, 'connect.cjs'), 'disconnect', 'disconnect-wording']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /removed from this machine/i);
  assert.match(result.stdout, /fully revoke access/i);
  assert.match(result.stdout, /provider.*account settings/i);
});

test('secret argv flags are rejected with one-line stdin guidance', () => {
  for (const args of [
    [path.join(DIR, 'connect.cjs'), 'register-app', 'google', '--client-id', 'ID', '--client-secret', 'SECRET'],
    [path.join(DIR, 'connect.cjs'), 'set-key', 'linear', '--key', 'SECRET', '--no-probe'],
  ]) {
    const result = run(args);
    assert.notEqual(result.status, 0);
    const lines = result.stderr.trim().split(/\r?\n/);
    assert.equal(lines.length, 1, result.stderr);
    assert.match(lines[0], /stdin/i);
  }
});

test('first-run credential commands fail immediately with clear interactive guidance when stdin is empty', () => {
  const cases = [
    [path.join(DIR, 'connect.cjs'), 'register-app', 'first-run-oauth'],
    [path.join(DIR, 'connect.cjs'), 'set-key', 'linear', '--no-probe'],
  ];
  for (const args of cases) {
    const result = run(args);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /interactive terminal/i);
    assert.match(result.stderr, /hidden prompt/i);
  }
  assert.equal(store.getOAuthApp('first-run-oauth'), null);
  assert.equal(store.loadToken('linear'), null);
});

test('get-token OAuth defaults to least privilege; --full and --access-token-only remain explicit', () => {
  store.saveToken(
    'least-privilege',
    { access_token: 'ACCESS', refresh_token: 'REFRESH', expires_at: Date.now() + 3600_000, scope: 'a b' },
    { provider: 'google' }
  );
  const normal = JSON.parse(run([path.join(DIR, 'get-token.cjs'), 'least-privilege']).stdout);
  assert.deepEqual(Object.keys(normal).sort(), ['access_token', 'expires_at']);
  assert.equal(normal.access_token, 'ACCESS');
  assert.ok(!JSON.stringify(normal).includes('REFRESH'));

  const full = JSON.parse(run([path.join(DIR, 'get-token.cjs'), 'least-privilege', '--full']).stdout);
  assert.equal(full.refresh_token, 'REFRESH');
  assert.equal(run([path.join(DIR, 'get-token.cjs'), 'least-privilege', '--access-token-only']).stdout, 'ACCESS');
  store.deleteToken('least-privilege');
});

test('unsupported OAuth mode is browse-only and connect refuses with the honest reason', () => {
  const descriptor = catalog.getProviderConfig('garmin');
  assert.equal(descriptor.supported, false);
  assert.match(descriptor.reason, /OAuth 1/i);

  const listed = run([path.join(DIR, 'connect.cjs'), 'providers', 'garmin']);
  assert.equal(listed.status, 0);
  assert.match(listed.stdout, /garmin/i);
  assert.match(listed.stdout, /browse-only/i);

  const attempted = run([path.join(DIR, 'connect.cjs'), 'connect', 'garmin']);
  assert.notEqual(attempted.status, 0);
  assert.match(attempted.stderr, /not connectable/i);
  assert.match(attempted.stderr, /OAuth 1/i);

  const described = run([path.join(DIR, 'connect.cjs'), 'describe', 'garmin']);
  assert.equal(described.status, 0);
  assert.match(described.stdout, /browse-only/i);
  assert.match(described.stdout, /OAuth 1/i);
});

test('verified providers are identified and supported unverified providers remain advanced-tier', () => {
  assert.deepEqual(catalog.VERIFIED_PROVIDERS, ['google', 'slack', 'linear']);
  assert.equal(catalog.getProviderConfig('google').verified, true);
  assert.equal(catalog.listOAuthProviders().some((p) => p.id === 'linear'), false, 'the key override replaces raw Linear OAuth');
  assert.equal(catalog.listKeyProviders().find((p) => p.id === 'linear').verified, true);
  const unverified = catalog.listOAuthProviders().find((p) => p.supported && !p.verified);
  assert.ok(unverified, 'the browse catalog keeps supported-but-unverified providers');
  assert.equal(catalog.getProviderConfig(unverified.id).supported, true);

  const attempted = run([path.join(DIR, 'connect.cjs'), 'connect', unverified.id]);
  assert.match(attempted.stdout, /warning: .*not security-reviewed/i);
  assert.match(attempted.stdout, /Unverified provider — advanced tier, expect quirks\./);
});

test('providers that depend on Nango post-connection scripts are browse-only', () => {
  const descriptor = catalog.getProviderConfig('atlassian-government-cloud');
  assert.equal(descriptor.supported, false);
  assert.match(descriptor.reason, /post-connection server script/i);
});

test('MCP providers that require dynamic client registration are browse-only', () => {
  const descriptor = catalog.getProviderConfig('granola-mcp');
  assert.equal(descriptor.supported, false);
  assert.match(descriptor.reason, /dynamic client registration/i);
});

test('Slack normalizes its catalog-declared alternate user access-token path', async () => {
  const originalFetch = global.fetch;
  global.fetch = async () => ({
    ok: true,
    status: 200,
    text: async () =>
      JSON.stringify({
        ok: true,
        access_token: 'BOT-TOKEN',
        authed_user: { access_token: 'USER-TOKEN' },
        refresh_token: 'REFRESH',
        expires_in: 3600,
      }),
  });
  try {
    const token = await oauth.exchangeCodeForToken(catalog.getProviderConfig('slack'), {
      code: 'CODE',
      clientId: 'ID',
      clientSecret: 'SECRET',
      redirectUri: 'http://127.0.0.1/callback',
    });
    assert.equal(token.access_token, 'USER-TOKEN');
  } finally {
    global.fetch = originalFetch;
  }
});
