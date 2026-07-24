'use strict';
/**
 * connection-manager.hardening.test.cjs: failure-mode coverage for the token
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
const catalog = require('./catalog.cjs');
const authctx = require('./auth-context.cjs');

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
  // so if our process tried its own refresh it would throw, proving the
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

// ---- corrupt token files (fix: one bad file must not kill the sweep) ---------

function corruptTokens() {
  return fs.readdirSync(TOKENS_DIR).filter((n) => n.includes('.corrupt-'));
}

test('corrupt token: truncated file becomes needs_reauth with reason, file quarantined not deleted', () => {
  store.saveApiKey('corrupt-a', { apiKey: 'FAKE-key-a' }, { provider: 'corrupt-a', authMode: 'API_KEY' });
  const p = path.join(TOKENS_DIR, 'corrupt-a.json');
  const garbage = '{"v":1,"iv":'; // truncated mid-write, pre-atomic style
  fs.writeFileSync(p, garbage);

  const h = health.connectionHealth('corrupt-a');
  assert.equal(h.status, 'needs_reauth', 'corrupt file maps to needs_reauth, not a crash');
  assert.equal(h.error, 'token_file_corrupt', 'the reason is explicit');

  assert.ok(!fs.existsSync(p), 'the corrupt file is moved out of the live path');
  const q = corruptTokens().filter((n) => n.startsWith('corrupt-a.json.corrupt-'));
  assert.equal(q.length, 1, 'exactly one quarantine file');
  assert.equal(fs.readFileSync(path.join(TOKENS_DIR, q[0]), 'utf8'), garbage, 'quarantined bytes preserved verbatim');

  const reg = store.readRegistry()['corrupt-a'];
  assert.equal(reg.status, 'needs_reauth');
  assert.equal(reg.error, 'token_file_corrupt');
  assert.ok(reg.corruptFile, 'registry records which quarantine file holds the evidence');

  // The state is stable on subsequent reads (file already quarantined).
  assert.equal(store.loadToken('corrupt-a'), null);
  assert.equal(health.connectionHealth('corrupt-a').status, 'needs_reauth');
  store.deleteToken('corrupt-a');
});

test('corrupt token: tampered ciphertext (GCM auth failure) takes the same quarantine path', () => {
  store.saveApiKey('corrupt-b', { apiKey: 'FAKE-key-b' }, { provider: 'corrupt-b', authMode: 'API_KEY' });
  const p = path.join(TOKENS_DIR, 'corrupt-b.json');
  const envelope = JSON.parse(fs.readFileSync(p, 'utf8'));
  envelope.data = Buffer.from('tampered-bytes-here').toString('base64'); // valid JSON, fails tag verification
  fs.writeFileSync(p, JSON.stringify(envelope));

  const h = health.connectionHealth('corrupt-b');
  assert.equal(h.status, 'needs_reauth');
  assert.equal(h.error, 'token_file_corrupt');
  assert.ok(corruptTokens().some((n) => n.startsWith('corrupt-b.json.corrupt-')), 'tampered file quarantined');
  store.deleteToken('corrupt-b');
});

test('corrupt token: the health sweep survives and still reports the healthy connections', () => {
  store.saveApiKey('sweep-good', { apiKey: 'FAKE-good' }, { provider: 'sweep-good', authMode: 'API_KEY' });
  store.saveApiKey('sweep-bad', { apiKey: 'FAKE-bad' }, { provider: 'sweep-bad', authMode: 'API_KEY' });
  fs.writeFileSync(path.join(TOKENS_DIR, 'sweep-bad.json'), 'not even json');

  const rows = health.allConnectionsHealth();
  const good = rows.find((r) => r.service === 'sweep-good');
  const bad = rows.find((r) => r.service === 'sweep-bad');
  assert.equal(good.status, 'connected', 'healthy connection unaffected by the corrupt one');
  assert.equal(bad.status, 'needs_reauth');
  assert.equal(bad.error, 'token_file_corrupt');
  store.deleteToken('sweep-good');
  store.deleteToken('sweep-bad');
});

test('corrupt token: get-token exits 3 with a reconnect message, not a crash or exit 2', () => {
  store.saveApiKey('corrupt-cli', { apiKey: 'FAKE-cli-key' }, { provider: 'corrupt-cli', authMode: 'API_KEY' });
  fs.writeFileSync(path.join(TOKENS_DIR, 'corrupt-cli.json'), '%%%');
  let code = 0;
  let stderr = '';
  try {
    execFileSync('node', [path.join(DIR, 'get-token.cjs'), 'corrupt-cli'], { env: childEnv, stdio: 'pipe' });
  } catch (err) {
    code = err.status;
    stderr = err.stderr.toString();
  }
  assert.equal(code, 3, 'corrupt credential is a re-auth (3), not not-connected (2) or crash (1)');
  assert.match(stderr, /re-authentication/, 'message tells the user to reconnect');
  assert.match(stderr, /token_file_corrupt/, 'message carries the reason');
  store.deleteToken('corrupt-cli');
});

// ---- corrupt registry (fix: damage must never silently wipe the connection list) ----

function resetRegistryFile() {
  // Tests only: with no token files on disk an empty object is a valid registry.
  fs.writeFileSync(REGISTRY, '{}');
}

function quarantinedRegistries() {
  return fs.readdirSync(CRED_DIR).filter((n) => n.startsWith('connections.json.corrupt-'));
}

test('corrupt registry: quarantined and rebuilt from token files, not silently reset', () => {
  store.saveApiKey('reg-key', { apiKey: 'FAKE-reg-key' }, { provider: 'reg-key', authMode: 'API_KEY' });
  store.saveToken(
    'reg-ali:work',
    { access_token: 'FAKE-AT', refresh_token: 'FAKE-RT', expires_at: Date.now() + 3600_000, scope: 'a b' },
    { provider: 'reg-ali' }
  );
  const before = quarantinedRegistries().length;
  fs.writeFileSync(REGISTRY, '{"this is": not even json');

  const reg = store.readRegistry(); // any read triggers recovery
  assert.equal(quarantinedRegistries().length, before + 1, 'the damaged registry is preserved, not deleted');
  assert.ok(reg['reg-key'], 'API-key connection recovered from its token file');
  assert.ok(reg['reg-ali:work'], 'aliased OAuth connection recovered from its token file');
  assert.equal(reg['reg-key'].authMode, 'API_KEY', 'auth mode recovered from the decrypted token');
  assert.equal(reg['reg-ali:work'].alias, 'work', 'alias recovered from the filename');
  assert.equal(reg['reg-ali:work'].provider, 'reg-ali');
  assert.deepEqual(reg['reg-ali:work'].scopes, ['a', 'b'], 'scopes recovered from the decrypted token');
  assert.equal(reg._meta.notice, 'registry_rebuilt', 'a visible warning state is recorded');
  assert.equal(reg._meta.recovered, 2);

  // The recovered store still works end to end.
  assert.equal(store.loadToken('reg-key').apiKey, 'FAKE-reg-key');
  assert.equal(health.connectionHealth('reg-key').status, 'connected');

  // And the old amnesia bug is dead: a write after recovery keeps everything.
  store.upsertConnection('reg-new', { provider: 'reg-new', status: 'connected' });
  const reg2 = store.readRegistry();
  assert.ok(reg2['reg-key'] && reg2['reg-ali:work'] && reg2['reg-new'], 'no entries lost on the next write');

  store.deleteToken('reg-key');
  store.deleteToken('reg-ali:work');
  store.deleteToken('reg-new');
  resetRegistryFile();
});

test('corrupt registry: missing file with tokens on disk is rebuilt (crash-window self-heal)', () => {
  store.saveApiKey('reg-miss', { apiKey: 'FAKE-miss' }, { provider: 'reg-miss', authMode: 'API_KEY' });
  fs.rmSync(REGISTRY);
  const reg = store.readRegistry();
  assert.ok(reg['reg-miss'], 'entry rebuilt from the surviving token file');
  assert.equal(reg._meta.reason, 'registry_missing');
  store.deleteToken('reg-miss');
  resetRegistryFile();
});

test('corrupt registry: valid JSON of the wrong shape (array) is treated as corrupt', () => {
  store.saveApiKey('reg-shape', { apiKey: 'FAKE-shape' }, { provider: 'reg-shape', authMode: 'API_KEY' });
  fs.writeFileSync(REGISTRY, '[1,2,3]');
  const reg = store.readRegistry();
  assert.ok(reg['reg-shape'], 'rebuilt');
  assert.equal(reg._meta.reason, 'registry_corrupt');
  store.deleteToken('reg-shape');
  resetRegistryFile();
});

test('corrupt registry: empty object while tokens exist (the legacy wipe end-state) is rebuilt', () => {
  store.saveApiKey('reg-wiped', { apiKey: 'FAKE-wiped' }, { provider: 'reg-wiped', authMode: 'API_KEY' });
  fs.writeFileSync(REGISTRY, '{}');
  const reg = store.readRegistry();
  assert.ok(reg['reg-wiped'], 'orphaned token resurfaces instead of looking disconnected forever');
  assert.equal(reg._meta.reason, 'registry_empty_with_tokens');
  store.deleteToken('reg-wiped');
  resetRegistryFile();
});

test('corrupt registry: rebuild quarantines undecryptable token files and recovers the rest', () => {
  store.saveApiKey('reg-ok', { apiKey: 'FAKE-ok' }, { provider: 'reg-ok', authMode: 'API_KEY' });
  store.saveApiKey('reg-bad', { apiKey: 'FAKE-bad' }, { provider: 'reg-bad', authMode: 'API_KEY' });
  fs.writeFileSync(path.join(TOKENS_DIR, 'reg-bad.json'), 'garbage-not-json');
  fs.writeFileSync(REGISTRY, 'BROKEN');
  const reg = store.readRegistry();
  assert.equal(reg['reg-ok'].status, 'connected');
  assert.equal(reg['reg-bad'].status, 'needs_reauth');
  assert.equal(reg['reg-bad'].error, 'token_file_corrupt');
  assert.ok(corruptTokens().some((n) => n.startsWith('reg-bad.json.corrupt-')), 'bad token quarantined during rebuild');
  assert.equal(reg._meta.recovered, 1);
  assert.equal(reg._meta.unreadable, 1);
  store.deleteToken('reg-ok');
  store.deleteToken('reg-bad');
  resetRegistryFile();
});

test('corrupt registry: hostile token filename is skipped, never becomes a registry entry', () => {
  store.saveApiKey('reg-host', { apiKey: 'FAKE-host' }, { provider: 'reg-host', authMode: 'API_KEY' });
  const hostile = path.join(TOKENS_DIR, '-evil__x.json'); // derives provider '-evil', which fails the charset guard
  fs.writeFileSync(hostile, '{}');
  fs.writeFileSync(REGISTRY, 'BROKEN');
  const reg = store.readRegistry();
  assert.ok(reg['reg-host'], 'legit entry recovered');
  assert.equal(reg['-evil:x'], undefined, 'hostile name does not become an entry');
  assert.ok(fs.existsSync(hostile), 'hostile file left untouched for inspection');
  fs.rmSync(hostile);
  store.deleteToken('reg-host');
  resetRegistryFile();
});

test('ids: path-traversal connection ids are rejected before they reach the filesystem', () => {
  assert.throws(() => store.parseConnectionId('../etc'), /Invalid provider/);
  assert.throws(() => store.saveApiKey('../escape', { apiKey: 'FAKE-x' }), /Invalid provider/);
  assert.throws(() => store.parseConnectionId('a/b'), /Invalid provider/);
  // normal ids still fine
  assert.equal(store.parseConnectionId('google:work').connId, 'google:work');
  assert.equal(store.parseConnectionId('7shifts').provider, '7shifts');
});

// ---- key loss (fix: never silently mint a new key over existing tokens) -------

const KEY_FILE = path.join(CRED_DIR, '.dex-cm.key');

test('key loss: reads surface an explicit state, never a silent new key or quarantine', () => {
  store.saveApiKey('kl-a', { apiKey: 'FAKE-kl-a' }, { provider: 'kl-a', authMode: 'API_KEY' });
  store.saveApiKey('kl-b', { apiKey: 'FAKE-kl-b' }, { provider: 'kl-b', authMode: 'API_KEY' });
  assert.ok(fs.existsSync(KEY_FILE), 'file-based key exists (keychain disabled in this suite)');
  const originalKey = fs.readFileSync(KEY_FILE, 'utf8');
  fs.rmSync(KEY_FILE);

  // A fresh process (empty key cache) tries to read a token.
  let code = 0;
  let stderr = '';
  try {
    execFileSync('node', [CHILD, 'load-token', 'kl-a'], { env: childEnv, stdio: 'pipe' });
  } catch (err) {
    code = err.status;
    stderr = err.stderr.toString();
  }
  assert.equal(code, 9, 'load throws the explicit DEX_CM_KEY_LOST state');
  assert.match(stderr, /encryption key is missing/, 'the message says what happened');
  assert.match(stderr, /reconnect/i, 'and what to do about it');

  assert.ok(!fs.existsSync(KEY_FILE), 'no replacement key was minted by a read');
  assert.ok(fs.existsSync(path.join(TOKENS_DIR, 'kl-a.json')), 'token file untouched (key loss is not file corruption)');
  assert.equal(fs.readdirSync(TOKENS_DIR).filter((n) => n.includes('kl-a') && n.includes('.corrupt-')).length, 0, 'nothing quarantined');

  // The health sweep keeps working and flags every connection with the reason.
  const rows = JSON.parse(execFileSync('node', [CHILD, 'health-sweep'], { env: childEnv }).toString());
  const a = rows.find((r) => r.service === 'kl-a');
  const b = rows.find((r) => r.service === 'kl-b');
  assert.equal(a.status, 'needs_reauth');
  assert.equal(a.error, 'encryption_key_lost');
  assert.equal(b.status, 'needs_reauth');
  assert.equal(b.error, 'encryption_key_lost');
  assert.ok(!fs.existsSync(KEY_FILE), 'the sweep did not mint a key either');

  // Nothing was persisted: when the key comes back (e.g. keychain blip ends),
  // everything self-heals with zero residue.
  fs.writeFileSync(KEY_FILE, originalKey, { mode: 0o600 });
  const rows2 = JSON.parse(execFileSync('node', [CHILD, 'health-sweep'], { env: childEnv }).toString());
  assert.equal(rows2.find((r) => r.service === 'kl-a').status, 'connected', 'key restored: state fully self-heals');
  assert.equal(rows2.find((r) => r.service === 'kl-b').status, 'connected');
});

test('key loss: reconnecting recovers explicitly and loudly (old tokens preserved, others flagged)', () => {
  // kl-a / kl-b still exist from the previous test; lose the key for real now.
  const originalKey = fs.readFileSync(KEY_FILE, 'utf8');
  fs.rmSync(KEY_FILE);

  // The user reconnects a tool in a fresh process: this is the ONE sanctioned
  // path that mints a new key, and it must say so and preserve the old tokens.
  const res = execFileSync('node', [CHILD, 'save-key', 'kl-new', 'FAKE-kl-new'], { env: childEnv, stdio: 'pipe' }).toString();
  assert.equal(res, 'saved');

  assert.ok(fs.existsSync(KEY_FILE), 'a fresh key now exists');
  assert.notEqual(fs.readFileSync(KEY_FILE, 'utf8'), originalKey, 'and it is a new key, not the lost one');
  const keyloss = fs.readdirSync(TOKENS_DIR).filter((n) => n.includes('.keyloss-'));
  assert.ok(keyloss.some((n) => n.startsWith('kl-a.json.keyloss-')), 'old token preserved as *.keyloss-*');
  assert.ok(keyloss.some((n) => n.startsWith('kl-b.json.keyloss-')), 'old token preserved as *.keyloss-*');

  const reg = store.readRegistry();
  assert.equal(reg['kl-a'].status, 'needs_reauth');
  assert.equal(reg['kl-a'].error, 'encryption_key_lost');
  assert.equal(reg['kl-b'].error, 'encryption_key_lost');
  assert.equal(reg['kl-new'].status, 'connected', 'the reconnected tool is healthy under the new key');

  // The new connection round-trips in another fresh process.
  const tok = JSON.parse(execFileSync('node', [CHILD, 'load-token', 'kl-new'], { env: childEnv }).toString());
  assert.equal(tok.apiKey, 'FAKE-kl-new');

  // status explains the situation to the user.
  const status = execFileSync('node', [path.join(DIR, 'connect.cjs'), 'status'], { env: childEnv }).toString();
  assert.match(status, /encryption key is missing or unreadable/);
  assert.match(status, /Reconnect each tool/);

  // Cleanup. deleteToken never decrypts, so the parent's stale in-process key
  // cache is irrelevant here; restore key-file/cache parity for later tests.
  store.deleteToken('kl-new');
  store.deleteToken('kl-a');
  store.deleteToken('kl-b');
  fs.writeFileSync(KEY_FILE, originalKey, { mode: 0o600 });
  resetRegistryFile();
});

test('corrupt registry: status CLI surfaces the rebuilt warning to the user', () => {
  store.saveApiKey('reg-warn', { apiKey: 'FAKE-warn' }, { provider: 'reg-warn', authMode: 'API_KEY' });
  fs.writeFileSync(REGISTRY, 'BROKEN');
  const out = execFileSync('node', [path.join(DIR, 'connect.cjs'), 'status'], { env: childEnv }).toString();
  assert.match(out, /connection list was damaged/, 'the warning is visible, not buried');
  assert.match(out, /rebuilt from your saved tokens/);
  assert.match(out, /reg-warn/, 'the recovered connection is listed');
  store.deleteToken('reg-warn');
  resetRegistryFile();
});

// ---- secrets in logs (fix: no token material in any diagnostic output) -------

test('logs: secretsOf + redactSecrets strip header, query, scheme and key-in-URL secrets', () => {
  const ctx = {
    kind: 'api_key',
    baseUrl: 'https://api.telegram.org/botFAKE-URL-KEY-123',
    headers: { authorization: 'Bearer FAKE-BEARER-456', 'x-api-key': 'FAKE-HEADER-789' },
    query: { api_key: 'FAKE-QUERY-321' },
    apiKey: 'FAKE-URL-KEY-123',
  };
  const secrets = authctx.secretsOf(ctx);
  assert.ok(secrets.includes('FAKE-URL-KEY-123'), 'raw apiKey collected');
  assert.ok(secrets.includes('FAKE-BEARER-456'), 'bearer token collected without the scheme');
  const line = `200 OK GET https://api.telegram.org/botFAKE-URL-KEY-123/getMe?api_key=FAKE-QUERY-321 auth=Bearer FAKE-BEARER-456 x=FAKE-HEADER-789`;
  const red = authctx.redactSecrets(line, secrets);
  for (const s of ['FAKE-URL-KEY-123', 'FAKE-BEARER-456', 'FAKE-HEADER-789', 'FAKE-QUERY-321']) {
    assert.ok(!red.includes(s), `redacted line must not contain ${s}: ${red}`);
  }
  assert.match(red, /getMe/, 'non-secret parts of the URL survive for debugging');
});

test('logs: refresh prints no token material, not even a prefix', () => {
  store.saveToken(
    'noleak-oauth',
    { access_token: 'FAKE-AT-MUSTNOTPRINT-9876543210', refresh_token: 'FAKE-RT-MUSTNOTPRINT', expires_at: Date.now() + 3600_000 },
    { provider: 'google' }
  );
  const out = execFileSync('node', [path.join(DIR, 'connect.cjs'), 'refresh', 'noleak-oauth'], { env: childEnv }).toString();
  assert.match(out, /token valid/, 'the command still confirms success');
  assert.ok(!out.includes('FAKE-AT'), 'no access-token material in output');
  assert.ok(!out.includes('FAKE-AT-MUSTNOTPRINT-9876543210'.slice(0, 10)), 'not even the old 10-char prefix');
  assert.ok(!out.includes('FAKE-RT'), 'no refresh-token material in output');
  store.deleteToken('noleak-oauth');
});

test('logs: a full offline flow never echoes fixture secrets (get-token contract calls excluded)', () => {
  const SECRET = 'FAKE-FLOW-SECRET-123xyz';
  const OAUTH_AT = 'FAKE-FLOW-AT-abcdef';
  const OAUTH_RT = 'FAKE-FLOW-RT-ghijkl';
  const keyProv = (catalog.listKeyProviders().find((p) => p.authMode === 'API_KEY' && catalog.requiredConnectionConfig(p.id).length === 0) || {}).id;
  assert.ok(keyProv, 'catalog provides a single-key provider');

  const captured = [];
  const run = (cmd, cmdArgs, input) => {
    const r = require('node:child_process').spawnSync('node', [path.join(DIR, cmd), ...cmdArgs], {
      env: childEnv,
      input,
      encoding: 'utf8',
    });
    captured.push(r.stdout || '', r.stderr || '');
    return r;
  };

  run('connect.cjs', ['set-key', keyProv, '--no-probe'], `${SECRET}\n`); // paste a key (stdin)
  store.saveToken('flow-oauth', { access_token: OAUTH_AT, refresh_token: OAUTH_RT, expires_at: Date.now() + 3600_000 }, { provider: 'google' });
  run('connect.cjs', ['status']); // sweep over both
  run('connect.cjs', ['refresh', 'flow-oauth']); // refresh path
  run('get-token.cjs', ['never-was-connected']); // error path (exit 2)
  fs.writeFileSync(path.join(TOKENS_DIR, 'flow-oauth.json'), '{"v":1,"iv":"x"'); // corrupt it
  run('connect.cjs', ['status']); // sweep over the corruption
  run('get-token.cjs', ['flow-oauth']); // corrupt-credential error path (exit 3)

  const all = captured.join('\n');
  for (const s of [SECRET, OAUTH_AT, OAUTH_RT]) {
    assert.ok(!all.includes(s), `no command output may contain the fixture secret ${s}`);
  }
  assert.match(all, /token_file_corrupt/, 'sanity: the flow did exercise the corruption path');

  store.deleteToken(keyProv);
  store.deleteToken('flow-oauth');
  resetRegistryFile();
});
