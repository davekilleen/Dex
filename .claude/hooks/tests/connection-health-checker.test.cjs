const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../..');
const HOOK_PATH = path.join(ROOT, '.claude', 'hooks', 'connection-health-checker.cjs');
const PATHS_PATH = path.join(ROOT, '.claude', 'hooks', 'paths.cjs');
const SETTINGS_PATH = path.join(ROOT, '.claude', 'settings.json');

function createFixture(t, rows = []) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-connection-health-'));
  const hooksDir = path.join(vault, '.claude', 'hooks');
  const managerDir = path.join(vault, 'core', 'integrations', 'connection-manager');
  fs.mkdirSync(hooksDir, { recursive: true });
  fs.mkdirSync(managerDir, { recursive: true });
  fs.cpSync(HOOK_PATH, path.join(hooksDir, 'connection-health-checker.cjs'));
  fs.cpSync(PATHS_PATH, path.join(hooksDir, 'paths.cjs'));
  fs.writeFileSync(
    path.join(managerDir, 'health.cjs'),
    [
      "'use strict';",
      "const fs = require('node:fs');",
      'module.exports.allConnectionsHealth = () => {',
      '  fs.appendFileSync(process.env.HEALTH_CALLS_FILE, "called\\n");',
      '  if (process.env.HEALTH_THROW === "1") throw new Error("fixture failure");',
      '  return JSON.parse(process.env.HEALTH_ROWS || "[]");',
      '};',
      '',
    ].join('\n'),
  );
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  return {
    vault,
    hookPath: path.join(hooksDir, 'connection-health-checker.cjs'),
    managerDir,
    callsFile: path.join(vault, 'health-calls.txt'),
    rows,
  };
}

function runHook(fixture, env = {}) {
  return spawnSync(process.execPath, [fixture.hookPath], {
    cwd: fixture.vault,
    encoding: 'utf8',
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: fixture.vault,
      DEX_VAULT: fixture.vault,
      HEALTH_CALLS_FILE: fixture.callsFile,
      HEALTH_ROWS: JSON.stringify(fixture.rows),
      ...env,
    },
    timeout: 5_000,
  });
}

function assertCleanExit(result) {
  assert.equal(
    result.status,
    0,
    `hook exited ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
  );
  assert.equal(result.stderr, '');
}

test('SessionStart runs the connection health checker without changing existing hooks', () => {
  const settings = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8'));
  const commands = settings.hooks.SessionStart.flatMap((entry) => entry.hooks || []).map((hook) => hook.command);
  assert.ok(commands.includes('node .claude/hooks/connection-health-checker.cjs'));
  assert.ok(commands.includes('bash .claude/hooks/session-start.sh'));
  assert.ok(commands.includes('python3 "$CLAUDE_PROJECT_DIR/core/utils/update_verifier.py" --vault "$CLAUDE_PROJECT_DIR" --session-start'));
  assert.ok(commands.includes('bash .claude/hooks/dex-core-orientation.sh'));
});

test('stays silent when no connection needs attention', (t) => {
  const fixture = createFixture(t, [
    { service: 'google', status: 'connected' },
    { service: 'slack', status: 'expiring' },
    { service: 'linear', status: 'error' },
  ]);

  const result = runHook(fixture);

  assertCleanExit(result);
  assert.equal(result.stdout, '');
});

test('surfaces a connection that needs reauthentication', (t) => {
  const fixture = createFixture(t, [
    { service: 'google:work', status: 'needs_reauth' },
    { service: 'slack', status: 'expired' },
  ]);

  const result = runHook(fixture);

  assertCleanExit(result);
  assert.match(result.stdout, /google:work — needs re-authentication/);
  assert.match(result.stdout, /Run \/connect google:work to reconnect/);
  assert.match(result.stdout, /slack — expired/);
});

test('runs the local health sweep at most once per day', (t) => {
  const fixture = createFixture(t, [
    { service: 'google', status: 'needs_reauth' },
  ]);

  const first = runHook(fixture);
  const second = runHook(fixture);

  assertCleanExit(first);
  assertCleanExit(second);
  assert.match(first.stdout, /google — needs re-authentication/);
  assert.equal(second.stdout, '');
  assert.equal(fs.readFileSync(fixture.callsFile, 'utf8'), 'called\n');
});

test('a failed local sweep is still throttled for the rest of the day', (t) => {
  const fixture = createFixture(t);

  const first = runHook(fixture, { HEALTH_THROW: '1' });
  const second = runHook(fixture, { HEALTH_THROW: '1' });

  assertCleanExit(first);
  assertCleanExit(second);
  assert.equal(first.stdout, '');
  assert.equal(second.stdout, '');
  assert.equal(fs.readFileSync(fixture.callsFile, 'utf8'), 'called\n');
});

test('exits zero and stays silent when the vault or connection manager is missing', (t) => {
  const noVault = createFixture(t);
  const vaultResult = runHook(noVault, {
    CLAUDE_PROJECT_DIR: '',
    DEX_VAULT: '',
    VAULT_PATH: '',
  });

  assertCleanExit(vaultResult);
  assert.equal(vaultResult.stdout, '');
  assert.equal(fs.existsSync(noVault.callsFile), false);

  const noManager = createFixture(t);
  fs.rmSync(noManager.managerDir, { recursive: true, force: true });
  const managerResult = runHook(noManager);

  assertCleanExit(managerResult);
  assert.equal(managerResult.stdout, '');
  assert.equal(fs.existsSync(noManager.callsFile), false);
});
