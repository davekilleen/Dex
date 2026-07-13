'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const REPO_ROOT = path.resolve(__dirname, '../../..');
const HOOK_PATH = path.join(REPO_ROOT, '.claude', 'hooks', 'vault-autocommit.cjs');

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
});

test('enabled hook commits all eligible vault changes locally with fallback identity', (t) => {
  const hook = require(HOOK_PATH);
  const root = fixture(t, true);
  fs.writeFileSync(path.join(root, 'note.md'), 'private note\n');

  const result = hook.run({ root, now: new Date('2026-07-13T10:00:00Z') });

  assert.equal(result.feature_status, 'ok');
  assert.equal(result.success, true);
  assert.equal(git(root, 'log', '-1', '--format=%s'), 'Dex vault 2026-07-13');
  assert.equal(git(root, 'show', 'HEAD:note.md'), 'private note');
  assert.equal(git(root, 'config', '--local', '--get', 'user.name'), 'Dex Vault');
  assert.equal(git(root, 'config', '--local', '--get', 'user.email'), 'vault@dex.local');
});

test('enabled hook reports a clean vault without creating an empty commit', (t) => {
  const hook = require(HOOK_PATH);
  const root = fixture(t, true);
  fs.writeFileSync(path.join(root, 'first.md'), 'first\n');
  hook.run({ root, now: new Date('2026-07-13T10:00:00Z') });
  const before = git(root, 'rev-parse', 'HEAD');

  const result = hook.run({ root, now: new Date('2026-07-14T10:00:00Z') });

  assert.equal(result.feature_status, 'ok');
  assert.match(result.user_message, /already saved/i);
  assert.equal(git(root, 'rev-parse', 'HEAD'), before);
});

test('migration lock and in-progress Git operations pause auto-commit', (t) => {
  const hook = require(HOOK_PATH);
  const locked = fixture(t, true);
  fs.mkdirSync(path.join(locked, 'System', '.dex'), { recursive: true });
  fs.writeFileSync(path.join(locked, 'System', '.dex', '.migration-lock'), '{}\n');
  fs.writeFileSync(path.join(locked, 'locked.md'), 'not committed\n');
  const lockResult = hook.run({ root: locked });
  assert.equal(lockResult.feature_status, 'off');
  assert.match(lockResult.user_message, /migration or update is running/i);

  const merging = fixture(t, true);
  fs.writeFileSync(path.join(merging, '.git', 'MERGE_HEAD'), `${'a'.repeat(40)}\n`);
  fs.writeFileSync(path.join(merging, 'merge.md'), 'not committed\n');
  const mergeResult = hook.run({ root: merging });
  assert.equal(mergeResult.feature_status, 'off');
  assert.match(mergeResult.user_message, /Git operation is in progress/i);
});

test('the hook never pushes and CLI failures silently degrade to feature status', (t) => {
  const hook = require(HOOK_PATH);
  const root = fixture(t, true);
  const bare = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-vault-autocommit-remote-'));
  t.after(() => fs.rmSync(bare, { recursive: true, force: true }));
  git(bare, 'init', '--bare', '--quiet');
  git(root, 'remote', 'add', 'backup', bare);
  fs.writeFileSync(path.join(root, 'local-only.md'), 'never pushed\n');
  hook.run({ root, now: new Date('2026-07-13T10:00:00Z') });
  assert.equal(git(bare, 'for-each-ref', '--format=%(refname)'), '');
  assert.doesNotMatch(fs.readFileSync(HOOK_PATH, 'utf8'), /\bgit\s+push\b|['"]push['"]/);

  fs.writeFileSync(path.join(root, '.git', 'HEAD'), 'broken head\n');
  const cli = spawnSync(process.execPath, [HOOK_PATH], {
    cwd: root,
    encoding: 'utf8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: root },
  });
  assert.equal(cli.status, 0);
  assert.equal(cli.stdout, '');
  assert.equal(cli.stderr, '');
  const degraded = hook.run({ root });
  assert.ok(['broken', 'unknown'].includes(degraded.feature_status));
  assert.equal(typeof degraded.user_message, 'string');
});

test('settings wires vault auto-commit after the existing SessionEnd hook and profiles default off', () => {
  const settings = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, '.claude', 'settings.json'), 'utf8'));
  const commands = settings.hooks.SessionEnd[0].hooks.map((entry) => entry.command);
  assert.match(commands[0], /session-end\.sh/);
  assert.match(commands[1], /vault-autocommit\.cjs/);
  for (const relative of [
    'System/user-profile.yaml',
    'System/user-profile.example.yaml',
    'System/user-profile-template.yaml',
  ]) {
    const profile = fs.readFileSync(path.join(REPO_ROOT, relative), 'utf8');
    assert.match(profile, /^vault:\n  auto_commit: false$/m, relative);
  }
  const migrator = fs.readFileSync(
    path.join(REPO_ROOT, 'core', 'migrations', 'v1-to-v2-brain-vault-split.cjs'),
    'utf8',
  );
  assert.match(migrator, /auto-commit is off by default/i);
  assert.match(migrator, /auto_commit: true/);
  assert.match(migrator, /never pushes/i);
});
