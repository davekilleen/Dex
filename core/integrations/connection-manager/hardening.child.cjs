#!/usr/bin/env node
'use strict';
/**
 * hardening.child.cjs — subprocess driver for the hardening test suite.
 * NOT a test file (the name deliberately avoids node --test discovery).
 *
 * The tests spawn this script as a real second process to exercise behaviour
 * that cannot be simulated in-process: crash-during-write (via the
 * DEX_CM_TEST_CRASH_BEFORE_RENAME fault injection), cross-process lock
 * contention, and fresh-process key/cache state.
 *
 * Usage: DEX_VAULT=... node hardening.child.cjs <verb> [args...]
 * All fixture values passed through here are obviously fake; never real secrets.
 */

const store = require('./token-store.cjs');

async function main() {
  const [verb, ...args] = process.argv.slice(2);
  switch (verb) {
    case 'upsert-one': {
      // upsert-one <connId> [provider]
      const [connId, provider] = args;
      store.upsertConnection(connId, { provider: provider || connId, status: 'connected' });
      process.stdout.write('ok');
      return;
    }
    default:
      process.stderr.write(`unknown verb: ${verb}\n`);
      process.exit(64);
  }
}

main().catch((err) => {
  process.stderr.write(`${err.code || ''} ${err.message}\n`);
  process.exit(1);
});
