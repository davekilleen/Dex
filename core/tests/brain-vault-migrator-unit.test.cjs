'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const MIGRATOR_PATH = path.resolve(
  __dirname,
  '..',
  'migrations',
  'v1-to-v2-brain-vault-split.cjs',
);

function git(root, ...args) {
  const result = spawnSync('git', args, { cwd: root, encoding: 'utf8' });
  assert.equal(result.status, 0, `${args.join(' ')}\n${result.stdout}\n${result.stderr}`);
  return result.stdout.trim();
}

function makeGitFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-release-ref-'));
  git(root, 'init', '--quiet', '--initial-branch=main');
  git(root, 'config', 'user.name', 'Dex Migration Test');
  git(root, 'config', 'user.email', 'migration-test@dex.local');
  fs.writeFileSync(path.join(root, 'base.txt'), 'base\n');
  git(root, 'add', 'base.txt');
  git(root, 'commit', '--quiet', '-m', 'base');
  return root;
}

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

test('CLAUDE regeneration separates custom text without changing its bytes on disk', () => {
  const migrator = require(MIGRATOR_PATH);
  const template = [
    '# Dex',
    '## USER_EXTENSIONS_START',
    'release placeholder',
    '## USER_EXTENSIONS_END',
    '# After custom instructions',
    '',
  ].join('\n');
  const custom = 'Keep this exact final character: café';

  assert.equal(
    migrator.regenerateClaude(template, custom),
    '# Dex\nKeep this exact final character: café\n# After custom instructions\n',
  );
  assert.equal(custom.endsWith('\n'), false);
});

