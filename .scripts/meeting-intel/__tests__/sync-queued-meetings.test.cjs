'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const https = require('node:https');
const test = require('node:test');

const {
  getNewMeetingsFromApi,
  loadState,
  persistState,
  processedMeetingsPaths,
} = require('../sync-from-granola.cjs');

function meetingsFixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-sync-queue-'));
  const meetingsDir = path.join(root, '00-Inbox', 'Meetings');
  fs.mkdirSync(meetingsDir, { recursive: true });
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { root, meetingsDir };
}

test('API sync skips queued meetings unless force-today is set', async (t) => {
  const originalRequest = https.request;
  const detailRequests = [];
  const createdAt = new Date().toISOString();

  https.request = (url, options, callback) => {
    const request = new EventEmitter();
    request.destroy = () => {};
    request.end = () => setImmediate(() => {
      const response = new PassThrough();
      response.statusCode = 200;
      response.headers = {};
      callback(response);

      const isDetailRequest = String(url).includes('include=transcript');
      if (isDetailRequest) detailRequests.push(String(url));
      const body = isDetailRequest
        ? {
            id: 'already-queued',
            title: 'Queued customer sync',
            created_at: createdAt,
            summary_text: 'This fixture has enough meaningful meeting content to pass the detail filter.',
          }
        : {
            notes: [{ id: 'already-queued', title: 'Queued customer sync', created_at: createdAt }],
            hasMore: false,
            cursor: null,
          };
      response.end(JSON.stringify(body));
    });
    return request;
  };
  t.after(() => {
    https.request = originalRequest;
  });

  const { meetingsDir } = meetingsFixture(t);
  const state = {
    processedMeetings: {},
    queuedMeetings: {
      'already-queued': { queueFile: 'already-queued.json' },
    },
  };

  const ordinaryMeetings = await getNewMeetingsFromApi(
    'fixture-key',
    state,
    false,
    {},
    { meetingsDir },
  );
  assert.deepEqual(ordinaryMeetings, []);
  assert.equal(detailRequests.length, 0);

  const forcedMeetings = await getNewMeetingsFromApi(
    'fixture-key',
    state,
    true,
    {},
    { meetingsDir },
  );
  assert.deepEqual(forcedMeetings.map((meeting) => meeting.id), ['already-queued']);
  assert.equal(detailRequests.length, 1);
});

test('API sync does not re-queue a meeting whose note already exists', async (t) => {
  const originalRequest = https.request;
  const detailRequests = [];
  const createdAt = new Date().toISOString();
  const { meetingsDir } = meetingsFixture(t);
  const day = createdAt.slice(0, 10);
  const noteDir = path.join(meetingsDir, day);
  fs.mkdirSync(noteDir, { recursive: true });
  fs.writeFileSync(
    path.join(noteDir, 'already-on-disk.md'),
    [
      '---',
      'granola_id: already-on-disk',
      '---',
      '',
      '# Already processed',
      '',
    ].join('\n'),
  );

  https.request = (url, options, callback) => {
    const request = new EventEmitter();
    request.destroy = () => {};
    request.end = () => setImmediate(() => {
      const response = new PassThrough();
      response.statusCode = 200;
      response.headers = {};
      callback(response);

      const isDetailRequest = String(url).includes('include=transcript');
      if (isDetailRequest) detailRequests.push(String(url));
      const body = isDetailRequest
        ? {
            id: 'already-on-disk',
            title: 'Already processed',
            created_at: createdAt,
            summary_text: 'This fixture has enough meaningful meeting content to pass the detail filter.',
          }
        : {
            notes: [{ id: 'already-on-disk', title: 'Already processed', created_at: createdAt }],
            hasMore: false,
            cursor: null,
          };
      response.end(JSON.stringify(body));
    });
    return request;
  };
  t.after(() => {
    https.request = originalRequest;
  });

  const ordinaryMeetings = await getNewMeetingsFromApi(
    'fixture-key',
    { processedMeetings: {}, queuedMeetings: {} },
    false,
    {},
    { meetingsDir },
  );
  assert.deepEqual(ordinaryMeetings, []);
  assert.equal(detailRequests.length, 0);

  const forcedMeetings = await getNewMeetingsFromApi(
    'fixture-key',
    { processedMeetings: {}, queuedMeetings: {} },
    true,
    {},
    { meetingsDir },
  );
  assert.deepEqual(forcedMeetings.map((meeting) => meeting.id), ['already-on-disk']);
  assert.equal(detailRequests.length, 1);
});

test('processed meeting state writes to the runtime path and still reads the old file', (t) => {
  const { root } = meetingsFixture(t);
  const { runtime, legacy } = processedMeetingsPaths(root);
  fs.mkdirSync(path.dirname(legacy), { recursive: true });
  fs.writeFileSync(
    legacy,
    JSON.stringify({
      processedMeetings: { 'legacy-id': { title: 'Old mark' } },
      lastSync: '2026-09-01T00:00:00.000Z',
    }),
  );

  const loaded = loadState(root);
  assert.equal(loaded.processedMeetings['legacy-id'].title, 'Old mark');

  persistState({
    processedMeetings: { 'legacy-id': { title: 'Old mark' }, 'new-id': { title: 'Kept' } },
    lastSync: '2026-09-21T00:00:00.000Z',
  }, root);

  assert.equal(fs.existsSync(runtime), true);
  const saved = JSON.parse(fs.readFileSync(runtime, 'utf8'));
  assert.equal(saved.processedMeetings['new-id'].title, 'Kept');
  assert.equal(loadState(root).processedMeetings['new-id'].title, 'Kept');
});
