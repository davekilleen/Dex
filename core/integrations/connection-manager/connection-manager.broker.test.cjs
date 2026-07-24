'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');

const TMP_ROOT = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-broker-test-'));
const TMP_VAULT = path.join(TMP_ROOT, 'vault');
const TMP_RUNTIME = path.join(os.tmpdir(), `dex-cm-broker-runtime-${process.pid}`);
fs.mkdirSync(TMP_VAULT, { recursive: true });
process.env.DEX_VAULT = TMP_VAULT;
process.env.DEX_CM_RUNTIME_DIR = TMP_RUNTIME;
process.env.DEX_CM_NO_KEYCHAIN = '1';
process.env.DEX_CM_BROKER_IDLE_MS = '150';

const store = require('./token-store.cjs');
const authContext = require('./auth-context.cjs');
const broker = require('./broker.cjs');
const client = require('./broker-client.cjs');

function mode(file) {
  return fs.statSync(file).mode & 0o777;
}

function rawRequest(request) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(broker.socketPath());
    let data = '';
    socket.setEncoding('utf8');
    socket.on('connect', () => socket.end(`${JSON.stringify(request)}\n`));
    socket.on('data', (chunk) => {
      data += chunk;
    });
    socket.on('error', reject);
    socket.on('end', () => {
      try {
        resolve(JSON.parse(data.trim()));
      } catch (error) {
        reject(error);
      }
    });
  });
}

function runClientChild(connId) {
  const script = [
    `const client = require(${JSON.stringify(path.join(__dirname, 'broker-client.cjs'))});`,
    `client.brokerRequest({op:'rendered',connId:${JSON.stringify(connId)}})`,
    ".then((result)=>process.stdout.write(JSON.stringify(result)))",
    '.catch((error)=>{console.error(error);process.exit(1);});',
  ].join('');
  const child = spawn(process.execPath, ['-e', script], {
    env: { ...process.env },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  return new Promise((resolve, reject) => {
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8').on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr.setEncoding('utf8').on('data', (chunk) => {
      stderr += chunk;
    });
    child.on('error', reject);
    child.on('exit', (code) => {
      if (code !== 0) {
        reject(new Error(`broker client child exited ${code}: ${stderr}`));
        return;
      }
      resolve(JSON.parse(stdout));
    });
  });
}

