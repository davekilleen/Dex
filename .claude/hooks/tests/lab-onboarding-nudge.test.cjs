const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('path');

const HOOK_PATH = path.resolve(__dirname, '..', 'lab-onboarding-nudge.cjs');

function createSandbox(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-lab-nudge-'));
  const vault = path.join(root, 'vault');
  fs.mkdirSync(path.join(vault, 'System'), { recursive: true });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { vault };
}

function runHook(sandbox, payload) {
  return spawnSync(process.execPath, [HOOK_PATH], {
    cwd: sandbox.vault,
    encoding: 'utf-8',
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: sandbox.vault,
    },
    input: `${JSON.stringify(payload)}\n`,
    timeout: 5_000,
  });
}

function writeTranscript(sandbox, assistantText) {
  const transcriptPath = path.join(sandbox.vault, 'session.jsonl');
  fs.writeFileSync(
    transcriptPath,
    `${JSON.stringify({
      type: 'assistant',
      message: { content: [{ type: 'text', text: assistantText }] },
    })}\n`,
    'utf8',
  );
  return transcriptPath;
}

test('missing lab marker allows the stop', (t) => {
  const sandbox = createSandbox(t);
  const transcriptPath = writeTranscript(sandbox, '*(one moment)*');
  const result = runHook(sandbox, { transcript_path: transcriptPath });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), '');
});

test('a wait-line stall in a lab folder nudges once', (t) => {
  const sandbox = createSandbox(t);
  fs.writeFileSync(path.join(sandbox.vault, 'System', '.onboarding-lab'), '{"lab":true}\n');
  const transcriptPath = writeTranscript(sandbox, '*(one moment)*');
  const result = runHook(sandbox, { transcript_path: transcriptPath });
  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.decision, 'block');
  assert.match(payload.reason, /Read the calendar yourself/);
  assert.match(payload.reason, /Do not say one moment/);
});

test('a real question for her is not a stall', (t) => {
  const sandbox = createSandbox(t);
  fs.writeFileSync(path.join(sandbox.vault, 'System', '.onboarding-lab'), '{"lab":true}\n');
  const transcriptPath = writeTranscript(
    sandbox,
    "I'm reading the last three weeks now.\n\nWhat's the third?",
  );
  const result = runHook(sandbox, { transcript_path: transcriptPath });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), '');
});

test('an already-nudged stop is not nudged again', (t) => {
  const sandbox = createSandbox(t);
  fs.writeFileSync(path.join(sandbox.vault, 'System', '.onboarding-lab'), '{"lab":true}\n');
  const transcriptPath = writeTranscript(sandbox, '*(nearly there)*');
  const result = runHook(sandbox, {
    transcript_path: transcriptPath,
    stop_hook_active: true,
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), '');
});

test('empty stdin exits cleanly', (t) => {
  const sandbox = createSandbox(t);
  const result = spawnSync(process.execPath, [HOOK_PATH], {
    cwd: sandbox.vault,
    encoding: 'utf-8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: sandbox.vault },
    input: '{}\n',
    timeout: 5_000,
  });
  assert.equal(result.status, 0, result.stderr);
});
