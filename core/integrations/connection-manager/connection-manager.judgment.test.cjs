'use strict';

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const TMP_VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-judgment-'));
process.env.DEX_VAULT = TMP_VAULT;
process.env.DEX_CM_NO_KEYCHAIN = '1';

const DIR = __dirname;
const store = require('./token-store.cjs');
const catalog = require('./catalog.cjs');
const health = require('./health.cjs');
const oauthFlow = require('./oauth-flow.cjs');
const { refreshOAuthToken } = require('./lib/oauth-refresh.js');
const { createConnectorVerify, CATEGORY } = require('./lib/connector-verify.js');
const { createConnectorLedger } = require('./lib/connector-ledger.js');

const childEnv = { ...process.env, DEX_VAULT: TMP_VAULT, DEX_CM_NO_KEYCHAIN: '1' };

test.after(() => fs.rmSync(TMP_VAULT, { recursive: true, force: true }));

function response(status, body, headers = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => headers[String(name).toLowerCase()] ?? null },
    json: async () => body,
  };
}

function withProviderConfig(provider, overrides, fn) {
  const original = catalog.getProviderConfig;
  catalog.getProviderConfig = (id, config) =>
    id === provider ? { ...original(provider, config), ...overrides } : original(id, config);
  return Promise.resolve()
    .then(fn)
    .finally(() => {
      catalog.getProviderConfig = original;
    });
}

function seedOAuth(connId, provider, token = {}) {
  store.setOAuthApp(provider, { clientId: 'CID', clientSecret: 'CSECRET' });
  store.saveToken(
    connId,
    {
      access_token: 'OLD-AT',
      refresh_token: 'OLD-RT',
      expires_at: Date.now() - 1,
      scope: 'scope-a scope-b',
      instance_url: 'https://instance.example',
      ...token,
    },
    { provider }
  );
}

test('the legacy oauth-flow refresher is deleted so only the lifted refresher remains', () => {
  assert.equal(oauthFlow.refreshAccessToken, undefined);
  assert.doesNotMatch(fs.readFileSync(path.join(DIR, 'oauth-flow.cjs'), 'utf8'), /function refreshAccessToken/);
});

test('OAuth code exchange refuses redirects before sending codes or client secrets', async () => {
  let request;
  const originalFetch = global.fetch;
  global.fetch = async (url, options) => {
    request = { url, options };
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ access_token: 'AT', refresh_token: 'RT', expires_in: 3600 }),
    };
  };
  try {
    await oauthFlow.exchangeCodeForToken(
      {
        tokenUrl: 'https://tokens.example/exchange',
        tokenRequestAuthMethod: 'basic',
        bodyFormat: 'form',
      },
      {
        code: 'AUTH-CODE',
        clientId: 'CLIENT-ID',
        clientSecret: 'CLIENT-SECRET',
        redirectUri: 'http://127.0.0.1/callback',
      }
    );
    assert.equal(request.url, 'https://tokens.example/exchange');
    assert.equal(request.options.redirect, 'error');
  } finally {
    global.fetch = originalFetch;
  }
});

test('OAuth refresh refuses redirects before sending refresh tokens or client secrets', async () => {
  let request;
  await refreshOAuthToken({
    tokenUrl: 'https://tokens.example/refresh',
    refreshToken: 'REFRESH-TOKEN',
    clientId: 'CLIENT-ID',
    clientSecret: 'CLIENT-SECRET',
    fetchImpl: async (url, options) => {
      request = { url, options };
      return response(200, { access_token: 'AT', expires_in: 3600 });
    },
  });
  assert.equal(request.url, 'https://tokens.example/refresh');
  assert.equal(request.options.redirect, 'error');
});

test('live verification refuses redirects before sending access tokens or API keys', async () => {
  let request;
  const verifier = createConnectorVerify({
    fetchImpl: async (url, options) => {
      request = { url, options };
      return response(200, { data: { viewer: { id: 'viewer-1' } } });
    },
  });
  const result = await verifier.verify('linear', { provider: 'linear', token: 'LINEAR-KEY' });
  assert.equal(result.ok, true);
  assert.equal(request.options.redirect, 'error');
});

test('permanent refresh failure stamps needs_reauth and records refresh + break evidence', async () => {
  seedOAuth('refresh-permanent', 'google');
  const originalFetch = global.fetch;
  global.fetch = async () => response(400, { error: 'invalid_grant' });
  try {
    await withProviderConfig(
      'google',
      { tokenUrl: 'https://tokens.example/refresh', refreshUrl: null },
      async () => {
        await assert.rejects(health.refreshToken('refresh-permanent', { force: true }), (error) => {
          assert.equal(error.needsReauth, true);
          assert.equal(error.permanent, true);
          return true;
        });
      }
    );
    const reg = store.readRegistry()['refresh-permanent'];
    assert.equal(reg.status, 'needs_reauth');
    assert.equal(reg.error, 'invalid_grant');
    assert.deepEqual(
      health.connectionLedger().tail('refresh-permanent', 2).map((entry) => entry.op),
      ['refresh', 'break']
    );
  } finally {
    global.fetch = originalFetch;
    store.deleteToken('refresh-permanent');
  }
});

