'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const yaml = require('js-yaml');
const { renderCompanyPage } = require('../../lib/entity-pages.cjs');
const { contactIdFor, recordObservations } = require('../lib/contacts-state.cjs');
const { summaryLine, verifyEntities } = require('../verify-entities.cjs');

function withVault(profile, fn) {
  const oldVault = process.env.VAULT_PATH;
  const oldProject = process.env.CLAUDE_PROJECT_DIR;
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-verify-'));
  process.env.VAULT_PATH = vault;
  delete process.env.CLAUDE_PROJECT_DIR;
  fs.mkdirSync(path.join(vault, 'System'), { recursive: true });
  fs.writeFileSync(path.join(vault, 'System', 'user-profile.yaml'), yaml.dump(profile));
  try { return fn(vault); } finally {
    if (oldVault === undefined) delete process.env.VAULT_PATH; else process.env.VAULT_PATH = oldVault;
    if (oldProject === undefined) delete process.env.CLAUDE_PROJECT_DIR; else process.env.CLAUDE_PROJECT_DIR = oldProject;
    fs.rmSync(vault, { recursive: true, force: true });
  }
}

function writeMeeting(vault, attendees, date = '2026-06-10') {
  const directory = path.join(vault, '00-Inbox', 'Meetings', date);
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, 'meeting.md'), `---\n${yaml.dump({
    date,
    attendees,
  })}---\n# Meeting\n`);
}

test('verification resolves every outcome class and writes the report', () => withVault(
  { entity_creation: { mode: 'auto' } },
  vault => {
    const attendees = [
      { name: 'Page Person', email: 'page@example.com', location: 'external' },
      { name: 'Suggested Person', email: 'suggested@example.com', location: 'external' },
      { name: 'Dismissed Person', email: 'dismissed@example.com', location: 'external' },
      { name: 'Suppressed Person', email: 'suppressed@example.com', location: 'external' },
      { name: 'Tracking Person', email: 'tracking@example.com', location: 'external' },
      { name: 'Mystery Person', email: null, location: 'unknown' },
    ];
    writeMeeting(vault, attendees);
    recordObservations('m1', { date: '2026-06-01', hasTranscript: false, attendees });
    recordObservations('m2', { date: '2026-06-08', hasTranscript: false, attendees: attendees.slice(0, 4) });

    const peopleDirectory = path.join(vault, '05-Areas', 'People', 'External');
    fs.mkdirSync(peopleDirectory, { recursive: true });
    fs.writeFileSync(path.join(peopleDirectory, 'Page_Person.md'), '# Page Person\n');
    const suggestionDirectory = path.join(vault, 'System', '.dex');
    fs.mkdirSync(suggestionDirectory, { recursive: true });
    fs.writeFileSync(path.join(suggestionDirectory, 'entity-suggestions.json'), JSON.stringify({
      version: 1,
      suggestions: [
        ['Suggested Person', 'suggested@example.com', 'suggested'],
        ['Dismissed Person', 'dismissed@example.com', 'dismissed'],
        ['Suppressed Person', 'suppressed@example.com', 'suppressed'],
      ].map(([name, email, status]) => ({ id: contactIdFor({ name, email }), name, email, status })),
    }));

    const { report, summary } = verifyEntities({ days: 14, now: new Date('2026-06-10T12:00:00Z') });
    assert.deepEqual(report.counts, {
      page: 1,
      suggested: 1,
      dismissed: 1,
      suppressed: 1,
      tracking: 1,
      unverified_identity: 1,
      disabled: 0,
    });
    assert.match(summary, /^entities: 6 attendees -> .*; \d+ unresolved; companies: .*$/);
    const written = JSON.parse(fs.readFileSync(path.join(suggestionDirectory, 'entity-verification.json')));
    assert.equal(written.mode, 'auto');
    assert.equal(written.window_days, 14);
  },
));

test('off mode resolves an emailed attendee as disabled', () => withVault(
  { entity_creation: { mode: 'off' } },
  vault => {
    writeMeeting(vault, [{ name: 'Disabled Person', email: 'disabled@example.com', location: 'external' }]);
    const { report } = verifyEntities({ now: new Date('2026-06-10T12:00:00Z') });
    assert.equal(report.counts.disabled, 1);
    assert.equal(report.companies.counts.disabled, 1);
  },
));

test('auto mode reports a qualified routable contact without a page as unresolved', () => withVault(
  { entity_creation: { mode: 'auto' } },
  vault => {
    const attendee = { name: 'Missing Person', email: 'missing@example.com', location: 'external' };
    writeMeeting(vault, [attendee]);
    recordObservations('m1', { date: '2026-06-01', hasTranscript: false, attendees: [attendee] });
    recordObservations('m2', { date: '2026-06-08', hasTranscript: false, attendees: [attendee] });
    const { report } = verifyEntities({ days: 14, now: new Date('2026-06-10T12:00:00Z') });
    const personUnresolved = report.unresolved.filter(item => item.kind !== 'company');
    assert.equal(personUnresolved.length, 1);
    assert.match(personUnresolved[0].why, /qualified external contact/);
  },
));

test('summary line has the stable one-line format', () => {
  const report = {
    attendees: 12,
    counts: { page: 8, suggested: 2, dismissed: 0, suppressed: 0, tracking: 1, unverified_identity: 1, disabled: 0 },
    unresolved: [],
  };
  assert.equal(summaryLine(report), 'entities: 12 attendees -> 8 pages, 2 suggested, 1 tracking, 1 no-email; 0 unresolved; companies: 0 pages');
});

