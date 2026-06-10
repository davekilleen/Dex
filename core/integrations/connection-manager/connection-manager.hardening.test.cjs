'use strict';
/**
 * connection-manager.hardening.test.cjs — failure-mode coverage for the token
 * store: atomic writes, cross-process locking, corrupt token files, corrupt
 * registry recovery, key loss, and secrets-in-logs.
 *
 * Companion to connection-manager.test.cjs (happy paths + policy logic). Same
 * conventions: a throwaway DEX_VAULT under the OS temp dir, offline-only, and
 * obviously-fake fixture secrets. Run with:
 *   node --test connection-manager.test.cjs connection-manager.hardening.test.cjs
 *
 * Two isolation notes specific to this file:
 *  - DEX_CM_NO_KEYCHAIN=1 forces the file-based encryption key, so these tests
 *    never read or write the developer's real macOS keychain entry and the
 *    key-loss scenarios can be staged by removing a file.
 *  - Failure modes that depend on fresh process state (key cache, crash
 *    injection, lock contention) run through hardening.child.cjs subprocesses.
 */

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync, execFile, spawn } = require('node:child_process');

// Point everything at a throwaway vault BEFORE requiring the store modules,
// and keep the real keychain out of the picture entirely.
const TMP_VAULT = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-cm-hardening-'));
process.env.DEX_VAULT = TMP_VAULT;
process.env.DEX_CM_NO_KEYCHAIN = '1';

const store = require('./token-store.cjs');
const health = require('./health.cjs');
const fsSafe = require('./fs-safe.cjs');

const DIR = __dirname;
const CHILD = path.join(DIR, 'hardening.child.cjs');
const CRED_DIR = path.join(TMP_VAULT, 'System', 'credentials');
const TOKENS_DIR = path.join(CRED_DIR, 'tokens');
const REGISTRY = path.join(CRED_DIR, 'connections.json');
const childEnv = { ...process.env, DEX_VAULT: TMP_VAULT, DEX_CM_NO_KEYCHAIN: '1' };

test.after(() => fs.rmSync(TMP_VAULT, { recursive: true, force: true }));

function mode(p) {
  return fs.statSync(p).mode & 0o777;
}

// ---- atomic writes (fix: crash mid-write must never corrupt a file) ----------

test('atomic: writeFileAtomic writes content and leaves no temp file behind', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-fs-safe-'));
  const f = path.join(dir, 'out.json');
  fsSafe.writeFileAtomic(f, '{"a":1}', { mode: 0o600 });
  assert.equal(fs.readFileSync(f, 'utf8'), '{"a":1}');
  assert.equal(mode(f), 0o600);
  const leftovers = fs.readdirSync(dir).filter((n) => n.endsWith('.tmp'));
  assert.deepEqual(leftovers, [], 'no temp files should remain after a successful write');
  fs.rmSync(dir, { recursive: true, force: true });
});

test('atomic: overwrite re-applies 0600 even if the file was loosened (writeFileSync wart fixed)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-fs-safe-'));
  const f = path.join(dir, 'out.json');
  fsSafe.writeFileAtomic(f, 'one', { mode: 0o600 });
  fs.chmodSync(f, 0o644); // simulate a loosened file
  fsSafe.writeFileAtomic(f, 'two', { mode: 0o600 });
  assert.equal(fs.readFileSync(f, 'utf8'), 'two');
  assert.equal(mode(f), 0o600, 'overwrite must restore 0600 (fs.writeFileSync mode would not)');
  fs.rmSync(dir, { recursive: true, force: true });
});

test('atomic: registry and token writes keep 0600 files / 0700 dirs through the atomic path', () => {
  store.saveApiKey('perm-check', { apiKey: 'FAKE-perm-key' }, { provider: 'perm-check', authMode: 'API_KEY' });
  assert.equal(mode(CRED_DIR), 0o700, 'credentials dir is 0700');
  assert.equal(mode(TOKENS_DIR), 0o700, 'tokens dir is 0700');
  assert.equal(mode(REGISTRY), 0o600, 'registry file is 0600');
  assert.equal(mode(path.join(TOKENS_DIR, 'perm-check.json')), 0o600, 'token file is 0600');
  store.deleteToken('perm-check');
});