test('transient 500 retries once, succeeds, and never stamps a reconnect error', async () => {
  seedOAuth('refresh-transient', 'google');
  let calls = 0;
  const originalFetch = global.fetch;
  global.fetch = async () => {
    calls += 1;
    return calls === 1
      ? response(500, { error: 'server_error' })
      : response(200, { access_token: 'NEW-AT', expires_in: 3600 });
  };
  try {
    await withProviderConfig(
      'google',
      { tokenUrl: 'https://tokens.example/refresh', refreshUrl: null, refreshRetryDelayMs: 0 },
      async () => {
        assert.equal(await health.refreshToken('refresh-transient', { force: true }), 'NEW-AT');
      }
    );
    assert.equal(calls, 2);
    const reg = store.readRegistry()['refresh-transient'];
    assert.equal(reg.status, 'connected');
    assert.equal(reg.error, null);
  } finally {
    global.fetch = originalFetch;
    store.deleteToken('refresh-transient');
  }
});

test('429 Retry-After is honored and clamped to sixty seconds', async () => {
  let calls = 0;
  const waits = [];
  const token = await refreshOAuthToken({
    tokenUrl: 'https://tokens.example/refresh',
    refreshToken: 'RT',
    clientId: 'CID',
    fetchImpl: async () => {
      calls += 1;
      return calls === 1
        ? response(429, {}, { 'retry-after': '120' })
        : response(200, { access_token: 'AT', expires_in: 60 });
    },
    delayImpl: async (ms) => waits.push(ms),
  });
  assert.equal(token.accessToken, 'AT');
  assert.deepEqual(waits, [60_000]);
});

test('Slack nested rotated token is normalized without losing scope or instance_url', async () => {
  seedOAuth('slack-nested', 'slack');
  const originalFetch = global.fetch;
  global.fetch = async () =>
    response(200, {
      ok: true,
      authed_user: { access_token: 'SLACK-AT', refresh_token: 'SLACK-RT', expires_in: 7200 },
    });
  try {
    await withProviderConfig(
      'slack',
      { tokenUrl: 'https://slack.example/refresh', refreshUrl: null },
      async () => {
        assert.equal(await health.refreshToken('slack-nested', { force: true }), 'SLACK-AT');
      }
    );
    const stored = store.loadToken('slack-nested');
    assert.equal(stored.access_token, 'SLACK-AT');
    assert.equal(stored.refresh_token, 'SLACK-RT');
    assert.equal(stored.scope, 'scope-a scope-b');
    assert.equal(stored.instance_url, 'https://instance.example');
  } finally {
    global.fetch = originalFetch;
    store.deleteToken('slack-nested');
  }
});

test('two concurrent forced refreshes share one network call', async () => {
  seedOAuth('refresh-single-flight', 'google');
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const originalFetch = global.fetch;
  global.fetch = async () => {
    calls += 1;
    await gate;
    return response(200, { access_token: 'ONE-AT', expires_in: 3600 });
  };
  try {
    await withProviderConfig(
      'google',
      { tokenUrl: 'https://tokens.example/refresh', refreshUrl: null },
      async () => {
        const first = health.refreshToken('refresh-single-flight', { force: true });
        const second = health.ensureFreshToken('refresh-single-flight');
        release();
        assert.deepEqual(await Promise.all([first, second]), ['ONE-AT', 'ONE-AT']);
      }
    );
    assert.equal(calls, 1);
  } finally {
    global.fetch = originalFetch;
    store.deleteToken('refresh-single-flight');
  }
});

test('provider probes use one bounded authenticated read and only auth-class signals disconnect', async () => {
  const verify401 = createConnectorVerify({
    fetchImpl: async () => response(401, { error: 'invalid_token' }),
  });
  assert.equal((await verify401.verify('google', { provider: 'google', token: 'AT' })).error.category, CATEGORY.AUTH_PERMANENT);

  const verify429 = createConnectorVerify({
    fetchImpl: async () => response(429, {}, { 'retry-after': '2' }),
  });
  assert.equal((await verify429.verify('google', { provider: 'google', token: 'AT' })).error.category, CATEGORY.RATE_LIMITED);

  const verifyOffline = createConnectorVerify({
    fetchImpl: async () => {
      throw new Error('offline');
    },
  });
  assert.equal((await verifyOffline.verify('slack', { provider: 'slack', token: 'AT' })).error.category, CATEGORY.OFFLINE);

  const verifyTimeout = createConnectorVerify({
    timeoutMs: 5,
    fetchImpl: (_url, options) =>
      new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
      }),
  });
  assert.equal((await verifyTimeout.verify('slack', { provider: 'slack', token: 'AT' })).error.category, CATEGORY.TIMEOUT);
});