test('dead letters make entity verification observably broken with a fix path', () => withVault(
  { entity_creation: { mode: 'auto' } },
  vault => {
    const runtime = path.join(vault, 'System', '.dex');
    fs.mkdirSync(runtime, { recursive: true });
    fs.writeFileSync(
      path.join(runtime, 'entity-dead-letter.jsonl'),
      `{"dead_letter_id":\n${JSON.stringify({
        dead_letter_id: 'example-dead-letter',
        meeting_id: 'meeting-1',
        meeting_ids: ['meeting-1'],
        op_type: 'mutate',
        entity_path: path.join(
          vault,
          '05-Areas',
          'People',
          'External',
          'Jane_Example.md',
        ),
        entity_identity: {
          kind: 'person',
          name: 'Jane Example',
          emails: ['jane@example.com'],
        },
        reason: 'target page missing',
      })}\n`,
    );

    const result = verifyEntities({
      now: new Date('2026-06-10T12:00:00Z'),
    });

    assert.equal(result.feature_status, 'broken');
    assert.equal(result.success, false);
    assert.match(result.user_message, /1 entity write/i);
    assert.match(result.user_message, /System\/\.dex\/entity-dead-letter\.jsonl/);
    assert.match(result.user_message, /\/dex-doctor/);
    assert.match(result.user_message, /re-queue/i);
    assert.equal(result.report.dead_letter_count, 1);
    assert.match(result.summary, /1 entity write failed permanently/i);
  },
));

test('stale paths.json missing ENTITY_VERIFICATION_FILE still writes the report', () => withVault(
  { entity_creation: { mode: 'auto' } },
  vault => {
    const coreDir = path.join(vault, 'core');
    fs.mkdirSync(coreDir, { recursive: true });
    // A generated paths.json from before ENTITY_VERIFICATION_FILE existed.
    // Granola sync used to throw "The path argument must be of type string.
    // Received undefined" and skip verification.
    fs.writeFileSync(path.join(coreDir, 'paths.json'), JSON.stringify({
      VAULT_ROOT: vault,
      MEETINGS_DIR: path.join(vault, '00-Inbox', 'Meetings'),
      PEOPLE_DIR: path.join(vault, '05-Areas', 'People'),
      COMPANIES_DIR: path.join(vault, '05-Areas', 'Companies'),
      USER_PROFILE_FILE: path.join(vault, 'System', 'user-profile.yaml'),
      CONTACTS_STATE_FILE: path.join(vault, 'System', '.dex', 'contacts.json'),
      ENTITY_SUGGESTIONS_FILE: path.join(vault, 'System', '.dex', 'entity-suggestions.json'),
      ENTITY_PENDING_FILE: path.join(vault, 'System', '.dex', 'entity-pending.json'),
    }));

    writeMeeting(vault, [{ name: 'Stale Path Person', email: 'stale@example.com', location: 'external' }]);
    const { report } = verifyEntities({ now: new Date('2026-06-10T12:00:00Z') });
    const written = JSON.parse(fs.readFileSync(
      path.join(vault, 'System', '.dex', 'entity-verification.json'),
    ));
    assert.equal(report.counts.tracking, 1);
    assert.equal(written.mode, 'auto');
    assert.ok(written.generated_at);
  },
));

test('company verification reports pages, suggestions, tracking, and auto invariant', () => withVault(
  { work_email: 'owner@dex.test', entity_creation: { mode: 'auto' } },
  vault => {
    const attendees = [
      { name: 'Acme One', email: 'one@acme.com', location: 'external' },
      { name: 'Beta One', email: 'one@beta.com', location: 'external' },
      { name: 'Gamma One', email: 'one@gamma.com', location: 'external' },
      { name: 'Free Mail', email: 'free@gmail.com', location: 'external' },
      { name: 'Internal', email: 'inside@dex.test', location: 'internal' },
    ];
    writeMeeting(vault, attendees);
    recordObservations('m1', { date: '2026-06-01', hasTranscript: false, attendees });
    recordObservations('m2', { date: '2026-06-08', hasTranscript: false, attendees });

    const companies = path.join(vault, '05-Areas', 'Companies');
    fs.mkdirSync(companies, { recursive: true });
    fs.writeFileSync(path.join(companies, 'Acme.md'), renderCompanyPage('Acme', ['acme.com']));
    const runtime = path.join(vault, 'System', '.dex');
    fs.mkdirSync(runtime, { recursive: true });
    fs.writeFileSync(path.join(runtime, 'entity-suggestions.json'), JSON.stringify({
      version: 1,
      suggestions: [{ id: 'domain:beta.com', kind: 'company', status: 'suggested' }],
    }));

    const { report, summary } = verifyEntities({ days: 14, now: new Date('2026-06-10T12:00:00Z') });
    assert.deepEqual(report.companies.counts, { page: 1, suggested: 1, tracking: 1, disabled: 0 });
    assert.deepEqual(report.companies.domains.map(item => [item.domain, item.outcome]), [
      ['acme.com', 'page'], ['beta.com', 'suggested'], ['gamma.com', 'tracking'],
    ]);
    assert.equal(report.unresolved.filter(item => item.kind === 'company').length, 1);
    assert.equal(report.unresolved.find(item => item.kind === 'company').domain, 'gamma.com');
    assert.match(summary, /companies: 1 page, 1 suggested, 1 tracking$/);
  },
));
