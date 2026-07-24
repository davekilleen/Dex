'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  entityWriteMessage,
  retryEntityPhases,
} = require('../lib/entity-phase.cjs');

test('a saved pending meeting reruns entity creation without rewriting its note', () => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-entity-phase-'));
  const note = path.join(vault, '00-Inbox', 'Meetings', '2026-07-01', 'example.md');
  fs.mkdirSync(path.dirname(note), { recursive: true });
  fs.writeFileSync(note, '# Existing meeting note\n');
  const original = fs.readFileSync(note);
  const state = {
    processedMeetings: {
      'meeting-1': {
        title: 'Example',
        filepath: note,
        entity_phase: 'pending',
        entity_payload: {
          id: 'meeting-1',
          createdAt: '2026-07-01T10:00:00.000Z',
          hasTranscript: true,
          filteredAttendees: [{
            name: 'Jane Example',
            email: 'jane@example.com',
            location: 'external',
          }],
        },
      },
    },
  };
  let persisted = 0;
  const result = retryEntityPhases(state, {}, {
    processEntityCreation: (meetings) => {
      assert.deepEqual(meetings, [
        state.processedMeetings['meeting-1'].entity_payload,
      ]);
      return {
        entity_write: {
          ok: true,
          completed_meeting_ids: ['meeting-1'],
          dead_lettered_ops: [],
        },
      };
    },
    persistState: () => { persisted += 1; },
  });

  assert.equal(result.entity_write.ok, true);
  assert.equal(state.processedMeetings['meeting-1'].entity_phase, 'complete');
  assert.equal(persisted, 1);
  assert.deepEqual(fs.readFileSync(note), original);
  fs.rmSync(vault, { recursive: true, force: true });
});

test('a meeting whose only operation dead-letters becomes terminal failed and is surfaced', () => {
  const state = {
    processedMeetings: {
      'meeting-1': {
        entity_phase: 'pending',
        entity_payload: {
          id: 'meeting-1',
          createdAt: '2026-07-01T10:00:00.000Z',
          hasTranscript: false,
          filteredAttendees: [{
            name: 'Jane Example',
            email: 'jane@example.org',
            location: 'external',
          }],
        },
      },
    },
  };
  const result = retryEntityPhases(state, {}, {
    processEntityCreation: () => ({
      entity_write: {
        ok: false,
        completed_meeting_ids: [],
        dead_lettered_ops: [{
          meeting_id: 'meeting-1',
          meeting_ids: ['meeting-1'],
          entity_path: '/vault/05-Areas/People/External/Jane_Example.md',
          op_type: 'create',
          reason: 'entity engine rejected the operation',
        }],
      },
    }),
    persistState: () => {},
  });
  const record = state.processedMeetings['meeting-1'];

  assert.equal(record.entity_phase, 'failed');
  assert.equal(record.entity_terminal, true);
  assert.match(record.entity_error, /rejected/);
  assert.match(entityWriteMessage(result.entity_write), /1 entity write failed permanently/i);
  assert.match(entityWriteMessage(result.entity_write), /System\/\.dex\/entity-dead-letter\.jsonl/);
  assert.match(entityWriteMessage(result.entity_write), /\/dex-doctor/);
});

test('a non-terminal failed phase is retried on the next sync', () => {
  const state = {
    processedMeetings: {
      'meeting-1': {
        entity_phase: 'failed',
        entity_terminal: false,
        entity_error: 'process interrupted',
        entity_payload: {
          id: 'meeting-1',
          createdAt: '2026-07-01T10:00:00.000Z',
          filteredAttendees: [],
        },
      },
    },
  };
  let calls = 0;
  retryEntityPhases(state, {}, {
    processEntityCreation: () => {
      calls += 1;
      return {
        entity_write: {
          ok: true,
          completed_meeting_ids: ['meeting-1'],
          dead_lettered_ops: [],
        },
      };
    },
    persistState: () => {},
  });

  assert.equal(calls, 1);
  assert.equal(state.processedMeetings['meeting-1'].entity_phase, 'complete');
});

test('a prior dead-letter ledger entry repairs lifecycle state after a crash', () => {
  const state = {
    processedMeetings: {
      'meeting-1': {
        entity_phase: 'pending',
        entity_payload: {
          id: 'meeting-1',
          createdAt: '2026-07-01T10:00:00.000Z',
          filteredAttendees: [],
        },
      },
    },
  };
  retryEntityPhases(state, {}, {
    processEntityCreation: () => ({
      entity_write: {
        ok: true,
        completed_meeting_ids: [],
        dead_lettered_ops: [],
      },
    }),
    deadLetteredOps: [{
      meeting_id: 'meeting-1',
      meeting_ids: ['meeting-1'],
      entity_path: '/vault/05-Areas/People/External/Jane_Example.md',
      op_type: 'mutate',
      reason: 'target page missing',
    }],
    persistState: () => {},
  });

  assert.equal(state.processedMeetings['meeting-1'].entity_phase, 'failed');
  assert.equal(state.processedMeetings['meeting-1'].entity_terminal, true);
});
