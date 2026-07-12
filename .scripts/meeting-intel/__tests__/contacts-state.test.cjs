'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
  contactIdFor,
  deriveStats,
  loadState,
  qualifiedContacts,
  recordObservations,
  updateContact,
} = require('../lib/contacts-state.cjs');
const { loadSuggestions, updateSuggestion } = require('../lib/entity-creation.cjs');

function withVault(fn) {
  const previousVault = process.env.VAULT_PATH;
  const previousProject = process.env.CLAUDE_PROJECT_DIR;
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-contacts-'));
  process.env.VAULT_PATH = vault;
  delete process.env.CLAUDE_PROJECT_DIR;
  try { return fn(vault); } finally {
    if (previousVault === undefined) delete process.env.VAULT_PATH;
    else process.env.VAULT_PATH = previousVault;
    if (previousProject === undefined) delete process.env.CLAUDE_PROJECT_DIR;
    else process.env.CLAUDE_PROJECT_DIR = previousProject;
    fs.rmSync(vault, { recursive: true, force: true });
  }
}

const jane = { name: 'Jane Doe', email: 'jane@acme.com', location: 'external' };

test('recording the same meeting twice is observation-idempotent', () => withVault(() => {
  recordObservations('m1', { date: '2026-06-01', hasTranscript: true, attendees: [jane] });
  const first = loadState();
  recordObservations('m1', { date: '2026-06-01', hasTranscript: true, attendees: [jane] });
  const second = loadState();
  const id = contactIdFor(jane);
  assert.equal(Object.keys(second.observations).length, 1);
  assert.deepEqual(deriveStats(second, id), deriveStats(first, id));
}));

test('qualification follows meeting, week, transcript, and identity rules', () => {
  const cases = [
    { dates: ['2026-06-01'], transcripts: [false], email: true, expected: false },
    { dates: ['2026-06-01', '2026-06-02'], transcripts: [false, false], email: true, expected: false },
    { dates: ['2026-06-01', '2026-06-08'], transcripts: [false, false], email: true, expected: true },
    { dates: ['2026-06-01', '2026-06-02'], transcripts: [true, false], email: true, expected: true },
    { dates: ['2026-06-01', '2026-06-08'], transcripts: [true, true], email: false, expected: false },
  ];
  for (const scenario of cases) withVault(() => {
    const attendee = { ...jane, email: scenario.email ? jane.email : null };
    scenario.dates.forEach((date, index) => recordObservations(`m${index}`, {
      date,
      hasTranscript: scenario.transcripts[index],
      attendees: [attendee],
    }));
    assert.equal(qualifiedContacts(loadState()).length > 0, scenario.expected);
  });
});

test('internal-only meetings are observations but do not count as tracked', () => withVault(() => {
  const attendee = { ...jane, location: 'internal' };
  recordObservations('m1', { date: '2026-06-01', hasTranscript: true, attendees: [attendee] });
  recordObservations('m2', { date: '2026-06-08', hasTranscript: true, attendees: [attendee] });
  const state = loadState();
  assert.equal(Object.keys(state.observations).length, 2);
  assert.equal(deriveStats(state, contactIdFor(attendee)).tracked_meetings, 0);
}));

test('sequential locked read-modify-writes preserve both updates', () => withVault(() => {
  recordObservations('m1', { date: '2026-06-01', hasTranscript: false, attendees: [jane] });
  const filePath = path.join(process.env.VAULT_PATH, 'System', '.dex', 'contacts.json');
  const id = contactIdFor(jane);
  updateContact(filePath, id, { page_path: 'one.md' });
  updateContact(filePath, id, { state: 'created' });
  assert.equal(loadState().contacts[id].page_path, 'one.md');
  assert.equal(loadState().contacts[id].state, 'created');
}));

test('dismissed suggestions require new evidence; suppressed suggestions never return', () => withVault(() => {
  recordObservations('m1', { date: '2026-06-01', hasTranscript: false, attendees: [jane] });
  recordObservations('m2', { date: '2026-06-08', hasTranscript: false, attendees: [jane] });
  const state = loadState();
  const contact = state.contacts[contactIdFor(jane)];
  const stats = deriveStats(state, contact.id);
  updateSuggestion(contact, stats, { newEvidence: true });
  const suggestionsPath = path.join(process.env.VAULT_PATH, 'System', '.dex', 'entity-suggestions.json');
  const store = loadSuggestions(suggestionsPath);
  store.suggestions[0].status = 'dismissed';
  fs.writeFileSync(suggestionsPath, JSON.stringify(store));
  assert.equal(updateSuggestion(contact, stats, { newEvidence: false }).suggestion.status, 'dismissed');
  assert.equal(updateSuggestion(contact, stats, { newEvidence: true }).suggestion.status, 'suggested');

  const suppressed = loadSuggestions(suggestionsPath);
  suppressed.suggestions[0].status = 'suppressed';
  fs.writeFileSync(suggestionsPath, JSON.stringify(suppressed));
  assert.equal(updateSuggestion(contact, stats, { newEvidence: true }).suggestion.status, 'suppressed');
}));
