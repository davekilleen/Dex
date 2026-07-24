'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const pinned = require('./pinned-providers.cjs');
const TMP_VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-phase5b-'));
const TMP_RUNTIME = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-phase5b-runtime-'));
process.env.DEX_VAULT = TMP_VAULT;
process.env.DEX_CM_RUNTIME_DIR = TMP_RUNTIME;
process.env.DEX_CM_BROKER_IDLE_MS = '100';
process.env.DEX_CM_NO_KEYCHAIN = '1';

const catalog = require('./catalog.cjs');
const oauth = require('./oauth-flow.cjs');
const store = require('./token-store.cjs');
const connect = require('./connect.cjs');
const dexCall = require('./dex-call.cjs');
const health = require('./health.cjs');

const DIR = __dirname;
const childEnv = {
  ...process.env,
  DEX_VAULT: TMP_VAULT,
  DEX_CM_NO_KEYCHAIN: '1',
  DEX_CM_PRESENCE_OPTIONAL: '1',
};

test.after(() => {
  fs.rmSync(TMP_VAULT, { recursive: true, force: true });
  fs.rmSync(TMP_RUNTIME, { recursive: true, force: true });
});

test('reviewed providers expose immutable origin pins and reject every unpinned destination', () => {
  assert.equal(pinned.isVetted('google'), true);
  assert.equal(pinned.isVetted('linear'), true);
  assert.equal(pinned.isVetted('active-campaign'), false);
  assert.deepEqual(pinned.pinnedOriginsFor('google'), {
    authorizationOrigin: 'https://accounts.google.com',
    tokenOrigin: 'https://oauth2.googleapis.com',
    refreshOrigin: 'https://oauth2.googleapis.com',
    apiOrigins: ['https://www.googleapis.com'],
    verificationOrigin: 'https://www.googleapis.com',
    tenant: null,
  });
  assert.equal(Object.isFrozen(pinned.pinnedOriginsFor('google')), true);
  assert.equal(Object.isFrozen(pinned.pinnedOriginsFor('google').apiOrigins), true);

  assert.doesNotThrow(() => pinned.assertPinnedOrigin('google', 'authorization', 'https://accounts.google.com/o/oauth2/v2/auth'));
  assert.doesNotThrow(() => pinned.assertPinnedOrigin('google', 'token', 'https://oauth2.googleapis.com/token'));
  assert.doesNotThrow(() => pinned.assertPinnedOrigin('linear', 'api', 'https://api.linear.app/graphql'));

  for (const [provider, kind, url] of [
    ['google', 'api', 'https://evil.example/calendar'],
    ['google', 'api', 'http://www.googleapis.com/calendar'],
    ['linear', 'token', 'https://api.linear.app/oauth/token'],
    ['unknown-provider', 'api', 'https://api.example.test'],
  ]) {
    assert.throws(
      () => pinned.assertPinnedOrigin(provider, kind, url),
      (error) => error && error.code === 'DEX_CM_ORIGIN_UNPINNED' && error.exitCode === 1
    );
  }
});

test('tenant origin pins accept exactly one reviewed subdomain label', () => {
  pinned.__setPinnedForTest({
    'tenant-fixture': {
      apiOrigins: [],
      verificationOrigin: null,
      tenant: {
        pinnedSuffix: 'activehosted.com',
        labelPattern: '^[a-z0-9][a-z0-9-]{0,62}$',
      },
    },
  });
  try {
    assert.doesNotThrow(() =>
      pinned.assertPinnedOrigin('tenant-fixture', 'api', 'https://acme.activehosted.com/api/3')
    );
    for (const url of [
      'https://activehosted.com/api/3',
      'https://a.b.activehosted.com/api/3',
      'https://acme.activehosted.com.evil.example/api/3',
      'http://acme.activehosted.com/api/3',
    ]) {
      assert.throws(
        () => pinned.assertPinnedOrigin('tenant-fixture', 'api', url),
        (error) => error && error.code === 'DEX_CM_ORIGIN_UNPINNED'
      );
    }
  } finally {
    pinned.__setPinnedForTest(null);
  }
});