test('Linear GraphQL 401 AUTHENTICATION_ERROR is a disconnect signal', async () => {
  const verifier = createConnectorVerify({
    fetchImpl: async () =>
      response(401, {
        errors: [{ message: 'Authentication required', extensions: { code: 'AUTHENTICATION_ERROR', statusCode: 401 } }],
      }),
  });
  const result = await verifier.verify('linear', { provider: 'linear', token: 'lin-key' });
  assert.equal(result.error.category, CATEGORY.AUTH_PERMANENT);
});

test('probe stamps only permanent auth failures and records every attempt without token material', async () => {
  store.saveApiKey('linear-probe', { apiKey: 'SECRET-LINEAR-TOKEN' }, { provider: 'linear' });
  try {
    const unknown = await health.probeConnection('linear-probe', {
      fetchImpl: async () => response(429, {}, { 'retry-after': '1' }),
    });
    assert.equal(unknown.error.category, CATEGORY.RATE_LIMITED);
    assert.equal(store.readRegistry()['linear-probe'].error, null);

    const broken = await health.probeConnection('linear-probe', {
      fetchImpl: async () =>
        response(401, {
          errors: [{ extensions: { code: 'AUTHENTICATION_ERROR', statusCode: 401 } }],
        }),
    });
    assert.equal(broken.error.category, CATEGORY.AUTH_PERMANENT);
    assert.equal(store.readRegistry()['linear-probe'].status, 'needs_reauth');

    const ledgerText = fs.readFileSync(
      path.join(store.credentialsDir(), 'ledger', 'linear-probe.jsonl'),
      'utf8'
    );
    assert.ok(!ledgerText.includes('SECRET-LINEAR-TOKEN'));
    assert.deepEqual(
      ledgerText.trim().split('\n').map((line) => JSON.parse(line).op),
      ['probe', 'probe', 'break']
    );
  } finally {
    store.deleteToken('linear-probe');
  }
});

test('timeout, 429, and network probe failures stay unknown and never stamp needs_reauth', async () => {
  const cases = [
    [
      'probe-429',
      {
        fetchImpl: async () => response(429, {}, { 'retry-after': '1' }),
      },
      CATEGORY.RATE_LIMITED,
    ],
    [
      'probe-network',
      {
        fetchImpl: async () => {
          throw new Error('offline');
        },
      },
      CATEGORY.OFFLINE,
    ],
    [
      'probe-timeout',
      {
        timeoutMs: 5,
        fetchImpl: (_url, options) =>
          new Promise((_resolve, reject) => {
            options.signal.addEventListener('abort', () =>
              reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
            );
          }),
      },
      CATEGORY.TIMEOUT,
    ],
  ];
  for (const [connId, options, category] of cases) {
    store.saveApiKey(connId, { apiKey: `${connId}-secret` }, { provider: 'linear' });
    try {
      const result = await health.probeConnection(connId, options);
      assert.equal(result.error.category, category);
      assert.equal(store.readRegistry()[connId].status, 'connected');
      assert.equal(store.readRegistry()[connId].error, null);
      assert.equal(health.connectionHealth(connId).verified, false);
    } finally {
      store.deleteToken(connId);
    }
  }
});

test('ledger is per-connection JSONL, atomic-writer backed, capped, and secret-whitelisted', () => {
  const stateDir = path.join(TMP_VAULT, 'ledger-unit');
  const ledger = createConnectorLedger({ stateDir, maxEntriesPerConnector: 2, now: () => 1_700_000_000_000 });
  ledger.append('google:work', { op: 'connect', ok: true, access_token: 'NEVER-WRITE-AT' });
  ledger.append('google:work', { op: 'refresh', ok: true, refresh_token: 'NEVER-WRITE-RT' });
  ledger.append('google:work', { op: 'probe', ok: true });

  const file = path.join(stateDir, 'google:work.jsonl');
  const text = fs.readFileSync(file, 'utf8');
  const rows = text.trim().split('\n').map((line) => JSON.parse(line));
  assert.deepEqual(rows.map((row) => row.op), ['refresh', 'probe']);
  assert.ok(!text.includes('NEVER-WRITE'));
  assert.equal(ledger.rollup('google:work').lastVerifiedAt, new Date(1_700_000_000_000).toISOString());
});