async function waitForGone(file, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs;
  while (fs.existsSync(file) && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

test.after(async () => {
  await waitForGone(broker.socketPath());
  fs.rmSync(TMP_ROOT, { recursive: true, force: true });
  fs.rmSync(TMP_RUNTIME, { recursive: true, force: true });
});

test('runtime paths are machine-local and permissions are private', async () => {
  assert.equal(path.resolve(broker.runtimeDir()).startsWith(`${path.resolve(TMP_VAULT)}${path.sep}`), false);
  const running = await broker.startBroker({ idleMs: 60_000 });
  try {
    assert.equal(mode(broker.runtimeDir()), 0o700);
    assert.equal(mode(broker.socketPath()), 0o600);
    assert.equal(mode(broker.capabilityPath()), 0o600);
    assert.equal(Buffer.from(fs.readFileSync(broker.capabilityPath(), 'utf8').trim(), 'base64').length, 32);
  } finally {
    await running.close();
  }
});

test('broker gates every operation, renders least privilege, pins origins, and verifies trust', async (t) => {
  const linear = 'linear:broker';
  const google = 'google:broker';
  const unvetted = 'airtable-pat:broker';
  const forged = 'linear:broker-forged';
  store.saveApiKey(linear, { apiKey: 'LINEAR-BROKER-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
  store.saveToken(
    google,
    {
      access_token: 'GOOGLE-BROKER-ACCESS',
      refresh_token: 'GOOGLE-BROKER-REFRESH',
      expires_at: Date.now() + 3_600_000,
    },
    { provider: 'google' }
  );
  store.saveApiKey(
    unvetted,
    { apiKey: 'UNVETTED-BROKER-SECRET' },
    { provider: 'airtable-pat', authMode: 'API_KEY' }
  );
  store.saveApiKey(
    forged,
    { apiKey: 'FORGED-BROKER-SECRET' },
    { provider: 'linear', authMode: 'API_KEY' }
  );

  const running = await broker.startBroker({ idleMs: 60_000 });
  const capability = fs.readFileSync(broker.capabilityPath(), 'utf8').trim();
  const presenceCalls = [];
  const originalPresence = broker.assertPresence;
  broker.assertPresence = async (connId, op) => {
    presenceCalls.push([connId, op]);
  };
  try {
    await t.test('missing or wrong capability returns forbidden with no credential data', async () => {
      for (const badCapability of [undefined, Buffer.alloc(32, 7).toString('base64')]) {
        const response = await rawRequest({
          ...(badCapability ? { capability: badCapability } : {}),
          op: 'rendered',
          connId: linear,
        });
        assert.deepEqual(response, { ok: false, error: { category: 'forbidden' } });
        assert.equal(JSON.stringify(response).includes('LINEAR-BROKER-SECRET'), false);
      }
    });

    await t.test('rendered matches resolveAuthContext without returning raw apiKey', async () => {
      const expected = await authContext.resolveAuthContext(linear);
      const response = await rawRequest({ capability, op: 'rendered', connId: linear });
      assert.deepEqual(response, {
        ok: true,
        kind: expected.kind,
        baseUrl: expected.baseUrl,
        headers: expected.headers,
        query: expected.query,
      });
      assert.equal(Object.hasOwn(response, 'apiKey'), false);
      assert.deepEqual(presenceCalls, []);
    });

    await t.test('privileged access-token and full exports invoke presence', async () => {
      const access = await rawRequest({ capability, op: 'access-token', connId: linear });
      assert.deepEqual(access, { ok: true, value: 'LINEAR-BROKER-SECRET' });
      const full = await rawRequest({ capability, op: 'full', connId: google });
      assert.equal(full.ok, true);
      assert.equal(full.token.access_token, 'GOOGLE-BROKER-ACCESS');
      assert.equal(full.token.refresh_token, 'GOOGLE-BROKER-REFRESH');
      assert.deepEqual(presenceCalls, [
        [linear, 'access-token'],
        [google, 'full'],
      ]);
    });

    await t.test('vetted targets must stay pinned and unvetted providers need consent', async () => {
      assert.equal(
        (await rawRequest({
          capability,
          op: 'rendered',
          connId: linear,
          targetOrigin: 'https://api.linear.app/graphql',
        })).ok,
        true
      );
      assert.deepEqual(
        await rawRequest({
          capability,
          op: 'rendered',
          connId: linear,
          targetOrigin: 'https://evil.example/graphql',
        }),
        { ok: false, error: { category: 'forbidden' } }
      );
      assert.deepEqual(
        await rawRequest({ capability, op: 'rendered', connId: unvetted }),
        { ok: false, error: { category: 'unvetted' } }
      );
      assert.equal(
        (await rawRequest({
          capability,
          op: 'rendered',
          connId: unvetted,
          allowUnvetted: true,
        })).ok,
        true
      );
    });

    await t.test('forged registry trust is rejected through the broker', async () => {
      const registryPath = path.join(store.credentialsDir(), 'connections.json');
      const registry = JSON.parse(fs.readFileSync(registryPath, 'utf8'));
      registry[forged].status = 'connected';
      delete registry[forged].mac;
      fs.writeFileSync(registryPath, JSON.stringify(registry, null, 2));
      assert.deepEqual(
        await rawRequest({ capability, op: 'access-token', connId: forged }),
        { ok: false, error: { category: 'needs_reauth' } }
      );
    });

    await t.test('status returns the same MAC-verified monitoring data', async () => {
      const response = await rawRequest({ capability, op: 'status' });
      assert.equal(response.ok, true);
      assert.deepEqual(response.connections, require('./health.cjs').allConnectionsHealth());
      assert.deepEqual(response.registryNotice, store.readRegistry()._meta || null);
    });
  } finally {
    broker.assertPresence = originalPresence;
    await running.close();
    for (const connId of [linear, google, unvetted, forged]) {
      if (store.getConnection(connId)) store.deleteToken(connId);
    }
  }
});

test('client maps legacy CLI exit codes', () => {
  assert.equal(client.exitCodeForError('forbidden'), 1);
  assert.equal(client.exitCodeForError('unvetted'), 1);
  assert.equal(client.exitCodeForError('needs_reauth'), 3);
  assert.equal(client.exitCodeForError('not_connected'), 2);
  assert.equal(client.exitCodeForError('http'), 4);
  assert.equal(client.exitCodeForError('anything_else'), 1);
});

test('concurrent clients auto-spawn exactly one usable broker', async () => {
  const connId = 'linear:auto-spawn';
  fs.rmSync(broker.socketPath(), { force: true });
  store.saveApiKey(connId, { apiKey: 'AUTO-SPAWN-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
  try {
    const [first, second] = await Promise.all([runClientChild(connId), runClientChild(connId)]);
    assert.equal(first.ok, true);
    assert.equal(second.ok, true);
    assert.equal(fs.existsSync(broker.socketPath()), true);
    assert.equal(mode(broker.socketPath()), 0o600);
  } finally {
    if (store.getConnection(connId)) store.deleteToken(connId);
    await waitForGone(broker.socketPath());
  }
});
