'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const REPO_ROOT = path.resolve(__dirname, '../../..');
const HOOK_PATH = path.join(REPO_ROOT, '.claude', 'hooks', 'vault-autocommit.cjs');
const CONTRACT_PATH = path.join(
  REPO_ROOT,
  'packages',
  'dex-contracts',
  'dist',
  'portable-vault.contract.json',
);

function git(root, ...args) {
  const result = spawnSync('git', ['-C', root, ...args], { encoding: 'utf8' });
  assert.equal(result.status, 0, `${args.join(' ')}\n${result.stdout}\n${result.stderr}`);
  return result.stdout.trim();
}

function fixture(t, enabled = false) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-vault-autocommit-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  git(root, 'init', '--quiet');
  fs.writeFileSync(path.join(root, '.git', 'dex-vault-v2'), '{"role":"vault"}\n');
  fs.mkdirSync(path.join(root, 'System'), { recursive: true });
  fs.writeFileSync(
    path.join(root, 'System', 'user-profile.yaml'),
    `name: Test User\nvault:\n  auto_commit: ${enabled ? 'true' : 'false'}\n`,
  );
  const contract = path.join(root, 'packages', 'dex-contracts', 'dist');
  fs.mkdirSync(contract, { recursive: true });
  fs.copyFileSync(CONTRACT_PATH, path.join(contract, 'portable-vault.contract.json'));
  return root;
}

test('vault auto-commit is off unless the nested profile switch is exactly true', (t) => {
  const hook = require(HOOK_PATH);
  const root = fixture(t, false);
  fs.writeFileSync(path.join(root, 'note.md'), 'private note\n');

  const result = hook.run({ root, now: new Date('2026-07-13T10:00:00Z') });

  assert.equal(result.feature_status, 'off');
  assert.equal(result.success, false);
  assert.match(result.user_message, /off by default/i);
  assert.equal(git(root, 'for-each-ref', '--format=%(refname)'), '');
  fs.writeFileSync(
    path.join(root, 'System', 'user-profile.yaml'),
    'vault:\n  nested:\n    auto_commit: true\n',
  );
  assert.equal(hook.run({ root }).feature_status, 'off');
});

test('enabled hook commits only contract-owned vault and seed changes locally', (t) => {
  const hook = require(HOOK_PATH);
  const root = fixture(t, true);
  fs.writeFileSync(path.join(root, 'note.md'), 'unclassified stays out\n');
  fs.mkdirSync(path.join(root, '04-Projects'), { recursive: true });
  fs.writeFileSync(path.join(root, '04-Projects', 'private.md'), 'private note\n');
  fs.mkdirSync(path.join(root, '03-Tasks'), { recursive: true });
  fs.writeFileSync(path.join(root, '03-Tasks', 'Tasks.md'), '# edited seed\n');
  fs.mkdirSync(path.join(root, 'core'), { recursive: true });
  fs.writeFileSync(path.join(root, 'core', 'brain.py'), 'BRAIN = true\n');
  fs.mkdirSync(path.join(root, 'System', '.dex'), { recursive: true });
  fs.writeFileSync(path.join(root, 'System', '.dex', 'runtime.json'), '{}\n');

  const result = hook.run({ root, now: new Date('2026-07-13T10:00:00Z') });

  assert.equal(result.feature_status, 'ok');
  assert.equal(result.success, true);
  assert.equal(git(root, 'log', '-1', '--format=%s'), 'Dex vault 2026-07-13');
  assert.equal(git(root, 'show', 'HEAD:04-Projects/private.md'), 'private note');
  assert.equal(git(root, 'show', 'HEAD:03-Tasks/Tasks.md'), '# edited seed');
  for (const relative of ['note.md', 'core/brain.py', 'System/.dex/runtime.json']) {
    assert.equal(git(root, 'ls-tree', '--name-only', 'HEAD', '--', relative), '', relative);
  }
});

test('enabled hook holds back contract-denied paths and staged content secrets', (t) => {
  const hook = require(HOOK_PATH);
  const root = fixture(t, true);
  fs.mkdirSync(path.join(root, '04-Projects'), { recursive: true });
  fs.writeFileSync(path.join(root, '04-Projects', 'safe.md'), 'safe note\n');
  fs.writeFileSync(
    path.join(root, '04-Projects', 'session.md'),
    '{"access_token":"scanner-positive-fixture-value"}\n',
  );
  fs.writeFileSync(path.join(root, '.env'), 'API_KEY=fixture-secret-value\n');
  git(root, 'add', '--', '04-Projects/session.md');

  const result = hook.run({ root, now: new Date('2026-07-13T10:00:00Z') });

  assert.equal(result.feature_status, 'ok');
  assert.match(result.user_message, /held back|protected/i);
  assert.equal(git(root, 'show', 'HEAD:04-Projects/safe.md'), 'safe note');
  for (const relative of ['04-Projects/session.md', '.env']) {
    assert.equal(git(root, 'ls-tree', '--name-only', 'HEAD', '--', relative), '', relative);
  }
  assert.equal(git(root, 'diff', '--cached', '--name-only'), '');
});

