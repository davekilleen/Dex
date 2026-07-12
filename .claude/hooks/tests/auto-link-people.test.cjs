const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const SCRIPT_PATH = path.resolve(__dirname, '../../../.scripts/auto-link-people.cjs');

function loadScript() {
  delete require.cache[SCRIPT_PATH];
  return require(SCRIPT_PATH);
}

function makeRegistry({
  fullNames = [],
  firstNames = [],
  aliases = [],
  targets,
  ownerName = '',
} = {}) {
  const registry = {
    fullNames: new Set(fullNames),
    firstNameToFull: new Map(firstNames),
    aliases: new Map(aliases),
    ownerName,
  };
  if (targets) registry.targetsByFullName = new Map(targets);
  return registry;
}

function createVault(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-auto-link-'));
  const vault = path.join(root, 'vault');
  const peopleDir = path.join(vault, '05-Areas', 'People');
  const meetingsDir = path.join(vault, '00-Inbox', 'Meetings');
  const systemDir = path.join(vault, 'System');
  const userProfileFile = path.join(systemDir, 'user-profile.yaml');

  fs.mkdirSync(peopleDir, { recursive: true });
  fs.mkdirSync(meetingsDir, { recursive: true });
  fs.mkdirSync(systemDir, { recursive: true });
  // obsidian_mode on: these tests exercise linking behavior; the gate that
  // no-ops plain-markdown vaults is covered in auto-link-gate.test.cjs.
  fs.writeFileSync(userProfileFile, 'name: Test User\nobsidian_mode: true\n');

  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { vault, peopleDir, meetingsDir, userProfileFile };
}

function writePerson(peopleDir, subdirectory, fileName, content = '') {
  const directory = path.join(peopleDir, subdirectory);
  fs.mkdirSync(directory, { recursive: true });
  const filePath = path.join(directory, fileName);
  fs.writeFileSync(filePath, content || `# ${path.basename(fileName, '.md')}\n`);
  return filePath;
}

function cliEnv(vault) {
  return {
    CLAUDE_PROJECT_DIR: vault,
    HOME: path.dirname(vault),
    PATH: '/usr/bin:/bin',
    VAULT_PATH: vault,
  };
}

function runCli(vault, args) {
  return spawnSync(process.execPath, [SCRIPT_PATH, ...args], {
    cwd: vault,
    encoding: 'utf-8',
    env: cliEnv(vault),
    timeout: 10_000,
  });
}

function localDateString(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

test('exports the auto-link module contract', () => {
  assert.ok(fs.existsSync(SCRIPT_PATH), `${SCRIPT_PATH} must exist`);
  const module = loadScript();
  assert.equal(typeof module.autoLinkContent, 'function');
  assert.equal(typeof module.buildRegistry, 'function');
});

test('uses the shared path contract without raw vault paths', () => {
  const source = fs.readFileSync(SCRIPT_PATH, 'utf-8');
  assert.match(
    source,
    /const \{ loadPaths \} = require\('\.\.\/\.claude\/hooks\/paths\.cjs'\);/,
  );
  assert.doesNotMatch(
    source,
    /00-Inbox|01-Quarter_Goals|02-Week_Priorities|03-Tasks|04-Projects|05-Areas|06-Resources|07-Archives/,
  );
});

test('links a full name to its person page', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Sarah Chen'],
    firstNames: [['Sarah', 'Sarah Chen']],
    targets: [['Sarah Chen', '05-Areas/People/External/Sarah_Chen']],
  });

  assert.equal(
    autoLinkContent('Met Sarah Chen today.', registry),
    'Met [[05-Areas/People/External/Sarah_Chen|Sarah Chen]] today.',
  );
});

test('links an unambiguous alias with its visible text preserved', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Grace Brown'],
    firstNames: [['Grace', 'Grace Brown']],
    aliases: [['Alex', 'Grace Brown']],
    targets: [['Grace Brown', '05-Areas/People/External/Grace_Brown']],
  });

  assert.equal(
    autoLinkContent('Alex raised the risk.', registry),
    '[[05-Areas/People/External/Grace_Brown|Alex]] raised the risk.',
  );
});

test('falls back to display-name links when a hand-built registry has no targets', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Sarah Chen', 'Grace Brown'],
    firstNames: [['Sarah', 'Sarah Chen'], ['Grace', 'Grace Brown']],
    aliases: [['Alex', 'Grace Brown']],
  });

  assert.equal(autoLinkContent('Sarah Chen spoke.', registry), '[[Sarah Chen]] spoke.');
  assert.equal(autoLinkContent('Alex spoke.', registry), '[[Grace Brown|Alex]] spoke.');
});

test('does not link an ambiguous standalone first name', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Sarah Chen', 'Sarah Jones'],
    firstNames: [['Sarah', null]],
  });

  assert.equal(autoLinkContent('Sarah raised the risk.', registry), 'Sarah raised the risk.');
});

