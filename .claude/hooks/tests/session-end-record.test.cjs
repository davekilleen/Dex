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

function pythonBin() {
  if (process.env.DEX_PYTHON && fs.existsSync(process.env.DEX_PYTHON)) {
    return process.env.DEX_PYTHON;
  }
  for (const candidate of ['/usr/bin/python3', '/usr/local/bin/python3', '/opt/homebrew/bin/python3']) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return '';
}

function run(vault, { stdin = '', args = [] } = {}) {
  const env = { ...process.env, CLAUDE_PROJECT_DIR: vault };
  const python = pythonBin();
  if (python) {
    env.DEX_PYTHON = python;
  }
  return spawnSync('/bin/bash', [HOOK_PATH, ...args], {
    encoding: 'utf8',
    input: stdin,
    env,
  });
}

function userLine(text) {
  return `${JSON.stringify({
    type: 'user',
    message: { role: 'user', content: [{ type: 'text', text }] },
  })}\n`;
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

test('extracts an obvious preference from the transcript as a pending lesson', (t) => {
  const vault = sandbox(t);
  const transcript = path.join(vault, 'transcript.jsonl');
  fs.writeFileSync(transcript, userLine('I prefer summaries in bullet points'));

  const result = run(vault, { stdin: JSON.stringify({ transcript_path: transcript }) });

  assert.equal(result.status, 0);
  const text = learningFile(vault);
  assert.match(text, /Session completed/u);
  assert.match(text, /I prefer summaries in bullet points/u);
  assert.match(text, /\*\*Status:\*\* pending/u);
  assert.match(text, /Run \/daily-review/u);
});

test('does not treat ordinary work as a lesson', (t) => {
  const vault = sandbox(t);
  const transcript = path.join(vault, 'transcript.jsonl');
  fs.writeFileSync(transcript, userLine('run the daily plan'));

  run(vault, { stdin: JSON.stringify({ transcript_path: transcript }) });

  const text = learningFile(vault);
  assert.match(text, /Session completed/u);
  assert.doesNotMatch(text, /\*\*Status:\*\* pending/u);
});

test('does not treat bare conversational words as corrections', (t) => {
  const vault = sandbox(t);
  const transcript = path.join(vault, 'transcript.jsonl');
  fs.writeFileSync(
    transcript,
    userLine('no') + userLine('stop') + userLine('actually, I think we should wait'),
  );

  run(vault, { stdin: JSON.stringify({ transcript_path: transcript }) });

  const text = learningFile(vault);
  assert.match(text, /Session completed/u);
  assert.doesNotMatch(text, /\*\*Status:\*\* pending/u);
});

test('parallel session-end hooks for the same session write one marker', (t) => {
  const vault = sandbox(t);
  const transcript = path.join(vault, 'transcript.jsonl');
  fs.writeFileSync(transcript, userLine('no, that is not what I asked'));
  const stdin = JSON.stringify({ transcript_path: transcript, session_id: 'sess-parallel' });

  const first = run(vault, { stdin });
  const second = run(vault, { stdin });
  // Sequential is the lock's observable contract; the Python helper also
  // covers two overlapping processes in test_session_lesson_extract.py.
  assert.equal(first.status, 0);
  assert.equal(second.status, 0);

  const text = learningFile(vault);
  assert.equal((text.match(/Session completed/gu) || []).length, 1);
  assert.equal((text.match(/that is not what I asked/gu) || []).length, 1);
});

test('does not write a second copy of a correction already captured live', (t) => {
  const vault = sandbox(t);
  const words = 'no, stop over inferring from timesheet entries';
  const today = new Date().toISOString().slice(0, 10);
  const learnings = path.join(vault, 'System', 'Session_Learnings');
  fs.mkdirSync(learnings, { recursive: true });
  fs.writeFileSync(
    path.join(learnings, `${today}.md`),
    `# Session Learnings - ${today}\n\n## 09:15 - Correction\n\n**What was said:**\n\n> ${words}\n\n**Status:** pending\n\n---\n\n`,
  );
  const transcript = path.join(vault, 'transcript.jsonl');
  fs.writeFileSync(transcript, userLine(words));

  run(vault, { stdin: JSON.stringify({ transcript_path: transcript }) });

  assert.equal((learningFile(vault).match(/stop over inferring/gu) || []).length, 1);
});

test('extractor failure still records the session marker', (t) => {
  const vault = sandbox(t);
  const transcript = path.join(vault, 'transcript.jsonl');
  fs.writeFileSync(transcript, userLine('I prefer shorter answers'));

  const result = spawnSync('/bin/bash', [HOOK_PATH], {
    encoding: 'utf8',
    input: JSON.stringify({ transcript_path: transcript }),
    env: { ...process.env, CLAUDE_PROJECT_DIR: vault, DEX_PYTHON: path.join(vault, 'missing-python') },
  });

  assert.equal(result.status, 0);
  assert.match(learningFile(vault), /Session completed/u);
});
