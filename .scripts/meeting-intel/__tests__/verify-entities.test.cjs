'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const yaml = require('js-yaml');
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
    assert.match(summary, /^entities: 6 attendees -> .*; \d+ unresolved$/);
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
    assert.equal(report.unresolved.length, 1);
    assert.match(report.unresolved[0].why, /qualified external contact/);
  },
));

test('summary line has the stable one-line format', () => {
  const report = {
    attendees: 12,
    counts: { page: 8, suggested: 2, dismissed: 0, suppressed: 0, tracking: 1, unverified_identity: 1, disabled: 0 },
    unresolved: [],
  };
  assert.equal(summaryLine(report), 'entities: 12 attendees -> 8 pages, 2 suggested, 1 tracking, 1 no-email; 0 unresolved');
});
