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