test('migrator root writes require a positive ownership class or exact migration exception', () => {
  const migrator = require(MIGRATOR_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-write-guard-'));

  assert.throws(
    () => migrator.assertMigrationWrite(root, path.join(root, 'System', 'user-note.md')),
    /refused.*vault/i,
  );
  assert.throws(
    () => migrator.assertMigrationWrite(root, path.join(root, '04-Projects', 'user.md')),
    /refused/i,
  );
  assert.doesNotThrow(
    () => migrator.assertMigrationWrite(root, path.join(root, 'System', '.dex', 'state.json')),
  );
  assert.doesNotThrow(
    () => migrator.assertMigrationWrite(root, path.join(root, 'CLAUDE-custom.md')),
  );
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

test('migrator lock recovery and release never unlink a different owner', () => {
  const migrator = require(MIGRATOR_PATH);
  const releaseRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-lock-release-'));
  const releaseLock = path.join(releaseRoot, 'System', '.dex', '.migration-lock');
  const release = migrator.acquireLock(releaseRoot);
  fs.writeFileSync(
    releaseLock,
    `${JSON.stringify({ pid: process.pid, kind: 'other', token: 'foreign-release-owner' })}\n`,
  );
  release();
  assert.equal(JSON.parse(fs.readFileSync(releaseLock, 'utf8')).token, 'foreign-release-owner');

  const staleRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-lock-stale-'));
  const staleLock = path.join(staleRoot, 'System', '.dex', '.migration-lock');
  fs.mkdirSync(path.dirname(staleLock), { recursive: true });
  fs.writeFileSync(staleLock, `${JSON.stringify({ pid: 2147483647, token: 'stale-owner' })}\n`);
  const originalOpen = fs.openSync;
  let reads = 0;
  fs.openSync = (candidate, flags, ...args) => {
    if (candidate === staleLock && flags === 'r') {
      reads += 1;
      if (reads === 2) {
        const descriptor = originalOpen(staleLock, 'w', 0o600);
        fs.writeSync(descriptor, `${JSON.stringify({ pid: process.pid, token: 'race-winner' })}\n`);
        fs.closeSync(descriptor);
      }
    }
    return originalOpen(candidate, flags, ...args);
  };
  try {
    assert.throws(() => migrator.acquireLock(staleRoot), /another Dex migration/i);
  } finally {
    fs.openSync = originalOpen;
  }
  assert.equal(JSON.parse(fs.readFileSync(staleLock, 'utf8')).token, 'race-winner');
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

test('an auto snapshot adopts the original report saved by an earlier dry-run', () => {
  const migrator = require(MIGRATOR_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-report-preview-'));
  const report = path.join(root, 'System', 'migration-report-v2.md');
  fs.mkdirSync(path.dirname(report), { recursive: true });
  fs.writeFileSync(report, 'original user report\n');

  migrator.snapshotFiles(root, 'dry-run');
  fs.writeFileSync(report, 'generated preview report\n');
  migrator.snapshotFiles(root, 'real-migration');
  fs.writeFileSync(report, 'generated final report\n');
  migrator.restoreSnapshot(root);

  assert.equal(fs.readFileSync(report, 'utf8'), 'original user report\n');
});

test('release discovery trusts official URLs and refuses contaminated local fallbacks', () => {
  const migrator = require(MIGRATOR_PATH);

  const renamedRemote = makeGitFixture();
  const releaseCommit = git(renamedRemote, 'rev-parse', 'HEAD');
  git(renamedRemote, 'remote', 'add', 'dex', 'git@github.com:davekilleen/Dex.git');
  git(renamedRemote, 'update-ref', 'refs/remotes/dex/release', releaseCommit);
  assert.deepEqual(migrator.findReleaseRef(renamedRemote, path.join(renamedRemote, '.git')), {
    ref: 'refs/remotes/dex/release',
    commit: releaseCommit,
  });

  const ancestorFallback = makeGitFixture();
  git(ancestorFallback, 'branch', 'release', 'HEAD');
  git(ancestorFallback, 'remote', 'add', 'spoof', 'https://evil.example/github.com/davekilleen/Dex.git');
  git(ancestorFallback, 'update-ref', 'refs/remotes/spoof/release', 'HEAD');
  fs.writeFileSync(path.join(ancestorFallback, 'mine.txt'), 'personal\n');
  git(ancestorFallback, 'add', 'mine.txt');
  git(ancestorFallback, 'commit', '--quiet', '-m', 'personal work');
  assert.throws(
    () => migrator.findReleaseRef(ancestorFallback, path.join(ancestorFallback, '.git')),
    /restore the official upstream remote/i,
  );

  const backupContaminated = makeGitFixture();
  git(backupContaminated, 'tag', 'backup-before-v2');
  git(backupContaminated, 'checkout', '--quiet', '-b', 'release');
  fs.writeFileSync(path.join(backupContaminated, 'release.txt'), 'release\n');
  git(backupContaminated, 'add', 'release.txt');
  git(backupContaminated, 'commit', '--quiet', '-m', 'local release');
  git(backupContaminated, 'checkout', '--quiet', 'main');
  assert.throws(
    () => migrator.findReleaseRef(backupContaminated, path.join(backupContaminated, '.git')),
    /restore the official upstream remote/i,
  );

  const safeFallback = makeGitFixture();
  git(safeFallback, 'checkout', '--quiet', '-b', 'release');
  fs.writeFileSync(path.join(safeFallback, 'release.txt'), 'release\n');
  git(safeFallback, 'add', 'release.txt');
  git(safeFallback, 'commit', '--quiet', '-m', 'clean release');
  const safeRelease = git(safeFallback, 'rev-parse', 'HEAD');
  git(safeFallback, 'checkout', '--quiet', 'main');
  assert.deepEqual(migrator.findReleaseRef(safeFallback, path.join(safeFallback, '.git')), {
    ref: 'refs/heads/release',
    commit: safeRelease,
  });
});

test('restore refuses an unmarked archive without replacing a healthy current repository', () => {
  const migrator = require(MIGRATOR_PATH);
  const root = makeGitFixture();
  const currentHead = git(root, 'rev-parse', 'HEAD');
  const archive = path.join(root, '.dex', 'pre-split-archive.git');
  fs.mkdirSync(path.dirname(archive), { recursive: true });
  git(root, 'clone', '--quiet', '--bare', root, archive);
  migrator.writeJournal(root, {
    schemaVersion: 1,
    startedAt: 'migration-under-test',
    nextPhase: 5,
    preflight: { head: currentHead, releaseCommit: currentHead },
  });

  assert.throws(
    () => migrator.restoreMigration(root),
    /archive.*migration marker.*refus/i,
  );
  assert.equal(git(root, 'rev-parse', 'HEAD'), currentHead);
  assert.ok(fs.existsSync(path.join(root, '.git')));
  assert.ok(fs.existsSync(archive));
});

test('ZIP and failed-preflight reports preserve a pre-existing user report before writing', () => {
  const migrator = require(MIGRATOR_PATH);
  const cases = [
    { root: fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-report-zip-')), expectedStatus: 0 },
    { root: makeGitFixture(), expectedStatus: 1 },
  ];
  for (const { root, expectedStatus } of cases) {
    const report = path.join(root, 'System', 'migration-report-v2.md');
    fs.mkdirSync(path.dirname(report), { recursive: true });
    fs.writeFileSync(report, 'pre-existing user report\n');

    assert.equal(migrator.main(['--auto'], root), expectedStatus);

    const backup = path.join(
      root,
      'System',
      'backups',
      'pre-split',
      'files',
      'System',
      'migration-report-v2.md',
    );
    assert.equal(fs.readFileSync(backup, 'utf8'), 'pre-existing user report\n');
  }
});
