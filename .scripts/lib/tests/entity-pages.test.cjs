'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const yaml = require('js-yaml');
const {
  mergeFrontmatterText,
  parseEntityPage,
  readFrontmatterField,
  relationshipEdgeKey,
  renderRelationships,
  renderUpdateLog,
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

test('parseEntityPage reads touches only from valid frontmatter', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const page = path.join(dir, 'Touched.md');
  const touches = [{
    ts: '2026-07-22',
    type: 'meeting',
    direction: 'none',
    source: { id: 'meeting-1', title: 'Roadmap' },
  }];
  fs.writeFileSync(page, [
    '---',
    'type: person',
    `touches: ${JSON.stringify(touches)}`,
    'last_touched: 2026-07-22',
    '---',
    '# Touched',
    '',
  ].join('\n'));
  assert.deepEqual(parseEntityPage(page).touches, touches);
  assert.equal(parseEntityPage(page).last_touched, '2026-07-22');
  assert.deepEqual(readFrontmatterField(fs.readFileSync(page, 'utf8'), 'touches'), touches);

  const unquoted = path.join(dir, 'Unquoted.md');
  fs.writeFileSync(unquoted, [
    '---', 'type: person', 'touches:', '  - ts: 2026-07-22',
    '    type: meeting', '    source: {id: meeting-1}',
    'last_touched: 2026-07-22', '---', '# Unquoted', '',
  ].join('\n'));
  assert.equal(parseEntityPage(unquoted).touches[0].ts, '2026-07-22');
  assert.equal(readFrontmatterField(
    fs.readFileSync(unquoted, 'utf8'), 'touches',
  )[0].ts, '2026-07-22');

  const malformed = path.join(dir, 'Malformed.md');
  fs.writeFileSync(malformed, [
    '---', 'type: person', 'touches: nope', 'last_touched: [bad]', '---',
    '# Malformed', '', '**Touches:** legacy must be ignored', '',
  ].join('\n'));
  assert.deepEqual(parseEntityPage(malformed).touches, []);
  assert.equal(parseEntityPage(malformed).last_touched, null);
  assert.deepEqual(readFrontmatterField(fs.readFileSync(malformed, 'utf8'), 'touches'), []);
});

test('renderUpdateLog matches the canonical golden bytes deterministically', () => {
  const input = {
    touches: [{
      ts: '2026-07-22T10:00:00Z',
      type: 'meeting',
      direction: 'none',
      source: { id: 'meeting-2', title: 'Roadmap' },
    }],
    relationshipProvenance: [{
      recorded_at: '2026-07-21T09:00:00Z',
      type: 'reports_to',
      target: '05-Areas/People/Internal/Alex.md',
      source: { id: 'meeting-1', title: 'Weekly 1:1' },
    }],
    creationMetadata: {
      created_at: '2026-07-20T08:00:00Z',
      source: { id: 'ritual', title: 'Ritual Intelligence' },
    },
  };
  const expected = [
    '- 2026-07-20 — created — Ritual Intelligence [ritual]',
    '- 2026-07-21 — relationship · reports_to — 05-Areas/People/Internal/Alex.md — Weekly 1:1 [meeting-1]',
    '- 2026-07-22 — meeting · two-way — Roadmap [meeting-2]',
  ].join('\n');
  assert.equal(renderUpdateLog(input), expected);
  assert.equal(renderUpdateLog({ ...input, touches: [...input.touches].reverse() }), expected);
  assert.equal(renderUpdateLog({
    touches: [{
      ts: '2026-07-23',
      type: 'meeting',
      direction: 'none',
      source: { id: ' meeting  3 ', title: ' Product\n review ' },
      nature: ' Agreed\n  next steps. ',
    }],
  }), '- 2026-07-23 — meeting · two-way — Product review [meeting 3] — Agreed next steps.');
});

test('renderRelationships matches the canonical grouped bytes deterministically', () => {
  const relationships = [
    {
      type: 'related_to',
      target: '[[Zoe]]',
      status: 'suggested',
      source: { kind: 'co-attendance', id: 'meeting-2' },
      date: '2026-07-23',
    },
    {
      type: 'works_at',
      target: '[[Beta Co]]',
      status: 'confirmed',
      source: { kind: 'manual', id: 'confirmation-1' },
      date: '2026-07-22',
    },
    {
      type: 'works_at',
      target: '[[Acme]]',
      status: 'suggested',
      source: { kind: 'domain-match', id: 'acme.test' },
      date: '2026-07-21',
    },
  ];
  const expected = [
    '### works_at',
    '- [[Acme]] (suggested)',
    '- [[Beta Co]]',
    '',
    '### related_to',
    '- [[Zoe]] (suggested)',
  ].join('\n');

  assert.equal(renderRelationships(relationships), expected);
  assert.equal(renderRelationships([...relationships].reverse()), expected);
  assert.throws(
    () => renderRelationships([{ ...relationships[0], type: 'invented_relation' }]),
    /unknown relationship type/,
  );
});

