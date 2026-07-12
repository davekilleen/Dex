'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { parseEntityPage, renderCompanyPage, renderPersonPage } = require('../../lib/entity-pages.cjs');
const { loadState } = require('../lib/contacts-state.cjs');
const { loadSuggestions, processEntityCreation } = require('../lib/entity-creation.cjs');

function withVault(fn) {
  const oldVault = process.env.VAULT_PATH;
  const oldProject = process.env.CLAUDE_PROJECT_DIR;
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-creation-'));
  process.env.VAULT_PATH = vault;
  delete process.env.CLAUDE_PROJECT_DIR;
  try { return fn(vault); } finally {
    if (oldVault === undefined) delete process.env.VAULT_PATH; else process.env.VAULT_PATH = oldVault;
    if (oldProject === undefined) delete process.env.CLAUDE_PROJECT_DIR; else process.env.CLAUDE_PROJECT_DIR = oldProject;
    fs.rmSync(vault, { recursive: true, force: true });
  }
}

function meetings(location = 'external') {
  const attendee = { name: 'Jane Doe', email: 'jane@acme.com', location };
  return [
    { id: 'm1', createdAt: '2026-06-01T10:00:00Z', transcript: '', filteredAttendees: [attendee] },
    { id: 'm2', createdAt: '2026-06-08T10:00:00Z', transcript: '', filteredAttendees: [attendee] },
  ];
}

function companyMeetings(domain = 'acme.com', location = 'external') {
  const attendees = [
    { name: 'Jane Doe', email: `jane@${domain}`, location },
    { name: 'John Roe', email: `john@${domain}`, location },
  ];
  return [
    { id: 'm1', createdAt: '2026-06-01T10:00:00Z', transcript: '', filteredAttendees: attendees },
    { id: 'm2', createdAt: '2026-06-08T10:00:00Z', transcript: '', filteredAttendees: attendees },
  ];
}

test('auto mode creates one canonical external page and reruns create nothing', () => withVault(vault => {
  const first = processEntityCreation(meetings(), { entity_creation: { mode: 'auto' } });
  assert.equal(first.created.length, 1);
  const pagePath = path.join(vault, first.created[0].page_path);
  assert.deepEqual(parseEntityPage(pagePath).emails, ['jane@acme.com']);
  assert.equal(parseEntityPage(pagePath).location, 'external');
  assert.equal(processEntityCreation(meetings(), { entity_creation: { mode: 'auto' } }).created.length, 0);
}));

for (const [label, profile] of [
  ['suggest mode', { entity_creation: { mode: 'suggest' } }],
  ['missing mode', {}],
]) {
  test(`${label} writes a suggestion and no page`, () => withVault(vault => {
    const result = processEntityCreation(meetings(), profile);
    assert.equal(result.created.length, 0);
    assert.equal(loadSuggestions().suggestions[0].status, 'suggested');
    assert.equal(fs.existsSync(path.join(vault, '05-Areas', 'People', 'External', 'Jane_Doe.md')), false);
  }));
}

test('off mode records observations only', () => withVault(() => {
  const result = processEntityCreation(meetings(), { entity_creation: { mode: 'off' } });
  assert.equal(result.created.length, 0);
  assert.equal(result.suggested.length, 0);
  assert.equal(Object.keys(loadState().observations).length, 2);
  assert.equal(loadSuggestions().suggestions.length, 0);
}));

test('unknown location in auto mode is suggested, not created', () => withVault(() => {
  const result = processEntityCreation(meetings('unknown'), { entity_creation: { mode: 'auto' } });
  assert.equal(result.created.length, 0);
  assert.equal(result.suggested.length, 1);
}));

test('matching collision is adopted and a mismatched collision gets a domain suffix', () => {
  withVault(vault => {
    const directory = path.join(vault, '05-Areas', 'People', 'External');
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, 'Jane_Doe.md'), renderPersonPage('Jane Doe', null, null, ['jane@acme.com']));
    const result = processEntityCreation(meetings(), { entity_creation: { mode: 'auto' } });
    assert.equal(result.created[0].adopted, true);
    assert.equal(result.created[0].created, false);
  });
  withVault(vault => {
    const directory = path.join(vault, '05-Areas', 'People', 'External');
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, 'Jane_Doe.md'), renderPersonPage('Other Jane', null, null, ['other@else.com']));
    const result = processEntityCreation(meetings(), { entity_creation: { mode: 'auto' } });
    assert.equal(path.basename(result.created[0].filePath), 'Jane_Doe_(acme.com).md');
    assert.deepEqual(parseEntityPage(result.created[0].filePath).emails, ['jane@acme.com']);
  });
});

test('auto mode creates a canonical company page from two observed contacts', () => withVault(vault => {
  const lines = [];
  const result = processEntityCreation(
    companyMeetings(), { entity_creation: { mode: 'auto' } }, line => lines.push(line),
  );
  assert.equal(result.companies_created.length, 1);
  const companyPath = path.join(vault, '05-Areas', 'Companies', 'Acme.md');
  const company = parseEntityPage(companyPath);
  assert.equal(company.type, 'company');
  assert.deepEqual(company.domains, ['acme.com']);
  assert.match(lines.join('\n'), /Created company page:/);
}));

test('freemail, internal, and unknown-location domains never create companies', () => {
  withVault(vault => {
    const result = processEntityCreation(companyMeetings('gmail.com'), { entity_creation: { mode: 'auto' } });
    assert.equal(result.companies_created.length, 0);
    assert.equal(fs.existsSync(path.join(vault, '05-Areas', 'Companies')), false);
  });
  withVault(() => {
    const result = processEntityCreation(companyMeetings('dex.test'), {
      work_email: 'owner@dex.test', entity_creation: { mode: 'auto' },
    });
    assert.equal(result.companies_created.length, 0);
  });
  withVault(() => {
    const result = processEntityCreation(companyMeetings('acme.com', 'unknown'), {
      entity_creation: { mode: 'auto' },
    });
    assert.equal(result.companies_created.length, 0);
  });
});

test('existing company domain wins and a name collision uses a domain suffix', () => {
  withVault(vault => {
    const directory = path.join(vault, '05-Areas', 'Companies');
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, 'Existing.md'), renderCompanyPage('Existing', ['acme.com']));
    const result = processEntityCreation(companyMeetings(), { entity_creation: { mode: 'auto' } });
    assert.equal(result.companies_created.length, 0);
  });
  withVault(vault => {
    const directory = path.join(vault, '05-Areas', 'Companies');
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, 'Acme.md'), renderCompanyPage('Acme Other', ['other.com']));
    const result = processEntityCreation(companyMeetings(), { entity_creation: { mode: 'auto' } });
    assert.equal(path.basename(result.companies_created[0].filePath), 'Acme_(acme.com).md');
  });
});

test('suggest mode writes one deduplicated company suggestion', () => withVault(() => {
  const first = processEntityCreation(companyMeetings(), { entity_creation: { mode: 'suggest' } });
  const second = processEntityCreation(companyMeetings(), { entity_creation: { mode: 'suggest' } });
  assert.equal(first.companies_suggested.length, 1);
  assert.equal(second.companies_suggested.length, 1);
  const companies = loadSuggestions().suggestions.filter(item => item.kind === 'company');
  assert.equal(companies.length, 1);
  assert.deepEqual(companies[0].domains, ['acme.com']);
  assert.equal(companies[0].reason, '2 contacts across 2 meetings');
}));
