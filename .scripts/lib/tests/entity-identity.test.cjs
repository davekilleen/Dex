'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { resolveEntityPath } = require('../entity-identity.cjs');
const {
  renderCompanyPage,
  renderPersonPage,
} = require('../entity-pages.cjs');

function makeVault(t) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-entity-identity-'));
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  return vault;
}

function writePerson(vault, filename, name, emails) {
  const filePath = path.join(
    vault,
    '05-Areas',
    'People',
    'External',
    filename,
  );
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(
    filePath,
    renderPersonPage(name, '', '', emails, [], 'external'),
  );
  return filePath;
}

function writeCompany(vault, filename, name, domains) {
  const filePath = path.join(vault, '05-Areas', 'Companies', filename);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, renderCompanyPage(name, domains));
  return filePath;
}

test('an unmatched person email never falls back to a namesake', (t) => {
  const vault = makeVault(t);
  writePerson(
    vault,
    'John_Smith_Acme.md',
    'John Smith',
    ['john.smith@example.com'],
  );

  assert.equal(resolveEntityPath(vault, {
    kind: 'person',
    name: 'John Smith',
    emails: ['john.smith@example.org'],
  }), null);
});

test('an email-less person identity may resolve by a unique name', (t) => {
  const vault = makeVault(t);
  const namesake = writePerson(
    vault,
    'John_Smith.md',
    'John Smith',
    ['john.smith@example.com'],
  );

  assert.equal(resolveEntityPath(vault, {
    kind: 'person',
    name: 'John Smith',
    emails: [],
  }), namesake);
});

test('a matching person email retargets even when the name changed', (t) => {
  const vault = makeVault(t);
  const renamed = writePerson(
    vault,
    'Jane_Renamed.md',
    'Jane Renamed',
    ['jane@example.org'],
  );

  assert.equal(resolveEntityPath(vault, {
    kind: 'person',
    name: 'Jane Example',
    emails: ['jane@example.org'],
  }), renamed);
});

test('a matching company domain retargets even when the name changed', (t) => {
  const vault = makeVault(t);
  const renamed = writeCompany(
    vault,
    'Example_Collective.md',
    'Example Collective',
    ['example.com'],
  );

  assert.equal(resolveEntityPath(vault, {
    kind: 'company',
    name: 'Example Incorporated',
    domains: ['www.example.com'],
  }), renamed);
});

test('an unmatched company domain never falls back to a namesake', (t) => {
  const vault = makeVault(t);
  writeCompany(
    vault,
    'Example_Inc.md',
    'Example Inc',
    ['example.com'],
  );

  assert.equal(resolveEntityPath(vault, {
    kind: 'company',
    name: 'Example Inc',
    domains: ['example.org'],
  }), null);
});

test('two live namesakes cannot be resolved by name alone', (t) => {
  const vault = makeVault(t);
  writePerson(
    vault,
    'John_Smith_One.md',
    'John Smith',
    ['john.smith@example.com'],
  );
  writePerson(
    vault,
    'John_Smith_Two.md',
    'John Smith',
    ['john.smith@example.org'],
  );

  assert.equal(resolveEntityPath(vault, {
    kind: 'person',
    name: 'John Smith',
    emails: [],
  }), null);
});