test('credential-bearing request builders refuse catalog drift away from vetted origins', async () => {
  const googleContext = {
    provider: 'google',
    baseUrl: 'https://evil.example',
    headers: { Authorization: 'Bearer SECRET' },
    query: {},
  };
  assert.throws(
    () => dexCall.buildRequest(googleContext, 'GET', '/calendar', {}),
    (error) => error && error.code === 'DEX_CM_ORIGIN_UNPINNED' && error.exitCode === 1
  );

  const google = catalog.getProviderConfig('google');
  assert.throws(
    () => oauth.buildAuthorizationUrl(
      { ...google, authorizationUrl: 'https://evil.example/oauth' },
      { clientId: 'CID', redirectUri: 'http://127.0.0.1/callback' }
    ),
    (error) => error && error.code === 'DEX_CM_ORIGIN_UNPINNED'
  );

  let fetchCalled = false;
  const originalFetch = global.fetch;
  global.fetch = async () => {
    fetchCalled = true;
    throw new Error('must not send');
  };
  try {
    await assert.rejects(
      oauth.exchangeCodeForToken(
        { ...google, tokenUrl: 'https://evil.example/token' },
        {
          code: 'CODE',
          clientId: 'CID',
          clientSecret: 'SECRET',
          redirectUri: 'http://127.0.0.1/callback',
        }
      ),
      (error) => error && error.code === 'DEX_CM_ORIGIN_UNPINNED'
    );
    assert.equal(fetchCalled, false);
  } finally {
    global.fetch = originalFetch;
  }

  fetchCalled = false;
  global.fetch = async () => {
    fetchCalled = true;
    throw new Error('must not send');
  };
  try {
    await assert.rejects(
      connect.probeKey(
        'linear',
        { ...catalog.getProviderConfig('linear'), proxyBaseUrl: 'https://evil.example' },
        { apiKey: 'SECRET' }
      ),
      (error) => error && error.code === 'DEX_CM_ORIGIN_UNPINNED'
    );
    assert.equal(fetchCalled, false);
  } finally {
    global.fetch = originalFetch;
  }

  const refreshConn = 'google:origin-drift';
  store.setOAuthApp('google', { clientId: 'CID', clientSecret: 'SECRET' });
  store.saveToken(
    refreshConn,
    { access_token: 'OLD', refresh_token: 'REFRESH', expires_at: Date.now() - 1 },
    { provider: 'google' }
  );
  const originalGetProviderConfig = catalog.getProviderConfig;
  catalog.getProviderConfig = (id, config) =>
    id === 'google'
      ? { ...originalGetProviderConfig(id, config), tokenUrl: 'https://evil.example/token', refreshUrl: null }
      : originalGetProviderConfig(id, config);
  fetchCalled = false;
  global.fetch = async () => {
    fetchCalled = true;
    throw new Error('must not send');
  };
  try {
    await assert.rejects(
      health.refreshToken(refreshConn, { force: true }),
      (error) => error && error.code === 'DEX_CM_ORIGIN_UNPINNED'
    );
    assert.equal(fetchCalled, false);
  } finally {
    global.fetch = originalFetch;
    catalog.getProviderConfig = originalGetProviderConfig;
    store.deleteToken(refreshConn);
  }
});

test('unvetted connect use needs explicit consent and never auto-probes', async () => {
  const provider = 'airtable-pat';
  const refused = spawnSync(
    process.execPath,
    [path.join(DIR, 'connect.cjs'), 'set-key', provider, '--no-probe'],
    { env: childEnv, input: 'UNVETTED-SECRET\n', encoding: 'utf8' }
  );
  assert.equal(refused.status, 1);
  assert.match(refused.stderr, /not security-reviewed/i);

  const allowed = spawnSync(
    process.execPath,
    [path.join(DIR, 'connect.cjs'), 'set-key', provider, '--allow-unvetted', '--no-probe'],
    { env: childEnv, input: 'UNVETTED-SECRET\n', encoding: 'utf8' }
  );
  try {
    assert.equal(allowed.status, 0, allowed.stderr);
    assert.match(allowed.stdout, /warning.*not security-reviewed/i);
  } finally {
    if (store.getConnection(provider)) store.deleteToken(provider);
  }

  let probeCalls = 0;
  const originalFetch = global.fetch;
  global.fetch = async () => {
    probeCalls += 1;
    throw new Error('must not send');
  };
  try {
    const outcome = await connect.probeKey(
      provider,
      catalog.getProviderConfig(provider),
      { apiKey: 'UNVETTED-SECRET' }
    );
    assert.equal(outcome, 'skipped');
    assert.equal(probeCalls, 0);
  } finally {
    global.fetch = originalFetch;
  }
});

