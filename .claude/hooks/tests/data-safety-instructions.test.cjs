'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const REPO_ROOT = path.resolve(__dirname, '../../..');
const UPDATE_SKILL_PATH = path.join(REPO_ROOT, '.claude', 'skills', 'dex-update', 'SKILL.md');
const ROLLBACK_SKILL_PATH = path.join(REPO_ROOT, '.claude', 'skills', 'dex-rollback', 'SKILL.md');
const SETTINGS_PATH = path.join(REPO_ROOT, '.claude', 'settings.json');
const SESSION_START_PATH = path.join(REPO_ROOT, '.claude', 'hooks', 'session-start.sh');

function read(relative) {
  return fs.readFileSync(path.join(REPO_ROOT, relative), 'utf8');
}

function allHookCommands(settings) {
  const commands = [];
  for (const groups of Object.values(settings.hooks || {})) {
    for (const group of groups) {
      for (const hook of group.hooks || []) {
        if (typeof hook.command === 'string') commands.push(hook.command);
      }
    }
  }
  return commands;
}

test('SessionStart has no ambient pull and delegates its context to the shipped script', () => {
  const settings = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8'));
  const commands = allHookCommands(settings);

  assert.ok(commands.includes('bash .claude/hooks/session-start.sh'));
  assert.equal(commands.some((command) => /\bgit\s+pull\b/.test(command)), false);
});

test('the update skill is a thin updater/migrator orchestration with explicit recovery', () => {
  const skill = fs.readFileSync(UPDATE_SKILL_PATH, 'utf8');

  assert.match(skill, /apply-update\.cjs --check/);
  assert.match(skill, /apply-update\.cjs --apply/);
  assert.match(skill, /BREAKING/);
  assert.match(skill, /confirm/i);
  assert.match(skill, /v1-to-v2-brain-vault-split\.cjs/);
  assert.match(skill, /DEX_DEPENDENCIES/);
  assert.match(skill, /npm install/);
  assert.match(skill, /pip|requirements\.txt/);
  assert.match(skill, /doctor\.py/);
  assert.match(skill, /smoke\.py/);
  assert.match(skill, /System\/migration-report-v2\.md/);
  assert.match(skill, /System\/\.dex\/update-report\.md/);
  assert.doesNotMatch(skill, /System\/update-report\.md/);
  assert.match(skill, /--resume.*--restore.*--rollback/is);
  assert.match(skill, /never raw Git|never use raw Git/i);
  assert.match(skill, /ZIP/i);
  assert.match(skill, /convert|conversion/i);
  assert.match(skill, /manual update/i);
  assert.doesNotMatch(skill, /git (?:pull|merge|reset --hard|clean)/);
});

test('the rollback skill routes each topology to the owning recovery script', () => {
  const skill = fs.readFileSync(ROLLBACK_SKILL_PATH, 'utf8');

  assert.match(skill, /System\/\.dex\/topology\.json/);
  assert.match(skill, /apply-update\.cjs --rollback/);
  assert.match(skill, /v1-to-v2-brain-vault-split\.cjs --restore/);
  assert.match(skill, /one release cycle/i);
  assert.match(skill, /confirm/i);
  assert.match(skill, /plain English|plain-English/i);
  assert.match(skill, /System\/\.dex\/update-report\.md/);
  assert.match(skill, /never raw Git|never use raw Git/i);
  assert.doesNotMatch(skill, /git (?:pull|merge|reset --hard|clean)/);
});

test('session-start emits migration-pending additionalContext only for a pre-split v2 vault', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-session-migration-pending-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, '.git'));
  fs.mkdirSync(path.join(root, 'core', 'update'), { recursive: true });
  fs.writeFileSync(path.join(root, 'core', 'update', 'apply-update.cjs'), '// v2 updater\n');

  const run = (dedup) => spawnSync('/bin/bash', [SESSION_START_PATH], {
    cwd: root,
    encoding: 'utf8',
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: root,
      DEX_SESSION_CONTEXT_DEDUP_FILE: path.join(root, dedup),
      HOME: path.join(root, 'home'),
    },
  });
  const pending = run('.dedup-pending');
  assert.equal(pending.status, 0, pending.stderr);
  assert.match(pending.stdout, /^Dex needs a one-time upgrade — run \/dex-update$/m);
  assert.doesNotMatch(pending.stdout, /hookSpecificOutput|additionalContext/);

  fs.writeFileSync(path.join(root, '.git', 'dex-vault-v2'), '{"role":"vault"}\n');
  const split = run('.dedup-split');
  assert.equal(split.status, 0, split.stderr);
  assert.doesNotMatch(split.stdout, /Dex needs a one-time upgrade/);
});

test('the session-start implementation performs only a cheap sentinel check for migration pending', () => {
  const source = read('.claude/hooks/session-start.sh');
  assert.match(source, /core\/update\/apply-update\.cjs/);
  assert.match(source, /dex-vault-v2/);
  assert.doesNotMatch(source, /hookSpecificOutput|additionalContext/);
  assert.doesNotMatch(source, /\bgit\s+pull\b/);
});