test('enabled hook scans NUL-containing buffers for secret content', (t) => {
  const hook = require(HOOK_PATH);
  const root = fixture(t, true);
  fs.mkdirSync(path.join(root, '04-Projects'), { recursive: true });
  fs.writeFileSync(
    path.join(root, '04-Projects', 'binary-note.bin'),
    Buffer.from('safe-prefix\0{"access_token":"scanner-positive-fixture-value"}\n'),
  );

  const result = hook.run({ root, now: new Date('2026-07-13T10:00:00Z') });

  assert.equal(result.feature_status, 'ok');
  assert.match(result.user_message, /held back|protected/i);
  assert.equal(git(root, 'ls-tree', '--name-only', 'HEAD', '--', '04-Projects/binary-note.bin'), '');
  assert.equal(git(root, 'diff', '--cached', '--name-only'), '');
});

test('enabled hook disables commit hooks and never pushes', (t) => {
  const hook = require(HOOK_PATH);
  const root = fixture(t, true);
  const hooks = path.join(root, 'hostile-hooks');
  const marker = path.join(root, 'post-commit-ran');
  fs.mkdirSync(hooks);
  fs.writeFileSync(path.join(hooks, 'post-commit'), `#!/bin/sh\nprintf ran > "${marker}"\n`, {
    mode: 0o755,
  });
  git(root, 'config', 'core.hooksPath', hooks);
  const remote = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-vault-autocommit-remote-'));
  t.after(() => fs.rmSync(remote, { recursive: true, force: true }));
  git(remote, 'init', '--bare', '--quiet');
  git(root, 'remote', 'add', 'backup', remote);
  fs.mkdirSync(path.join(root, '04-Projects'), { recursive: true });
  fs.writeFileSync(path.join(root, '04-Projects', 'local-only.md'), 'never pushed\n');

  const result = hook.run({ root, now: new Date('2026-07-13T10:00:00Z') });

  assert.equal(result.feature_status, 'ok');
  assert.equal(fs.existsSync(marker), false);
  assert.equal(git(remote, 'for-each-ref', '--format=%(refname)'), '');
  assert.doesNotMatch(fs.readFileSync(HOOK_PATH, 'utf8'), /\bgit\s+push\b|['"]push['"]/);
});

test('the shared transaction lock pauses auto-commit and is held while Git runs', (t) => {
  const hook = require(HOOK_PATH);
  const root = fixture(t, true);
  fs.mkdirSync(path.join(root, 'System', '.dex'), { recursive: true });
  const lock = path.join(root, 'System', '.dex', 'mutation.lock');
  fs.writeFileSync(lock, `${JSON.stringify({ pid: process.pid, kind: 'update' })}\n`);
  assert.equal(hook.run({ root }).feature_status, 'off');
  fs.unlinkSync(lock);
  fs.mkdirSync(path.join(root, '04-Projects'), { recursive: true });
  fs.writeFileSync(path.join(root, '04-Projects', 'note.md'), 'serialized snapshot\n');
  let observed = false;

  const result = hook.run({
    root,
    onLockAcquired() {
      observed = true;
      assert.equal(fs.existsSync(lock), true);
      assert.throws(() => fs.openSync(lock, 'wx'), { code: 'EEXIST' });
    },
  });

  assert.equal(result.feature_status, 'ok');
  assert.equal(observed, true);
  assert.equal(fs.existsSync(lock), false);
});

test('settings wires the opt-in hook after session-end and the shipped profile defaults off', () => {
  const settings = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, '.claude', 'settings.json'), 'utf8'));
  const commands = settings.hooks.SessionEnd[0].hooks.map((entry) => entry.command);
  assert.match(commands[0], /session-end\.sh/);
  assert.match(commands[1], /vault-autocommit\.cjs/);
  const profile = fs.readFileSync(path.join(REPO_ROOT, 'System', 'user-profile-template.yaml'), 'utf8');
  assert.match(profile, /^vault:\n  auto_commit: false$/m);
});