test('poisons a known first name when an unknown full name uses it', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Sarah Chen'],
    firstNames: [['Sarah', 'Sarah Chen']],
  });
  const input = 'Met Sarah Connor. Later Sarah spoke. Sarah Chen replied.';

  assert.equal(
    autoLinkContent(input, registry),
    'Met Sarah Connor. Later Sarah spoke. [[Sarah Chen]] replied.',
  );
});

test('does not poison a first name from a known multi-part full name', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Sarah Jane Chen'],
    firstNames: [['Sarah', 'Sarah Jane Chen']],
  });

  assert.equal(
    autoLinkContent('Sarah spoke. Later Sarah Jane Chen joined.', registry),
    '[[Sarah Jane Chen|Sarah]] spoke. Later Sarah Jane Chen joined.',
  );
});

test('does not link a stoplisted word standalone but still links its full name', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Mark Lee'],
    firstNames: [['Mark', 'Mark Lee']],
  });

  assert.equal(
    autoLinkContent('Mark this. Mark Lee agreed.', registry),
    'Mark this. [[Mark Lee]] agreed.',
  );
});

test('applies the complete stoplist case-sensitively', () => {
  const { autoLinkContent } = loadScript();
  const stoplisted = [
    'Will', 'May', 'Mark', 'Grace', 'Art', 'Rose', 'Dawn', 'Bill', 'Penny', 'Summer',
    'June', 'April', 'Jay', 'Ray', 'Miles', 'Drew', 'Chase', 'Hope', 'Faith', 'Joy',
  ];

  for (const firstName of stoplisted) {
    const fullName = `${firstName} Person`;
    const registry = makeRegistry({
      fullNames: [fullName],
      firstNames: [[firstName, fullName]],
    });
    assert.equal(
      autoLinkContent(`${firstName} spoke. ${fullName} replied.`, registry),
      `${firstName} spoke. [[${fullName}]] replied.`,
      `${firstName} must remain plain when standalone`,
    );
  }

  const lowercaseRegistry = makeRegistry({
    fullNames: ['mark Person'],
    firstNames: [['mark', 'mark Person']],
  });
  assert.equal(
    autoLinkContent('mark spoke.', lowercaseRegistry),
    '[[mark Person|mark]] spoke.',
  );
});

test('leaves protected Markdown untouched and links the first prose occurrence', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Sarah Chen'],
    firstNames: [['Sarah', 'Sarah Chen']],
  });
  const input = [
    '---',
    'attendee: Sarah Chen',
    '---',
    '```js',
    'const person = "Sarah Chen";',
    '```',
    'Inline `Sarah Chen` stays code.',
    '[Sarah Chen](https://example.test/Sarah-Chen)',
    '[Notes about Sarah Chen]',
    '[Notes about Sarah Chen]: https://example.test/people/Sarah',
    'Bare URL: https://example.test/people/Sarah',
    'Obsidian URL: obsidian://open?person=Sarah',
    'Sarah Chen spoke in prose.',
  ].join('\n');
  const expected = input.replace(
    'Sarah Chen spoke in prose.',
    '[[Sarah Chen]] spoke in prose.',
  );

  assert.equal(autoLinkContent(input, registry), expected);
});

test('an existing wiki-link is untouched and consumes the person link for the file', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Sarah Chen'],
    firstNames: [['Sarah', 'Sarah Chen']],
  });
  const input = 'Already [[Sarah Chen|Sarah]]. Later Sarah Chen spoke.';

  assert.equal(autoLinkContent(input, registry), input);
});

test('uses an Internal person path and consumes existing links by path basename or alias label', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Morgan Reed'],
    firstNames: [['Morgan', 'Morgan Reed']],
    aliases: [['Mo', 'Morgan Reed']],
    targets: [['Morgan Reed', '05-Areas/People/Internal/Morgan_Reed']],
  });
  const input = 'Morgan Reed joined. Morgan followed up.';
  const once = autoLinkContent(input, registry);

  assert.equal(
    once,
    '[[05-Areas/People/Internal/Morgan_Reed|Morgan Reed]] joined. Morgan followed up.',
  );
  assert.equal(autoLinkContent(once, registry), once);
  assert.equal(
    autoLinkContent('Already [[elsewhere/person|mo]]. Later Morgan Reed spoke.', registry),
    'Already [[elsewhere/person|mo]]. Later Morgan Reed spoke.',
  );
});

test('never links the owner by full name, first name, or alias', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Dave Killeen', 'Dave Smith'],
    firstNames: [['Dave', 'Dave Smith']],
    aliases: [['Davy', 'Dave Killeen']],
    ownerName: 'Dave Killeen',
  });

  assert.equal(
    autoLinkContent('Dave Killeen, Dave, and Davy met Dave Smith.', registry),
    'Dave Killeen, Dave, and Davy met [[Dave Smith]].',
  );
});

test('links only the earliest eligible occurrence for a person', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Sarah Chen'],
    firstNames: [['Sarah', 'Sarah Chen']],
  });

  assert.equal(
    autoLinkContent('Sarah spoke before Sarah Chen replied.', registry),
    '[[Sarah Chen|Sarah]] spoke before Sarah Chen replied.',
  );
});

