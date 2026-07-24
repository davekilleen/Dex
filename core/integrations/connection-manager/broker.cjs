#!/usr/bin/env node
'use strict';
/**
 * Local credential broker.
 *
 * Honest security boundary: on a single-user OS, another process running as
 * this user can read any 0600 file the user owns and scrape a blessed
 * consumer's memory. This broker alone therefore does NOT stop same-user
 * malware. It removes raw-secret-to-stdout as the default, centralises release
 * at the Phase 5d user-presence gate, and enforces capability, pinned-origin,
 * and trust-MAC policy in one place.
 *
 * Node has no portable SO_PEERCRED API and this project deliberately carries no
 * native addon. The 0700 runtime directory limits socket access to the same uid;
 * the capability is a weak blessed-consumer distinction subject to the ceiling
 * above.
 */

const crypto = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const authContext = require('./auth-context.cjs');
const health = require('./health.cjs');
const pinned = require('./pinned-providers.cjs');
const presence = require('./presence.cjs');
const store = require('./token-store.cjs');
const { withLock, writeFileAtomic } = require('./fs-safe.cjs');

const DEFAULT_IDLE_MS = 5 * 60 * 1000;
const MAX_REQUEST_BYTES = 64 * 1024;

function pathIsWithin(child, parent) {
  const relative = path.relative(path.resolve(parent), path.resolve(child));
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}

function runtimeDir() {
  let dir;
  if (process.env.DEX_CM_RUNTIME_DIR) {
    dir = path.resolve(process.env.DEX_CM_RUNTIME_DIR);
  } else if (process.platform === 'darwin') {
    dir = path.join(os.homedir(), 'Library', 'Application Support', 'Dex', 'cm');
  } else if (process.env.XDG_RUNTIME_DIR) {
    dir = path.join(process.env.XDG_RUNTIME_DIR, 'dex-cm');
  } else {
    dir = path.join(os.homedir(), '.local', 'state', 'dex-cm');
  }
  const vault = process.env.DEX_VAULT || process.env.VAULT_PATH;
  if (vault && pathIsWithin(dir, vault)) {
    throw new Error('DEX_CM_RUNTIME_DIR must be machine-local and must not be inside DEX_VAULT.');
  }
  return dir;
}

function socketPath() {
  return path.join(runtimeDir(), 'cm.sock');
}

function capabilityPath() {
  return path.join(runtimeDir(), 'cm.cap');
}

function ensurePrivateRuntime() {
  const dir = runtimeDir();
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const stat = fs.lstatSync(dir);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error(`Credential broker runtime path is not a real directory: ${dir}`);
  }
  fs.chmodSync(dir, 0o700);
}

function ensureCapability() {
  const file = capabilityPath();
  if (!fs.existsSync(file)) {
    writeFileAtomic(file, crypto.randomBytes(32).toString('base64'), { mode: 0o600 });
  }
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`Credential broker capability path is not a regular file: ${file}`);
  }
  fs.chmodSync(file, 0o600);
  const capability = fs.readFileSync(file, 'utf8').trim();
  if (Buffer.from(capability, 'base64').length !== 32) {
    throw new Error('Credential broker capability file is invalid.');
  }
  return capability;
}

function capabilityMatches(actual, expected) {
  if (typeof actual !== 'string') return false;
  const actualBytes = Buffer.from(actual, 'utf8');
  const expectedBytes = Buffer.from(expected, 'utf8');
  return actualBytes.length === expectedBytes.length && crypto.timingSafeEqual(actualBytes, expectedBytes);
}

function socketIsLive(file) {
  return new Promise((resolve) => {
    const socket = net.createConnection(file);
    let settled = false;
    const finish = (live) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(live);
    };
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
    socket.setTimeout(150, () => finish(false));
  });
}

async function assertPresence(connId, op) {
  // Keep this exported indirection: tests and the desktop host can observe the
  // broker seam without weakening the provider policy in presence.cjs.
  return presence.assertPresence(connId, op);
}

function errorCategory(error) {
  if (error && error.code === 'DEX_CM_ORIGIN_UNPINNED') return 'forbidden';
  if (error && (error.exitCode === 3 || error.needsReauth)) return 'needs_reauth';
  if (error && error.exitCode === 2) return 'not_connected';
  if (error && (error.exitCode === 4 || error.category === 'http')) return 'http';
  return (error && error.category) || 'error';
}

function providerFor(connId, context) {
  if (context && context.provider) return context.provider;
  const connection = store.getConnection(connId) || {};
  return connection.provider || store.parseConnectionId(connId).provider;
}

async function renderedResponse(request) {
  const context = await authContext.resolveAuthContext(request.connId);
  const provider = providerFor(request.connId, context);
  if (!pinned.isVetted(provider)) {
    if (!request.allowUnvetted) return { ok: false, error: { category: 'unvetted', provider } };
  } else {
    if (context.baseUrl) pinned.assertPinnedOrigin(provider, 'api', context.baseUrl);
    if (request.targetOrigin) pinned.assertPinnedOrigin(provider, 'api', request.targetOrigin);
  }
  return {
    ok: true,
    kind: context.kind,
    baseUrl: context.baseUrl,
    headers: context.headers,
    query: context.query,
    provider,
  };
}