test('status distinguishes stored-but-unverified from probe-verified and supports JSON', async () => {
  store.saveApiKey('linear-status', { apiKey: 'STATUS-KEY' }, { provider: 'linear' });
  try {
    let current = health.connectionHealth('linear-status');
    assert.equal(current.status, 'connected');
    assert.equal(current.verified, false);
    assert.equal(current.lastVerifiedAt, null);

    await health.probeConnection('linear-status', {
      fetchImpl: async () => response(200, { data: { viewer: { id: 'viewer-1' } } }),
    });
    current = health.connectionHealth('linear-status');
    assert.equal(current.verified, true);
    assert.match(current.lastVerifiedAt, /^\d{4}-\d{2}-\d{2}T/);

    const jsonRun = spawnSync('node', [path.join(DIR, 'connect.cjs'), 'status', '--json'], {
      env: childEnv,
      encoding: 'utf8',
    });
    assert.equal(jsonRun.status, 0, jsonRun.stderr);
    const payload = JSON.parse(jsonRun.stdout);
    const row = payload.connections.find((entry) => entry.service === 'linear-status');
    assert.equal(row.verified, true);
    assert.equal(typeof row.lastVerifiedAt, 'string');

    const textRun = spawnSync('node', [path.join(DIR, 'connect.cjs'), 'status'], {
      env: childEnv,
      encoding: 'utf8',
    });
    assert.equal(textRun.status, 0, textRun.stderr);
    assert.match(textRun.stdout, /last verified/i);
  } finally {
    store.deleteToken('linear-status');
  }
});

test('probe CLI supports one connection and stamps permanent auth failure', () => {
  store.saveApiKey('linear-cli-probe', { apiKey: 'CLI-PROBE-KEY' }, { provider: 'linear' });
  const script = `
    global.fetch = async () => ({
      ok: false,
      status: 401,
      headers: { get() { return null; } },
      async json() { return { errors: [{ extensions: { code: 'AUTHENTICATION_ERROR', statusCode: 401 } }] }; }
    });
    process.argv = ['node', ${JSON.stringify(path.join(DIR, 'connect.cjs'))}, 'probe', 'linear-cli-probe', '--json'];
    require(${JSON.stringify(path.join(DIR, 'connect.cjs'))}).main();
  `;
  try {
    const run = spawnSync('node', ['-e', script], { env: childEnv, encoding: 'utf8' });
    assert.equal(run.status, 1, run.stderr);
    const payload = JSON.parse(run.stdout);
    assert.equal(payload.results[0].status, 'needs_reauth');
    assert.equal(store.readRegistry()['linear-cli-probe'].status, 'needs_reauth');
  } finally {
    store.deleteToken('linear-cli-probe');
  }
});

test('set-key records a secret-free connect event', () => {
  const run = spawnSync(
    'node',
    [path.join(DIR, 'connect.cjs'), 'set-key', 'linear:connect-ledger', '--no-probe'],
    { env: childEnv, input: 'CONNECT-SECRET\n', encoding: 'utf8' }
  );
  try {
    assert.equal(run.status, 0, run.stderr);
    const ledgerFile = path.join(store.credentialsDir(), 'ledger', 'linear:connect-ledger.jsonl');
    const text = fs.readFileSync(ledgerFile, 'utf8');
    assert.deepEqual(text.trim().split('\n').map((line) => JSON.parse(line).op), ['connect']);
    assert.ok(!text.includes('CONNECT-SECRET'));
  } finally {
    store.deleteToken('linear:connect-ledger');
  }
});

test('set-key persists a successful live verification in the durable ledger', () => {
  const connId = 'linear:verified-on-save';
  const script = `
    global.fetch = async () => ({
      ok: true,
      status: 200,
      headers: { get() { return null; } },
      async json() { return { data: { viewer: { id: 'viewer-1' } } }; }
    });
    process.argv = ['node', ${JSON.stringify(path.join(DIR, 'connect.cjs'))}, 'set-key', ${JSON.stringify(connId)}];
    require(${JSON.stringify(path.join(DIR, 'connect.cjs'))}).main();
  `;
  const run = spawnSync('node', ['-e', script], {
    env: childEnv,
    input: 'VERIFIED-SECRET\n',
    encoding: 'utf8',
  });
  try {
    assert.equal(run.status, 0, run.stderr);
    assert.match(run.stdout, /Verified live/);
    assert.deepEqual(
      health.connectionLedger().tail(connId, 2).map((entry) => [entry.op, entry.ok]),
      [
        ['connect', true],
        ['probe', true],
      ]
    );
    assert.equal(health.connectionHealth(connId).verified, true);
  } finally {
    store.deleteToken(connId);
  }
});