test('relationship frontmatter is owned and round-trips through the JS twin', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const page = path.join(dir, 'Related.md');
  const relationships = [{
    type: 'works_at',
    target: '[[Acme]]',
    status: 'suggested',
    source: { kind: 'domain-match', id: 'acme.test' },
    date: '2026-07-23',
  }];
  fs.writeFileSync(page, '# Related\n');

  assert.equal(upsertFrontmatter(page, { relationships }), true);
  assert.deepEqual(parseEntityPage(page).relationships, relationships);
  assert.deepEqual(
    readFrontmatterField(fs.readFileSync(page, 'utf8'), 'relationships'),
    relationships,
  );
});

test('per-edge ownership, tombstones, stale fallback, and NFC identity merge in the JS twin', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-relationships-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const page = path.join(dir, 'Related.md');
  const relationship = (target, overrides = {}) => ({
    type: 'works_at',
    target,
    status: 'suggested',
    source: { kind: 'domain-match', id: 'acme.test' },
    date: '2026-07-23',
    ...overrides,
  });
  const confirmed = relationship('[[Acme]]', { status: 'confirmed' });
  const beta = relationship('[[Beta]]', {
    source: { kind: 'domain-match', id: 'beta.test' },
  });
  fs.writeFileSync(page, [
    '---',
    'type: person',
    'name: Related Person',
    'relationships:',
    '  - type: works_at',
    '    target: "[[Acme]]"',
    '    status: suggested',
    '    source: {kind: domain-match, id: acme.test}',
    "    date: '2026-07-23'",
    'dex_pinned: {relationships: user}',
    'dex_last_written:',
    '  relationships:',
    '    - type: works_at',
    '      target: "[[Acme]]"',
    '      status: suggested',
    '      source: {kind: domain-match, id: acme.test}',
    "      date: '2026-07-23'",
    '---',
    '# Related Person',
    '',
  ].join('\n'));

  assert.equal(upsertFrontmatter(page, {
    relationships: [
      relationship('[[Cafe\u0301]]'),
      relationship('[[Café]]', { source: { kind: 'domain-match', id: 'nfc' } }),
      beta,
    ],
  }), true);
  const merged = yaml.load(fs.readFileSync(page, 'utf8').split('---', 2)[1]);
  assert.deepEqual(merged.relationships, [
    confirmed,
    relationship('[[Cafe\u0301]]'),
    beta,
  ]);
  assert.equal(Object.hasOwn(merged.dex_pinned, 'relationships'), false);
  assert.equal(relationshipEdgeKey(relationship('[[Café]]')), 'works_at::[[café]]');

  const tombstoned = mergeFrontmatterText(page, [
    '---',
    'type: person',
    'relationships: []',
    'dex_pinned: {}',
    'dex_last_written: {relationships: []}',
    'dex_dismissed_relationships:',
    '  - {key: "works_at::[[acme]]", date: "2026-07-24"}',
    '---',
    '# Related',
    '',
  ].join('\n'), { relationships: [relationship('[[Acme]]')] });
  const dismissed = yaml.load(tombstoned.split('---', 2)[1]);
  assert.deepEqual(dismissed.relationships, []);
  assert.deepEqual(dismissed.dex_dismissed_relationships, [
    { key: 'works_at::[[acme]]', date: '2026-07-24' },
  ]);

  const stale = mergeFrontmatterText(page, [
    '---',
    'type: person',
    'relationships:',
    '  - type: works_at',
    '    target: "[[Acme]]"',
    '    status: suggested',
    '    source: {kind: domain-match, id: acme.test}',
    "    date: '2026-07-23'",
    'dex_pinned: {}',
    'dex_last_written: {type: person}',
    '---',
    '# Related',
    '',
  ].join('\n'), { relationships: [beta] });
  assert.deepEqual(yaml.load(stale.split('---', 2)[1]).relationships, [
    relationship('[[Acme]]'),
    beta,
  ]);

  const reliableBase = [
    '---',
    'type: person',
    'relationships:',
    '  - type: works_at',
    '    target: "[[Acme]]"',
    '    status: suggested',
    '    source: {kind: domain-match, id: acme.test}',
    "    date: '2026-07-23'",
    'dex_pinned: {}',
    'dex_last_written:',
    '  relationships:',
    '    - type: works_at',
    '      target: "[[Acme]]"',
    '      status: suggested',
    '      source: {kind: domain-match, id: acme.test}',
    "      date: '2026-07-23'",
    '---',
    '# Related',
    '',
  ].join('\n');

  const handDeleted = reliableBase.replace(
    /relationships:\n(?:  .+\n)+dex_pinned:/,
    'relationships: []\ndex_pinned:',
  );
  const handDeleteMerge = yaml.load(
    mergeFrontmatterText(page, handDeleted, {
      relationships: [relationship('[[Acme]]')],
    }).split('---', 2)[1],
  );
  assert.deepEqual(handDeleteMerge.relationships, []);
  assert.equal(
    handDeleteMerge.dex_dismissed_relationships[0].key,
    'works_at::[[acme]]',
  );

  const retargeted = yaml.load(
    mergeFrontmatterText(
      page,
      reliableBase,
      { relationships: [relationship('[[Beta]]')] },
      { relationshipRemovedKeys: ['works_at::[[acme]]'] },
    ).split('---', 2)[1],
  );
  assert.deepEqual(retargeted.relationships, [relationship('[[Beta]]')]);
  assert.equal(retargeted.dex_dismissed_relationships, undefined);

  const relabelledCurrent = reliableBase.replace(
    /type: works_at\n    target: "\[\[Acme\]\]"/,
    'type: related_to\n    target: "[[Acme]]"',
  );
  const relabelled = relationship(
    '[[Acme]]',
    { type: 'related_to' },
  );
  const relabelMerge = yaml.load(
    mergeFrontmatterText(page, relabelledCurrent, {
      relationships: [relabelled],
    }).split('---', 2)[1],
  );
  assert.deepEqual(relabelMerge.relationships, [relabelled]);
  assert.equal(
    relabelMerge.dex_dismissed_relationships[0].key,
    'works_at::[[acme]]',
  );
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
  assert.doesNotMatch(first.toString(), /dex_pinned/);
  assert.doesNotMatch(first.toString(), /dex_last_written/);
  assert.match(first.toString(), /---\n\n# Human body\n$/);
  assert.equal(fs.statSync(page).mode & 0o777, 0o640);
  assert.deepEqual(fs.readdirSync(dir).filter(name => name.endsWith('.tmp')), []);
});

