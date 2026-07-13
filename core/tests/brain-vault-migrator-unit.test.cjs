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

test('the fsynced journal falls back to its previous complete record after truncation', () => {
  const migrator = require(MIGRATOR_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-journal-'));

  for (let phase = 0; phase <= 9; phase += 1) {
    migrator.writeJournal(root, { schemaVersion: 1, phase: `P${phase}`, nextPhase: phase });
  }
  const journalPath = path.join(root, 'System', '.dex', 'migration-v2-state.json');
  fs.truncateSync(journalPath, 11);

  const recovered = migrator.readJournal(root);
  assert.equal(recovered.phase, 'P8');
  assert.equal(recovered.nextPhase, 8);
  assert.equal(recovered.recoveredFromPrevious, true);
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
