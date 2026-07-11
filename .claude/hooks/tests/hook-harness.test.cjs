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
    const command = hookName.endsWith('.sh') ? '/bin/bash' : process.execPath;
    const result = spawnSync(command, [hookPath], {
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
