'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const yaml = require('js-yaml');
const {
  extractAttendees,
  isServiceAccount,
  getInternalDomains,
  classifyAttendee,
  filterOwner,
} = require('../lib/attendees.cjs');
const {
  renderAttendeesYamlBlock,
  renderParticipants,
} = require('../sync-from-granola.cjs');

test('extractAttendees retains and normalizes email addresses', () => {
  assert.deepEqual(
    extractAttendees({ attendees: [{ name: 'Jane Doe', email: '  JANE@EXAMPLE.COM ' }] }),
    [{ name: 'Jane Doe', email: 'jane@example.com' }]
  );
});

test('extractAttendees prettifies an email-only attendee and keeps the email', () => {
  assert.deepEqual(
    extractAttendees({ attendees: [{ email: 'john.smith@example.com' }] }),
    [{ name: 'John Smith', email: 'john.smith@example.com' }]
  );
});

test('extractAttendees deduplicates name variants by email', () => {
  const attendees = extractAttendees({
    attendees: [
      { name: 'J. Smith', email: 'person@example.com' },
      { name: 'Jordan Smith', email: 'PERSON@example.com' },
    ],
  });
  assert.deepEqual(attendees, [{ name: 'J. Smith', email: 'person@example.com' }]);
});

test('service accounts mirror ritual intelligence rules and are filtered', () => {
  for (const attendee of [
    { name: 'Board Room', email: 'place@example.com' },
    { name: 'Useful Name', email: 'resource-123@example.com' },
    { name: 'Sales Group', email: null },
    { name: 'Robot', email: 'noreply@example.com' },
  ]) {
    assert.equal(isServiceAccount(attendee), true);
  }
  assert.deepEqual(extractAttendees({ attendees: [
    { name: 'Board Room', email: 'room@example.com' },
    { name: 'Actual Person', email: 'person@example.com' },
  ] }), [{ name: 'Actual Person', email: 'person@example.com' }]);
});

test('filterOwner prefers email matching over names', () => {
  const attendees = [
    { name: 'Different Display Name', email: 'owner@example.com' },
    { name: 'Owner Name', email: 'other@example.com' },
    { name: 'Guest', email: 'guest@example.com' },
  ];
  assert.deepEqual(
    filterOwner(attendees, { name: 'Owner Name', work_email: 'OWNER@example.com' }, {}),
    [attendees[1], attendees[2]]
  );
  assert.deepEqual(
    filterOwner(attendees, { name: 'Unrelated Profile' }, { email: 'OWNER@example.com' }),
    [attendees[1], attendees[2]]
  );
});

test('classification is internal, external, or unknown without guessing', () => {
  const domains = getInternalDomains({
    email_domain: ' a.com, B.com ',
    work_email: 'owner@c.com',
  });
  assert.deepEqual([...domains].sort(), ['a.com', 'b.com', 'c.com']);
  assert.equal(classifyAttendee({ email: 'one@a.com' }, domains), 'internal');
  assert.equal(classifyAttendee({ email: 'two@b.com' }, domains), 'internal');
  assert.equal(classifyAttendee({ email: 'three@elsewhere.com' }, domains), 'external');
  assert.equal(classifyAttendee({ email: null }, domains), 'unknown');
  assert.equal(classifyAttendee({ email: 'person@elsewhere.com' }, getInternalDomains({ email_domain: '' })), 'unknown');
});

test('attendees frontmatter block is valid YAML and preserves null email', () => {
  const block = renderAttendeesYamlBlock([
    { name: 'Colon: Person', email: null, location: 'unknown' },
    { name: 'Jane Doe', email: 'jane@example.com', location: 'external' },
  ]);
  assert.deepEqual(yaml.load(block), {
    attendees: [
      { name: 'Colon: Person', email: null, location: 'unknown' },
      { name: 'Jane Doe', email: 'jane@example.com', location: 'external' },
    ],
  });
});

test('participants render for Obsidian on, off, and unknown location', () => {
  const attendees = [
    { name: 'Internal Person', email: 'i@example.com', location: 'internal' },
    { name: 'External Person', email: 'e@elsewhere.com', location: 'external' },
    { name: 'Mystery Person', email: null, location: 'unknown' },
  ];
  assert.equal(
    renderParticipants(attendees, { obsidian_mode: true }),
    '[[05-Areas/People/Internal/Internal_Person|Internal Person]], '
      + '[[05-Areas/People/External/External_Person|External Person]], Mystery Person'
  );
  assert.equal(
    renderParticipants(attendees, { obsidian_mode: false }),
    'Internal Person, External Person, Mystery Person'
  );
  assert.equal(
    renderParticipants(attendees, {}),
    'Internal Person, External Person, Mystery Person'
  );
  assert.equal(
    renderParticipants([attendees[2]], { obsidian_mode: true }),
    'Mystery Person'
  );
});
