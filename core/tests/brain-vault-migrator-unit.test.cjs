'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const MIGRATOR_PATH = path.resolve(
  __dirname,
  '..',
  'migrations',
  'v1-to-v2-brain-vault-split.cjs',
);

test('CLAUDE regeneration lifts the legacy extension bytes and removes legacy markers', () => {
  const migrator = require(MIGRATOR_PATH);
  const legacy = [
    '# Dex',
    '',
    'Before.',
    '## USER_EXTENSIONS_START',
    'Keep  two spaces.  ',
    'Unicode: café',
    '',
    '## USER_EXTENSIONS_END',
    'After.',
    '',
  ].join('\n');
  const expectedCustom = 'Keep  two spaces.  \nUnicode: café\n\n';

  assert.equal(migrator.extractLegacyExtensions(legacy), expectedCustom);
  const template = migrator.emptyLegacyExtensionBlock(legacy);
  assert.match(template, /USER_EXTENSIONS_START\n## USER_EXTENSIONS_END/);

  const generated = migrator.regenerateClaude(template, expectedCustom);
  assert.equal(generated, '# Dex\n\nBefore.\nKeep  two spaces.  \nUnicode: café\n\nAfter.\n');
  assert.doesNotMatch(generated, /USER_EXTENSIONS_(START|END)/);
});

test('the fsynced journal recovers after truncation between every phase pair', () => {
  const migrator = require(MIGRATOR_PATH);
  for (let phase = 0; phase < 9; phase += 1) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), `dex-migration-journal-p${phase}-`));
    migrator.writeJournal(root, { schemaVersion: 1, phase: `P${phase}`, nextPhase: phase });
    migrator.writeJournal(root, {
      schemaVersion: 1,
      phase: `P${phase + 1}`,
      nextPhase: phase + 1,
    });
    const journalPath = path.join(root, 'System', '.dex', 'migration-v2-state.json');
    fs.truncateSync(journalPath, 11);

    const recovered = migrator.readJournal(root);
    assert.equal(recovered.phase, `P${phase}`);
    assert.equal(recovered.nextPhase, phase);
    assert.equal(recovered.recoveredFromPrevious, true);
  }
});