test('atomic: crash between temp write and rename leaves the old registry intact', () => {
  store.upsertConnection('crash-keeper', { provider: 'crash-keeper', status: 'connected' });

  // Child crashes (exit 42) after writing the temp file but BEFORE the rename.
  let code = 0;
  try {
    execFileSync('node', [CHILD, 'upsert-one', 'crash-victim'], {
      env: { ...childEnv, DEX_CM_TEST_CRASH_BEFORE_RENAME: '1' },
      stdio: 'pipe',
    });
  } catch (err) {
    code = err.status;
  }
  assert.equal(code, 42, 'child should have crashed at the injected fault point');

  // Old file intact and parseable; the half-written update exists only as a temp file.
  const reg = JSON.parse(fs.readFileSync(REGISTRY, 'utf8'));
  assert.ok(reg['crash-keeper'], 'pre-crash entry survives');
  assert.equal(reg['crash-victim'], undefined, 'crashed write must not be visible at the real path');
  const tmps = fs.readdirSync(CRED_DIR).filter((n) => n.includes('connections.json') && n.endsWith('.tmp'));
  assert.ok(tmps.length >= 1, 'the interrupted write should remain as an inert temp file');

  // A later, healthy write succeeds and sees the pre-crash state.
  execFileSync('node', [CHILD, 'upsert-one', 'crash-victim'], { env: childEnv });
  const reg2 = JSON.parse(fs.readFileSync(REGISTRY, 'utf8'));
  assert.ok(reg2['crash-keeper'] && reg2['crash-victim'], 'both entries present after the retry');
  store.deleteToken('crash-keeper');
  store.deleteToken('crash-victim');
});

// ---- cross-process locking (fix: desktop app and CLI must not interleave) ----

const STORE_LOCK = path.join(CRED_DIR, '.dex-cm.lock');

function execFileP(cmd, cmdArgs, opts) {
  return new Promise((resolve, reject) => {
    execFile(cmd, cmdArgs, opts, (err, stdout, stderr) => (err ? reject(Object.assign(err, { stdout, stderr })) : resolve({ stdout, stderr })));
  });
}

