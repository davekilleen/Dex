const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOKS_DIR = path.resolve(__dirname, '..');
const GATE = path.join(HOOKS_DIR, 'correction-capture.sh');

function sandbox(t) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-correction-'));
  fs.mkdirSync(path.join(vault, 'System'), { recursive: true });
  fs.cpSync(HOOKS_DIR, path.join(vault, '.claude', 'hooks'), { recursive: true });
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  return vault;
}

function submit(vault, prompt) {
  return spawnSync('/bin/bash', [GATE], {
    encoding: 'utf8',
    input: JSON.stringify({ prompt }),
    env: { ...process.env, CLAUDE_PROJECT_DIR: vault },
  });
}

function captured(vault) {
  const today = new Date().toISOString().slice(0, 10);
  const file = path.join(vault, 'System', 'Session_Learnings', `${today}.md`);
  return fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : '';
}

// Real corrections from a single session, kept verbatim: these are the data the
// pattern set was tuned against, so a regression shows up as a named failure
// rather than a percentage drifting quietly.
const CORRECTIONS = [
  'no... i want to honour the architectural patterns of dex upstream',
  'come on - thats a time code, its stupid inference',
  'no no no - stop over inferring from timesheet entries',
  'STOP',
  'its not an invitation - your index is stale and youre not checking properly',
  'so why didnt you pick this up in todays plan or yesterdays review?',
  'do nothing then and stop making recommendations you havent thought through',
  'ok, so you keep writing failure patterns and then keep failing on them',
];

const ORDINARY = [
  'run the daily plan',
  'log it against G003',
  'yes, do both',
  'carry on with 564',
  'close DEX-105',
  'write both issues up separately then start the PR work',
  'does this run into conflict management with upstream?',
];

for (const prompt of CORRECTIONS) {
  test(`captures: ${prompt.slice(0, 44)}`, (t) => {
    const vault = sandbox(t);
    submit(vault, prompt);
    assert.match(captured(vault), /- Correction/u);
  });
}

for (const prompt of ORDINARY) {
  test(`ignores: ${prompt.slice(0, 44)}`, (t) => {
    const vault = sandbox(t);
    submit(vault, prompt);
    assert.equal(captured(vault), '', 'an ordinary instruction must not be recorded as a correction');
  });
}

test('the boundary is not whitespace, because JSON puts a quote before the word', (t) => {
  const vault = sandbox(t);

  // {"prompt":"STOP"} has no space before STOP. A whitespace-anchored pattern
  // silently never fires on real input while passing a test built from bare text.
  submit(vault, 'STOP');

  assert.match(captured(vault), /- Correction/u);
});

test('stores the user words verbatim rather than a summary', (t) => {
  const vault = sandbox(t);
  const words = 'no no no - stop over inferring from timesheet entries';

  submit(vault, words);

  assert.ok(captured(vault).includes(words), 'a paraphrase would carry the misunderstanding forward');
});

test('writes the pending status the routing step already expects', (t) => {
  const vault = sandbox(t);

  submit(vault, 'STOP');
  const text = captured(vault);

  assert.match(text, /\*\*Status:\*\* pending/u);
  assert.match(text, /\*\*What was said:\*\*/u);
});

test('truncates a correction buried in a wall of pasted context', (t) => {
  const vault = sandbox(t);

  submit(vault, `stop doing that. ${'x'.repeat(2000)}`);
  const text = captured(vault);

  assert.match(text, /truncated/u);
  assert.ok(text.length < 1800, 'the file has to stay readable');
});

test('appends, so several corrections in one day all survive', (t) => {
  const vault = sandbox(t);

  submit(vault, 'STOP');
  submit(vault, 'no, thats wrong');

  assert.equal((captured(vault).match(/- Correction/gu) || []).length, 2);
});

test('never blocks a prompt, whatever the payload', (t) => {
  const vault = sandbox(t);

  for (const input of ['', 'not json at all', '{"prompt":null}', '[]']) {
    const result = spawnSync('/bin/bash', [GATE], {
      encoding: 'utf8',
      input,
      env: { ...process.env, CLAUDE_PROJECT_DIR: vault },
    });
    assert.equal(result.status, 0, `exit 0 required for payload: ${input}`);
  }
});

test('stays silent when there is no vault to write to', (t) => {
  const bare = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-correction-bare-'));
  t.after(() => fs.rmSync(bare, { recursive: true, force: true }));

  const result = spawnSync('/bin/bash', [GATE], {
    encoding: 'utf8',
    input: JSON.stringify({ prompt: 'STOP' }),
    env: { ...process.env, CLAUDE_PROJECT_DIR: bare },
  });

  assert.equal(result.status, 0);
  assert.equal(result.stdout, '', 'a hook that cannot record must not say so on every prompt');
});