test('the P2 snapshot resumes after a stop between backup files', () => {
  const migrator = require(MIGRATOR_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-snapshot-'));
  const claudeBytes = Buffer.from('# Dex\n');
  const ignoreBytes = Buffer.from('.env\n');
  fs.writeFileSync(path.join(root, 'CLAUDE.md'), claudeBytes);
  fs.writeFileSync(path.join(root, '.gitignore'), ignoreBytes);

  process.env.DEX_MIGRATION_STOP_AFTER_SNAPSHOT_FILE = 'CLAUDE.md';
  try {
    assert.throws(
      () => migrator.snapshotFiles(root),
      /Stopped safely while testing P2 snapshot recovery/,
    );
  } finally {
    delete process.env.DEX_MIGRATION_STOP_AFTER_SNAPSHOT_FILE;
  }

  const manifest = migrator.snapshotFiles(root);
  const backupRoot = path.join(root, 'System', 'backups', 'pre-split');
  assert.equal(manifest.entries.find((entry) => entry.path === 'CLAUDE.md').existed, true);
  assert.deepEqual(fs.readFileSync(path.join(backupRoot, 'files', 'CLAUDE.md')), claudeBytes);
  assert.deepEqual(fs.readFileSync(path.join(backupRoot, 'files', '.gitignore')), ignoreBytes);
  assert.ok(fs.existsSync(path.join(backupRoot, 'snapshot.json')));
});

test('the topology reconciler has an explicit decision for all 16 presence states', () => {
  const migrator = require(MIGRATOR_PATH);
  const decisions = new Set([
    'zip',
    'pre-split',
    'continue-swap',
    'post-split',
    'restore-archive',
    'invalid',
  ]);

  for (let mask = 0; mask < 16; mask += 1) {
    const topology = {
      rootGit: Boolean(mask & 1),
      vaultStaging: Boolean(mask & 2),
      brainGit: Boolean(mask & 4),
      archiveGit: Boolean(mask & 8),
      rootIsVault: Boolean(mask & 8) && Boolean(mask & 1),
    };
    const decision = migrator.topologyDecision(topology);
    assert.ok(decisions.has(decision), `${mask.toString(2).padStart(4, '0')}: ${decision}`);
  }

  assert.equal(
    migrator.topologyDecision({
      rootGit: false,
      vaultStaging: true,
      brainGit: true,
      archiveGit: true,
      rootIsVault: false,
    }),
    'continue-swap',
  );
  assert.equal(
    migrator.topologyDecision({
      rootGit: true,
      vaultStaging: false,
      brainGit: true,
      archiveGit: true,
      rootIsVault: true,
    }),
    'post-split',
  );
  assert.equal(
    migrator.topologyDecision({
      rootGit: false,
      vaultStaging: false,
      brainGit: false,
      archiveGit: true,
      rootIsVault: false,
    }),
    'restore-archive',
  );
});

test('migration refuses every symlinked mutation root before writing through it', () => {
  const migrator = require(MIGRATOR_PATH);
  const cases = [
    ['root', ''],
    ['System', 'System'],
    ['.dex', '.dex'],
    ['System/.dex', path.join('System', '.dex')],
    ['System/backups', path.join('System', 'backups')],
  ];

  for (const [label, relative] of cases) {
    const fixtureParent = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-symlink-'));
    const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-outside-'));
    let root = path.join(fixtureParent, 'vault');
    if (label === 'root') {
      fs.mkdirSync(path.join(fixtureParent, 'real-vault'));
      fs.symlinkSync(path.join(fixtureParent, 'real-vault'), root);
    } else {
      fs.mkdirSync(root);
      fs.mkdirSync(path.dirname(path.join(root, relative)), { recursive: true });
      fs.symlinkSync(outside, path.join(root, relative));
    }

    assert.throws(
      () => migrator.assertSafeMutationRoots(root),
      new RegExp(`${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}.*symlink`, 'i'),
    );
    assert.deepEqual(fs.readdirSync(outside), [], label);
  }

  const fixtureParent = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-entry-symlink-'));
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-entry-outside-'));
  const root = path.join(fixtureParent, 'vault');
  fs.mkdirSync(root);
  fs.symlinkSync(outside, path.join(root, 'System'));
  assert.equal(migrator.main(['--auto'], root), 1);
  assert.deepEqual(fs.readdirSync(outside), []);
});

test('P6 is replay-safe and preserves distinct custom and inline instructions', () => {
  const migrator = require(MIGRATOR_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-p6-'));
  fs.mkdirSync(path.join(root, 'System'), { recursive: true });
  const inline = 'Inline instruction byte-for-byte.  \n';
  const existingCustom = 'Existing custom instruction.\n';
  fs.writeFileSync(
    path.join(root, 'CLAUDE.md'),
    `# Dex\n\n## USER_EXTENSIONS_START\n${inline}## USER_EXTENSIONS_END\nAfter.\n`,
  );
  fs.writeFileSync(path.join(root, 'CLAUDE-custom.md'), existingCustom);
  fs.writeFileSync(path.join(root, 'System', 'user-profile.yaml'), 'name: Test\n');
  fs.writeFileSync(path.join(root, 'package.json'), '{"name":"fixture"}\n');
  const state = { schemaVersion: 1, nextPhase: 6, analysis: {} };

  migrator.phase6Rematerialize(root, state);
  const firstClaude = fs.readFileSync(path.join(root, 'CLAUDE.md'));
  const firstCustom = fs.readFileSync(path.join(root, 'CLAUDE-custom.md'), 'utf8');
  assert.match(firstCustom, /Existing custom instruction/);
  assert.match(firstCustom, /## Lifted from CLAUDE\.md during v2 migration/);
  assert.ok(firstCustom.includes(inline));
  assert.equal(state.p6.liftComplete, true);
  assert.match(state.p6.claudeSha256, /^[a-f0-9]{64}$/);
  assert.equal(state.analysis.liftedInlineExtensions, true);

  migrator.writeJournal(root, { ...state, status: 'starting', nextPhase: 6 });
  assert.doesNotThrow(() => migrator.phase6Rematerialize(root, state));
  assert.deepEqual(fs.readFileSync(path.join(root, 'CLAUDE.md')), firstClaude);
  assert.equal(fs.readFileSync(path.join(root, 'CLAUDE-custom.md'), 'utf8'), firstCustom);
});

test('the pre-split snapshot restores a pre-existing migration report', () => {
  const migrator = require(MIGRATOR_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-report-snapshot-'));
  const report = path.join(root, 'System', 'migration-report-v2.md');
  fs.mkdirSync(path.dirname(report), { recursive: true });
  fs.writeFileSync(report, 'my pre-existing report\n');

  migrator.snapshotFiles(root, 'report-test');
  fs.writeFileSync(report, 'migration output\n');
  migrator.restoreSnapshot(root);

  assert.equal(fs.readFileSync(report, 'utf8'), 'my pre-existing report\n');
});