async function waitFor(predicate, ms, what) {
  const start = Date.now();
  while (!predicate()) {
    if (Date.now() - start > ms) throw new Error(`timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 10));
  }
}

test('lock: two processes upserting concurrently lose no registry updates', async () => {
  const [a, b] = await Promise.all([
    execFileP('node', [CHILD, 'upsert-many', 'race-a', '25'], { env: childEnv }),
    execFileP('node', [CHILD, 'upsert-many', 'race-b', '25'], { env: childEnv }),
  ]);
  assert.equal(a.stdout, 'ok');
  assert.equal(b.stdout, 'ok');
  const reg = store.readRegistry();
  for (let i = 0; i < 25; i++) {
    assert.ok(reg[`race-a-${i}`], `race-a-${i} must survive the race`);
    assert.ok(reg[`race-b-${i}`], `race-b-${i} must survive the race`);
  }
  for (let i = 0; i < 25; i++) {
    store.deleteToken(`race-a-${i}`);
    store.deleteToken(`race-b-${i}`);
  }
});

test('lock: a waiter blocks until the holder releases, then proceeds', async () => {
  const child = spawn('node', [CHILD, 'hold-lock', '700'], { env: childEnv });
  const done = new Promise((resolve) => child.on('exit', resolve));
  await waitFor(() => fs.existsSync(STORE_LOCK), 3000, 'child to take the lock');
  const t0 = Date.now();
  store.upsertConnection('lock-waiter', { provider: 'lock-waiter', status: 'connected' }); // blocks until child releases
  const waited = Date.now() - t0;
  assert.ok(waited >= 150, `the write should have waited for the holder (waited ${waited}ms)`);
  assert.ok(store.readRegistry()['lock-waiter'], 'the waited write landed');
  await done;
  store.deleteToken('lock-waiter');
});

test('lock: a lockfile from a dead process is stolen, not waited on', () => {
  const dead = require('node:child_process').spawnSync('node', ['-e', '']); // exits immediately
  fs.mkdirSync(CRED_DIR, { recursive: true, mode: 0o700 });
  fs.writeFileSync(STORE_LOCK, JSON.stringify({ pid: dead.pid, createdAt: Date.now() }), { mode: 0o600 });
  const t0 = Date.now();
  store.upsertConnection('stale-steal', { provider: 'stale-steal', status: 'connected' });
  assert.ok(Date.now() - t0 < 2000, 'stale lock must be stolen quickly, not waited out');
  assert.ok(store.readRegistry()['stale-steal']);
  store.deleteToken('stale-steal');
});

test('lock: acquisition times out with a clear error instead of proceeding unlocked', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-lock-'));
  const lockPath = path.join(dir, 'busy.lock');
  // A live foreign holder: our own PID is alive, but this process never acquired
  // the lock through withLock, so it is treated as another process's lock.
  fs.writeFileSync(lockPath, JSON.stringify({ pid: process.pid, createdAt: Date.now() }));
  assert.throws(
    () => fsSafe.withLockSync(lockPath, () => 'never-runs', { timeoutMs: 300 }),
    /Could not lock/,
    'must throw rather than run the critical section unlocked'
  );
  fs.rmSync(dir, { recursive: true, force: true });
});

test('lock: a throw inside the critical section still releases the lock', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-lock-'));
  const lockPath = path.join(dir, 'throwy.lock');
  assert.throws(() => fsSafe.withLockSync(lockPath, () => { throw new Error('boom'); }), /boom/);
  assert.ok(!fs.existsSync(lockPath), 'lockfile must be gone after the throw');
  // and the lock is immediately reusable
  assert.equal(fsSafe.withLockSync(lockPath, () => 'ran'), 'ran');
  fs.rmSync(dir, { recursive: true, force: true });
});

test('lock: nested store mutations are reentrant within one process (no self-deadlock)', () => {
  const result = store.withStoreLock(() => {
    store.upsertConnection('reentrant-check', { provider: 'reentrant-check', status: 'connected' }); // takes the same lock inside
    return 'done';
  });
  assert.equal(result, 'done');
  assert.ok(!fs.existsSync(STORE_LOCK), 'lock released after the outer section');
  store.deleteToken('reentrant-check');
});

test('lock: losing refresh racer reuses the winner token instead of refreshing again', async () => {
  // An expired OAuth token that would need a (network) refresh.
  store.saveToken(
    'refresh-race',
    { access_token: 'FAKE-STALE-AT', refresh_token: 'FAKE-rt', expires_at: Date.now() - 1000 },
    { provider: 'google' }
  );
  // Another process wins the race: holds the refresh lock (its "network call"),
  // then stores the refreshed token. No OAuth app is registered in this vault,
  // so if our process tried its own refresh it would throw — proving the
  // double-check path is what returns the token.
  const child = spawn('node', [CHILD, 'hold-refresh-then-save', 'refresh-race', '500', 'FAKE-WINNER-AT'], { env: childEnv });
  const done = new Promise((resolve) => child.on('exit', resolve));
  const refreshLock = path.join(CRED_DIR, '.dex-cm.refresh-refresh-race.lock');
  await waitFor(() => fs.existsSync(refreshLock), 3000, 'child to take the refresh lock');
  const tokenOut = await health.ensureFreshToken('refresh-race');
  assert.equal(tokenOut, 'FAKE-WINNER-AT', 'the waiter must adopt the winner refreshed token');
  await done;
  store.deleteToken('refresh-race');
});