test('unvetted dex-call refuses by default and warns after explicit consent', () => {
  const connId = 'airtable-pat:call-consent';
  const preload = path.join(TMP_VAULT, 'offline-fetch.cjs');
  fs.writeFileSync(
    preload,
    "globalThis.fetch=async()=>({ok:true,status:200,statusText:'OK',text:async()=>'{}'});\n"
  );
  store.saveApiKey(connId, { apiKey: 'UNVETTED-CALL-SECRET' }, { provider: 'airtable-pat', authMode: 'API_KEY' });
  try {
    const refused = spawnSync(
      process.execPath,
      ['--require', preload, path.join(DIR, 'dex-call.cjs'), connId, '/v0/meta'],
      { env: childEnv, encoding: 'utf8' }
    );
    assert.equal(refused.status, 1);
    assert.match(refused.stderr, /not security-reviewed/i);

    const allowed = spawnSync(
      process.execPath,
      ['--require', preload, path.join(DIR, 'dex-call.cjs'), connId, '/v0/meta', '--allow-unvetted'],
      { env: childEnv, encoding: 'utf8' }
    );
    assert.equal(allowed.status, 0, allowed.stderr);
    assert.match(allowed.stderr, /warning.*not security-reviewed/i);
  } finally {
    store.deleteToken(connId);
  }
});

function registryFile() {
  return path.join(store.credentialsDir(), 'connections.json');
}

function tokenFile(connId) {
  return path.join(store.credentialsDir(), 'tokens', `${connId.replace(/:/g, '__')}.json`);
}

function readRawRegistry() {
  return JSON.parse(fs.readFileSync(registryFile(), 'utf8'));
}

function registryMacPayload(connId, entry) {
  return {
    connId,
    service: entry.service,
    provider: entry.provider,
    status: entry.status,
    error: entry.error,
    verification: entry.verification,
    credentialDigest: entry.credentialDigest,
    epoch: entry.epoch,
    counter: entry.counter,
  };
}

