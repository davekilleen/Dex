/**
 * Tests for auto-link-people.cjs — the script CLAUDE.md mandates running on
 * every generated vault file. It rewrites user markdown in place, so the
 * safe-zone and ambiguity rules are load-bearing.
 *
 * Run with: node --test .scripts/tests/*.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  autoLinkContent,
  buildRegistry,
  buildLinkMaps,
  splitSafeZones,
  findUnknownFullNames,
} = require('../auto-link-people.cjs');

function makeVault(people) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-autolink-'));
  for (const [relPath, content] of Object.entries(people)) {
    const abs = path.join(vault, relPath);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return vault;
}

const STANDARD_VAULT = makeVault({
  'People/External/Jane_Roe.md': '# Jane Roe\n',
  'People/Internal/Aaron_Fry.md': '---\nname: Aaron Fry\n---\n# Aaron Fry\n',
  // Two Sams — first-name linking for "Sam" must be suppressed as ambiguous
  'People/Internal/Sam_Hill.md': '# Sam Hill\n',
  'People/External/Sam_Cooke.md': '# Sam Cooke\n',
});

const link = (content) => autoLinkContent(content, { vaultRoot: STANDARD_VAULT });

test('registry maps filename stems and frontmatter names', () => {
  const people = buildRegistry(STANDARD_VAULT);
  const aaron = people.find((p) => p.wikiTarget === 'Aaron_Fry');
  assert.equal(aaron.fullName, 'Aaron Fry');
  assert.equal(aaron.firstName, 'Aaron');
  const jane = people.find((p) => p.wikiTarget === 'Jane_Roe');
  assert.equal(jane.fullName, 'Jane Roe'); // derived from stem
});

test('full names become alias wikilinks', () => {
  assert.equal(
    link('Met with Jane Roe about pricing.'),
    'Met with [[Jane_Roe|Jane Roe]] about pricing.'
  );
});

test('unambiguous first name links, ambiguous first name does not', () => {
  assert.equal(link('Ping Aaron tomorrow.'), 'Ping [[Aaron_Fry|Aaron]] tomorrow.');
  // "Sam" maps to two people — must stay plain text
  assert.equal(link('Ping Sam tomorrow.'), 'Ping Sam tomorrow.');
});

test('existing wikilinks are not double-wrapped', () => {
  const original = 'Met with [[Jane_Roe|Jane Roe]] again.';
  assert.equal(link(original), original);
});

test('frontmatter is never modified', () => {
  const original = '---\nowner: Jane Roe\n---\nBody mentions Jane Roe.\n';
  const result = link(original);
  assert.match(result, /^---\nowner: Jane Roe\n---\n/);
  assert.match(result, /Body mentions \[\[Jane_Roe\|Jane Roe\]\]\./);
});

test('code blocks and inline code are never modified', () => {
  const original = 'Jane Roe said:\n```\nJane Roe = attendee\n```\nAlso `Jane Roe` inline.';
  const result = link(original);
  assert.match(result, /```\nJane Roe = attendee\n```/);
  assert.match(result, /`Jane Roe` inline/);
  assert.match(result, /^\[\[Jane_Roe\|Jane Roe\]\] said:/);
});

test('markdown links and URLs are never modified', () => {
  const original = 'See [Jane Roe profile](https://example.com/Jane_Roe) and https://x.com/Jane_Roe';
  assert.equal(link(original), original);
});

test('first name is suppressed when doc contains an unknown full name', () => {
  // "Aaron Jolly" is not in the registry, so a standalone "Aaron" elsewhere
  // in the same doc could be that person — do not link it.
  const original = 'Aaron Jolly joined. Aaron will follow up.';
  const result = link(original);
  assert.ok(!result.includes('[[Aaron_Fry|Aaron]]'), `unexpected link in: ${result}`);
});

test('empty registry leaves content unchanged', () => {
  const emptyVault = makeVault({});
  assert.equal(
    autoLinkContent('Met with Jane Roe.', { vaultRoot: emptyVault }),
    'Met with Jane Roe.'
  );
});

test('splitSafeZones round-trips content exactly', () => {
  const content = '---\na: 1\n---\ntext [[Link]] `code`\n```\nfence\n```\nmore https://a.b end';
  const segments = splitSafeZones(content);
  assert.equal(segments.map((s) => s.text).join(''), content);
  assert.ok(segments.some((s) => s.safe));
  assert.ok(segments.some((s) => !s.safe));
});

test('findUnknownFullNames flags first names followed by surnames', () => {
  const people = buildRegistry(STANDARD_VAULT);
  const { firstNameMap } = buildLinkMaps(people);
  const suspicious = findUnknownFullNames('Aaron Jolly attended.', firstNameMap);
  assert.ok(suspicious.has('aaron'));
  assert.equal(findUnknownFullNames('aaron lowercase pair.', firstNameMap).size, 0);
});
