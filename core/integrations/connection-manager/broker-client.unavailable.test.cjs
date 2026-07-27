'use strict';

const { test } = require('node:test');
const assert = require('node:assert');
const os = require('node:os');
const fs = require('node:fs');
const path = require('node:path');

// Module-load env (before requiring the client) mirrors the other suites: keep
// this file self-contained so it never reads or pollutes shared state.
process.env.DEX_VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-broker-unavailable-'));
process.env.DEX_CM_RUNTIME_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-broker-unavailable-rt-'));

const { isBrokerUnavailable } = require('./broker-client.cjs');

const withCode = (code) => Object.assign(new Error(code), { code });

test('broker-unavailable classification triggers the spawn-and-resend recovery for pre-delivery failures only', () => {
  // Pre-delivery failures — the request never reached a broker, so a fresh
  // spawn + single resend is always safe:
  assert.equal(isBrokerUnavailable(withCode('ENOENT')), true, 'no socket file');
  assert.equal(isBrokerUnavailable(withCode('ECONNREFUSED')), true, 'nothing listening');
  // EPIPE is the idle-exit race: the broker accepted the connection but closed
  // before our request bytes were parsed (accepted sockets only count as
  // activity once a request starts). Regression guard for the spurious
  // exit-1 this caused in get-token under load.
  assert.equal(isBrokerUnavailable(withCode('EPIPE')), true, 'accepted then idle-closed before delivery');

  // Post-delivery / ambiguous failures must NOT be resent — the broker may
  // have already executed a mutating operation (e.g. a token refresh):
  assert.equal(isBrokerUnavailable(withCode('ECONNRESET')), false, 'may have executed');
  assert.equal(isBrokerUnavailable(withCode('ETIMEDOUT')), false, 'may have executed');
  assert.equal(isBrokerUnavailable(new Error('response exceeded 1 MiB.')), false, 'protocol errors are terminal');
  assert.ok(!isBrokerUnavailable(undefined), 'no error object is never unavailable');
});
