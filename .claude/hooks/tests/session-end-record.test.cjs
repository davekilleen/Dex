const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK_PATH = path.resolve(__dirname, '..', 'session-end.sh');

function sandbox(t) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-session-end-'));
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  return vault;
}

function run(vault, { stdin = '', args = [] } = {}) {
  return spawnSync('/bin/bash', [HOOK_PATH, ...args], {
    encoding: 'utf8',
    input: stdin,
    env: { ...process.env, CLAUDE_PROJECT_DIR: vault },
  });
}

function learningFile(vault) {
  const today = new Date().toISOString().slice(0, 10);
  return fs.readFileSync(
    path.join(vault, 'System', 'Session_Learnings', `${today}.md`),
    'utf8',
  );
}

test('reads the transcript path from the JSON payload on stdin', (t) => {
  const vault = sandbox(t);
  const transcript = path.join(vault, 'transcript.jsonl');
  fs.writeFileSync(transcript, '{}\n');

  const result = run(vault, { stdin: JSON.stringify({ transcript_path: transcript }) });

  assert.equal(result.status, 0);
  const text = learningFile(vault);
  assert.match(text, new RegExp(`Transcript:.*${transcript.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'u'));
  assert.match(text, /Run \/daily-review/u);
});

test('records the session even when no transcript is supplied', (t) => {
  const vault = sandbox(t);

  // This is the real-world case: settings.json passed "$transcript_path", a
  // shell variable nothing sets, so the hook received nothing on every run.
  const result = run(vault, { stdin: '{}' });

  assert.equal(result.status, 0);
  const text = learningFile(vault);
  assert.match(text, /Session completed/u, 'the session boundary must be recorded regardless');
  assert.match(text, /not supplied to this hook/u, 'and the gap must be stated, not hidden');
});

test('says so when the transcript path points at nothing', (t) => {
  const vault = sandbox(t);

  run(vault, { stdin: JSON.stringify({ transcript_path: '/nonexistent/x.jsonl' }) });

  const text = learningFile(vault);
  assert.match(text, /no file exists there/u);
  assert.doesNotMatch(text, /Run \/daily-review/u, 'must not promise extraction it cannot do');
});

test('still accepts an argv transcript, for direct invocation', (t) => {
  const vault = sandbox(t);
  const transcript = path.join(vault, 'transcript.jsonl');
  fs.writeFileSync(transcript, '{}\n');

  run(vault, { args: [transcript] });

  assert.match(learningFile(vault), /Run \/daily-review/u);
});

test('a day file is never left containing only its header', (t) => {
  const vault = sandbox(t);

  run(vault, { stdin: '{}' });

  const text = learningFile(vault);
  const afterHeader = text.split('---')[1] || '';
  assert.notEqual(
    afterHeader.trim(),
    '',
    'an empty day file is indistinguishable from a day where nothing was captured',
  );
});

test('appends rather than replacing when a session already ended today', (t) => {
  const vault = sandbox(t);

  run(vault, { stdin: '{}' });
  run(vault, { stdin: '{}' });

  const occurrences = learningFile(vault).match(/Session completed/gu) || [];
  assert.equal(occurrences.length, 2);
});
