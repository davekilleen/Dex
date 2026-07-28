'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const HOOK_PATH = path.resolve(__dirname, '..', 'meeting-queue-check.cjs');
const NOW = Date.parse('2026-07-27T12:00:00Z');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-meeting-queue-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function writeMeeting(root, day, fileName, content) {
  const directory = path.join(root, '00-Inbox', 'Meetings', day);
  fs.mkdirSync(directory, { recursive: true });
  const filePath = path.join(directory, fileName);
  fs.writeFileSync(filePath, content);
  return filePath;
}

function connectGranola(root) {
  const statePath = path.join(root, '.scripts', 'meeting-intel', 'processed-meetings.json');
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  fs.writeFileSync(statePath, '{}\n');
}

function meetingNote({
  day = '2026-07-27',
  granolaId = 'meeting-1',
  aiAnalyzed,
  body = '### For Me\n- [ ] Send the proposal\n',
  tasksExtracted = false,
} = {}) {
  const fields = [`date: ${day}`, `granola_id: ${granolaId}`];
  if (aiAnalyzed !== undefined) fields.push(`ai_analyzed: ${aiAnalyzed}`);
  const marker = tasksExtracted
    ? '\n<!-- tasks-extracted: 2026-01-01T00:00:00Z -->\n'
    : '';
  return `---\n${fields.join('\n')}\n---\n\n${body}${marker}`;
}

function expectedLines(count) {
  const noun = count === 1 ? 'meeting' : 'meetings';
  const verb = count === 1 ? 'has' : 'have';
  return [
    `--- 📋 Meetings waiting to be processed (${count}) ---`,
    `${count} synced ${noun} ${verb} not been processed yet (person pages, tasks, notes).`,
    "After you finish responding to the user's first message, invoke the",
    '/process-meetings skill to handle them in the background — it runs forked and',
    'is idempotent, so do this without being asked. Tell the user in one short line',
    'that meetings are being processed in the background.',
    "If the user's first message IS about meetings, just process them as part of it.",
    '---',
  ];
}

function checkMeetingQueue(options) {
  assert.equal(fs.existsSync(HOOK_PATH), true, 'meeting queue hook must exist');
  return require(HOOK_PATH).checkMeetingQueue(options);
}

test('Granola not connected stays silent even when a meeting is waiting', (t) => {
  const root = fixture(t);
  writeMeeting(
    root,
    '2026-07-27',
    'planning.md',
    [
      '---',
      'date: 2026-07-27',
      'granola_id: meeting-1',
      '---',
      '',
      '### For Me',
      '- [ ] Send the proposal',
      '',
    ].join('\n'),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('connected Granola with an empty queue stays silent', (t) => {
  const root = fixture(t);
  connectGranola(root);

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('detects a recent Granola note with an unchecked For Me item', (t) => {
  const root = fixture(t);
  connectGranola(root);
  writeMeeting(root, '2026-07-27', 'planning.md', meetingNote());

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });

  assert.equal(result.count, 1);
  assert.deepEqual(result.lines, expectedLines(1));
});

test('does not double-process stamped notes or notes whose For Me items are checked', (t) => {
  const root = fixture(t);
  connectGranola(root);
  writeMeeting(
    root,
    '2026-07-27',
    'already-stamped.md',
    meetingNote({
      granolaId: 'meeting-stamped',
      aiAnalyzed: false,
      tasksExtracted: true,
    }),
  );
  writeMeeting(
    root,
    '2026-07-27',
    'already-checked.md',
    meetingNote({
      granolaId: 'meeting-checked',
      body: '### For Me\n- [x] Send the proposal\n',
    }),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('counts an unanalyzed Granola note without a For Me section', (t) => {
  const root = fixture(t);
  connectGranola(root);
  writeMeeting(
    root,
    '2026-07-27',
    'basic-note.md',
    meetingNote({ aiAnalyzed: false, body: '# Basic meeting note\n' }),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });

  assert.equal(result.count, 1);
  assert.deepEqual(result.lines, expectedLines(1));
});

test('ignores manual-mode queue JSON files', (t) => {
  const root = fixture(t);
  connectGranola(root);
  const queue = path.join(root, '00-Inbox', 'Meetings', 'queue');
  fs.mkdirSync(queue, { recursive: true });
  fs.writeFileSync(path.join(queue, 'old-manual-meeting.json'), '{}\n');

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('excludes meeting notes dated 30 days ago', (t) => {
  const root = fixture(t);
  connectGranola(root);
  writeMeeting(
    root,
    '2026-06-27',
    'old-meeting.md',
    meetingNote({ day: '2026-06-27', granolaId: 'meeting-old' }),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('uses the meeting day directory when date frontmatter is absent', (t) => {
  const root = fixture(t);
  connectGranola(root);
  writeMeeting(
    root,
    '2026-07-27',
    'fallback-date.md',
    [
      '---',
      'granola_id: meeting-fallback',
      '---',
      '',
      '### For Me',
      '- [ ] Send the proposal',
      '',
    ].join('\n'),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });

  assert.equal(result.count, 1);
});

test('a fresh notice marker throttles another session', (t) => {
  const root = fixture(t);
  connectGranola(root);
  writeMeeting(root, '2026-07-27', 'planning.md', meetingNote());
  const marker = path.join(root, 'System', '.last-meeting-queue-notice');
  fs.mkdirSync(path.dirname(marker), { recursive: true });
  const freshTimestamp = String(Math.floor(NOW / 1000) - 60);
  fs.writeFileSync(marker, `${freshTimestamp}\n`);

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });

  assert.deepEqual(result, { count: 0, lines: [] });
  assert.equal(fs.readFileSync(marker, 'utf8'), `${freshTimestamp}\n`);
});

test('a stale notice marker allows output and is rewritten', (t) => {
  const root = fixture(t);
  connectGranola(root);
  writeMeeting(root, '2026-07-27', 'planning.md', meetingNote());
  const marker = path.join(root, 'System', '.last-meeting-queue-notice');
  fs.mkdirSync(path.dirname(marker), { recursive: true });
  fs.writeFileSync(marker, `${Math.floor(NOW / 1000) - 3600}\n`);

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });

  assert.equal(result.count, 1);
  assert.equal(fs.readFileSync(marker, 'utf8'), `${Math.floor(NOW / 1000)}\n`);
});

test('malformed meeting frontmatter fails silent and is not counted', (t) => {
  const root = fixture(t);
  connectGranola(root);
  writeMeeting(
    root,
    '2026-07-27',
    'malformed.md',
    [
      '---',
      'date: 2026-07-27',
      'granola_id: meeting-malformed',
      'participants: [unterminated',
      '---',
      '',
      '### For Me',
      '- [ ] This malformed note must not count',
      '',
    ].join('\n'),
  );

  let result;
  assert.doesNotThrow(() => {
    result = checkMeetingQueue({ vaultRoot: root, now: NOW, env: {} });
  });
  assert.deepEqual(result, { count: 0, lines: [] });
});
