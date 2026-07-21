const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK_PATH = path.resolve(__dirname, '..', 'session-start.sh');
const MEETING_INTEL_PLIST = 'com.dex.meeting-intel.plist';
const MEETING_INTEL_LOG = '.scripts/logs/meeting-intel.log';

function createSandbox(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-session-staleness-'));
  const vault = path.join(root, 'vault');
  const home = path.join(root, 'home');
  const launchAgents = path.join(root, 'LaunchAgents');
  const dedupFile = path.join(root, 'session-context-dedup');
  fs.mkdirSync(vault, { recursive: true });
  fs.mkdirSync(home, { recursive: true });
  fs.mkdirSync(launchAgents, { recursive: true });
  t.after(() => {
    fs.rmSync(root, { recursive: true, force: true });
  });
  return { vault, home, launchAgents, dedupFile };
}

function installMeetingIntel(sandbox) {
  fs.writeFileSync(path.join(sandbox.launchAgents, MEETING_INTEL_PLIST), '<plist/>\n');
}

function writeMeetingIntelLog(sandbox) {
  const logPath = path.join(sandbox.vault, MEETING_INTEL_LOG);
  fs.mkdirSync(path.dirname(logPath), { recursive: true });
  fs.writeFileSync(logPath, 'meeting sync ran\n');
  return logPath;
}

function completeOnboarding(sandbox) {
  const marker = path.join(sandbox.vault, 'System', '.onboarding-complete');
  fs.mkdirSync(path.dirname(marker), { recursive: true });
  fs.writeFileSync(marker, '{}\n');
}

function installMovedVaultConflict(sandbox, plistName) {
  const oldVault = path.join(path.dirname(sandbox.vault), 'old-vault');
  const breadcrumb = path.join(sandbox.home, '.config', 'dex', 'vault-path');
  const launchAgents = path.join(sandbox.home, 'Library', 'LaunchAgents');
  const plist = path.join(launchAgents, plistName);
  fs.mkdirSync(path.dirname(breadcrumb), { recursive: true });
  fs.mkdirSync(launchAgents, { recursive: true });
  fs.writeFileSync(breadcrumb, `${oldVault}\n`);
  fs.writeFileSync(
    plist,
    `<plist><string>${oldVault}/.scripts/dex-launcher.sh</string></plist>\n`,
  );
  return { oldVault, breadcrumb, plist, plistBytes: fs.readFileSync(plist) };
}

function writeSmokeResult(sandbox, broken) {
  const resultPath = path.join(sandbox.vault, 'System', '.smoke-last-run.json');
  fs.mkdirSync(path.dirname(resultPath), { recursive: true });
  fs.writeFileSync(
    resultPath,
    JSON.stringify({
      schema_version: 1,
      generated_at: '2026-07-12T03:15:00+00:00',
      journeys: [
        {
          id: 'task_lifecycle',
          verdict: broken ? 'BROKEN' : 'OK',
          detail: broken ? 'task creation failed after the config changed' : 'task lifecycle passed',
          duration_ms: 10,
        },
      ],
      summary: { ok: broken ? 0 : 1, off: 0, broken: broken ? 1 : 0, unknown: 0 },
    }),
  );
}

