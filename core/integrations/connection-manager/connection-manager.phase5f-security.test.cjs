'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const TMP_VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-phase5f-'));
process.env.DEX_VAULT = TMP_VAULT;
process.env.DEX_CM_NO_KEYCHAIN = '1';
process.env.DEX_OAUTH_ABSORB_LMS_CLIENT_ID = 'ATTACKER-CONTROLLED-PUBLIC-CLIENT';

const store = require('./token-store.cjs');
const health = require('./health.cjs');

function registryFile() {
  return path.join(store.credentialsDir(), 'connections.json');
}

function readRawRegistry() {
  return JSON.parse(fs.readFileSync(registryFile(), 'utf8'));
}

function writeRawRegistry(registry) {
  fs.writeFileSync(registryFile(), JSON.stringify(registry, null, 2));
}

function response(body) {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  };
}

function forgeRefreshRouting(connId) {
  store.saveToken(
    connId,
    {
      access_token: 'REAL-ACCESS-TOKEN',
      refresh_token: 'REAL-REFRESH-TOKEN',
      expires_at: Date.now() - 1,
    },
    {
      provider: 'google',
      extra: { connectionConfig: { hostname: 'trusted.example' } },
    }
  );
  const raw = readRawRegistry();
  raw[connId].provider = 'absorb-lms';
  raw[connId].connectionConfig = { portalRoute: 'attacker.example' };
  writeRawRegistry(raw); // Deliberately leave the original entry MAC stale.
}

async function assertRefreshRefusedWithoutFetch(operation) {
  const requestedUrls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    requestedUrls.push(String(url));
    return response({ access_token: 'ATTACKER-SAW-THE-REFRESH', expires_in: 3600 });
  };
  let caught;
  try {
    await operation();
  } catch (error) {
    caught = error;
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(requestedUrls, []);
  assert.equal(caught && caught.needsReauth, true);
}

test('refreshToken refuses stale-MAC provider/config steering before any fetch', async () => {
  const connId = 'google:phase5f-refresh';
  forgeRefreshRouting(connId);
  try {
    await assertRefreshRefusedWithoutFetch(() => health.refreshToken(connId, { force: true }));
  } finally {
    store.deleteToken(connId);
  }
});

test('ensureFreshToken refuses stale-MAC provider/config steering before any fetch', async () => {
  const connId = 'google:phase5f-ensure';
  forgeRefreshRouting(connId);
  try {
    await assertRefreshRefusedWithoutFetch(() => health.ensureFreshToken(connId));
  } finally {
    store.deleteToken(connId);
  }
});

test('ensureFreshToken refuses a fresh OAuth credential with no authenticated registry entry', async () => {
  const connId = 'google:phase5f-missing-entry';
  const keeperConnId = 'linear:phase5f-keeper';
  store.saveToken(
    keeperConnId,
    { access_token: 'KEEPER-AT', refresh_token: 'KEEPER-RT', expires_at: Date.now() + 3600_000 },
    { provider: 'linear' }
  );
  store.saveToken(
    connId,
    { access_token: 'UNBOUND-AT', refresh_token: 'UNBOUND-RT', expires_at: Date.now() + 3600_000 },
    { provider: 'google' }
  );
  const raw = readRawRegistry();
  delete raw[connId];
  writeRawRegistry(raw);
  try {
    await assertRefreshRefusedWithoutFetch(() => health.ensureFreshToken(connId));
  } finally {
    store.deleteToken(connId);
    store.deleteToken(keeperConnId);
  }
});

test('refresh lock rechecks trust before reusing a concurrently updated token', async () => {
  const connId = 'google:phase5f-lock-recheck';
  store.saveToken(
    connId,
    { access_token: 'OLD-AT', refresh_token: 'OLD-RT', expires_at: Date.now() - 1 },
    { provider: 'google' }
  );
  const originalWithRefreshLock = store.withRefreshLock;
  store.withRefreshLock = async (_lockedConnId, operation) => {
    store.saveToken(
      connId,
      { access_token: 'CONCURRENT-AT', refresh_token: 'CONCURRENT-RT', expires_at: Date.now() + 3600_000 },
      { provider: 'google' }
    );
    const raw = readRawRegistry();
    raw[connId].provider = 'absorb-lms';
    raw[connId].connectionConfig = { portalRoute: 'attacker.example' };
    writeRawRegistry(raw);
    return operation();
  };
  try {
    await assertRefreshRefusedWithoutFetch(() => health.refreshToken(connId, { force: true }));
  } finally {
    store.withRefreshLock = originalWithRefreshLock;
    store.deleteToken(connId);
  }
});

