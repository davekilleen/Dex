'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const HOOK_PATH = path.resolve(__dirname, '..', 'meeting-queue-check.cjs');
const NOW = Date.parse('2026-07-27T12:00:00Z');
const TODAY = new Date(NOW).toISOString().slice(0, 10);

function dayFromNow(dayOffset) {
  const date = new Date(NOW);
  date.setUTCDate(date.getUTCDate() + dayOffset);
  return date.toISOString().slice(0, 10);
}

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-meeting-queue-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function meetingsRoot(root) {
  return path.join(root, '00-Inbox', 'Meetings');
}

function writeFlatMeeting(root, fileName, content) {
  const directory = meetingsRoot(root);
  fs.mkdirSync(directory, { recursive: true });
  const filePath = path.join(directory, fileName);
  fs.writeFileSync(filePath, content);
  return filePath;
}

function writeDayMeeting(root, day, fileName, content) {
  const directory = path.join(meetingsRoot(root), day);
  fs.mkdirSync(directory, { recursive: true });
  const filePath = path.join(directory, fileName);
  fs.writeFileSync(filePath, content);
  return filePath;
}

function writeQueueMeeting(root, fileName, content = '{}\n') {
  const directory = path.join(meetingsRoot(root), 'queue');
  fs.mkdirSync(directory, { recursive: true });
  const filePath = path.join(directory, fileName);
  fs.writeFileSync(filePath, content);
  return filePath;
}

function meetingNote({
  day = TODAY,
  granolaId,
  aiAnalyzed,
  body = '### For Me\n- [ ] Send the proposal\n',
  tasksExtracted = false,
  skipProcessing = false,
} = {}) {
  const fields = [`date: ${day}`];
  if (granolaId !== undefined) fields.push(`granola_id: ${granolaId}`);
  if (aiAnalyzed !== undefined) fields.push(`ai_analyzed: ${aiAnalyzed}`);
  const markers = [
    tasksExtracted ? '<!-- tasks-extracted: 2026-01-01T00:00:00Z -->' : '',
    skipProcessing ? '<!-- dex:skip-processing -->' : '',
  ].filter(Boolean);
  const markerBlock = markers.length > 0 ? `\n${markers.join('\n')}\n` : '';
  return `---\n${fields.join('\n')}\n---\n\n${body}${markerBlock}`;
}

function expectedLines(count) {
  const noun = count === 1 ? 'meeting' : 'meetings';
  const verb = count === 1 ? 'has' : 'have';
  return [
    `--- 📋 Meetings waiting to be processed (${count}) ---`,
    `${count} ${noun} ${verb} not been processed yet (person pages, tasks, notes).`,
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

test('detects a waiting manual note with no Granola signals anywhere', (t) => {
  const root = fixture(t);
  writeDayMeeting(root, TODAY, 'manual-notes.md', meetingNote());

  assert.equal(fs.existsSync(path.join(root, '.scripts', 'meeting-intel')), false);
  assert.doesNotMatch(
    fs.readFileSync(path.join(meetingsRoot(root), TODAY, 'manual-notes.md'), 'utf8'),
    /granola/i,
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 1, lines: expectedLines(1) });
});

test('counts a recent flat note without frontmatter using its filename date', (t) => {
  const root = fixture(t);
  writeFlatMeeting(
    root,
    `${TODAY} - Planning.md`,
    '# Planning\n\n### For Me\n- [ ] Send the proposal\n',
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 1, lines: expectedLines(1) });
});

