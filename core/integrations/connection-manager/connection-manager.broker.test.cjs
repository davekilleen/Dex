'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');

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
const presence = require('./presence.cjs');
const broker = require('./broker.cjs');
const client = require('./broker-client.cjs');
const connect = require('./connect.cjs');

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
        const response = JSON.parse(data.trim());
        const serverAuth = fs.readFileSync(broker.serverIdentityPath(), 'utf8').trim();
        assert.equal(response.serverAuth, serverAuth, 'every wire response must authenticate the broker');
        delete response.serverAuth;
        resolve(response);
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

function runCli(file, args, extraEnv = {}) {
  const child = spawn(process.execPath, [file, ...args], {
    env: { ...process.env, ...extraEnv },
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
    child.on('exit', (status) => resolve({ status, stdout, stderr }));
  });
}

function prepareClientAuthFiles() {
  const capability = Buffer.alloc(32, 7).toString('base64');
  const serverIdentity = Buffer.alloc(32, 9).toString('base64');
  fs.mkdirSync(broker.runtimeDir(), { recursive: true, mode: 0o700 });
  fs.writeFileSync(broker.capabilityPath(), capability, { mode: 0o600 });
  fs.writeFileSync(path.join(broker.runtimeDir(), 'cm.srv'), serverIdentity, { mode: 0o600 });
  return { capability, serverIdentity };
}