test('connectionConfig is covered by the authenticated registry entry', () => {
  const connId = 'google:phase5f-config-mac';
  store.saveToken(
    connId,
    { access_token: 'AT', refresh_token: 'RT', expires_at: Date.now() + 3600_000 },
    {
      provider: 'google',
      extra: { connectionConfig: { hostname: 'trusted.example' } },
    }
  );
  try {
    const raw = readRawRegistry();
    raw[connId].connectionConfig.hostname = 'attacker.example';
    writeRawRegistry(raw);

    const connection = store.getConnection(connId);
    assert.equal(connection.status, 'needs_reauth');
    assert.equal(connection.error, 'trust_unverified');
  } finally {
    store.deleteToken(connId);
  }
});

test('reconnect never authenticates routing config inherited from a distrusted entry', () => {
  const connId = 'absorb-lms:phase5f-reconnect';
  store.saveToken(
    connId,
    { access_token: 'OLD-AT', refresh_token: 'OLD-RT', expires_at: Date.now() - 1 },
    {
      provider: 'absorb-lms',
      extra: { connectionConfig: { portalRoute: 'trusted.example' } },
    }
  );
  try {
    const raw = readRawRegistry();
    raw[connId].connectionConfig.portalRoute = 'attacker.example';
    writeRawRegistry(raw);
    assert.equal(store.getConnection(connId).error, 'trust_unverified');

    store.saveToken(
      connId,
      { access_token: 'NEW-AT', refresh_token: 'NEW-RT', expires_at: Date.now() + 3600_000 },
      { provider: 'absorb-lms' }
    );

    const reconnected = store.getConnection(connId);
    assert.equal(reconnected.status, 'connected');
    assert.equal(reconnected.error, null);
    assert.equal(reconnected.connectionConfig, undefined);
  } finally {
    store.deleteToken(connId);
  }
});

test('a stale-MAC forged default never returns another provider credential', () => {
  const linearConnId = 'linear:phase5f-x';
  store.saveToken(
    linearConnId,
    { access_token: 'LINEAR-CREDENTIAL', refresh_token: 'LINEAR-REFRESH', expires_at: Date.now() + 3600_000 },
    { provider: 'linear' }
  );
  try {
    const raw = readRawRegistry();
    raw._defaults = { ...(raw._defaults || {}), google: linearConnId };
    writeRawRegistry(raw); // Deliberately leave the registry meta MAC stale.

    let token;
    let caught;
    try {
      token = store.loadToken('google');
    } catch (error) {
      caught = error;
    }
    assert.notEqual(token && token.access_token, 'LINEAR-CREDENTIAL');
    assert.equal(caught && caught.needsReauth, true);
  } finally {
    store.deleteToken(linearConnId);
  }
});

test('a MAC-valid default still cannot cross provider boundaries', () => {
  const linearConnId = 'linear:phase5f-signed-x';
  store.saveToken(
    linearConnId,
    { access_token: 'LINEAR-SIGNED-CREDENTIAL', refresh_token: 'LINEAR-REFRESH', expires_at: Date.now() + 3600_000 },
    { provider: 'linear' }
  );
  try {
    const raw = readRawRegistry();
    raw._defaults = { ...(raw._defaults || {}), google: linearConnId };
    raw._meta.mac = crypto
      .createHmac('sha256', store.trustMacKey())
      .update(store.canonicalJSON({ counter: raw._meta.counter, defaults: raw._defaults }))
      .digest('base64');
    writeRawRegistry(raw);

    assert.throws(
      () => store.resolveConnId('google'),
      (error) => error && error.needsReauth === true
    );
  } finally {
    store.deleteToken(linearConnId);
  }
});
