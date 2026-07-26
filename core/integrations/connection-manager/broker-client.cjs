'use strict';
/**
 * Client for the local credential broker.
 *
 * `DEX_CM_CAPABILITY` is the stronger per-launch handoff. Reading cm.cap is the
 * same-uid compatibility fallback: any process running as the user can read
 * that 0600 file, matching the explicitly documented security ceiling in
 * broker.cjs. The separate 0600 cm.srv identity authenticates each broker
 * response and prevents trivial pre-bound/stale socket impersonation, with the
 * same disclosed same-user file-read ceiling.
 */

const crypto = require('node:crypto');
const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const broker = require('./broker.cjs');
const { withLock } = require('./fs-safe.cjs');

const READY_TIMEOUT_MS = 3000;
const DEFAULT_CLIENT_TIMEOUT_MS = 10_000;
let startFlight = null;

function exitCodeForError(category) {
  return {
    forbidden: 1,
    unvetted: 1,
    presence_required: 1,
    needs_reauth: 3,
    not_connected: 2,
    http: 4,
  }[category] || 1;
}

function capability() {
  if (process.env.DEX_CM_CAPABILITY) return process.env.DEX_CM_CAPABILITY;
  return fs.readFileSync(broker.capabilityPath(), 'utf8').trim();
}

function serverAuthenticationError() {
  const error = new Error('Credential broker response authentication failed.');
  error.code = 'DEX_CM_SERVER_AUTH_INVALID';
  return error;
}

function serverIdentity() {
  const file = broker.serverIdentityPath();
  let value;
  try {
    const stat = fs.lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink()) throw serverAuthenticationError();
    value = fs.readFileSync(file, 'utf8').trim();
  } catch (error) {
    if (error && error.code === 'DEX_CM_SERVER_AUTH_INVALID') throw error;
    throw serverAuthenticationError();
  }
  if (Buffer.from(value, 'base64').length !== 32) throw serverAuthenticationError();
  return value;
}

function serverIdentityMatches(actual, expected) {
  if (typeof actual !== 'string' || typeof expected !== 'string') return false;
  const actualBytes = Buffer.from(actual, 'utf8');
  const expectedBytes = Buffer.from(expected, 'utf8');
  return actualBytes.length === expectedBytes.length && crypto.timingSafeEqual(actualBytes, expectedBytes);
}

function clientTimeoutMs() {
  const configured = Number(process.env.DEX_CM_CLIENT_TIMEOUT_MS);
  return Number.isFinite(configured) && configured >= 0 ? configured : DEFAULT_CLIENT_TIMEOUT_MS;
}

function ensurePrivateRuntime() {
  const dir = broker.runtimeDir();
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const stat = fs.lstatSync(dir);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error(`Credential broker runtime path is not a real directory: ${dir}`);
  }
  fs.chmodSync(dir, 0o700);
}

function exchange(request) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(broker.socketPath());
    const timeoutMs = clientTimeoutMs();
    let output = '';
    let expectedServerIdentity;
    let settled = false;
    let timer;
    const rejectOnce = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    };
    const resolveOnce = (response) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(response);
    };
    timer = setTimeout(() => {
      const error = new Error(`Credential broker did not return a complete response within ${timeoutMs} ms.`);
      error.code = 'DEX_CM_CLIENT_TIMEOUT';
      socket.destroy();
      rejectOnce(error);
    }, timeoutMs);
    socket.setEncoding('utf8');
    socket.once('connect', () => {
      let token;
      try {
        token = capability();
        expectedServerIdentity = serverIdentity();
      } catch (error) {
        socket.destroy();
        rejectOnce(error);
        return;
      }
      socket.end(`${JSON.stringify({ capability: token, ...request })}\n`);
    });
    socket.on('data', (chunk) => {
      output += chunk;
      if (output.length > 1024 * 1024) {
        socket.destroy();
        rejectOnce(new Error('Credential broker response exceeded 1 MiB.'));
      }
    });
    socket.once('error', rejectOnce);
    socket.once('end', () => {
      try {
        const response = JSON.parse(output.trim());
        if (!serverIdentityMatches(response.serverAuth, expectedServerIdentity)) {
          throw serverAuthenticationError();
        }
        delete response.serverAuth;
        resolveOnce(response);
      } catch (error) {
        rejectOnce(error);
      }
    });
  });
}

function socketReady() {
  return new Promise((resolve) => {
    const socket = net.createConnection(broker.socketPath());
    let settled = false;
    const finish = (ready) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(ready);
    };
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
    socket.setTimeout(100, () => finish(false));
  });
}

async function pollUntilReady() {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await socketReady()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error('Credential broker did not become ready within 3 seconds.');
}

async function startBrokerSingleFlight() {
  if (startFlight) return startFlight;
  ensurePrivateRuntime();
  startFlight = withLock(
    path.join(broker.runtimeDir(), 'client-start.lock'),
    async () => {
      if (await socketReady()) return;
      const child = spawn(process.execPath, [path.join(__dirname, 'broker.cjs')], {
        detached: true,
        stdio: 'ignore',
        env: { ...process.env },
      });
      child.unref();
      await pollUntilReady();
    },
    { timeoutMs: READY_TIMEOUT_MS + 500 }
  ).finally(() => {
    startFlight = null;
  });
  return startFlight;
}

function isBrokerUnavailable(error) {
  return error && (error.code === 'ENOENT' || error.code === 'ECONNREFUSED');
}

async function brokerRequest({ op = 'rendered', connId, targetOrigin, allowUnvetted, privileged: _privileged } = {}) {
  ensurePrivateRuntime();
  const request = {
    op,
    ...(connId ? { connId } : {}),
    ...(targetOrigin ? { targetOrigin } : {}),
    ...(allowUnvetted ? { allowUnvetted: true } : {}),
  };
  try {
    return await exchange(request);
  } catch (error) {
    if (!isBrokerUnavailable(error)) throw error;
  }
  await startBrokerSingleFlight();
  return exchange(request);
}

module.exports = { brokerRequest, exitCodeForError, ensurePrivateRuntime };
