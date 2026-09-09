const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK_PATH = path.resolve(__dirname, '..', 'session-clock.sh');

function sandbox(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-session-clock-'));
  const vault = path.join(root, 'vault');
  fs.mkdirSync(path.join(vault, 'System', '.dex'), { recursive: true });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { vault, stateFile: path.join(root, 'clock-day') };
}

function run({ vault, stateFile }) {
  return spawnSync('/bin/bash', [HOOK_PATH], {
    encoding: 'utf8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: vault, DEX_SESSION_CLOCK_STATE: stateFile },
  });
}

test('always reports the time, so the clock in context is never older than one turn', (t) => {
  const box = sandbox(t);

  const result = run(box);

  assert.equal(result.status, 0);
  // Deliberately unconditional: a hook that only speaks when something changed
  // is a hook with a branch that can quietly not fire, which is the bug class
  // this exists to close.
  assert.match(result.stdout, /^🕐 \d{4}-\d{2}-\d{2} \d{2}:\d{2}/u);
});

test('says nothing about a day change on the first run of a fresh vault', (t) => {
  const box = sandbox(t);

  const result = run(box);

  assert.doesNotMatch(result.stdout, /date has changed/u);
});

test('calls out a day boundary crossed mid-session', (t) => {
  const box = sandbox(t);
  fs.writeFileSync(box.stateFile, '2000-01-01\n');

  const result = run(box);

  // The transition is the moment context stops being merely old and becomes
  // wrong, so it is stated rather than left for the reader to notice.
  assert.match(result.stdout, /date has changed since this session last checked \(was 2000-01-01\)/u);
  assert.match(result.stdout, /stale/u);
});

test('stays quiet on the next run once the day is recorded', (t) => {
  const box = sandbox(t);
  fs.writeFileSync(box.stateFile, '2000-01-01\n');

  run(box);
  const second = run(box);

  assert.doesNotMatch(second.stdout, /date has changed/u);
  assert.match(second.stdout, /^🕐 /u);
});

test('still reports the time when the vault has no state directory', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-session-clock-bare-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));

  const result = spawnSync('/bin/bash', [HOOK_PATH], {
    encoding: 'utf8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: root, DEX_SESSION_CLOCK_STATE: path.join(root, 'x') },
  });

  assert.equal(result.status, 0);
  assert.match(result.stdout, /^🕐 /u);
});

test('an unwritable state file costs the clock line nothing', (t) => {
  const box = sandbox(t);
  fs.mkdirSync(box.stateFile);

  const result = run(box);

  assert.equal(result.status, 0, 'a vault that cannot record the day is no worse off than before');
  assert.match(result.stdout, /^🕐 /u);
});
