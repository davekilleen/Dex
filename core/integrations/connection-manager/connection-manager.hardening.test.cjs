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
