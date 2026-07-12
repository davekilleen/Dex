const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOKS_DIR = path.resolve(__dirname, '..');
const FIXTURE_VAULT = path.resolve(__dirname, '../../../core/tests/fixtures/vault');
const HOOK_PROGRAMS = fs.readdirSync(HOOKS_DIR)
  .filter((name) => name.endsWith('.cjs') || name.endsWith('.sh'))
  .sort();
const DIRECT_SHELL_HOOKS = new Set(['session-end.sh']);

assert.ok(HOOK_PROGRAMS.length > 0, 'no root hook programs discovered');

function createSandbox(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-hook-harness-'));
  const vault = path.join(root, 'vault');
  const home = path.join(root, 'home');
  fs.cpSync(FIXTURE_VAULT, vault, { recursive: true });
  fs.mkdirSync(home);
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { vault, home };
}

function minimalEnv(sandbox) {
  return {
    CLAUDE_HOOK_CONTEXT: '{}',
    CLAUDE_PROJECT_DIR: sandbox.vault,
    DEX_HOOK_DEBUG: '1',
    HOME: sandbox.home,
    PATH: '/usr/bin:/bin',
    VAULT_PATH: sandbox.vault,
  };
}

for (const hookName of HOOK_PROGRAMS) {
  test(`benign stdin exits cleanly: ${hookName}`, (t) => {
    const sandbox = createSandbox(t);
    const hookPath = path.join(HOOKS_DIR, hookName);
    const isShellHook = hookName.endsWith('.sh');
    if (isShellHook) {
      assert.notEqual(
        fs.statSync(hookPath).mode & 0o111,
        0,
        `${hookName} must retain an executable mode`,
      );
    }
    const directInvocation = DIRECT_SHELL_HOOKS.has(hookName);
    const command = directInvocation ? hookPath : isShellHook ? '/bin/bash' : process.execPath;
    const args = directInvocation ? [] : [hookPath];
    const result = spawnSync(command, args, {
      cwd: sandbox.vault,
      encoding: 'utf-8',
      env: minimalEnv(sandbox),
      input: '{}\n',
      timeout: 10_000,
    });

    assert.equal(
      result.status,
      0,
      `${hookName} exited ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
    );
  });
}

test('session end runs directly and records its transcript', (t) => {
  const sandbox = createSandbox(t);
  const hookPath = path.join(HOOKS_DIR, 'session-end.sh');
  const transcriptPath = path.join(sandbox.vault, 'session-transcript.jsonl');
  fs.writeFileSync(transcriptPath, '{"type":"test"}\n');

  const result = spawnSync(hookPath, [transcriptPath], {
    cwd: sandbox.vault,
    encoding: 'utf-8',
    env: minimalEnv(sandbox),
    timeout: 10_000,
  });

  assert.equal(
    result.status,
    0,
    `session-end.sh exited ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
  );
  const learningsDir = path.join(sandbox.vault, 'System', 'Session_Learnings');
  const learningFiles = fs.readdirSync(learningsDir).filter((name) => name.endsWith('.md'));
  assert.equal(learningFiles.length, 1);
  const learning = fs.readFileSync(path.join(learningsDir, learningFiles[0]), 'utf-8');
  assert.match(learning, /Session completed/);
  assert.ok(learning.includes(transcriptPath));
});

test('safety guard uses its documented exit 2 contract for blocked commands', (t) => {
  const sandbox = createSandbox(t);
  const result = spawnSync('/bin/bash', [path.join(HOOKS_DIR, 'dex-safety-guard.sh')], {
    cwd: sandbox.vault,
    encoding: 'utf-8',
    env: minimalEnv(sandbox),
    input: JSON.stringify({ tool_name: 'Bash', tool_input: { command: 'rm -rf /' } }),
    timeout: 10_000,
  });

  assert.equal(result.status, 2);
  assert.match(result.stdout, /Blocked/);
});

test('meeting cache builder reads dated folders and skips queue', (t) => {
  const sandbox = createSandbox(t);
  const day = new Date().toISOString().slice(0, 10);
  const meetingsDir = path.join(sandbox.vault, '00-Inbox', 'Meetings');
  const datedDir = path.join(meetingsDir, day);
  const queueDir = path.join(datedDir, 'queue');
  fs.mkdirSync(datedDir, { recursive: true });
  fs.mkdirSync(queueDir, { recursive: true });
  fs.writeFileSync(
    path.join(datedDir, 'customer-sync.md'),
    [
      '---',
      `date: ${day}`,
      'participants: [Jane Doe]',
      '---',
      '# Nested Customer Sync',
      '',
      '## Action Items',
      '',
      '- [x] Close old loop ^task-20260711-061 ✅ 2026-07-10 08:30',
      '- [x] Close new loop ✅ 2026-07-10 08:30 ^task-20260711-062',
      '',
    ].join('\n'),
  );
  fs.writeFileSync(
    path.join(queueDir, 'must-not-cache.md'),
    `---\ndate: ${day}\n---\n# Must Not Cache\n`,
  );

  const hookPath = path.join(HOOKS_DIR, 'meeting-cache-builder.cjs');
  const result = spawnSync(process.execPath, [hookPath, '--rebuild'], {
    cwd: sandbox.vault,
    encoding: 'utf-8',
    env: minimalEnv(sandbox),
    timeout: 10_000,
  });

  assert.equal(
    result.status,
    0,
    `meeting-cache-builder.cjs exited ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
  );
  const cachePath = path.join(sandbox.vault, 'System', 'Memory', 'meeting-cache.json');
  const cache = JSON.parse(fs.readFileSync(cachePath, 'utf-8'));
  assert.deepEqual(cache.meetings.map((meeting) => meeting.title), ['Nested Customer Sync']);
  assert.equal(
    cache.meetings[0].source_file,
    path.join('00-Inbox', 'Meetings', day, 'customer-sync.md'),
  );
  assert.deepEqual(cache.meetings[0].action_items, ['Close old loop', 'Close new loop']);
});
