'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { parseEntityPage, renderCompanyPage, renderPersonPage } = require('../../lib/entity-pages.cjs');
const { installEntityEngineStub } = require('../../lib/tests/entity-engine-test-helper.cjs');
const { loadState } = require('../lib/contacts-state.cjs');
const { loadSuggestions, processEntityCreation } = require('../lib/entity-creation.cjs');

function withVault(fn, { python = null } = {}) {
  const oldVault = process.env.VAULT_PATH;
  const oldProject = process.env.CLAUDE_PROJECT_DIR;
  const oldPython = process.env.DEX_PYTHON;
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-creation-'));
  process.env.VAULT_PATH = vault;
  process.env.DEX_PYTHON = python || installEntityEngineStub(vault);
  delete process.env.CLAUDE_PROJECT_DIR;
  try { return fn(vault); } finally {
    if (oldVault === undefined) delete process.env.VAULT_PATH; else process.env.VAULT_PATH = oldVault;
    if (oldProject === undefined) delete process.env.CLAUDE_PROJECT_DIR; else process.env.CLAUDE_PROJECT_DIR = oldProject;
    if (oldPython === undefined) delete process.env.DEX_PYTHON; else process.env.DEX_PYTHON = oldPython;
    fs.rmSync(vault, { recursive: true, force: true });
  }
}

function installWriteThenFailStub(vault) {
  const executable = path.join(vault, 'entity-engine-write-then-fail');
  const source = [
    `#!${process.execPath}`,
    `'use strict';`,
    `if (process.argv[2] !== '-c') {`,
    `  require(${JSON.stringify(require.resolve('../../lib/tests/entity-engine-test-helper.cjs'))}).runEntityEngineStub();`,
    '  process.exitCode = 1;',
    `}`,
    '',
  ].join('\n');
  fs.writeFileSync(executable, source, 'utf8');
  fs.chmodSync(executable, 0o755);
  return executable;
}

function meetings(location = 'external', domain = 'acme.com') {
  const attendee = { name: 'Jane Doe', email: `jane@${domain}`, location };
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
  assert.equal(parseEntityPage(pagePath).touches.length, 2);
  assert.equal(processEntityCreation(meetings(), { entity_creation: { mode: 'auto' } }).created.length, 0);
}));

test('unavailable engine queues the create and does not claim the page was created', () => withVault(vault => {
  const profile = { entity_creation: { mode: 'auto' } };
  const first = processEntityCreation(
    meetings('external', 'example.com'),
    profile,
    () => {},
    { now: new Date('2026-07-01T00:00:00.000Z') },
  );
  assert.equal(first.created.length, 0);
  assert.equal(first.entity_write.ok, false);
  assert.deepEqual(first.entity_write.completed_meeting_ids, []);
  const pagePath = path.join(vault, '05-Areas', 'People', 'External', 'Jane_Doe.md');
  assert.equal(fs.existsSync(pagePath), false);
  const pendingPath = path.join(vault, 'System', '.dex', 'entity-pending.json');
  const pending = JSON.parse(fs.readFileSync(pendingPath, 'utf8'));
  assert.deepEqual(pending.batches[0].meeting_ids, ['m1', 'm2']);
  assert.equal(pending.batches[0].ops.length, 1);

  process.env.DEX_PYTHON = installEntityEngineStub(vault);
  const replay = processEntityCreation(
    [],
    profile,
    () => {},
    { now: new Date('2026-07-02T00:00:00.000Z') },
  );
  assert.equal(replay.created.length, 1);
  assert.equal(replay.entity_write.ok, true);
  assert.deepEqual(replay.entity_write.completed_meeting_ids, ['m1', 'm2']);
  assert.equal(fs.existsSync(pagePath), true);
  assert.equal(fs.existsSync(pendingPath), false);
}, { python: '/definitely/missing/dex-python' }));

test('lost engine acknowledgement is counted once when the pending create replays', () => withVault(vault => {
  const profile = { entity_creation: { mode: 'auto' } };
  process.env.DEX_PYTHON = installWriteThenFailStub(vault);
  const first = processEntityCreation(
    meetings('external', 'example.com'),
    profile,
    () => {},
    { now: new Date('2026-07-01T00:00:00.000Z') },
  );
  assert.equal(first.created.length, 0);
  assert.equal(first.entity_write.ok, false);
  const pagePath = path.join(vault, '05-Areas', 'People', 'External', 'Jane_Doe.md');
  assert.equal(fs.existsSync(pagePath), true);

  process.env.DEX_PYTHON = installEntityEngineStub(vault);
  const replay = processEntityCreation(
    [],
    profile,
    () => {},
    { now: new Date('2026-07-02T00:00:00.000Z') },
  );
  assert.equal(replay.created.length, 1);
  assert.deepEqual(replay.entity_write.completed_meeting_ids, ['m1', 'm2']);
  assert.equal(
    fs.existsSync(path.join(vault, 'System', '.dex', 'entity-pending.json')),
    false,
  );
}));

