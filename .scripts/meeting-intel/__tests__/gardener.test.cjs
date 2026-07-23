'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const yaml = require('js-yaml');
const {
  renderPersonPage,
  replaceMachineRegion,
  upsertFrontmatter,
} = require('../../lib/entity-pages.cjs');
const { gardenEntities } = require('../lib/gardener.cjs');

const NOW = new Date('2026-07-12T12:00:00.000Z');
const BULLETS = '- Product leader at Acme.\n- Discussing the launch plan.';

async function withVault(fn) {
  const oldVault = process.env.VAULT_PATH;
  const oldProject = process.env.CLAUDE_PROJECT_DIR;
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-gardener-'));
  process.env.VAULT_PATH = vault;
  delete process.env.CLAUDE_PROJECT_DIR;
  try {
    return await fn(vault);
  } finally {
    if (oldVault === undefined) delete process.env.VAULT_PATH; else process.env.VAULT_PATH = oldVault;
    if (oldProject === undefined) delete process.env.CLAUDE_PROJECT_DIR; else process.env.CLAUDE_PROJECT_DIR = oldProject;
    fs.rmSync(vault, { recursive: true, force: true });
  }
}

function writePerson(vault, name = 'Jane Doe', options = {}) {
  const directory = path.join(vault, '05-Areas', 'People', options.location || 'External');
  fs.mkdirSync(directory, { recursive: true });
  const filePath = path.join(directory, `${name.replace(/ /g, '_')}.md`);
  let text = renderPersonPage(name, options.role || 'Product Lead', 'Acme', [`${name.split(' ')[0].toLowerCase()}@acme.com`]);
  if (options.noHeading) text = text.replace(/\n## Key Context\n/, '\n');
  if (options.summary !== undefined) {
    if (!text.includes('dex:auto:context-summary')) {
      text = text.replace('## Key Context\n', '## Key Context\n\n<!-- dex:auto:context-summary -->\n<!-- /dex:auto -->\n');
    }
    text = replaceMachineRegion(text, 'context-summary', options.summary);
  }
  if (options.relatedTasks) text += `\n## Related Tasks\n\n${options.relatedTasks}\n`;
  fs.writeFileSync(filePath, text);
  return filePath;
}

function writeMeeting(vault, { date = '2026-07-10', email = 'jane@acme.com', body = 'Launch planning notes.' } = {}) {
  const directory = path.join(vault, '00-Inbox', 'Meetings', date);
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(directory, 'launch.md'), `---\n${yaml.dump({
    title: 'Launch review', date, attendees: [{ name: 'Jane Doe', email, location: 'external' }],
  })}---\n# Launch review\n\n${body}\n\n## Transcript\n\nDo not include this transcript.\n`);
}

function statePath(vault) {
  return path.join(vault, 'System', '.dex', 'gardener.json');
}

function readState(vault) {
  return JSON.parse(fs.readFileSync(statePath(vault), 'utf8'));
}