test('trust records derive a separate HKDF key and MAC registry plus ledger state', () => {
  const connId = 'linear:mac-shape';
  store.saveApiKey(connId, { apiKey: 'MAC-SHAPE-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
  health.recordConnectionEvent(connId, 'connect', { ok: true });
  try {
    const masterKey = Buffer.from(
      fs.readFileSync(path.join(store.credentialsDir(), '.dex-cm.key'), 'utf8').trim(),
      'base64'
    );
    const expectedMacKey = Buffer.from(
      crypto.hkdfSync('sha256', masterKey, Buffer.alloc(0), 'dex-cm-trust-mac-v1', 32)
    );
    assert.deepEqual(store.trustMacKey(), expectedMacKey);

    const raw = readRawRegistry();
    const entry = raw[connId];
    assert.equal(entry.credentialDigest, crypto.createHash('sha256').update(fs.readFileSync(tokenFile(connId))).digest('hex'));
    assert.equal(entry.epoch, 1);
    assert.equal(Number.isInteger(entry.counter), true);
    assert.equal(typeof entry.mac, 'string');
    assert.equal(Number.isInteger(raw._meta.counter), true);
    assert.equal(typeof raw._meta.mac, 'string');

    const expectedEntryMac = crypto
      .createHmac('sha256', expectedMacKey)
      .update(store.canonicalJSON(registryMacPayload(connId, entry)))
      .digest('base64');
    assert.equal(entry.mac, expectedEntryMac);

    const ledgerRow = health.connectionLedger().tail(connId, 1)[0];
    assert.equal(ledgerRow.connId, connId);
    assert.equal(Number.isInteger(ledgerRow.counter), true);
    assert.equal(typeof ledgerRow.mac, 'string');
  } finally {
    store.deleteToken(connId);
  }
});

test('hand-edited registry trust is downgraded and blocked by get-token plus dex-call', () => {
  const connId = 'linear:forged-registry';
  store.saveApiKey(connId, { apiKey: 'FORGED-REGISTRY-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
  try {
    const raw = readRawRegistry();
    raw[connId].status = 'needs_reauth';
    fs.writeFileSync(registryFile(), JSON.stringify(raw, null, 2));
    raw[connId].status = 'connected';
    delete raw[connId].mac;
    fs.writeFileSync(registryFile(), JSON.stringify(raw, null, 2));

    const downgraded = store.getConnection(connId);
    assert.equal(downgraded.status, 'needs_reauth');
    assert.equal(downgraded.verification, 'unverified');
    assert.equal(downgraded.error, 'trust_unverified');

    const getToken = spawnSync(
      process.execPath,
      [path.join(DIR, 'get-token.cjs'), connId, '--access-token-only'],
      { env: childEnv, encoding: 'utf8' }
    );
    assert.equal(getToken.status, 3, getToken.stderr);
    assert.match(getToken.stderr, /needs re-authentication/i);

    const call = spawnSync(
      process.execPath,
      [path.join(DIR, 'dex-call.cjs'), connId, 'POST', '/graphql', '--body', '{"query":"{ viewer { id } }"}'],
      { env: childEnv, encoding: 'utf8' }
    );
    assert.equal(call.status, 3, call.stderr);
    assert.match(call.stderr, /needs re-authentication/i);
  } finally {
    store.deleteToken(connId);
  }
});

test('credential digest changes and legacy unsigned entries both become trust_unverified', () => {
  const digestConn = 'linear:digest-tamper';
  const legacyConn = 'linear:legacy-unsigned';
  store.saveApiKey(digestConn, { apiKey: 'DIGEST-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
  store.saveApiKey(legacyConn, { apiKey: 'LEGACY-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
  try {
    fs.appendFileSync(tokenFile(digestConn), '\n');
    assert.equal(store.getConnection(digestConn).error, 'trust_unverified');

    const raw = readRawRegistry();
    delete raw[legacyConn].mac;
    delete raw[legacyConn].credentialDigest;
    delete raw[legacyConn].epoch;
    delete raw[legacyConn].counter;
    fs.writeFileSync(registryFile(), JSON.stringify(raw, null, 2));
    const legacy = store.getConnection(legacyConn);
    assert.equal(legacy.status, 'needs_reauth');
    assert.equal(legacy.verification, 'unverified');
    assert.equal(legacy.error, 'trust_unverified');
  } finally {
    store.deleteToken(digestConn);
    store.deleteToken(legacyConn);
  }
});

test('only authenticated probes from the current connect counter can verify a credential', () => {
  const connId = 'linear:ledger-replay';
  store.saveApiKey(connId, { apiKey: 'FIRST-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
  health.recordConnectionEvent(connId, 'connect', { ok: true });
  health.recordConnectionEvent(connId, 'probe', { ok: true });
  assert.equal(health.connectionHealth(connId).verified, true);
  const oldProbe = health.connectionLedger().tail(connId, 1)[0];
  const ledgerPath = health.connectionLedger().filePathFor(connId);
  try {
    const rows = fs.readFileSync(ledgerPath, 'utf8').trim().split('\n').map(JSON.parse);
    rows[rows.length - 1].ok = false;
    fs.writeFileSync(ledgerPath, `${rows.map(JSON.stringify).join('\n')}\n`);
    assert.equal(health.connectionHealth(connId).verified, false, 'wrong-MAC probe is not evidence');

    store.saveApiKey(connId, { apiKey: 'SECOND-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
    health.recordConnectionEvent(connId, 'connect', { ok: true });
    fs.appendFileSync(ledgerPath, `${JSON.stringify(oldProbe)}\n`);
    assert.equal(health.connectionHealth(connId).verified, false, 'old valid probe cannot cross reconnect');
  } finally {
    store.deleteToken(connId);
  }
});

test('registry rebuild from encrypted tokens creates authenticated entries', () => {
  const connId = 'linear:rebuilt-trust';
  store.saveApiKey(connId, { apiKey: 'REBUILD-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
  try {
    fs.unlinkSync(registryFile());
    const rebuilt = store.getConnection(connId);
    assert.equal(rebuilt.status, 'connected');
    assert.equal(rebuilt.error, null);
    assert.equal(typeof readRawRegistry()[connId].mac, 'string');
  } finally {
    store.deleteToken(connId);
  }
});
