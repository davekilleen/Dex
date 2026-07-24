#!/usr/bin/env node
'use strict';
/**
 * hardening.child.cjs: subprocess driver for the hardening test suite.
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
    case 'upsert-many': {
      // upsert-many <prefix> <count>: N sequential registry read-modify-writes.
      const [prefix, countStr] = args;
      const count = Number(countStr);
      for (let i = 0; i < count; i++) {
        store.upsertConnection(`${prefix}-${i}`, { provider: prefix, status: 'connected' });
      }
      process.stdout.write('ok');
      return;
    }
    case 'hold-lock': {
      // hold-lock <ms>: acquire the store mutation lock and sit on it.
      const ms = Number(args[0]);
      store.withStoreLock(() => {
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
      });
      process.stdout.write('held');
      return;
    }
    case 'hold-refresh-then-save': {
      // hold-refresh-then-save <connId> <ms> <accessToken>: simulate a process
      // that wins the refresh race: hold the per-connection refresh lock for a
      // while (the "network call"), store the refreshed token, release.
      const [connId, msStr, accessToken] = args;
      await store.withRefreshLock(connId, async () => {
        await new Promise((resolve) => setTimeout(resolve, Number(msStr)));
        store.saveToken(
          connId,
          { access_token: accessToken, refresh_token: 'FAKE-rt', expires_at: Date.now() + 3600_000 },
          { provider: 'google' }
        );
      });
      process.stdout.write('refreshed');
      return;
    }
    case 'load-token': {
      // load-token <connId>: prints the decrypted token JSON. Exit 9 on key loss
      // (distinct from generic failure) so tests can assert the explicit state.
      try {
        process.stdout.write(JSON.stringify(store.loadToken(args[0])));
      } catch (err) {
        process.stderr.write(`${err.code || ''} ${err.message}\n`);
        process.exit(err.code === 'DEX_CM_KEY_LOST' ? 9 : 1);
      }
      return;
    }
    case 'health-sweep': {
      // health-sweep: prints allConnectionsHealth() as JSON (fresh process, fresh key cache).
      const health = require('./health.cjs');
      process.stdout.write(JSON.stringify(health.allConnectionsHealth()));
      return;
    }
    case 'save-key': {
      // save-key <connId> <apiKey>: saveApiKey from a fresh process (exercises
      // explicit key-loss recovery when the key file has been removed).
      const [connId, apiKey] = args;
      store.saveApiKey(connId, { apiKey }, { provider: connId, authMode: 'API_KEY' });
      process.stdout.write('saved');
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
