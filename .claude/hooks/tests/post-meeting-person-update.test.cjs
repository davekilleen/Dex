const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK = path.resolve(__dirname, '../post-meeting-person-update.cjs');

function createVault(t) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-person-update-'));
  for (const directory of [
    '00-Inbox/Meetings',
    '05-Areas/People/Internal',
    '05-Areas/People/External',
    '05-Areas/People/CPO_Network',
    '05-Areas/Companies',
  ]) fs.mkdirSync(path.join(vault, directory), { recursive: true });
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  return vault;
}

function runHook(vault, payload) {
  return spawnSync(process.execPath, [HOOK], {
    cwd: vault,
    encoding: 'utf8',
    env: {
      CLAUDE_PROJECT_DIR: vault,
      DEX_HOOK_DEBUG: '1',
      PATH: '/usr/bin:/bin',
      VAULT_PATH: vault,
    },
    input: typeof payload === 'string' ? payload : JSON.stringify(payload),
  });
}

function personPage(name, region = true) {
  return [
    '---',
    'type: person',
    `name: ${name}`,
    'last_interaction: 2026-01-01',
    '---',
    `# ${name}`,
    '',
    region ? '## Recent Interactions' : '## Meetings',
    '',
    ...(region ? ['<!-- dex:auto:recent-interactions -->', '<!-- /dex:auto -->'] : ['- Older meeting']),
    '',
  ].join('\n');
}

function meetingNote(vault, name = 'roadmap.md') {
  const meeting = path.join(vault, '00-Inbox', 'Meetings', name);
  fs.writeFileSync(meeting, [
    '---',
    'title: Roadmap Review',
    'date: 2026-07-10',
    'attendees:',
    '  - name: Alice Smith',
    '    email: alice@example.com',
    '    location: internal',
    '---',
    '# Notes',
    '',
  ].join('\n'));
  return meeting;
}

test('attendees update an existing machine region and last_interaction', (t) => {
  const vault = createVault(t);
  const person = path.join(vault, '05-Areas/People/Internal/Alice_Smith.md');
  fs.writeFileSync(person, personPage('Alice Smith'));
  const meeting = meetingNote(vault);

  const result = runHook(vault, { tool_input: { file_path: meeting } });

  assert.equal(result.status, 0, result.stderr);
  const updated = fs.readFileSync(person, 'utf8');
  assert.match(updated, /last_interaction: '2026-07-10'/);
  assert.match(updated, /\[Roadmap Review\]\(00-Inbox\/Meetings\/roadmap\.md\) — 2026-07-10/);
});

test('legacy page receives the interaction under its existing heading', (t) => {
  const vault = createVault(t);
  const person = path.join(vault, '05-Areas/People/Internal/Alice_Smith.md');
  fs.writeFileSync(person, personPage('Alice Smith', false));
  const meeting = meetingNote(vault);

  assert.equal(runHook(vault, { tool_input: { file_path: meeting } }).status, 0);
  const updated = fs.readFileSync(person, 'utf8');
  assert.match(updated, /## Meetings\n\n- \[Roadmap Review\]/);
});

test('a second run is idempotent', (t) => {
  const vault = createVault(t);
  const person = path.join(vault, '05-Areas/People/Internal/Alice_Smith.md');
  fs.writeFileSync(person, personPage('Alice Smith'));
  const meeting = meetingNote(vault);

  runHook(vault, { tool_input: { file_path: meeting } });
  const once = fs.readFileSync(person, 'utf8');
  runHook(vault, { tool_input: { file_path: meeting } });
  assert.equal(fs.readFileSync(person, 'utf8'), once);
});

test('non-meeting paths and malformed stdin exit zero without changes', (t) => {
  const vault = createVault(t);
  const person = path.join(vault, '05-Areas/People/Internal/Alice_Smith.md');
  const original = personPage('Alice Smith');
  fs.writeFileSync(person, original);
  const note = path.join(vault, 'ordinary.md');
  fs.writeFileSync(note, 'met with Alice Smith');

  assert.equal(runHook(vault, { tool_input: { file_path: note } }).status, 0);
  assert.equal(runHook(vault, '{oops').status, 0);
  assert.equal(fs.readFileSync(person, 'utf8'), original);
});

test('missing person pages are never created', (t) => {
  const vault = createVault(t);
  const meeting = meetingNote(vault);

  assert.equal(runHook(vault, { tool_input: { file_path: meeting } }).status, 0);
  assert.equal(fs.existsSync(path.join(vault, '05-Areas/People/Internal/Alice_Smith.md')), false);
  assert.deepEqual(fs.readdirSync(path.join(vault, '05-Areas/Companies')), []);
});

for (const [label, payloadFor] of [
  ['snake_case', (meeting) => ({ tool_input: { file_path: meeting } })],
  ['camelCase', (meeting) => ({ toolInput: { filePath: meeting } })],
]) {
  test(`${label} payload shape works`, (t) => {
    const vault = createVault(t);
    const person = path.join(vault, '05-Areas/People/Internal/Alice_Smith.md');
    fs.writeFileSync(person, personPage('Alice Smith'));
    const meeting = meetingNote(vault);

    assert.equal(runHook(vault, payloadFor(meeting)).status, 0);
    assert.match(fs.readFileSync(person, 'utf8'), /Roadmap Review/);
  });
}

test('machine region keeps only the newest 20 interactions', (t) => {
  const vault = createVault(t);
  const person = path.join(vault, '05-Areas/People/Internal/Alice_Smith.md');
  const oldEntries = Array.from(
    { length: 20 },
    (_, index) => `- [Old ${index}](00-Inbox/Meetings/old-${index}.md) — 2026-06-${String(20 - index).padStart(2, '0')}`,
  );
  fs.writeFileSync(
    person,
    personPage('Alice Smith').replace(
      '<!-- dex:auto:recent-interactions -->\n',
      `<!-- dex:auto:recent-interactions -->\n${oldEntries.join('\n')}\n`,
    ),
  );
  const meeting = meetingNote(vault);

  assert.equal(runHook(vault, { tool_input: { file_path: meeting } }).status, 0);
  const region = /<!-- dex:auto:recent-interactions -->\n([\s\S]*?)<!-- \/dex:auto -->/
    .exec(fs.readFileSync(person, 'utf8'))[1]
    .trim()
    .split('\n');
  assert.equal(region.length, 20);
  assert.match(region[0], /Roadmap Review/);
  assert.doesNotMatch(region.join('\n'), /Old 19/);
});