function fakeClientSocket(t, onRequest) {
  const socket = new EventEmitter();
  socket.destroyed = false;
  socket.setEncoding = () => socket;
  socket.end = (input) => onRequest(socket, input);
  socket.destroy = () => {
    socket.destroyed = true;
  };
  t.mock.method(net, 'createConnection', () => {
    queueMicrotask(() => socket.emit('connect'));
    return socket;
  });
  return socket;
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

test('broker presence seam delegates to the provider-based presence layer', async (t) => {
  const calls = [];
  t.mock.method(presence, 'assertPresence', async (connId, op) => calls.push([connId, op]));

  await broker.assertPresence('linear:delegated', 'access-token');

  assert.deepEqual(calls, [['linear:delegated', 'access-token']]);
});

test('broker request processing preserves accessor shapes without a live socket', async () => {
  const capability = 'test-capability';
  const oauth = 'google:broker-unit';
  const classB = 'linear:broker-unit';
  store.saveToken(
    oauth,
    {
      access_token: 'UNIT-OAUTH-ACCESS',
      refresh_token: 'UNIT-OAUTH-REFRESH',
      expires_at: Date.now() + 3_600_000,
    },
    { provider: 'google' }
  );
  store.saveApiKey(classB, { apiKey: 'UNIT-CLASS-B-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
  const originalPresence = broker.assertPresence;
  const presenceCalls = [];
  broker.assertPresence = async (connId, op) => presenceCalls.push([connId, op]);
  try {
    assert.deepEqual(
      await broker.processRequest({ capability, op: 'get-token-default', connId: oauth }, capability),
      {
        ok: true,
        value: {
          access_token: 'UNIT-OAUTH-ACCESS',
          expires_at: store.loadToken(oauth).expires_at,
        },
      }
    );
    const rendered = await authContext.resolveAuthContext(classB);
    assert.deepEqual(
      await broker.processRequest({ capability, op: 'get-token-default', connId: classB }, capability),
      {
        ok: true,
        value: {
          kind: rendered.kind,
          baseUrl: rendered.baseUrl,
          headers: rendered.headers,
          query: rendered.query,
        },
      }
    );
    assert.deepEqual(presenceCalls, []);

    await broker.processRequest({ capability, op: 'full', connId: oauth }, capability);
    await broker.processRequest({ capability, op: 'access-token', connId: classB }, capability);
    assert.deepEqual(presenceCalls, [
      [oauth, 'full'],
      [classB, 'access-token'],
    ]);
  } finally {
    broker.assertPresence = originalPresence;
    store.deleteToken(oauth);
    store.deleteToken(classB);
  }
});

test('privileged broker denial returns presence_required without releasing a secret', async () => {
  const capability = 'presence-denial-capability';
  const connId = 'linear:presence-denial';
  const secret = 'MUST-NOT-BE-RELEASED';
  store.saveApiKey(connId, { apiKey: secret }, { provider: 'linear', authMode: 'API_KEY' });
  const originalPresence = broker.assertPresence;
  broker.assertPresence = async () => {
    const error = new Error('User presence is required for this credential operation.');
    error.code = 'DEX_CM_PRESENCE_REQUIRED';
    error.category = 'presence_required';
    throw error;
  };
  try {
    const response = await broker.processRequest(
      { capability, op: 'access-token', connId },
      capability
    );
    assert.equal(response.ok, false);
    assert.equal(response.error.category, 'presence_required');
    assert.match(response.error.message, /presence/i);
    assert.equal(JSON.stringify(response).includes(secret), false);
  } finally {
    broker.assertPresence = originalPresence;
    store.deleteToken(connId);
  }
});

test('set-key requires mocked presence before the first credential save', async () => {
  const connId = 'linear:first-connect-approved';
  const prompts = [];
  const provider = {
    available: true,
    async verify(request) {
      prompts.push(request);
      return true;
    },
  };
  try {
    await connect.cmdSetKey(connId, { 'no-probe': 'true' }, {
      presenceProvider: provider,
      readSecret: async () => 'FIRST-CONNECT-SECRET',
    });

    assert.equal(store.loadToken(connId).apiKey, 'FIRST-CONNECT-SECRET');
    assert.deepEqual(prompts, [{ connId, op: 'connect' }]);
  } finally {
    if (store.getConnection(connId)) store.deleteToken(connId);
  }
});

test('set-key denial stores nothing and cannot overwrite an existing credential', async () => {
  const deniedId = 'linear:first-connect-denied';
  const deniedProvider = { available: true, verify: async () => false };
  await assert.rejects(
    connect.cmdSetKey(deniedId, { 'no-probe': 'true' }, {
      presenceProvider: deniedProvider,
      readSecret: async () => 'DENIED-FIRST-CONNECT-SECRET',
    }),
    { code: 'DEX_CM_PRESENCE_REQUIRED', category: 'presence_required' }
  );
  assert.equal(store.getConnection(deniedId), null);

  const reconnectId = 'linear:reconnect-denied';
  store.saveApiKey(reconnectId, { apiKey: 'OLD-SECRET' }, { provider: 'linear', authMode: 'API_KEY' });
  let reconnectPrompts = 0;
  try {
    await assert.rejects(
      connect.cmdSetKey(reconnectId, { 'no-probe': 'true' }, {
        presenceProvider: {
          available: true,
          async verify() {
            reconnectPrompts += 1;
            return false;
          },
        },
        readSecret: async () => 'NEW-SECRET',
      }),
      { code: 'DEX_CM_PRESENCE_REQUIRED', category: 'presence_required' }
    );
    assert.equal(store.loadToken(reconnectId).apiKey, 'OLD-SECRET');
    assert.equal(reconnectPrompts, 1);
  } finally {
    if (store.getConnection(reconnectId)) store.deleteToken(reconnectId);
  }
});

test('OAuth connect requires mocked presence before the first token save', async () => {
  const connId = 'google:presence-oauth';
  store.setOAuthApp('google', { clientId: 'TEST-CLIENT', clientSecret: 'TEST-SECRET' });
  const prompts = [];
  const oauthProvider = {
    async startCallbackServer() {
      return {
        redirectUri: 'http://127.0.0.1:3847/callback',
        waitForCode: async () => ({ code: 'TEST-CODE' }),
      };
    },
    buildAuthorizationUrl() {
      return { url: 'https://accounts.google.com/test', codeVerifier: 'VERIFIER', state: 'STATE' };
    },
    async exchangeCodeForToken() {
      return { access_token: 'OAUTH-FIRST-CONNECT', refresh_token: 'OAUTH-REFRESH' };
    },
  };
  try {
    await connect.cmdConnect('google', { as: 'presence-oauth' }, {
      oauthProvider,
      openBrowser: () => {},
      presenceProvider: {
        available: true,
        async verify(request) {
          prompts.push(request);
          return true;
        },
      },
    });

    assert.equal(store.loadToken(connId).access_token, 'OAUTH-FIRST-CONNECT');
    assert.deepEqual(prompts, [{ connId, op: 'connect' }]);
  } finally {
    if (store.getConnection(connId)) store.deleteToken(connId);
  }
});

test('accessor CLIs clearly surface presence_required with exit code 1', async () => {
  const preload = path.join(TMP_ROOT, 'presence-required-preload.cjs');
  const clientPath = path.join(__dirname, 'broker-client.cjs');
  fs.writeFileSync(
    preload,
    [
      "'use strict';",
      `const clientPath = ${JSON.stringify(clientPath)};`,
      'require.cache[clientPath] = {',
      '  id: clientPath, filename: clientPath, loaded: true,',
      '  exports: {',
      "    exitCodeForError(category) { return category === 'presence_required' ? 1 : 99; },",
      "    async brokerRequest() { return {ok:false,error:{category:'presence_required'}}; },",
      '  },',
      '};',
    ].join('\n')
  );
  const env = { NODE_OPTIONS: `--require=${preload}` };

  const getToken = await runCli(
    path.join(__dirname, 'get-token.cjs'),
    ['linear:presence-cli', '--access-token-only'],
    env
  );
  assert.equal(getToken.status, 1);
  assert.match(getToken.stderr, /user presence/i);

  const dexCall = await runCli(
    path.join(__dirname, 'dex-call.cjs'),
    ['linear:presence-cli', 'GET', 'https://api.linear.app/graphql'],
    env
  );
  assert.equal(dexCall.status, 1);
  assert.match(dexCall.stderr, /user presence/i);
});

test('rendered broker auth retains key-in-URL redaction without exposing an apiKey field', async () => {
  const capability = 'redaction-capability';
  const connId = 'telegram:broker-redaction';
  const secret = '123456:UNIT-BROKER-URL-SECRET';
  store.saveApiKey(connId, { apiKey: secret }, { provider: 'telegram', authMode: 'API_KEY' });
  try {
    const response = await broker.processRequest(
      { capability, op: 'rendered', connId, allowUnvetted: true },
      capability
    );
    assert.equal(response.ok, true);
    assert.equal(response.baseUrl.includes(secret), true);
    assert.equal(Object.hasOwn(response, 'apiKey'), false);
    assert.equal(authContext.secretsOf(response).includes(secret), true);
  } finally {
    store.deleteToken(connId);
  }
});

test('accessor CLIs preserve their contracts while calling the broker client', async () => {
  const recordFile = path.join(TMP_ROOT, 'broker-client-records.jsonl');
  const preload = path.join(TMP_ROOT, 'broker-client-preload.cjs');
  const clientPath = path.join(__dirname, 'broker-client.cjs');
  fs.writeFileSync(
    preload,
    [
      "'use strict';",
      "const fs = require('node:fs');",
      `const clientPath = ${JSON.stringify(clientPath)};`,
      'require.cache[clientPath] = {',
      '  id: clientPath, filename: clientPath, loaded: true,',
      '  exports: {',
      '    exitCodeForError(category) { return ({needs_reauth:3,not_connected:2,http:4})[category] || 1; },',
      '    async brokerRequest(request) {',
      '      fs.appendFileSync(process.env.BROKER_RECORD_FILE, JSON.stringify(request) + "\\n");',
      "      if (request.op === 'get-token-default' && request.connId === 'oauth-cli')",
      "        return {ok:true,value:{access_token:'CLI-ACCESS',expires_at:1893456000000}};",
      "      if (request.op === 'get-token-default')",
      "        return {ok:true,value:{kind:'api_key',baseUrl:'https://api.linear.app',headers:{Authorization:'CLI-KEY'},query:{}}};",
      "      if (request.op === 'full')",
      "        return {ok:true,token:{access_token:'CLI-ACCESS',refresh_token:'CLI-REFRESH',expires_at:1893456000000}};",
      "      if (request.op === 'access-token') return {ok:true,value:'CLI-KEY'};",
      "      if (request.op === 'rendered')",
      "        return {ok:true,kind:'api_key',baseUrl:'https://api.linear.app',headers:{Authorization:'CLI-KEY'},query:{},provider:'linear'};",
      "      return {ok:false,error:{category:'error',message:'unexpected broker request'}};",
      '    },',
      '  },',
      '};',
      'globalThis.fetch = async (url, options) => ({',
      '  ok: true, status: 200, statusText: "OK",',
      '  text: async () => JSON.stringify({url, method: options.method, authorization: options.headers.Authorization}),',
      '});',
    ].join('\n')
  );
  const env = {
    NODE_OPTIONS: `--require=${preload}`,
    BROKER_RECORD_FILE: recordFile,
  };

  const oauthDefault = await runCli(path.join(__dirname, 'get-token.cjs'), ['oauth-cli'], env);
  assert.equal(oauthDefault.status, 0, oauthDefault.stderr);
  assert.deepEqual(JSON.parse(oauthDefault.stdout), {
    access_token: 'CLI-ACCESS',
    expires_at: 1893456000000,
  });

  const classBDefault = await runCli(path.join(__dirname, 'get-token.cjs'), ['linear:cli'], env);
  assert.equal(classBDefault.status, 0, classBDefault.stderr);
  assert.deepEqual(JSON.parse(classBDefault.stdout), {
    kind: 'api_key',
    baseUrl: 'https://api.linear.app',
    headers: { Authorization: 'CLI-KEY' },
    query: {},
  });

  const full = await runCli(path.join(__dirname, 'get-token.cjs'), ['oauth-cli', '--full'], env);
  assert.equal(full.status, 0, full.stderr);
  assert.equal(JSON.parse(full.stdout).refresh_token, 'CLI-REFRESH');

  const raw = await runCli(path.join(__dirname, 'get-token.cjs'), ['linear:cli', '--access-token-only'], env);
  assert.equal(raw.status, 0, raw.stderr);
  assert.equal(raw.stdout, 'CLI-KEY');

  const call = await runCli(
    path.join(__dirname, 'dex-call.cjs'),
    ['linear:cli', 'POST', 'https://api.linear.app/graphql', '--body', '{"query":"{ viewer { id } }"}'],
    env
  );
  assert.equal(call.status, 0, call.stderr);
  assert.deepEqual(JSON.parse(call.stdout), {
    url: 'https://api.linear.app/graphql',
    method: 'POST',
    authorization: 'CLI-KEY',
  });

  const requests = fs
    .readFileSync(recordFile, 'utf8')
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line));
  assert.deepEqual(requests, [
    { op: 'get-token-default', connId: 'oauth-cli' },
    { op: 'get-token-default', connId: 'linear:cli' },
    { op: 'full', connId: 'oauth-cli', privileged: true },
    { op: 'access-token', connId: 'linear:cli', privileged: true },
    {
      op: 'rendered',
      connId: 'linear:cli',
      targetOrigin: 'https://api.linear.app/graphql',
      allowUnvetted: false,
    },
  ]);
});

test('broker client rejects a forged response whose server identity does not match', async (t) => {
  prepareClientAuthFiles();
  fakeClientSocket(t, (socket) => {
    queueMicrotask(() => {
      socket.emit(
        'data',
        `${JSON.stringify({
          ok: true,
          connections: [{ connId: 'forged:status', status: 'connected' }],
          serverAuth: Buffer.alloc(32, 3).toString('base64'),
        })}\n`
      );
      socket.emit('end');
    });
  });

  await assert.rejects(
    client.brokerRequest({ op: 'status' }),
    (error) => error && error.code === 'DEX_CM_SERVER_AUTH_INVALID' && /authentication/i.test(error.message)
  );
});

test('broker client authenticates and removes serverAuth before returning a response', async (t) => {
  const { serverIdentity } = prepareClientAuthFiles();
  fakeClientSocket(t, (socket) => {
    queueMicrotask(() => {
      socket.emit('data', `${JSON.stringify({ ok: true, connections: [], serverAuth: serverIdentity })}\n`);
      socket.emit('end');
    });
  });

  assert.deepEqual(await client.brokerRequest({ op: 'status' }), { ok: true, connections: [] });
});

test('broker client enforces an absolute response deadline and destroys the listener', async (t) => {
  prepareClientAuthFiles();
  const originalTimeout = process.env.DEX_CM_CLIENT_TIMEOUT_MS;
  process.env.DEX_CM_CLIENT_TIMEOUT_MS = '10';
  const socket = fakeClientSocket(t, () => {});
  const guard = setTimeout(() => socket.emit('error', new Error('test guard: client timeout was not enforced')), 100);
  try {
    await assert.rejects(
      client.brokerRequest({ op: 'status' }),
      (error) => error && error.code === 'DEX_CM_CLIENT_TIMEOUT' && /within 10 ms/i.test(error.message)
    );
    assert.equal(socket.destroyed, true);
  } finally {
    clearTimeout(guard);
    if (originalTimeout === undefined) delete process.env.DEX_CM_CLIENT_TIMEOUT_MS;
    else process.env.DEX_CM_CLIENT_TIMEOUT_MS = originalTimeout;
  }
});

test('broker client rejects a symlinked runtime directory before connecting', () => {
  const originalRuntime = process.env.DEX_CM_RUNTIME_DIR;
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-client-symlink-'));
  const real = path.join(root, 'real');
  const link = path.join(root, 'link');
  fs.mkdirSync(real, { mode: 0o700 });
  fs.symlinkSync(real, link, 'dir');
  process.env.DEX_CM_RUNTIME_DIR = link;
  try {
    assert.throws(
      () => client.ensurePrivateRuntime(),
      /credential broker runtime path is not a real directory/i
    );
  } finally {
    if (originalRuntime === undefined) delete process.env.DEX_CM_RUNTIME_DIR;
    else process.env.DEX_CM_RUNTIME_DIR = originalRuntime;
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('socket (verify outside sandbox): runtime paths are machine-local and permissions are private', async () => {
  assert.equal(path.resolve(broker.runtimeDir()).startsWith(`${path.resolve(TMP_VAULT)}${path.sep}`), false);
  const running = await broker.startBroker({ idleMs: 60_000 });
  let firstServerIdentity;
  try {
    assert.equal(mode(broker.runtimeDir()), 0o700);
    assert.equal(mode(broker.socketPath()), 0o600);
    assert.equal(mode(broker.capabilityPath()), 0o600);
    assert.equal(mode(broker.serverIdentityPath()), 0o600);
    assert.equal(Buffer.from(fs.readFileSync(broker.capabilityPath(), 'utf8').trim(), 'base64').length, 32);
    firstServerIdentity = fs.readFileSync(broker.serverIdentityPath(), 'utf8').trim();
    assert.equal(Buffer.from(firstServerIdentity, 'base64').length, 32);
  } finally {
    await running.close();
  }
  const restarted = await broker.startBroker({ idleMs: 60_000 });
  try {
    const secondServerIdentity = fs.readFileSync(broker.serverIdentityPath(), 'utf8').trim();
    assert.notEqual(secondServerIdentity, firstServerIdentity, 'every broker startup must mint a fresh identity');
  } finally {
    await restarted.close();
  }
});

test('socket (verify outside sandbox): a pre-bound listener cannot forge an authenticated broker response', async () => {
  fs.mkdirSync(broker.runtimeDir(), { recursive: true, mode: 0o700 });
  fs.rmSync(broker.socketPath(), { force: true });
  const capability = Buffer.alloc(32, 11).toString('base64');
  const serverIdentity = Buffer.alloc(32, 12).toString('base64');
  fs.writeFileSync(broker.capabilityPath(), capability, { mode: 0o600 });
  fs.writeFileSync(path.join(broker.runtimeDir(), 'cm.srv'), serverIdentity, { mode: 0o600 });
  const hostile = net.createServer({ allowHalfOpen: true }, (socket) => {
    socket.setEncoding('utf8');
    socket.once('data', () => {
      socket.end(
        `${JSON.stringify({
          ok: true,
          kind: 'api_key',
          baseUrl: 'https://attacker.example',
          headers: { Authorization: 'FORGED' },
          query: {},
          serverAuth: Buffer.alloc(32, 13).toString('base64'),
        })}\n`
      );
    });
  });
  await new Promise((resolve, reject) => {
    hostile.once('error', reject);
    hostile.listen(broker.socketPath(), resolve);
  });
  try {
    await assert.rejects(
      client.brokerRequest({ op: 'rendered', connId: 'linear:prebound' }),
      (error) => error && error.code === 'DEX_CM_SERVER_AUTH_INVALID'
    );
  } finally {
    await new Promise((resolve) => hostile.close(resolve));
    fs.rmSync(broker.socketPath(), { force: true });
  }
});

test('socket (verify outside sandbox): idle shutdown destroys clients that never complete a request', async () => {
  const running = await broker.startBroker({ idleMs: 25 });
  const socket = net.createConnection(broker.socketPath());
  const closed = new Promise((resolve, reject) => {
    socket.once('close', () => resolve(true));
    socket.once('error', reject);
  });
  try {
    const didClose = await Promise.race([
      closed,
      new Promise((resolve) => setTimeout(() => resolve(false), 1000)),
    ]);
    assert.equal(didClose, true, 'idle broker must destroy an incomplete client socket');
    await waitForGone(broker.socketPath());
    assert.equal(fs.existsSync(broker.socketPath()), false);
  } finally {
    socket.destroy();
    await running.close();
  }
});

test('socket (verify outside sandbox): broker gates operations and accessor CLIs end to end', async (t) => {
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
        provider: 'linear',
      });
      assert.equal(Object.hasOwn(response, 'apiKey'), false);
      assert.deepEqual(presenceCalls, []);
    });

    await t.test('get-token default op preserves OAuth and Class-B least-privilege shapes without presence', async () => {
      assert.deepEqual(await rawRequest({ capability, op: 'get-token-default', connId: google }), {
        ok: true,
        value: {
          access_token: 'GOOGLE-BROKER-ACCESS',
          expires_at: store.loadToken(google).expires_at,
        },
      });
      const rendered = await authContext.resolveAuthContext(linear);
      assert.deepEqual(await rawRequest({ capability, op: 'get-token-default', connId: linear }), {
        ok: true,
        value: {
          kind: rendered.kind,
          baseUrl: rendered.baseUrl,
          headers: rendered.headers,
          query: rendered.query,
        },
      });
      assert.deepEqual(presenceCalls, []);
    });

    await t.test('denying presence returns presence_required without releasing the raw secret', async () => {
      const acceptingPresence = broker.assertPresence;
      broker.assertPresence = async () => {
        const error = new Error('User presence is required for this credential operation.');
        error.code = 'DEX_CM_PRESENCE_REQUIRED';
        error.category = 'presence_required';
        throw error;
      };
      try {
        const response = await rawRequest({ capability, op: 'access-token', connId: linear });
        assert.equal(response.ok, false);
        assert.equal(response.error.category, 'presence_required');
        assert.equal(JSON.stringify(response).includes('LINEAR-BROKER-SECRET'), false);
      } finally {
        broker.assertPresence = acceptingPresence;
      }
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

    await t.test('get-token CLI preserves all four output modes through the broker', async () => {
      const oauthDefault = await runCli(path.join(__dirname, 'get-token.cjs'), [google]);
      assert.equal(oauthDefault.status, 0, oauthDefault.stderr);
      assert.deepEqual(JSON.parse(oauthDefault.stdout), {
        access_token: 'GOOGLE-BROKER-ACCESS',
        expires_at: store.loadToken(google).expires_at,
      });

      const classBDefault = await runCli(path.join(__dirname, 'get-token.cjs'), [linear]);
      assert.equal(classBDefault.status, 0, classBDefault.stderr);
      const expectedClassB = await authContext.resolveAuthContext(linear);
      assert.deepEqual(JSON.parse(classBDefault.stdout), {
        kind: expectedClassB.kind,
        baseUrl: expectedClassB.baseUrl,
        headers: expectedClassB.headers,
        query: expectedClassB.query,
      });

      const full = await runCli(path.join(__dirname, 'get-token.cjs'), [google, '--full']);
      assert.equal(full.status, 0, full.stderr);
      assert.equal(JSON.parse(full.stdout).refresh_token, 'GOOGLE-BROKER-REFRESH');

      const accessOnly = await runCli(path.join(__dirname, 'get-token.cjs'), [linear, '--access-token-only']);
      assert.equal(accessOnly.status, 0, accessOnly.stderr);
      assert.equal(accessOnly.stdout, 'LINEAR-BROKER-SECRET');
      assert.deepEqual(presenceCalls.slice(-2), [
        [google, 'full'],
        [linear, 'access-token'],
      ]);
    });

    await t.test('dex-call CLI obtains rendered auth from the broker and still sends its own request', async () => {
      const preload = path.join(TMP_ROOT, 'dex-call-fetch-preload.cjs');
      fs.writeFileSync(
        preload,
        [
          "'use strict';",
          'globalThis.fetch = async (url, options) => ({',
          '  ok: true, status: 200, statusText: "OK",',
          '  text: async () => JSON.stringify({ url, method: options.method, authorization: options.headers.Authorization }),',
          '});',
        ].join('\n')
      );
      const presenceBefore = presenceCalls.length;
      const result = await runCli(
        path.join(__dirname, 'dex-call.cjs'),
        [linear, 'POST', 'https://api.linear.app/graphql', '--body', '{"query":"{ viewer { id } }"}'],
        { NODE_OPTIONS: `--require=${preload}` }
      );
      assert.equal(result.status, 0, result.stderr);
      assert.deepEqual(JSON.parse(result.stdout), {
        url: 'https://api.linear.app/graphql',
        method: 'POST',
        authorization: 'LINEAR-BROKER-SECRET',
      });
      assert.equal(presenceCalls.length, presenceBefore);
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
        { ok: false, error: { category: 'unvetted', provider: 'airtable-pat' } }
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
      const response = await rawRequest({ capability, op: 'access-token', connId: forged });
      assert.equal(response.ok, false);
      // 5b trust verification downgrades the un-MAC'd forged entry to
      // needs_reauth on read, so the broker refuses before releasing anything.
      assert.equal(response.error.category, 'needs_reauth');
      assert.match(response.error.message, /needs re-authentication/i);
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
  assert.equal(client.exitCodeForError('presence_required'), 1);
  assert.equal(client.exitCodeForError('needs_reauth'), 3);
  assert.equal(client.exitCodeForError('not_connected'), 2);
  assert.equal(client.exitCodeForError('http'), 4);
  assert.equal(client.exitCodeForError('anything_else'), 1);
});

test('socket (verify outside sandbox): concurrent clients auto-spawn exactly one usable broker', async () => {
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