test('excludes a flat note stamped as tasks extracted', (t) => {
  const root = fixture(t);
  writeFlatMeeting(
    root,
    `${TODAY} - Planning.md`,
    [
      '# Planning',
      '',
      '### For Me',
      '- [ ] Send the proposal',
      '',
      '<!-- tasks-extracted: 2026-07-27T11:00:00Z -->',
      '',
    ].join('\n'),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('excludes a waiting note marked to skip processing', (t) => {
  const root = fixture(t);
  writeDayMeeting(
    root,
    TODAY,
    'skip-me.md',
    meetingNote({ skipProcessing: true }),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('excludes a flat note with no resolvable date', (t) => {
  const root = fixture(t);
  writeFlatMeeting(
    root,
    'Planning.md',
    '# Planning\n\n### For Me\n- [ ] Send the proposal\n',
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('excludes a flat note whose filename date is 30 days old', (t) => {
  const root = fixture(t);
  writeFlatMeeting(
    root,
    `${dayFromNow(-30)} - Old planning.md`,
    '# Old planning\n\n### For Me\n- [ ] Send the proposal\n',
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('counts a recent day-directory Granola-style note with an unchecked For Me item', (t) => {
  const root = fixture(t);
  writeDayMeeting(
    root,
    TODAY,
    'granola-note.md',
    meetingNote({ granolaId: 'meeting-1' }),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 1, lines: expectedLines(1) });
});

test('excludes a stamped day-directory Granola-style note', (t) => {
  const root = fixture(t);
  writeDayMeeting(
    root,
    TODAY,
    'granola-note.md',
    meetingNote({ granolaId: 'meeting-1', tasksExtracted: true }),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('excludes a day-directory Granola-style note whose For Me items are all checked', (t) => {
  const root = fixture(t);
  writeDayMeeting(
    root,
    TODAY,
    'granola-note.md',
    meetingNote({
      granolaId: 'meeting-1',
      body: '### For Me\n- [x] Send the proposal\n',
    }),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('tasks-extracted marker overrides ai_analyzed false', (t) => {
  const root = fixture(t);
  writeDayMeeting(
    root,
    TODAY,
    'already-processed.md',
    meetingNote({
      aiAnalyzed: false,
      body: '# Basic meeting note\n',
      tasksExtracted: true,
    }),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 0, lines: [] });
});

test('counts ai_analyzed false using the day-directory date', (t) => {
  const root = fixture(t);
  writeDayMeeting(
    root,
    TODAY,
    'unanalyzed.md',
    [
      '---',
      'ai_analyzed: false',
      '---',
      '',
      '# Basic meeting note',
      '',
    ].join('\n'),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 1, lines: expectedLines(1) });
});

test('counts a queue JSON without applying a note age filter', (t) => {
  const root = fixture(t);
  writeQueueMeeting(root, 'old-manual-meeting.json');

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 1, lines: expectedLines(1) });
});

test('counts only two queue JSONs when meeting notes are already stamped', (t) => {
  const root = fixture(t);
  writeDayMeeting(
    root,
    TODAY,
    'already-stamped.md',
    meetingNote({ tasksExtracted: true }),
  );
  writeDayMeeting(
    root,
    TODAY,
    'also-stamped.md',
    meetingNote({ aiAnalyzed: false, tasksExtracted: true }),
  );
  writeQueueMeeting(root, 'manual-one.json');
  writeQueueMeeting(root, 'manual-two.json');

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 2, lines: expectedLines(2) });
});

test('counts unchecked For Me items despite garbled frontmatter using the day directory', (t) => {
  const root = fixture(t);
  writeDayMeeting(
    root,
    TODAY,
    'garbled.md',
    [
      '---',
      'participants: [unterminated',
      '---',
      '',
      '### For Me',
      '- [ ] This garbled note still counts',
      '',
    ].join('\n'),
  );

  let result;
  assert.doesNotThrow(() => {
    result = checkMeetingQueue({ vaultRoot: root, now: NOW });
  });
  assert.deepEqual(result, { count: 1, lines: expectedLines(1) });
});

test('a fresh notice marker throttles another session without being rewritten', (t) => {
  const root = fixture(t);
  writeDayMeeting(root, TODAY, 'planning.md', meetingNote());
  const marker = path.join(root, 'System', '.last-meeting-queue-notice');
  fs.mkdirSync(path.dirname(marker), { recursive: true });
  const freshTimestamp = String(Math.floor(NOW / 1000) - 60);
  fs.writeFileSync(marker, `${freshTimestamp}\n`);

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 0, lines: [] });
  assert.equal(fs.readFileSync(marker, 'utf8'), `${freshTimestamp}\n`);
});

test('a stale notice marker allows output and is rewritten', (t) => {
  const root = fixture(t);
  writeDayMeeting(root, TODAY, 'planning.md', meetingNote());
  const marker = path.join(root, 'System', '.last-meeting-queue-notice');
  fs.mkdirSync(path.dirname(marker), { recursive: true });
  fs.writeFileSync(marker, `${Math.floor(NOW / 1000) - 3600}\n`);

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });

  assert.deepEqual(result, { count: 1, lines: expectedLines(1) });
  assert.equal(fs.readFileSync(marker, 'utf8'), `${Math.floor(NOW / 1000)}\n`);
});

test('missing meeting directories return zero without throwing', (t) => {
  const root = fixture(t);

  let result;
  assert.doesNotThrow(() => {
    result = checkMeetingQueue({ vaultRoot: root, now: NOW });
  });
  assert.deepEqual(result, { count: 0, lines: [] });
});

test('an unreadable meetings directory returns zero without throwing', (t) => {
  const root = fixture(t);
  const directory = meetingsRoot(root);
  fs.mkdirSync(directory, { recursive: true });
  fs.chmodSync(directory, 0o000);

  let result;
  try {
    assert.doesNotThrow(() => {
      result = checkMeetingQueue({ vaultRoot: root, now: NOW });
    });
  } finally {
    fs.chmodSync(directory, 0o700);
  }
  assert.deepEqual(result, { count: 0, lines: [] });
});