test('upsert pins diverged fields while non-pinned fields and v2 metadata keep updating', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const page = path.join(dir, 'Person.md');
  fs.writeFileSync(page, [
    '---', 'type: person', 'name: Jane Doe', 'role: User-authored role', 'company: Old Co',
    'dex_last_written:', '  type: person', '  name: Jane Doe', '  role: Dex role',
    '  company: Old Co', '---', '# Jane Doe', '',
  ].join('\n'));

  const fields = {
    role: 'New Dex role',
    company: 'New Co',
    last_touched: '2026-07-22T12:00:00Z',
    touches: [{ ts: '2026-07-22T12:00:00Z', type: 'meeting' }],
  };
  assert.equal(upsertFrontmatter(page, fields), true);
  const first = fs.readFileSync(page);
  const frontmatter = yaml.load(fs.readFileSync(page, 'utf8').split('---', 2)[1]);
  assert.equal(frontmatter.role, 'User-authored role');
  assert.deepEqual(frontmatter.dex_pinned, { role: 'user' });
  assert.equal(frontmatter.dex_last_written.role, 'Dex role');
  assert.equal(frontmatter.company, 'New Co');
  assert.equal(frontmatter.dex_last_written.company, 'New Co');
  assert.equal(frontmatter.last_touched, '2026-07-22T12:00:00Z');
  assert.deepEqual(frontmatter.touches, [{ ts: '2026-07-22T12:00:00Z', type: 'meeting' }]);
  assert.equal(upsertFrontmatter(page, fields), false);
  assert.deepEqual(fs.readFileSync(page), first);
});

test('upsert never overwrites an explicitly pinned field', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const page = path.join(dir, 'Person.md');
  fs.writeFileSync(page, '---\nrole: Founder\ncompany: Old Co\ndex_pinned: {role: user}\n---\n# Person\n');
  assert.equal(upsertFrontmatter(page, { role: 'CEO', company: 'New Co' }), true);
  const frontmatter = yaml.load(fs.readFileSync(page, 'utf8').split('---', 2)[1]);
  assert.equal(frontmatter.role, 'Founder');
  assert.equal(frontmatter.company, 'New Co');
});

test('upsert preserves malformed v2 metadata without enabling ownership', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const page = path.join(dir, 'Person.md');
  fs.writeFileSync(page, '---\ncompany: Old Co\ndex_pinned: [role]\n---\n# Person\n');
  assert.equal(upsertFrontmatter(page, { company: 'New Co' }), true);
  const frontmatter = yaml.load(fs.readFileSync(page, 'utf8').split('---', 2)[1]);
  assert.equal(frontmatter.company, 'New Co');
  assert.deepEqual(frontmatter.dex_pinned, ['role']);
  assert.equal(Object.hasOwn(frontmatter, 'dex_last_written'), false);
});