test('duplicate company effects reconcile every newly observed contact', () => withVault(vault => {
  const profile = {
    entity_creation: { mode: 'auto' },
    capabilities: { companies: { enabled: true } },
  };
  process.env.DEX_PYTHON = '/definitely/missing/dex-python';
  processEntityCreation(
    companyMeetings('example.com'),
    profile,
    () => {},
    { now: new Date('2026-07-01T00:00:00.000Z') },
  );
  const expanded = companyMeetings('example.com');
  for (const meeting of expanded) {
    meeting.id = `${meeting.id}-later`;
    meeting.filteredAttendees.push({
      name: 'Jill Poe',
      email: 'jill@example.com',
      location: 'external',
    });
  }
  processEntityCreation(
    expanded,
    profile,
    () => {},
    { now: new Date('2026-07-01T01:00:00.000Z') },
  );

  process.env.DEX_PYTHON = installEntityEngineStub(vault);
  const replay = processEntityCreation(
    [],
    profile,
    () => {},
    { now: new Date('2026-07-03T00:00:00.000Z') },
  );
  assert.equal(replay.companies_created.length, 1);
  assert.deepEqual(
    replay.entity_write.completed_meeting_ids,
    ['m1', 'm1-later', 'm2', 'm2-later'],
  );
  const jill = Object.values(loadState().contacts)
    .find(contact => contact.emails.includes('jill@example.com'));
  assert.equal(jill.company_page, '05-Areas/Companies/Example.md');
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

test('a renamed person page is adopted by email identity', () => withVault(vault => {
  const directory = path.join(vault, '05-Areas', 'People', 'External');
  fs.mkdirSync(directory, { recursive: true });
  const renamed = path.join(directory, 'Jane_Renamed.md');
  fs.writeFileSync(
    renamed,
    renderPersonPage(
      'Jane Doe',
      null,
      null,
      ['jane@example.com'],
      [],
      'external',
    ),
  );

  const result = processEntityCreation(
    meetings('external', 'example.com'),
    { entity_creation: { mode: 'auto' } },
  );

  assert.equal(result.created.length, 1);
  assert.equal(result.created[0].adopted, true);
  assert.equal(result.created[0].filePath, renamed);
  assert.equal(
    fs.existsSync(path.join(directory, 'Jane_Doe.md')),
    false,
  );
}));

test('auto mode creates a canonical company page from two observed contacts', () => withVault(vault => {
  const lines = [];
  const result = processEntityCreation(
    companyMeetings(), {
      entity_creation: { mode: 'auto' }, capabilities: { companies: { enabled: true } },
    }, line => lines.push(line),
  );
  assert.equal(result.companies_created.length, 1);
  const companyPath = path.join(vault, '05-Areas', 'Companies', 'Acme.md');
  const company = parseEntityPage(companyPath);
  assert.equal(company.type, 'company');
  assert.deepEqual(company.domains, ['acme.com']);
  assert.match(lines.join('\n'), /Created company page:/);
}));

test('batch sync logs idempotent person and company touches without fabricating no-email attendees', () => withVault(vault => {
  const attendees = [
    { name: 'Jane Doe', email: 'jane@example.com', location: 'external' },
    { name: 'John Roe', email: 'john@example.com', location: 'external' },
    { name: 'No Email', location: 'external' },
  ];
  const batch = [
    {
      id: 'touch-meeting-1',
      title: 'Roadmap Review',
      createdAt: '2026-06-01T10:00:00Z',
      transcript: '',
      filteredAttendees: attendees,
    },
    {
      id: 'touch-meeting-2',
      createdAt: '2026-06-08T10:00:00Z',
      transcript: '',
      filteredAttendees: attendees,
    },
  ];
  const profile = {
    entity_creation: { mode: 'auto' },
    capabilities: { companies: { enabled: true } },
  };

  const first = processEntityCreation(batch, profile);
  assert.equal(first.created.length, 2);
  assert.equal(first.companies_created.length, 1);

  const personPath = path.join(vault, '05-Areas', 'People', 'External', 'Jane_Doe.md');
  const companyPath = path.join(vault, '05-Areas', 'Companies', 'Example.md');
  const expectedTouches = [
    {
      ts: '2026-06-01',
      type: 'meeting',
      direction: 'none',
      source: { id: 'touch-meeting-1', title: 'Roadmap Review' },
    },
    {
      ts: '2026-06-08',
      type: 'meeting',
      direction: 'none',
      source: { id: 'touch-meeting-2', title: 'Meeting 2026-06-08' },
    },
  ];
  assert.deepEqual(parseEntityPage(personPath).touches, expectedTouches);
  assert.deepEqual(parseEntityPage(companyPath).touches, expectedTouches);
  assert.equal(parseEntityPage(personPath).last_touched, '2026-06-08');
  assert.equal(parseEntityPage(companyPath).last_touched, '2026-06-08');
  assert.equal(
    fs.existsSync(path.join(vault, '05-Areas', 'People', 'External', 'No_Email.md')),
    false,
  );

  const personOnce = fs.readFileSync(personPath);
  const companyOnce = fs.readFileSync(companyPath);
  const second = processEntityCreation(batch, profile);
  assert.deepEqual(second.created, []);
  assert.deepEqual(second.companies_created, []);
  assert.deepEqual(fs.readFileSync(personPath), personOnce);
  assert.deepEqual(fs.readFileSync(companyPath), companyOnce);
}));

test('freemail, internal, and unknown-location domains never create companies', () => {
  withVault(vault => {
    const result = processEntityCreation(companyMeetings('gmail.com'), {
      entity_creation: { mode: 'auto' }, capabilities: { companies: { enabled: true } },
    });
    assert.equal(result.companies_created.length, 0);
    assert.equal(fs.existsSync(path.join(vault, '05-Areas', 'Companies')), false);
  });
  withVault(() => {
    const result = processEntityCreation(companyMeetings('dex.test'), {
      work_email: 'owner@dex.test', entity_creation: { mode: 'auto' },
      capabilities: { companies: { enabled: true } },
    });
    assert.equal(result.companies_created.length, 0);
  });
  withVault(() => {
    const result = processEntityCreation(companyMeetings('acme.com', 'unknown'), {
      entity_creation: { mode: 'auto' }, capabilities: { companies: { enabled: true } },
    });
    assert.equal(result.companies_created.length, 0);
  });
});

test('existing company domain wins and a name collision uses a domain suffix', () => {
  withVault(vault => {
    const directory = path.join(vault, '05-Areas', 'Companies');
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, 'Existing.md'), renderCompanyPage('Existing', ['acme.com']));
    const result = processEntityCreation(companyMeetings(), {
      entity_creation: { mode: 'auto' }, capabilities: { companies: { enabled: true } },
    });
    assert.equal(result.companies_created.length, 0);
  });
  withVault(vault => {
    const directory = path.join(vault, '05-Areas', 'Companies');
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, 'Acme.md'), renderCompanyPage('Acme Other', ['other.com']));
    const result = processEntityCreation(companyMeetings(), {
      entity_creation: { mode: 'auto' }, capabilities: { companies: { enabled: true } },
    });
    assert.equal(path.basename(result.companies_created[0].filePath), 'Acme_(acme.com).md');
  });
});

test('suggest mode writes one deduplicated company suggestion', () => withVault(() => {
  const profile = {
    entity_creation: { mode: 'suggest' }, capabilities: { companies: { enabled: true } },
  };
  const first = processEntityCreation(companyMeetings(), profile);
  const second = processEntityCreation(companyMeetings(), profile);
  assert.equal(first.companies_suggested.length, 1);
  assert.equal(second.companies_suggested.length, 1);
  const companies = loadSuggestions().suggestions.filter(item => item.kind === 'company');
  assert.equal(companies.length, 1);
  assert.deepEqual(companies[0].domains, ['acme.com']);
  assert.equal(companies[0].reason, '2 contacts across 2 meetings');
}));

test('companies room off records people but neither creates nor suggests companies', () => withVault(vault => {
  const result = processEntityCreation(companyMeetings(), { entity_creation: { mode: 'auto' } });
  assert.equal(result.created.length, 2);
  assert.deepEqual(result.companies_created, []);
  assert.deepEqual(result.companies_suggested, []);
  assert.equal(fs.existsSync(path.join(vault, '05-Areas', 'Companies')), false);
}));
