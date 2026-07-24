'use strict';
/**
 * Client for the local credential broker.
 *
 * `DEX_CM_CAPABILITY` is the stronger per-launch handoff. Reading cm.cap is the
 * same-uid compatibility fallback: any process running as the user can read
 * that 0600 file, matching the explicitly documented security ceiling in
 * broker.cjs.
 */

const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const broker = require('./broker.cjs');
const { withLock } = require('./fs-safe.cjs');

const READY_TIMEOUT_MS = 3000;
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

function exchange(request) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(broker.socketPath());
    let output = '';
    socket.setEncoding('utf8');
    socket.once('connect', () => {
      let token;
      try {
        token = capability();
      } catch (error) {
        socket.destroy();
        reject(error);
        return;
      }
      socket.end(`${JSON.stringify({ capability: token, ...request })}\n`);
    });
    socket.on('data', (chunk) => {
      output += chunk;
      if (output.length > 1024 * 1024) {
        socket.destroy();
        reject(new Error('Credential broker response exceeded 1 MiB.'));
      }
    });
    socket.once('error', reject);
    socket.once('end', () => {
      try {
        resolve(JSON.parse(output.trim()));
      } catch (error) {
        reject(error);
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
  startFlight = withLock(
    path.join(broker.runtimeDir(), 'client-start.lock'),
    async () => {
      if (await socketReady()) return;
      fs.mkdirSync(broker.runtimeDir(), { recursive: true, mode: 0o700 });
      fs.chmodSync(broker.runtimeDir(), 0o700);
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

module.exports = { brokerRequest, exitCodeForError };
