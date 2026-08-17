'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const meetingSync = require('../sync-from-granola.cjs');


test('Granola detail keeps only the calendar start identity needed for matching', () => {
  assert.equal(typeof meetingSync.captureIdentityFromDetail, 'function');
  const identity = meetingSync.captureIdentityFromDetail({
    calendar_event: {
      scheduled_start_time: '2026-07-15T09:00:00Z',
      event_title: 'Customer discovery',
      invitees: [{ email: 'alex@example.com' }],
      join_url: 'https://meet.example/secret',
      dial_in: '555-0100',
      access_code: '1234',
      raw_payload: { password: 'never-copy-this' },
    },
  });

  assert.deepEqual(identity, { captureStartedAt: '2026-07-15T09:00:00Z' });
  const serialized = JSON.stringify(identity);
  for (const secret of ['meet.example', '555-0100', '1234', 'never-copy-this']) {
    assert.equal(serialized.includes(secret), false);
  }
});


test('meeting notes persist an aware capture start without invite payload', (t) => {
  const meetingsDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-capture-identity-'));
  t.after(() => fs.rmSync(meetingsDir, { recursive: true, force: true }));
  const meeting = {
    id: 'not_capture_identity',
    title: 'Untitled Meeting',
    createdAt: '2026-07-15T09:02:00Z',
    captureStartedAt: '2026-07-15T09:00:00Z',
    participants: [],
    attendees: [],
    owner: null,
    company: '',
    duration: null,
    source: 'api',
    notes: '',
    transcript: '',
    calendarEvent: {
      join_url: 'https://meet.example/secret',
      access_code: '1234',
    },
  };

  const result = meetingSync.createMeetingNote(
    meeting,
    '## Summary\n\nNothing sensitive.',
    { obsidian_mode: false },
    ['work'],
    { meetingsDir, logger: () => {} },
  );
  const note = fs.readFileSync(result.filepath, 'utf8');

  assert.match(note, /^capture_started_at: 2026-07-15T09:00:00Z$/m);
  assert.equal(note.includes('meet.example'), false);
  assert.equal(note.includes('1234'), false);
});