async function getTokenDefaultResponse(request) {
  const context = await authContext.resolveAuthContext(request.connId);
  if (context.kind === 'api_key') {
    return {
      ok: true,
      value: {
        kind: context.kind,
        baseUrl: context.baseUrl,
        headers: context.headers,
        query: context.query,
      },
    };
  }
  const fresh = store.loadToken(request.connId);
  return {
    ok: true,
    value: {
      access_token: fresh.access_token,
      expires_at: fresh.expires_at || null,
    },
  };
}

async function privilegedResponse(request) {
  // Resolve first: this is the shared refresh + MAC-verified needs_reauth gate.
  const context = await authContext.resolveAuthContext(request.connId);
  await module.exports.assertPresence(request.connId, request.op);
  const token = store.loadToken(request.connId);
  if (request.op === 'full') return { ok: true, token };
  const value =
    context.kind === 'api_key'
      ? token.apiKey || token.password || ''
      : String(context.headers.Authorization || '').replace(/^Bearer\s+/i, '');
  return { ok: true, value };
}

async function processRequest(request, capability) {
  if (!capabilityMatches(request && request.capability, capability)) {
    return { ok: false, error: { category: 'forbidden' } };
  }
  const op = request.op || 'rendered';
  try {
    if (op === 'rendered') return await renderedResponse(request);
    if (op === 'get-token-default') return await getTokenDefaultResponse(request);
    if (op === 'access-token' || op === 'full') return await privilegedResponse({ ...request, op });
    if (op === 'status') {
      return {
        ok: true,
        connections: health.allConnectionsHealth(),
        registryNotice: store.readRegistry()._meta || null,
      };
    }
    return { ok: false, error: { category: 'unsupported' } };
  } catch (error) {
    const category = errorCategory(error);
    return {
      ok: false,
      error: {
        category,
        ...(category !== 'forbidden' && error && error.message ? { message: error.message } : {}),
      },
    };
  }
}

function createServer(capability, activity) {
  // allowHalfOpen: the client half-closes its write side after sending the
  // request (socket.end). Without this, the server auto-closes its write side on
  // that FIN, and a slow async handler (e.g. a presence check that spawns a
  // child process) would finish after the socket is already closing — dropping
  // the response. Keeping the write side open lets every response land; the
  // handler still explicitly ends the socket once it has written.
  return net.createServer({ allowHalfOpen: true }, (socket) => {
    socket.setEncoding('utf8');
    let input = '';
    let handled = false;
    socket.on('data', (chunk) => {
      if (handled) return;
      input += chunk;
      if (input.length > MAX_REQUEST_BYTES) {
        handled = true;
        socket.end(`${JSON.stringify({ ok: false, error: { category: 'invalid_request' } })}\n`);
        return;
      }
      const newline = input.indexOf('\n');
      if (newline === -1) return;
      handled = true;
      activity.begin();
      Promise.resolve()
        .then(() => JSON.parse(input.slice(0, newline)))
        .then((request) => processRequest(request, capability))
        .catch(() => ({ ok: false, error: { category: 'invalid_request' } }))
        .then((response) => socket.end(`${JSON.stringify(response)}\n`))
        .finally(() => activity.end());
    });
  });
}

async function startBroker({ idleMs } = {}) {
  ensurePrivateRuntime();
  const configuredIdle = Number(idleMs ?? process.env.DEX_CM_BROKER_IDLE_MS ?? DEFAULT_IDLE_MS);
  const effectiveIdle = Number.isFinite(configuredIdle) && configuredIdle >= 0 ? configuredIdle : DEFAULT_IDLE_MS;
  const startLock = path.join(runtimeDir(), 'broker-start.lock');

  return withLock(
    startLock,
    async () => {
      if (await socketIsLive(socketPath())) {
        return {
          alreadyRunning: true,
          close: async () => {},
        };
      }
      fs.rmSync(socketPath(), { force: true });
      const capability = ensureCapability();
      let activeRequests = 0;
      let idleTimer = null;
      let closed = false;
      let server;

      const close = () =>
        new Promise((resolve, reject) => {
          if (closed) {
            resolve();
            return;
          }
          closed = true;
          if (idleTimer) clearTimeout(idleTimer);
          server.close((error) => {
            fs.rmSync(socketPath(), { force: true });
            if (error && error.code !== 'ERR_SERVER_NOT_RUNNING') reject(error);
            else resolve();
          });
        });
      const scheduleIdle = () => {
        if (idleTimer) clearTimeout(idleTimer);
        idleTimer = setTimeout(() => {
          if (activeRequests === 0) void close();
          else scheduleIdle();
        }, effectiveIdle);
        idleTimer.unref();
      };
      const activity = {
        begin() {
          activeRequests += 1;
          if (idleTimer) clearTimeout(idleTimer);
        },
        end() {
          activeRequests = Math.max(0, activeRequests - 1);
          if (activeRequests === 0) scheduleIdle();
        },
      };
      server = createServer(capability, activity);
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(socketPath(), () => {
          server.off('error', reject);
          resolve();
        });
      });
      fs.chmodSync(socketPath(), 0o600);
      scheduleIdle();
      return { server, alreadyRunning: false, close };
    },
    { timeoutMs: 3500 }
  );
}

async function main() {
  const running = await startBroker();
  if (running.alreadyRunning) return;
  const shutdown = () => {
    void running.close().finally(() => process.exit(0));
  };
  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
}

module.exports = {
  runtimeDir,
  capabilityPath,
  socketPath,
  assertPresence,
  processRequest,
  startBroker,
  main,
};

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
