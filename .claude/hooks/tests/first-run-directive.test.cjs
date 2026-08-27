const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK_PATH = path.resolve(__dirname, '..', 'session-start.sh');

function createSandbox(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-first-run-'));
  const vault = path.join(root, 'vault');
  const home = path.join(root, 'home');
  const launchAgents = path.join(root, 'LaunchAgents');
  const dedupFile = path.join(root, 'session-context-dedup');
  fs.mkdirSync(vault, { recursive: true });
  fs.mkdirSync(home, { recursive: true });
  fs.mkdirSync(launchAgents, { recursive: true });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { vault, home, launchAgents, dedupFile };
}

function runSessionStart(sandbox, { timeoutMs = 10_000 } = {}) {
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
      DEX_SESSION_ANALYTICS_CALLS: sandbox.analyticsCalls
        || path.join(path.dirname(sandbox.vault), 'unused-session-analytics-calls'),
      DEX_SESSION_ANALYTICS_RESULT: sandbox.analyticsResult || '',
      DEX_SESSION_ANALYTICS_FINISHED: sandbox.analyticsFinished
        || path.join(path.dirname(sandbox.vault), 'unused-session-analytics-finished'),
      DEX_SESSION_HEALTH_CALLS: path.join(
        path.dirname(sandbox.vault),
        'unused-session-health-calls',
      ),
    },
    timeout: timeoutMs,
  });

  assert.equal(
    result.status,
    0,
    `session-start.sh exited ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
  );
  return result.stdout;
}

function completeOnboarding(sandbox) {
  const marker = path.join(sandbox.vault, 'System', '.onboarding-complete');
  fs.mkdirSync(path.dirname(marker), { recursive: true });
  fs.writeFileSync(marker, '{}\n');
}

function installAnalyticsProbe(sandbox) {
  const helper = path.join(sandbox.vault, 'core', 'mcp', 'analytics_helper.py');
  sandbox.analyticsCalls = path.join(path.dirname(sandbox.vault), 'session-analytics-calls');
  fs.mkdirSync(path.dirname(helper), { recursive: true });
  fs.writeFileSync(
    helper,
    [
      'import os',
      'import sys',
      'from pathlib import Path',
      'Path(os.environ["DEX_SESSION_ANALYTICS_CALLS"]).write_text(" ".join(sys.argv[1:]) + "\\n", encoding="utf-8")',
      'result = os.environ.get("DEX_SESSION_ANALYTICS_RESULT", "")',
      'if result:',
      '    print(result)',
      '',
    ].join('\n'),
  );
}

function installHangingAnalyticsProbe(sandbox) {
  const helper = path.join(sandbox.vault, 'core', 'mcp', 'analytics_helper.py');
  sandbox.analyticsFinished = path.join(path.dirname(sandbox.vault), 'session-analytics-finished');
  fs.mkdirSync(path.dirname(helper), { recursive: true });
  fs.writeFileSync(
    helper,
    [
      'import os',
      'import time',
      'from pathlib import Path',
      'print("private relay token")',
      'time.sleep(4)',
      'Path(os.environ["DEX_SESSION_ANALYTICS_FINISHED"]).write_text("finished\\n", encoding="utf-8")',
      '',
    ].join('\n'),
  );
}

async function waitForFile(filePath, timeoutMs = 500) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (fs.existsSync(filePath)) return true;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  return fs.existsSync(filePath);
}

test('a never-onboarded vault begins canonical onboarding on its first session', (t) => {
  const sandbox = createSandbox(t);

  const stdout = runSessionStart(sandbox);

  assert.match(stdout, /FIRST-TIME SETUP REQUIRED/);
  assert.match(stdout, /begin onboarding NOW/);
  assert.match(stdout, /start_onboarding_session\(\)/);
  assert.match(stdout, /\.claude\/flows\/onboarding\.md/);
  assert.doesNotMatch(stdout, /resume setup NOW/);
});

test('a practice lab folder points at /setup-lab instead of the shipped form', (t) => {
  const sandbox = createSandbox(t);
  const marker = path.join(sandbox.vault, 'System', '.onboarding-lab');
  fs.mkdirSync(path.dirname(marker), { recursive: true });
  fs.writeFileSync(marker, '{"lab": true}\n');

  const stdout = runSessionStart(sandbox);

  assert.match(stdout, /Wait for \/setup-lab/);
  assert.match(stdout, /first words she hears are a hello/);
  assert.match(stdout, /three weeks of meetings/);
  assert.match(stdout, /Do not follow \.claude\/flows\/onboarding\.md/);
  assert.doesNotMatch(stdout, /FIRST-TIME SETUP REQUIRED/);
  assert.doesNotMatch(stdout, /begin onboarding NOW/);
  assert.doesNotMatch(stdout, /follow the flow in \.claude\/flows\/onboarding\.md/);
});

test('an interrupted onboarding resumes through the canonical flow', (t) => {
  const sandbox = createSandbox(t);
  const sessionFile = path.join(
    sandbox.vault,
    'System',
    '.onboarding-session.json',
  );
  fs.mkdirSync(path.dirname(sessionFile), { recursive: true });
  fs.writeFileSync(sessionFile, JSON.stringify({ current_step: 3 }));

  const stdout = runSessionStart(sandbox);

  assert.match(stdout, /FIRST-TIME SETUP REQUIRED/);
  assert.match(stdout, /resume setup NOW/);
  assert.match(stdout, /restores their progress/);
});

test('an onboarded vault emits no first-time setup directive', (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);

  const stdout = runSessionStart(sandbox);

  assert.doesNotMatch(stdout, /FIRST-TIME SETUP REQUIRED/);
  assert.doesNotMatch(stdout, /begin onboarding NOW/);
  assert.doesNotMatch(stdout, /resume setup NOW/);
});

test('a completed vault starts the named session event with a bounded request once', async (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);
  installAnalyticsProbe(sandbox);

  runSessionStart(sandbox);

  assert.equal(await waitForFile(sandbox.analyticsCalls), true);
  assert.equal(
    fs.readFileSync(sandbox.analyticsCalls, 'utf8'),
    '--event session_started --request-timeout-seconds 2\n',
  );
});

test('a completed vault visibly reports a safe receipt-write failure', (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);
  sandbox.analyticsResult = JSON.stringify({
    receipt_written: false,
    receipt_reason: 'receipt_write_failed',
  });
  installAnalyticsProbe(sandbox);

  const stdout = runSessionStart(sandbox);

  assert.match(stdout, /Dex could not save the local analytics receipt/);
  assert.match(stdout, /No usage event was retried/);
  assert.doesNotMatch(stdout, /private relay token/);
});

test('a hanging analytics helper is killed within the session-start total budget', async (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);
  installHangingAnalyticsProbe(sandbox);

  const startedAt = Date.now();
  const stdout = runSessionStart(sandbox, { timeoutMs: 5_000 });
  const elapsedMs = Date.now() - startedAt;

  assert.ok(elapsedMs < 3_750, `session start took ${elapsedMs}ms`);
  assert.match(stdout, /Dex could not save the local analytics receipt/);
  assert.match(stdout, /No usage event was retried/);
  assert.doesNotMatch(stdout, /private relay token/);
  await new Promise((resolve) => setTimeout(resolve, 1_250));
  assert.equal(fs.existsSync(sandbox.analyticsFinished), false);
  assert.equal(
    fs.existsSync(path.join(sandbox.vault, 'System', '.dex', 'analytics-attempts.jsonl')),
    false,
  );
});

test('a never-onboarded vault does not start a session event', async (t) => {
  const sandbox = createSandbox(t);
  installAnalyticsProbe(sandbox);

  runSessionStart(sandbox);

  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(fs.existsSync(sandbox.analyticsCalls), false);
});