test('creates the summary region under Key Context and uses meeting signal', () => withVault(async vault => {
  const page = writePerson(vault);
  writeMeeting(vault);
  let prompt;
  const result = await gardenEntities({ generate: async value => { prompt = value; return BULLETS; }, now: NOW });
  const text = fs.readFileSync(page, 'utf8');
  assert.match(text, /## Key Context\n\n<!-- dex:auto:context-summary -->\n- Product leader at Acme\./);
  assert.match(prompt, /Launch review/);
  assert.doesNotMatch(prompt, /Do not include this transcript/);
  assert.equal(result.gardened.length, 1);
}));

test('appends Key Context when the heading is missing', () => withVault(async vault => {
  const page = writePerson(vault, 'Jane Doe', { noHeading: true });
  await gardenEntities({ generate: async () => BULLETS, now: NOW });
  assert.match(fs.readFileSync(page, 'utf8'), /## Key Context\n\n<!-- dex:auto:context-summary -->/);
}));

test('orphaned summary marker skips without changing user prose', () => withVault(async vault => {
  const page = writePerson(vault, 'Jane Doe', { noHeading: true });
  const before = `${fs.readFileSync(page, 'utf8')}<!-- dex:auto:context-summary -->\nMy irreplaceable notes.\nAnother hand-written detail.\n`;
  fs.writeFileSync(page, before);
  let calls = 0;
  const messages = [];
  const result = await gardenEntities({
    generate: async () => { calls += 1; return BULLETS; },
    now: NOW,
    log: message => messages.push(message),
  });
  const after = fs.readFileSync(page, 'utf8');
  assert.equal(after, before);
  assert.doesNotMatch(after, /Product leader at Acme/);
  assert.equal(calls, 0);
  assert.deepEqual(result.gardened, []);
  assert.equal(result.skipped, 1);
  assert.deepEqual(result.errors, []);
  assert.match(messages[0], /malformed-region/);
}));

test('replaceMachineRegion refuses to span an orphaned marker into a later region', () => {
  const text = [
    '<!-- dex:auto:context-summary -->',
    'My irreplaceable notes.',
    '<!-- dex:auto:context-summary -->',
    '- Existing summary',
    '<!-- /dex:auto -->',
  ].join('\n');
  assert.throws(
    () => replaceMachineRegion(text, 'context-summary', BULLETS),
    /malformed machine region: context-summary/,
  );
});

test('replaceMachineRegion throws when its end marker is missing', () => {
  const text = '<!-- dex:auto:context-summary -->\nMy irreplaceable notes.\n';
  assert.throws(
    () => replaceMachineRegion(text, 'context-summary', BULLETS),
    /malformed machine region: context-summary \(missing end marker\)/,
  );
});

test('replaceMachineRegion preserves replacement-dollar sequences literally', () => {
  const text = [
    'Before',
    '<!-- dex:auto:context-summary -->',
    '- Old summary',
    '<!-- /dex:auto -->',
    'After',
  ].join('\n');
  const content = '- Costs $& and $` and $\' literally';
  assert.equal(
    replaceMachineRegion(text, 'context-summary', content),
    [
      'Before',
      '<!-- dex:auto:context-summary -->',
      content,
      '<!-- /dex:auto -->',
      'After',
    ].join('\n'),
  );
});

test('respects seven-day cadence and unchanged input hash', () => withVault(async vault => {
  writePerson(vault);
  let calls = 0;
  const generate = async () => { calls += 1; return BULLETS; };
  await gardenEntities({ generate, now: NOW });
  await gardenEntities({ generate, now: new Date('2026-07-18T12:00:00Z') });
  await gardenEntities({ generate, now: new Date('2026-07-20T12:00:00Z') });
  assert.equal(calls, 1);
}));

test('user-edited summary becomes block-owned while facts and other blocks stay live', () => withVault(async vault => {
  const page = writePerson(vault);
  await gardenEntities({ generate: async () => BULLETS, now: NOW });
  let text = replaceMachineRegion(fs.readFileSync(page, 'utf8'), 'context-summary', '- Human edit');
  text = replaceMachineRegion(text, 'update-log', '- Existing log entry');
  fs.writeFileSync(page, text);
  let calls = 0;
  const run = () => gardenEntities({
    generate: async () => { calls += 1; return '- Replacement'; },
    now: new Date('2026-07-25T12:00:00Z'),
  });
  const first = await run();
  await run();
  assert.equal(calls, 0);
  assert.equal(first.preserved, 1);
  assert.match(fs.readFileSync(page, 'utf8'), /- Human edit/);
  assert.match(fs.readFileSync(page, 'utf8'), /- Existing log entry/);
  const entry = Object.values(readState(vault).pages)[0];
  assert.equal(entry.blocks['context-summary'].owner, 'user');
  assert.equal(Object.hasOwn(entry, 'locked'), false);

  assert.equal(upsertFrontmatter(page, { company: 'New Co' }), true);
  fs.writeFileSync(page, replaceMachineRegion(fs.readFileSync(page, 'utf8'), 'update-log', '- New log entry'));
  assert.match(fs.readFileSync(page, 'utf8'), /company: New Co/);
  assert.match(fs.readFileSync(page, 'utf8'), /- New log entry/);
  assert.match(fs.readFileSync(page, 'utf8'), /- Human edit/);
}));

test('migrates an old locked page to summary ownership without losing content', () => withVault(async vault => {
  const page = writePerson(vault);
  await gardenEntities({ generate: async () => BULLETS, now: NOW });
  const originalState = readState(vault);
  const relativePath = '05-Areas/People/External/Jane_Doe.md';
  fs.writeFileSync(page, replaceMachineRegion(fs.readFileSync(page, 'utf8'), 'context-summary', '- Human edit'));
  fs.writeFileSync(statePath(vault), JSON.stringify({
    version: 1,
    pages: {
      [relativePath]: {
        ...originalState.pages[relativePath],
        locked: true,
        locked_reason: 'user-edited',
      },
    },
  }));

  let calls = 0;
  const run = () => gardenEntities({
    generate: async () => { calls += 1; return '- Replacement'; },
    now: new Date('2026-07-25T12:00:00Z'),
  });
  const result = await run();
  assert.equal(calls, 0);
  assert.equal(result.migrated, 1);
  assert.match(fs.readFileSync(page, 'utf8'), /- Human edit/);
  const migrated = readState(vault);
  assert.equal(migrated.version, 2);
  assert.equal(migrated.pages[relativePath].blocks['context-summary'].owner, 'user');
  assert.equal(Object.hasOwn(migrated.pages[relativePath], 'locked'), false);

  const firstState = fs.readFileSync(statePath(vault));
  await run();
  assert.deepEqual(fs.readFileSync(statePath(vault)), firstState);
  assert.match(fs.readFileSync(page, 'utf8'), /- Human edit/);
}));

test('resume marker hands a user-owned summary back to Dex', () => withVault(async vault => {
  const page = writePerson(vault);
  await gardenEntities({ generate: async () => BULLETS, now: NOW });
  fs.writeFileSync(page, replaceMachineRegion(fs.readFileSync(page, 'utf8'), 'context-summary', '- Human edit'));
  await gardenEntities({ generate: async () => '- Ignored', now: new Date('2026-07-25T12:00:00Z') });

  const handBack = '- Human edit\n<!-- dex:resume:context-summary -->';
  fs.writeFileSync(page, replaceMachineRegion(fs.readFileSync(page, 'utf8'), 'context-summary', handBack));
  let calls = 0;
  const result = await gardenEntities({
    generate: async () => { calls += 1; return '- Dex owns this again'; },
    now: new Date('2026-08-02T12:00:00Z'),
  });
  assert.equal(calls, 1);
  assert.equal(result.gardened.length, 1);
  const text = fs.readFileSync(page, 'utf8');
  assert.match(text, /- Dex owns this again/);
  assert.doesNotMatch(text, /dex:resume:context-summary/);
  const entry = Object.values(readState(vault).pages)[0];
  assert.equal(entry.blocks['context-summary'].owner, 'dex');
}));

test('resume marker preserves a concurrent edit outside the summary block', () => withVault(async vault => {
  const page = writePerson(vault);
  await gardenEntities({ generate: async () => BULLETS, now: NOW });
  fs.writeFileSync(page, replaceMachineRegion(fs.readFileSync(page, 'utf8'), 'context-summary', '- Human edit'));
  await gardenEntities({ generate: async () => '- Ignored', now: new Date('2026-07-25T12:00:00Z') });
  const handBack = '- Human edit\n<!-- dex:resume:context-summary -->';
  fs.writeFileSync(page, replaceMachineRegion(fs.readFileSync(page, 'utf8'), 'context-summary', handBack));

  const originalRead = fs.readFileSync;
  let pageReads = 0;
  fs.readFileSync = function readWithConcurrentEdit(filePath, ...args) {
    const value = originalRead.call(this, filePath, ...args);
    if (filePath === page && typeof value === 'string') {
      pageReads += 1;
      if (pageReads === 2) {
        fs.writeFileSync(page, value.replace('## Notes\n', '## Notes\n\nConcurrent user note.\n'));
      }
    }
    return value;
  };
  try {
    await gardenEntities({
      generate: async () => '- Dex owns this again',
      now: new Date('2026-08-02T12:00:00Z'),
    });
  } finally {
    fs.readFileSync = originalRead;
  }

  const text = fs.readFileSync(page, 'utf8');
  assert.match(text, /Concurrent user note\./);
  assert.match(text, /- Dex owns this again/);
}));

test('limit is honored in never-gardened then oldest ordering', () => withVault(async vault => {
  writePerson(vault, 'Alpha Person');
  writePerson(vault, 'Beta Person');
  writePerson(vault, 'Gamma Person');
  const pages = {
    '05-Areas/People/External/Alpha_Person.md': { last_gardened: '2026-06-20T00:00:00Z' },
    '05-Areas/People/External/Beta_Person.md': { last_gardened: '2026-06-01T00:00:00Z' },
  };
  fs.mkdirSync(path.dirname(statePath(vault)), { recursive: true });
  fs.writeFileSync(statePath(vault), JSON.stringify({ version: 1, pages }));
  const result = await gardenEntities({ generate: async () => BULLETS, now: NOW, limit: 2 });
  assert.deepEqual(result.gardened, [
    '05-Areas/People/External/Gamma_Person.md',
    '05-Areas/People/External/Beta_Person.md',
  ]);
}));

test('empty or garbage LLM output skips without changing the page', () => withVault(async vault => {
  const page = writePerson(vault);
  const before = fs.readFileSync(page, 'utf8');
  const result = await gardenEntities({ generate: async () => 'Summary without bullets', now: NOW });
  assert.equal(result.gardened.length, 0);
  assert.equal(fs.readFileSync(page, 'utf8'), before);
  assert.equal(fs.existsSync(statePath(vault)), false);
}));

test('quarantined pages are skipped', () => withVault(async vault => {
  const page = writePerson(vault);
  fs.writeFileSync(page, '---\nname: [broken\n---\n# Broken\n');
  let called = false;
  const result = await gardenEntities({ generate: async () => { called = true; return BULLETS; }, now: NOW });
  assert.equal(called, false);
  assert.equal(result.skipped, 1);
}));

test('dry-run reports candidates but writes neither page nor state', () => withVault(async vault => {
  const page = writePerson(vault);
  const before = fs.readFileSync(page, 'utf8');
  const result = await gardenEntities({ generate: async () => BULLETS, now: NOW, dryRun: true });
  assert.equal(result.gardened.length, 1);
  assert.equal(fs.readFileSync(page, 'utf8'), before);
  assert.equal(fs.existsSync(statePath(vault)), false);
}));

test('signal is capped at 6000 characters', () => withVault(async vault => {
  const page = writePerson(vault, 'Jane Doe', { relatedTasks: Array(10).fill(`- ${'x'.repeat(900)}`).join('\n') });
  const recent = `${'y'.repeat(8000)}`;
  fs.writeFileSync(page, replaceMachineRegion(fs.readFileSync(page, 'utf8'), 'recent-interactions', recent));
  let prompt;
  await gardenEntities({ generate: async value => { prompt = value; return BULLETS; }, now: NOW });
  const signal = prompt.split('\nSIGNAL:\n')[1];
  assert.equal(signal.length, 6000);
}));

test('post-processing keeps six bullets and caps each line', () => withVault(async vault => {
  const page = writePerson(vault);
  const output = Array(8).fill(`- ${'z'.repeat(250)}`).join('\n');
  await gardenEntities({ generate: async () => output, now: NOW });
  const region = fs.readFileSync(page, 'utf8').match(/dex:auto:context-summary -->\n([\s\S]*?)\n<!-- \/dex:auto/)[1];
  assert.equal(region.split('\n').length, 6);
  assert.ok(region.split('\n').every(line => line.length === 200));
  assert.equal(readState(vault).pages['05-Areas/People/External/Jane_Doe.md'].output_hash,
    crypto.createHash('sha1').update(region).digest('hex'));
}));
