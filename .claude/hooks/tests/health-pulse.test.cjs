const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK_PATH = path.resolve(__dirname, '..', 'health-pulse.sh');

function createSandbox(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-health-pulse-'));
  const vault = path.join(root, 'vault');
  fs.mkdirSync(path.join(vault, 'System', '.dex', 'health', 'snapshots'), { recursive: true });
  t.after(() => {
    fs.rmSync(root, { recursive: true, force: true });
  });
  return { root, vault, dedupFile: path.join(root, 'pulse-dedup') };
}

function completeOnboarding(sandbox) {
  fs.writeFileSync(path.join(sandbox.vault, 'System', '.onboarding-complete'), '{}\n');
}

function writeSnapshotState(sandbox, { publishedAt, status }) {
  const snapshotId = 'snap-0001';
  fs.writeFileSync(
    path.join(sandbox.vault, 'System', '.dex', 'health', 'latest.json'),
    `${JSON.stringify({
      contract: 'dex.health.latest/v1',
      snapshot_id: snapshotId,
      path: `System/.dex/health/snapshots/${snapshotId}.json`,
      published_at: publishedAt,
    })}\n`,
  );
  fs.writeFileSync(
    path.join(sandbox.vault, 'System', '.dex', 'health', 'snapshots', `${snapshotId}.json`),
    `${JSON.stringify({ snapshot_id: snapshotId, overall_status: status })}\n`,
  );
}

function runPulse(sandbox) {
  const result = spawnSync('/bin/bash', [HOOK_PATH], {
    cwd: sandbox.vault,
    encoding: 'utf-8',
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: sandbox.vault,
      DEX_HEALTH_PULSE_DEDUP_FILE: sandbox.dedupFile,
      PATH: process.env.PATH || '/usr/bin:/bin',
    },
    timeout: 10_000,
  });
  assert.equal(result.status, 0, `health-pulse.sh exited ${result.status}\nstderr:\n${result.stderr}`);
  return result.stdout;
}

function isoHoursAgo(hours) {
  return new Date(Date.now() - hours * 60 * 60 * 1000).toISOString();
}

test('pulse is silent before onboarding and before the first snapshot', (t) => {
  const sandbox = createSandbox(t);
  assert.equal(runPulse(sandbox), '');

  completeOnboarding(sandbox);
  assert.equal(runPulse(sandbox), '');
});

test('pulse is silent for a fresh healthy snapshot', (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);
  writeSnapshotState(sandbox, { publishedAt: isoHoursAgo(1), status: 'healthy' });

  assert.equal(runPulse(sandbox), '');
});

test('pulse warns once per day when the snapshot is stale', (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);
  writeSnapshotState(sandbox, { publishedAt: isoHoursAgo(72), status: 'healthy' });

  const first = runPulse(sandbox);
  assert.match(first, /health checks haven't completed in 3 day\(s\)/);
  assert.match(first, /run \/dex-doctor/i);

  assert.equal(runPulse(sandbox), '', 'second pulse the same day must stay silent');
});

test('pulse surfaces a critical snapshot once per snapshot', (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);
  writeSnapshotState(sandbox, { publishedAt: isoHoursAgo(2), status: 'critical' });

  const first = runPulse(sandbox);
  assert.match(first, /self-check found a problem/);

  assert.equal(runPulse(sandbox), '', 'the same critical snapshot must not repeat');
});

test('pulse never fails on malformed health state', (t) => {
  const sandbox = createSandbox(t);
  completeOnboarding(sandbox);
  fs.writeFileSync(
    path.join(sandbox.vault, 'System', '.dex', 'health', 'latest.json'),
    'not json at all\n',
  );

  assert.equal(runPulse(sandbox), '');
});