function runSessionStart(sandbox) {
  const result = spawnSync('/bin/bash', [HOOK_PATH], {
    cwd: sandbox.vault,
    encoding: 'utf-8',
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: sandbox.vault,
      DEX_LAUNCH_AGENTS_DIR: sandbox.launchAgents,
      DEX_SESSION_CONTEXT_DEDUP_FILE: sandbox.dedupFile,
      HOME: sandbox.home,
      PATH: process.env.PATH || '/usr/bin:/bin',
      VAULT_PATH: sandbox.vault,
    },
    timeout: 10_000,
  });

  assert.equal(
    result.status,
    0,
    `session-start.sh exited ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
  );
  assert.equal(result.stderr, '', `session-start.sh wrote to stderr:\n${result.stderr}`);
  assert.ok(fs.existsSync(sandbox.dedupFile), 'session-start.sh must use the sandbox dedup file');
  return result.stdout;
}

test('session start warns when an installed meeting sync log is stale', (t) => {
  const sandbox = createSandbox(t);
  installMeetingIntel(sandbox);
  const logPath = writeMeetingIntelLog(sandbox);
  const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000);
  fs.utimesSync(logPath, threeDaysAgo, threeDaysAgo);

  const stdout = runSessionStart(sandbox);

  assert.match(
    stdout,
    /⏰ Meeting sync last ran 3 days ago \(expected every 2 days\) — run \/dex-doctor to investigate\./,
  );
});

test('session start stays silent for a fresh installed meeting sync log', (t) => {
  const sandbox = createSandbox(t);
  installMeetingIntel(sandbox);
  writeMeetingIntelLog(sandbox);

  const stdout = runSessionStart(sandbox);

  assert.doesNotMatch(stdout, /⏰ Meeting sync/);
});

test('session start ignores stale logs for launch agents that are not installed', (t) => {
  const sandbox = createSandbox(t);
  const logPath = writeMeetingIntelLog(sandbox);
  const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000);
  fs.utimesSync(logPath, threeDaysAgo, threeDaysAgo);

  const stdout = runSessionStart(sandbox);

  assert.doesNotMatch(stdout, /⏰ Meeting sync/);
});

test('session start warns when an installed meeting sync has never run', (t) => {
  const sandbox = createSandbox(t);
  installMeetingIntel(sandbox);

  const stdout = runSessionStart(sandbox);

  assert.match(
    stdout,
    /⏰ Meeting sync is installed but has never run — run \/dex-doctor to investigate\./,
  );
});

test('overnight smoke block is silent when the result file is missing', (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);

  const stdout = runSessionStart(sandbox);

  assert.doesNotMatch(stdout, /Overnight check found a problem/);
});

test('overnight smoke block is silent for a healthy result', (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);
  writeSmokeResult(sandbox, false);

  const stdout = runSessionStart(sandbox);

  assert.doesNotMatch(stdout, /Overnight check found a problem/);
});

test('overnight smoke block emits broken journey details', (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);
  writeSmokeResult(sandbox, true);

  const stdout = runSessionStart(sandbox);

  assert.match(stdout, /--- 🚨 Overnight check found a problem ---/);
  assert.match(stdout, /task_lifecycle — task creation failed after the config changed/);
  assert.match(stdout, /Run \/dex-doctor for diagnosis and the fix\./);
});

for (const plistName of ['com.dex.meeting-intel.plist', 'com.claudesidian.learning.plist']) {
  test(`session start reports but never changes moved-vault conflict in ${plistName}`, (t) => {
    const sandbox = createSandbox(t);
    completeOnboarding(sandbox);
    const conflict = installMovedVaultConflict(sandbox, plistName);

    const stdout = runSessionStart(sandbox);

    assert.match(
      stdout,
      /Dex found a background job that still points to this vault's old location — run \/dex-doctor to fix this safely\./,
    );
    assert.deepEqual(fs.readFileSync(conflict.plist), conflict.plistBytes);
    assert.equal(fs.readFileSync(conflict.breadcrumb, 'utf8'), `${conflict.oldVault}\n`);
  });
}

test('session start stays silent when no plist points to the stored former vault', (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);
  const conflict = installMovedVaultConflict(sandbox, 'com.dex.meeting-intel.plist');
  fs.writeFileSync(conflict.plist, '<plist><string>/another/vault</string></plist>\n');

  const stdout = runSessionStart(sandbox);

  assert.doesNotMatch(stdout, /still points to this vault's old location/);
  assert.equal(fs.readFileSync(conflict.breadcrumb, 'utf8'), `${conflict.oldVault}\n`);
});
