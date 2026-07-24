'use strict';

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { spawnSync } = require('node:child_process');

const TMP_VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-phase5a-'));
const TMP_RUNTIME = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-phase5a-runtime-'));
process.env.DEX_VAULT = TMP_VAULT;
process.env.DEX_CM_RUNTIME_DIR = TMP_RUNTIME;
process.env.DEX_CM_BROKER_IDLE_MS = '100';
process.env.DEX_CM_NO_KEYCHAIN = '1';

const store = require('./token-store.cjs');
const oauth = require('./oauth-flow.cjs');
const health = require('./health.cjs');

test.after(() => {
  fs.rmSync(TMP_VAULT, { recursive: true, force: true });
  fs.rmSync(TMP_RUNTIME, { recursive: true, force: true });
});

function callbackHarness() {
  const server = new EventEmitter();
  server.listening = false;
  server.listen = (port, _host, onListening) => {
    server.port = port;
    server.listening = true;
    queueMicrotask(onListening);
  };
  server.address = () => ({ port: server.port });
  server.close = () => {
    server.listening = false;
  };
  const request = (url) => {
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
  return { server, createServer: () => server, request };
}

test('M1: encrypted envelopes reject truncated GCM tags and preserve normal round-trips', () => {
  const envelope = store.encrypt('phase5a-secret', 'token:m1');

  assert.equal(store.decrypt(envelope, 'token:m1'), 'phase5a-secret');
  for (const bytes of [4, 8, 15]) {
    const truncated = {
      ...envelope,
      tag: Buffer.from(envelope.tag, 'base64').subarray(0, bytes).toString('base64'),
    };
    assert.throws(
      () => store.decrypt(truncated, 'token:m1'),
      /Unsupported encrypted credential envelope/i,
      `${bytes}-byte tag must be rejected before decryption`
    );
  }
});

test('M2: callback provider errors are HTML-safe and carry browser hardening headers', async () => {
  const harness = callbackHarness();
  const callback = await oauth.startCallbackServer({
    ports: [3847],
    timeoutMs: 1000,
    createServer: harness.createServer,
  });
  const pending = callback.waitForCode({ expectedState: 'right-state' });
  const rejected = assert.rejects(pending, /Provider returned error/);
  const response = harness.request(
    '/callback?state=right-state&error=%3Cscript%3Ealert(1)%3C%2Fscript%3E'
  );

  assert.equal(response.headers['Content-Type'], 'text/html; charset=utf-8');
  assert.equal(response.headers['Content-Security-Policy'], "default-src 'none'");
  assert.equal(response.headers['X-Content-Type-Options'], 'nosniff');
  assert.doesNotMatch(response.body, /<script>/i);
  assert.match(response.body, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  await rejected;
});

test('M4: connection ids reject the filename separator sentinel', () => {
  assert.throws(
    () => store.saveApiKey('foo__bar', { apiKey: 'FAKE-COLLISION-KEY' }),
    /reserved.*__/i
  );
  assert.throws(
    () => store.saveApiKey('foo:bar__baz', { apiKey: 'FAKE-COLLISION-KEY' }),
    /reserved.*__/i
  );
});

test('L1: invalid callback traffic cannot abort a pending OAuth flow', async () => {
  const harness = callbackHarness();
  const callback = await oauth.startCallbackServer({
    ports: [3847],
    timeoutMs: 1000,
    createServer: harness.createServer,
  });
  const pending = callback.waitForCode({ expectedState: 'right-state' });
  let settled = false;
  pending.then(
    () => {
      settled = true;
    },
    () => {
      settled = true;
    }
  );

  const unsolicited = harness.request('/callback?code=attacker&state=wrong-state');
  assert.equal(unsolicited.status, 404);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(settled, false, 'invalid state must leave the OAuth attempt pending');

  const valid = harness.request('/callback?code=good-code&state=right-state');
  assert.equal(valid.status, 200);
  assert.deepEqual(await pending, { code: 'good-code', state: 'right-state' });
});

test(
  'H2: a failing macOS keychain cannot silently fall back beside ciphertext',
  { skip: process.platform === 'darwin' ? false : 'macOS keychain behavior' },
  () => {
    const fakeBin = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-fake-security-'));
    const fakeSecurity = path.join(fakeBin, 'security');
    fs.writeFileSync(fakeSecurity, '#!/bin/sh\nexit 1\n', { mode: 0o700 });
    const storePath = path.join(__dirname, 'token-store.cjs');
    const command = `require(${JSON.stringify(storePath)}).encrypt('secret')`;

    const keychainVault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-keychain-fail-'));
    const keychainEnv = { ...process.env, DEX_VAULT: keychainVault, PATH: `${fakeBin}:${process.env.PATH}` };
    delete keychainEnv.DEX_CM_NO_KEYCHAIN;
    const failed = spawnSync(process.execPath, ['-e', command], { env: keychainEnv, encoding: 'utf8' });

    const fileVault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-keyfile-ok-'));
    const fileEnv = { ...keychainEnv, DEX_VAULT: fileVault, DEX_CM_NO_KEYCHAIN: '1' };
    const allowed = spawnSync(process.execPath, ['-e', command], { env: fileEnv, encoding: 'utf8' });

    try {
      assert.notEqual(failed.status, 0);
      assert.match(failed.stderr, /keychain.*failed|could not.*keychain/i);
      assert.equal(
        fs.existsSync(path.join(keychainVault, 'System', 'credentials', '.dex-cm.key')),
        false
      );
      assert.equal(allowed.status, 0, allowed.stderr);
      assert.equal(
        fs.existsSync(path.join(fileVault, 'System', 'credentials', '.dex-cm.key')),
        true
      );
    } finally {
      fs.rmSync(fakeBin, { recursive: true, force: true });
      fs.rmSync(keychainVault, { recursive: true, force: true });
      fs.rmSync(fileVault, { recursive: true, force: true });
    }
  }
);

test('H5: dex-call --status redacts encoded query-parameter credentials', () => {
  const secret = '/?+ ';
  const preloadDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-offline-fetch-'));
  const preload = path.join(preloadDir, 'preload.cjs');
  fs.writeFileSync(
    preload,
    "globalThis.fetch=async()=>({ok:true,status:200,statusText:'OK',text:async()=>'{}'});\n"
  );
  store.saveApiKey('google-gemini', { apiKey: secret }, { provider: 'google-gemini', authMode: 'API_KEY' });

  const result = spawnSync(
    process.execPath,
    ['--require', preload, path.join(__dirname, 'dex-call.cjs'), 'google-gemini', '/v1/models', '--status', '--raw'],
    {
      env: {
        ...process.env,
        DEX_VAULT: TMP_VAULT,
        DEX_CM_NO_KEYCHAIN: '1',
        DEX_CM_ALLOW_UNVETTED: '1',
      },
      encoding: 'utf8',
    }
  );

  try {
    assert.equal(result.status, 0, result.stderr);
    const output = `${result.stdout}\n${result.stderr}`;
    for (const representation of [
      secret,
      encodeURIComponent(secret),
      new URLSearchParams({ value: secret }).get('value'),
      new URLSearchParams({ value: secret }).toString().slice('value='.length),
      Buffer.from(secret).toString('base64'),
    ]) {
      assert.ok(!output.includes(representation), `status output leaked ${JSON.stringify(representation)}: ${output}`);
    }
    assert.match(result.stderr, /\*\*\*/);
  } finally {
    store.deleteToken('google-gemini');
    fs.rmSync(preloadDir, { recursive: true, force: true });
  }
});

test('H5: OAuth code-exchange errors never expose reflected codes or client secrets', async () => {
  const authorizationCode = 'FAKE-AUTH-CODE-MUST-NOT-LEAK';
  const clientSecret = 'FAKE-CLIENT-SECRET-MUST-NOT-LEAK';
  const originalFetch = global.fetch;
  global.fetch = async () => ({
    ok: false,
    status: 400,
    text: async () =>
      JSON.stringify({ error: `invalid_grant ${authorizationCode} ${clientSecret}` }),
  });

  try {
    await assert.rejects(
      oauth.exchangeCodeForToken(
        {
          tokenUrl: 'https://offline-token-endpoint.invalid/token',
          tokenRequestAuthMethod: 'body',
          bodyFormat: 'form',
        },
        {
          code: authorizationCode,
          clientId: 'FAKE-CLIENT-ID',
          clientSecret,
          redirectUri: 'http://127.0.0.1/callback',
        }
      ),
      (error) => {
        const diagnostic = `${error.message}\n${JSON.stringify(error)}`;
        assert.ok(!diagnostic.includes(authorizationCode), diagnostic);
        assert.ok(!diagnostic.includes(clientSecret), diagnostic);
        assert.equal(error.body, undefined);
        assert.equal(error.code, 'token_exchange_rejected');
        return true;
      }
    );
  } finally {
    global.fetch = originalFetch;
  }
});

test('H5: OAuth refresh stores only a normalized error code, never a reflected secret', async () => {
  const connId = 'h5-refresh';
  const refreshToken = 'FAKE-REFRESH-TOKEN-MUST-NOT-LEAK';
  const clientSecret = 'FAKE-REFRESH-CLIENT-SECRET-MUST-NOT-LEAK';
  store.setOAuthApp('google', { clientId: 'FAKE-CLIENT-ID', clientSecret });
  store.saveToken(
    connId,
    {
      access_token: 'FAKE-OLD-ACCESS-TOKEN',
      refresh_token: refreshToken,
      expires_at: Date.now() - 1,
    },
    { provider: 'google' }
  );

  const originalFetch = global.fetch;
  global.fetch = async () => ({
    ok: false,
    status: 400,
    headers: { get: () => null },
    json: async () => ({
      error: 'invalid_grant',
      error_description: `provider echoed ${refreshToken} ${clientSecret}`,
    }),
  });

  try {
    await assert.rejects(health.refreshToken(connId, { force: true }), (error) => {
      assert.ok(!error.message.includes(refreshToken), error.message);
      assert.ok(!error.message.includes(clientSecret), error.message);
      return true;
    });
    const registry = store.readRegistry()[connId];
    const evidence = health.connectionLedger().tail(connId, 10);
    const persisted = JSON.stringify({ registry, evidence });
    assert.equal(registry.error, 'invalid_grant');
    assert.ok(!persisted.includes(refreshToken), persisted);
    assert.ok(!persisted.includes(clientSecret), persisted);
  } finally {
    global.fetch = originalFetch;
    store.deleteToken(connId);
  }
});

test('H6: credential writes fail closed when any credentials path is already git-tracked', () => {
  const storePath = path.join(__dirname, 'token-store.cjs');
  const command = `require(${JSON.stringify(storePath)}).saveApiKey('h6-test',{apiKey:'FAKE-H6-KEY'})`;
  const makeRepo = (prefix) => {
    const vault = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
    const init = spawnSync('git', ['init', '-q', vault], { encoding: 'utf8' });
    assert.equal(init.status, 0, init.stderr);
    return vault;
  };

  const trackedVault = makeRepo('dex-cm-h6-tracked-');
  const trackedCredentials = path.join(trackedVault, 'System', 'credentials');
  fs.mkdirSync(trackedCredentials, { recursive: true });
  fs.writeFileSync(path.join(trackedCredentials, 'x'), 'already tracked\n');
  const add = spawnSync('git', ['-C', trackedVault, 'add', 'System/credentials/x'], {
    encoding: 'utf8',
  });
  assert.equal(add.status, 0, add.stderr);

  const cleanVault = makeRepo('dex-cm-h6-clean-');
  const run = (vault) =>
    spawnSync(process.execPath, ['-e', command], {
      env: { ...process.env, DEX_VAULT: vault, DEX_CM_NO_KEYCHAIN: '1' },
      encoding: 'utf8',
    });
  const blocked = run(trackedVault);
  const allowed = run(cleanVault);

  try {
    assert.notEqual(blocked.status, 0);
    assert.match(blocked.stderr, /tracked.*System\/credentials|git rm --cached/i);
    assert.equal(fs.existsSync(path.join(trackedCredentials, '.dex-cm.key')), false);
    assert.equal(fs.existsSync(path.join(trackedCredentials, 'connections.json')), false);
    assert.equal(fs.existsSync(path.join(trackedCredentials, 'tokens')), false);
    assert.equal(allowed.status, 0, allowed.stderr);
    assert.equal(
      fs.existsSync(path.join(cleanVault, 'System', 'credentials', 'tokens', 'h6-test.json')),
      true
    );
  } finally {
    fs.rmSync(trackedVault, { recursive: true, force: true });
    fs.rmSync(cleanVault, { recursive: true, force: true });
  }
});