test('is idempotent and preserves CRLF bytes outside the inserted link', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Sarah Chen'],
    firstNames: [['Sarah', 'Sarah Chen']],
  });
  const input = 'Sarah Chen spoke.\r\nSarah followed up.\r\n';
  const once = autoLinkContent(input, registry);

  assert.equal(once, '[[Sarah Chen]] spoke.\r\nSarah followed up.\r\n');
  assert.equal(autoLinkContent(once, registry), once);
});

test('does not match names inside longer words or compound identifiers', () => {
  const { autoLinkContent } = loadScript();
  const registry = makeRegistry({
    fullNames: ['Sarah Chen'],
    firstNames: [['Sarah', 'Sarah Chen']],
  });

  assert.equal(
    autoLinkContent('preSarah Sarahish Sarah2 _Sarah Sarah-Jane 𐐀Sarah Sarah–Jane Sarah', registry),
    'preSarah Sarahish Sarah2 _Sarah Sarah-Jane 𐐀Sarah Sarah–Jane [[Sarah Chen|Sarah]]',
  );
});

test('buildRegistry scans every nested People directory and rejects ambiguous aliases', (t) => {
  const { buildRegistry } = loadScript();
  const fixture = createVault(t);
  writePerson(
    fixture.peopleDir,
    'Community/Founders',
    'Sarah_Chen.md',
    '# Sarah Chen\n\n- Goes by "Saz"\n',
  );
  writePerson(
    fixture.peopleDir,
    'Partners',
    'Alex_Smith.md',
    '# Alex Smith\n\nGoes by "Lex"\n',
  );
  writePerson(
    fixture.peopleDir,
    'Advisors',
    'Samuel_Jones.md',
    '# Samuel Jones\n\nGoes by "Saz"\n',
  );
  fs.writeFileSync(fixture.userProfileFile, 'name: "Test User"\n');

  const registry = buildRegistry({
    VAULT_ROOT: fixture.vault,
    PEOPLE_DIR: fixture.peopleDir,
    USER_PROFILE_FILE: fixture.userProfileFile,
  });

  assert.deepEqual(
    [...registry.fullNames].sort(),
    ['Alex Smith', 'Samuel Jones', 'Sarah Chen'],
  );
  assert.equal(registry.firstNameToFull.get('Sarah'), 'Sarah Chen');
  assert.equal(registry.aliases.get('Lex'), 'Alex Smith');
  assert.equal(registry.aliases.has('Saz'), false);
  assert.equal(registry.ownerName, 'Test User');
  assert.equal(
    registry.targetsByFullName.get('Sarah Chen'),
    '05-Areas/People/Community/Founders/Sarah_Chen',
  );
});

test('dry-run prints proposed links and writes nothing', (t) => {
  const fixture = createVault(t);
  writePerson(fixture.peopleDir, 'Community', 'Sarah_Chen.md', '# Sarah Chen\n');
  const notePath = path.join(fixture.vault, 'note.md');
  const original = 'Sarah Chen joined. Sarah followed up.\n';
  fs.writeFileSync(notePath, original);

  const result = runCli(fixture.vault, ['--dry-run', notePath]);

  assert.equal(result.status, 0, `stdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
  assert.equal(fs.readFileSync(notePath, 'utf-8'), original);
  assert.match(result.stdout, /\[dry-run\]/);
  assert.match(
    result.stdout,
    /\[\[05-Areas\/People\/Community\/Sarah_Chen\|Sarah Chen\]\]/,
  );
});

test('--today processes only notes in today\'s nested meeting folder', (t) => {
  const fixture = createVault(t);
  writePerson(fixture.peopleDir, 'Community', 'Sarah_Chen.md', '# Sarah Chen\n');
  const today = localDateString();
  const todayDir = path.join(fixture.meetingsDir, today);
  const otherDir = path.join(fixture.meetingsDir, '1900-01-01');
  fs.mkdirSync(todayDir, { recursive: true });
  fs.mkdirSync(otherDir, { recursive: true });
  const todayNote = path.join(todayDir, 'standup.md');
  const otherNote = path.join(otherDir, 'old.md');
  const prefixedButNotToday = path.join(fixture.meetingsDir, `${today}0-old.md`);
  fs.writeFileSync(todayNote, 'Sarah Chen joined.\n');
  fs.writeFileSync(otherNote, 'Sarah Chen joined.\n');
  fs.writeFileSync(prefixedButNotToday, 'Sarah Chen joined.\n');

  const result = runCli(fixture.vault, ['--today']);

  assert.equal(result.status, 0, `stdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
  assert.equal(
    fs.readFileSync(todayNote, 'utf-8'),
    '[[05-Areas/People/Community/Sarah_Chen|Sarah Chen]] joined.\n',
  );
  assert.equal(fs.readFileSync(otherNote, 'utf-8'), 'Sarah Chen joined.\n');
  assert.equal(fs.readFileSync(prefixedButNotToday, 'utf-8'), 'Sarah Chen joined.\n');
});
