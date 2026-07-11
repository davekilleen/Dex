'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
  parseEntityPage,
  upsertFrontmatter,
  renderPersonPage,
  renderCompanyPage,
  replaceMachineRegion,
  replaceMachineRegionInFile,
} = require('../entity-pages.cjs');

const FIXTURES = path.resolve(__dirname, '../../../core/tests/fixtures/entity_pages');

test('parse golden fixtures', () => {
  const pages = fs.readdirSync(FIXTURES).filter(name => /^\d\d-.*\.md$/.test(name)).sort();
  assert.ok(pages.length >= 10);
  for (const name of pages) {
    const expectedPath = path.join(FIXTURES, name.replace(/\.md$/, '.expected.json'));
    const expected = JSON.parse(fs.readFileSync(expectedPath, 'utf8'));
    assert.deepEqual(parseEntityPage(path.join(FIXTURES, name)), expected, name);
  }
});

test('upsert preserves unknown keys, is idempotent, and leaves no temp files', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const page = path.join(dir, 'Person.md');
  fs.writeFileSync(page, '---\ncustom: keep\nname: Old\n---\n\n# Human body\n', { mode: 0o640 });
  const fields = { type: 'person', name: 'New', emails: ['LOUD@EXAMPLE.COM'], ignored: 'no' };
  assert.equal(upsertFrontmatter(page, fields), true);
  const first = fs.readFileSync(page);
  assert.equal(upsertFrontmatter(page, fields), false);
  assert.deepEqual(fs.readFileSync(page), first);
  assert.match(first.toString(), /custom: keep/);
  assert.match(first.toString(), /loud@example\.com/);
  assert.doesNotMatch(first.toString(), /ignored/);
  assert.match(first.toString(), /---\n\n# Human body\n$/);
  assert.equal(fs.statSync(page).mode & 0o777, 0o640);
  assert.deepEqual(fs.readdirSync(dir).filter(name => name.endsWith('.tmp')), []);
});

test('quarantined page refuses upsert', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const page = path.join(dir, 'Broken.md');
  const original = '---\nname: [broken\n---\n# Broken\n**Company:** Legacy\n';
  fs.writeFileSync(page, original);
  assert.equal(parseEntityPage(page).quarantined, true);
  assert.equal(upsertFrontmatter(page, { type: 'person' }), false);
  assert.equal(fs.readFileSync(page, 'utf8'), original);
});

test('renders byte-identical golden pages', () => {
  const person = JSON.parse(fs.readFileSync(path.join(FIXTURES, 'render-person.input.json')));
  const company = JSON.parse(fs.readFileSync(path.join(FIXTURES, 'render-company.input.json')));
  assert.equal(renderPersonPage(...[
    person.name, person.role, person.company, person.emails, person.aliases, person.location, person.notes,
  ]), fs.readFileSync(path.join(FIXTURES, 'render-person.expected.md'), 'utf8'));
  assert.equal(renderCompanyPage(company.name, company.domains, company.website, company.status),
    fs.readFileSync(path.join(FIXTURES, 'render-company.expected.md'), 'utf8'));
});

test('replaces machine region in text and atomically on disk', t => {
  const original = 'Before\n<!-- dex:auto:items -->\nold\n<!-- /dex:auto -->\nAfter\n';
  const expected = 'Before\n<!-- dex:auto:items -->\nnew\nvalue\n<!-- /dex:auto -->\nAfter\n';
  assert.equal(replaceMachineRegion(original, 'items', 'new\nvalue\n'), expected);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const page = path.join(dir, 'page.md');
  fs.writeFileSync(page, original);
  assert.equal(replaceMachineRegionInFile(page, 'items', 'new\nvalue'), true);
  assert.equal(fs.readFileSync(page, 'utf8'), expected);
  assert.deepEqual(fs.readdirSync(dir).filter(name => name.endsWith('.tmp')), []);
});