test('first v2 write conservatively pins legacy facts', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const page = path.join(dir, 'Legacy.md');
  fs.writeFileSync(page, '# User Name\n\n**Role:** User-authored role\n**Company:** Old Co\n');
  const fields = {
    type: 'person',
    name: 'Incoming Name',
    role: 'Incoming role',
    company: 'New Co',
    last_touched: '2026-07-22T12:00:00Z',
  };
  assert.equal(upsertFrontmatter(page, fields), true);
  const frontmatter = yaml.load(fs.readFileSync(page, 'utf8').split('---', 2)[1]);
  assert.deepEqual(frontmatter.dex_pinned, {
    role: 'user', company: 'user',
  });
  assert.equal(parseEntityPage(page).name, 'Incoming Name');
  assert.equal(parseEntityPage(page).type, 'person');
  assert.equal(parseEntityPage(page).role, 'User-authored role');
  assert.equal(parseEntityPage(page).company, 'Old Co');
  assert.equal(frontmatter.last_touched, '2026-07-22T12:00:00Z');
  const first = fs.readFileSync(page);
  assert.equal(upsertFrontmatter(page, fields), false);
  assert.deepEqual(fs.readFileSync(page), first);
});

test('first v2 write pins nonempty raw values before canonical validation', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const cases = [
    {
      field: 'location',
      original: '---\nlocation: London\n---\n# Person\n',
      fields: { location: 'external', last_touched: '2026-07-22T12:00:00Z' },
      rawValue: 'London',
    },
    {
      field: 'last_interaction',
      original: '# Person\n\n**Last interaction:** last summer\n',
      fields: { last_interaction: '2026-07-22', last_touched: '2026-07-22T12:00:00Z' },
      rawValue: '**Last interaction:** last summer',
    },
    {
      field: 'type',
      original: '# Person\n\n| **type** | colleague |\n',
      fields: { type: 'person', last_touched: '2026-07-22T12:00:00Z' },
      rawValue: '| **type** | colleague |',
    },
  ];

  for (const { field, original, fields, rawValue } of cases) {
    const page = path.join(dir, `Legacy-${field}.md`);
    fs.writeFileSync(page, original);

    assert.equal(upsertFrontmatter(page, fields), true);
    const updated = fs.readFileSync(page, 'utf8');
    const frontmatter = yaml.load(updated.split('---', 2)[1]);

    assert.equal(frontmatter.dex_pinned[field], 'user');
    if (field === 'location') {
      assert.equal(frontmatter[field], rawValue);
    } else {
      assert.equal(Object.hasOwn(frontmatter, field), false);
      assert.match(updated, new RegExp(rawValue.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    }
  }
});

test('upsert safely handles legacy, empty, and BOM pages and is idempotent', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'entity-pages-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));

  const legacy = path.join(dir, 'Legacy.md');
  const legacyBody = '# Legacy\n\n**Role:** Human-authored role\n';
  fs.writeFileSync(legacy, legacyBody);
  assert.equal(upsertFrontmatter(legacy, { type: 'person', name: 'Legacy' }), true);
  assert.ok(fs.readFileSync(legacy, 'utf8').endsWith(legacyBody));
  const legacyFirst = fs.readFileSync(legacy);
  assert.equal(upsertFrontmatter(legacy, { type: 'person', name: 'Legacy' }), false);
  assert.deepEqual(fs.readFileSync(legacy), legacyFirst);

  const empty = path.join(dir, 'Empty.md');
  fs.writeFileSync(empty, '');
  assert.equal(upsertFrontmatter(empty, { type: 'person', name: 'Empty' }), true);
  const emptyFirst = fs.readFileSync(empty);
  assert.equal(upsertFrontmatter(empty, { type: 'person', name: 'Empty' }), false);
  assert.deepEqual(fs.readFileSync(empty), emptyFirst);

  const bom = path.join(dir, 'Bom.md');
  fs.writeFileSync(bom, Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from('---\nname: Old\n---\n# Old\n')]));
  assert.equal(upsertFrontmatter(bom, { type: 'person', name: 'New' }), true);
  assert.deepEqual([...fs.readFileSync(bom).subarray(0, 3)], [0xef, 0xbb, 0xbf]);
  const bomFirst = fs.readFileSync(bom);
  assert.equal(upsertFrontmatter(bom, { type: 'person', name: 'New' }), false);
  assert.deepEqual(fs.readFileSync(bom), bomFirst);
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
  const renderedPerson = renderPersonPage(...[
    person.name, person.role, person.company, person.emails, person.aliases, person.location, person.notes,
  ]);
  const renderedCompany = renderCompanyPage(company.name, company.domains, company.website, company.status);
  assert.ok(renderedPerson.indexOf('## Relationships') < renderedPerson.indexOf('## Update Log'));
  assert.ok(renderedCompany.indexOf('## Relationships') < renderedCompany.indexOf('## Update Log'));
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
