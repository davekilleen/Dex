'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { parseEntityPage } = require('../../lib/entity-pages.cjs');
const { loadSuggestions, processEntityCreation } = require('../lib/entity-creation.cjs');
const {
  acceptSuggestion,
  dismissSuggestion,
  listSuggestions,
  suppressSuggestion,
} = require('../lib/suggestion-actions.cjs');

function withVault(fn) {
  const previousVault = process.env.VAULT_PATH;
  const previousProject = process.env.CLAUDE_PROJECT_DIR;
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-suggestion-actions-'));
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

function personMeetings(extra = []) {
  const attendee = { name: 'Jane Doe', email: 'jane@acme.com', location: 'external' };
  return [
    { id: 'm1', createdAt: '2026-06-01T10:00:00Z', transcript: '', filteredAttendees: [attendee] },
    { id: 'm2', createdAt: '2026-06-08T10:00:00Z', transcript: '', filteredAttendees: [attendee] },
    ...extra,
  ];
}

function companyMeetings() {
  const attendees = [
    { name: 'Jane Doe', email: 'jane@acme.com', location: 'external' },
    { name: 'John Roe', email: 'john@acme.com', location: 'external' },
  ];
  return [
    { id: 'm1', createdAt: '2026-06-01T10:00:00Z', transcript: '', filteredAttendees: attendees },
    { id: 'm2', createdAt: '2026-06-08T10:00:00Z', transcript: '', filteredAttendees: attendees },
  ];
}

test('listSuggestions returns only the stable suggested-entry facade', () => withVault(() => {
  processEntityCreation(personMeetings(), { entity_creation: { mode: 'suggest' } });
  const listed = listSuggestions();
  const person = listed.find(item => item.kind === 'person');
  assert.deepEqual(Object.keys(person).sort(), ['domains', 'emails', 'id', 'kind', 'name', 'reason']);
  assert.deepEqual(person.emails, ['jane@acme.com']);
  assert.deepEqual(person.domains, []);
}));

test('accept person creates a page, marks contact created, and accepts suggestion', () => withVault(vault => {
  processEntityCreation(personMeetings(), { entity_creation: { mode: 'suggest' } });
  const suggestion = listSuggestions().find(item => item.kind === 'person');
  const result = acceptSuggestion(suggestion.id);
  assert.equal(result.page_path, '05-Areas/People/External/Jane_Doe.md');
  assert.deepEqual(parseEntityPage(path.join(vault, result.page_path)).emails, ['jane@acme.com']);
  assert.equal(loadSuggestions().suggestions.find(item => item.id === suggestion.id).status, 'accepted');
  assert.equal(listSuggestions().some(item => item.id === suggestion.id), false);
}));

test('accept company creates a page and accepts the company suggestion', () => withVault(vault => {
  processEntityCreation(companyMeetings(), { entity_creation: { mode: 'suggest' } });
  const suggestion = listSuggestions().find(item => item.kind === 'company');
  const result = acceptSuggestion(suggestion.id);
  assert.equal(result.page_path, '05-Areas/Companies/Acme.md');
  assert.deepEqual(parseEntityPage(path.join(vault, result.page_path)).domains, ['acme.com']);
  assert.equal(loadSuggestions().suggestions.find(item => item.id === suggestion.id).status, 'accepted');
}));

test('dismissed suggestion resurfaces only after new evidence', () => withVault(() => {
  processEntityCreation(personMeetings(), { entity_creation: { mode: 'suggest' } });
  const suggestion = listSuggestions().find(item => item.kind === 'person');
  assert.deepEqual(dismissSuggestion(suggestion.id), { id: suggestion.id, status: 'dismissed' });
  processEntityCreation(personMeetings(), { entity_creation: { mode: 'suggest' } });
  assert.equal(listSuggestions().some(item => item.id === suggestion.id), false);
  const newMeeting = {
    id: 'm3', createdAt: '2026-06-15T10:00:00Z', transcript: '',
    filteredAttendees: [{ name: 'Jane Doe', email: 'jane@acme.com', location: 'external' }],
  };
  processEntityCreation(personMeetings([newMeeting]), { entity_creation: { mode: 'suggest' } });
  assert.equal(listSuggestions().some(item => item.id === suggestion.id), true);
}));

test('suppressed suggestion remains suppressed after new evidence', () => withVault(() => {
  processEntityCreation(personMeetings(), { entity_creation: { mode: 'suggest' } });
  const suggestion = listSuggestions().find(item => item.kind === 'person');
  assert.deepEqual(suppressSuggestion(suggestion.id), { id: suggestion.id, status: 'suppressed' });
  const newMeeting = {
    id: 'm3', createdAt: '2026-06-15T10:00:00Z', transcript: true,
    filteredAttendees: [{ name: 'Jane Doe', email: 'jane@acme.com', location: 'external' }],
  };
  processEntityCreation(personMeetings([newMeeting]), { entity_creation: { mode: 'suggest' } });
  assert.equal(loadSuggestions().suggestions.find(item => item.id === suggestion.id).status, 'suppressed');
  assert.equal(listSuggestions().some(item => item.id === suggestion.id), false);
}));

test('all actions return JSON-able not-found errors for an unknown id', () => withVault(() => {
  for (const action of [acceptSuggestion, dismissSuggestion, suppressSuggestion]) {
    const result = action('missing');
    assert.equal(result.ok, false);
    assert.equal(result.error.code, 'not_found');
    assert.doesNotThrow(() => JSON.stringify(result));
  }
}));
