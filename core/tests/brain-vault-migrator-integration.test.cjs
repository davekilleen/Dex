'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FIXTURE_SCRIPT = path.join(REPO_ROOT, 'scripts', 'make-aged-vault-fixture.sh');
const MIGRATOR_RELATIVE = path.join('core', 'migrations', 'v1-to-v2-brain-vault-split.cjs');

function command(commandName, args, options = {}) {
  const result = spawnSync(commandName, args, {
    cwd: options.cwd || REPO_ROOT,
    encoding: 'utf8',
    env: { ...process.env, ...(options.env || {}) },
    timeout: options.timeout || 120_000,
  });
  if (options.expectedStatuses) {
    assert.ok(
      options.expectedStatuses.includes(result.status),
      `${commandName} ${args.join(' ')}\n${result.stdout}\n${result.stderr}`,
    );
  } else {
    assert.equal(
      result.status,
      options.expectedStatus ?? 0,
      `${commandName} ${args.join(' ')}\n${result.stdout}\n${result.stderr}`,
    );
  }
  return result;
}

function makeFixture(...flags) {
  const result = command('bash', [FIXTURE_SCRIPT, ...flags], { timeout: 180_000 });
  const match = result.stdout.match(/Fixture ready: (.+)\n?$/m);
  assert.ok(match, result.stdout);
  return match[1];
}

function migrate(vault, mode, options = {}) {
  return command(process.execPath, [path.join(vault, MIGRATOR_RELATIVE), mode], {
    cwd: vault,
    ...options,
  });
}

function git(vault, ...args) {
  return command('git', args, { cwd: vault }).stdout.trim();
}

function snapshotFiles(root) {
  const snapshot = new Map();
  function visit(relative) {
    const absolute = path.join(root, relative);
    for (const entry of fs.readdirSync(absolute, { withFileTypes: true })) {
      const child = relative ? path.join(relative, entry.name) : entry.name;
      const portable = child.split(path.sep).join('/');
      if (
        portable === '.git'
        || portable.startsWith('.git/')
        || portable === 'System/migration-report-v2.md'
        || portable.startsWith('System/backups/pre-split/')
        || portable === 'System/backups/pre-split'
      ) continue;
      const childAbsolute = path.join(root, child);
      if (entry.isDirectory()) {
        visit(child);
      } else if (entry.isSymbolicLink()) {
        snapshot.set(portable, `link:${fs.readlinkSync(childAbsolute)}`);
      } else {
        const stat = fs.statSync(childAbsolute);
        const digest = crypto.createHash('sha256').update(fs.readFileSync(childAbsolute)).digest('hex');
        snapshot.set(portable, `${stat.mode & 0o777}:${digest}`);
      }
    }
  }
  visit('');
  return snapshot;
}

test('dry-run writes only its report and leaves the vault topology and file bytes alone', () => {
  const vault = makeFixture();
  const before = snapshotFiles(vault);
  const gitHead = git(vault, 'rev-parse', 'HEAD');

  const result = migrate(vault, '--dry-run');

  assert.match(result.stdout, /P0 preflight/);
  assert.match(result.stdout, /P1 report/);
  assert.deepEqual(snapshotFiles(vault), before);
  assert.equal(git(vault, 'rev-parse', 'HEAD'), gitHead);
  assert.ok(fs.existsSync(path.join(vault, 'System', 'migration-report-v2.md')));
  assert.equal(fs.existsSync(path.join(vault, '.dex', 'brain.git')), false);
});

test('real migration preserves user bytes and creates two isolated histories', () => {
  const vault = makeFixture();
  const ignoredUserFile = '04-Projects/ignored-by-v1.md';
  const ignoredBytes = fs.readFileSync(path.join(vault, ignoredUserFile));
  const taskBytes = fs.readFileSync(path.join(vault, '03-Tasks', 'Tasks.md'));
  const customSkillBytes = fs.readFileSync(
    path.join(vault, '.claude', 'skills', 'foo-custom', 'SKILL.md'),
  );
  const preSplitFileSnapshot = snapshotFiles(vault);
  const releaseCount = Number(git(vault, 'rev-list', '--count', 'upstream/release'));

  const result = migrate(vault, '--auto');
  assert.match(result.stdout, /P9 finalize complete/);

  assert.equal(fs.readFileSync(path.join(vault, ignoredUserFile)).compare(ignoredBytes), 0);
  assert.equal(fs.readFileSync(path.join(vault, '03-Tasks', 'Tasks.md')).compare(taskBytes), 0);
  assert.equal(
    fs.readFileSync(path.join(vault, '.claude', 'skills', 'foo-custom', 'SKILL.md'))
      .compare(customSkillBytes),
    0,
  );
  assert.equal(git(vault, 'ls-tree', '--name-only', 'HEAD', '--', ignoredUserFile), ignoredUserFile);
  assert.equal(
    git(vault, 'ls-tree', '--name-only', 'HEAD', '--', '.claude/skills/foo-custom/SKILL.md'),
    '.claude/skills/foo-custom/SKILL.md',
  );
  assert.equal(git(vault, 'ls-tree', '--name-only', 'HEAD', '--', '.mcp.json'), '.mcp.json');
  assert.equal(git(vault, 'remote'), '');
  assert.equal(git(vault, 'log', '--all', '--format=%s', '--', '.env'), '');
  assert.equal(git(vault, 'log', '--all', '--format=%s', '--', 'System/credentials'), '');

  const brain = path.join(vault, '.dex', 'brain.git');
  const archive = path.join(vault, '.dex', 'pre-split-archive.git');
  assert.equal(Number(command('git', [`--git-dir=${brain}`, 'rev-list', '--count', '--all']).stdout.trim()), releaseCount);
  assert.doesNotMatch(
    command('git', [`--git-dir=${brain}`, 'log', '--all', '--format=%s']).stdout,
    /Auto-save|user customization/i,
  );
  assert.equal(
    command('git', [`--git-dir=${brain}`, 'config', '--get', 'remote.origin.url']).stdout.trim(),
    'https://github.com/davekilleen/Dex.git',
  );
  assert.equal(
    command('git', [`--git-dir=${brain}`, 'config', '--get', 'core.worktree'], {
      expectedStatus: 1,
    }).stdout.trim(),
    '',
  );
  assert.doesNotMatch(
    command('git', [`--git-dir=${brain}`, 'fsck', '--unreachable', '--no-reflogs', '--no-progress']).stdout,
    /unreachable commit/,
  );
  command('git', [`--git-dir=${archive}`, 'fsck', '--no-progress']);
  assert.match(command('git', [`--git-dir=${archive}`, 'remote']).stdout, /upstream/);
  assert.match(command('git', [`--git-dir=${archive}`, 'remote']).stdout, /private-backup/);

  const expectedExtensions = 'Always answer with the fixture sentinel: café.\nKeep  two spaces.  \n';
  assert.equal(fs.readFileSync(path.join(vault, 'CLAUDE-custom.md'), 'utf8'), expectedExtensions);
  assert.match(fs.readFileSync(path.join(vault, 'CLAUDE.md'), 'utf8'), /fixture sentinel: café/);
  assert.doesNotMatch(fs.readFileSync(path.join(vault, 'CLAUDE.md'), 'utf8'), /USER_EXTENSIONS_/);
  assert.match(fs.readFileSync(path.join(vault, 'System', 'user-profile.yaml'), 'utf8'), /^vault_schema: 1$/m);
  assert.equal(JSON.parse(fs.readFileSync(path.join(vault, 'package.json'), 'utf8')).dex.brain_support, '>=2.0.0 <3.0.0');
  const reportAndBackupText = [
    fs.readFileSync(path.join(vault, 'System', 'migration-report-v2.md'), 'utf8'),
    ...[...snapshotFiles(path.join(vault, 'System', 'backups', 'pre-split')).keys()]
      .map((relative) => fs.readFileSync(path.join(vault, 'System', 'backups', 'pre-split', relative), 'utf8')),
  ].join('\n');
  assert.doesNotMatch(reportAndBackupText, /sk-fixture-secret|ghp_fixture_secret/);
  assert.equal(fs.existsSync(path.join(vault, '.dex', 'pre-split-archive.git')), true);

  const migratedHead = git(vault, 'rev-parse', 'HEAD');
  const rerun = migrate(vault, '--auto');
  assert.match(rerun.stdout, /already complete/i);
  assert.equal(git(vault, 'rev-parse', 'HEAD'), migratedHead);

  migrate(vault, '--restore');
  assert.deepEqual(snapshotFiles(vault), preSplitFileSnapshot);
  assert.equal(fs.existsSync(path.join(vault, '.dex')), false);
  assert.equal(fs.existsSync(path.join(vault, 'System', '.dex')), false);
  assert.equal(fs.existsSync(path.join(vault, 'System', 'backups', 'pre-split')), false);

  const secondCycleSentinel = '# changed after the first restore\n';
  fs.appendFileSync(path.join(vault, '.gitignore'), secondCycleSentinel);
  const secondCycleSnapshot = snapshotFiles(vault);
  migrate(vault, '--auto');
  migrate(vault, '--restore');
  assert.deepEqual(snapshotFiles(vault), secondCycleSnapshot);
  assert.match(fs.readFileSync(path.join(vault, '.gitignore'), 'utf8'), /changed after the first restore/);
});

test('a journaled stop after P4 resumes through the swap', () => {
  const vault = makeFixture();
  const stopped = migrate(vault, '--auto', {
    env: { DEX_MIGRATION_STOP_AFTER: 'P4' },
    expectedStatus: 75,
  });
  assert.match(stopped.stdout, /Stopped safely after P4/);
  assert.ok(fs.existsSync(path.join(vault, '.git')));
  assert.ok(fs.existsSync(path.join(vault, '.dex', 'vault-staging.git')));
  assert.ok(fs.existsSync(path.join(vault, '.dex', 'brain.git')));

  const resumed = migrate(vault, '--resume');
  assert.match(resumed.stdout, /P9 finalize complete/);
  assert.ok(fs.existsSync(path.join(vault, '.dex', 'pre-split-archive.git')));
  assert.equal(git(vault, 'remote'), '');
});

test('resume safely re-enters P6 after CLAUDE markers were already stripped', () => {
  const vault = makeFixture();
  const stopped = migrate(vault, '--auto', {
    env: { DEX_MIGRATION_STOP_DURING_P6: 'lift-complete' },
    expectedStatus: 1,
  });
  assert.match(stopped.stdout + stopped.stderr, /stopped safely inside P6/i);
  assert.doesNotMatch(fs.readFileSync(path.join(vault, 'CLAUDE.md'), 'utf8'), /USER_EXTENSIONS_/);
  const state = JSON.parse(
    fs.readFileSync(path.join(vault, 'System', '.dex', 'migration-v2-state.json'), 'utf8'),
  );
  assert.equal(state.nextPhase, 6);
  assert.equal(state.p6.liftComplete, true);

  const resumed = migrate(vault, '--resume');
  assert.match(resumed.stdout, /P9 finalize complete/);
});

test('startup reconciliation completes a kill between the two P5 moves', () => {
  const vault = makeFixture();
  const stopped = migrate(vault, '--auto', {
    env: { DEX_MIGRATION_STOP_DURING_P5: 'archive-moved' },
    expectedStatus: 75,
  });
  assert.match(stopped.stdout, /Stopped safely inside P5/);
  assert.equal(fs.existsSync(path.join(vault, '.git')), false);
  assert.ok(fs.existsSync(path.join(vault, '.dex', 'pre-split-archive.git')));
  assert.ok(fs.existsSync(path.join(vault, '.dex', 'vault-staging.git')));

  const resumed = migrate(vault, '--resume');
  assert.match(resumed.stdout, /Startup check completed the interrupted P5 swap/);
  assert.match(resumed.stdout, /P9 finalize complete/);
  assert.equal(git(vault, 'remote'), '');
});

test('restore reverses a journaled half-swap before the vault Git folder is active', () => {
  const vault = makeFixture();
  const before = snapshotFiles(vault);
  migrate(vault, '--auto', {
    env: { DEX_MIGRATION_STOP_DURING_P5: 'archive-moved' },
    expectedStatus: 75,
  });

  migrate(vault, '--restore');

  assert.deepEqual(snapshotFiles(vault), before);
  assert.ok(fs.existsSync(path.join(vault, '.git')));
  assert.equal(fs.existsSync(path.join(vault, '.dex')), false);
  assert.equal(fs.existsSync(path.join(vault, 'System', '.dex')), false);
});

test('huge vaults stop at bounded P3 batches and continue with --resume', () => {
  const vault = makeFixture('--huge');
  let result = migrate(vault, '--auto', { expectedStatuses: [0, 75] });
  let resumes = 0;
  while (result.status === 75 && resumes < 20) {
    assert.match(result.stdout, /P3 indexed batch/);
    result = migrate(vault, '--resume', { expectedStatuses: [0, 75] });
    resumes += 1;
  }
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.ok(resumes >= 2, `expected multiple bounded invocations, got ${resumes}`);
  assert.equal(git(vault, 'ls-tree', '-r', '--name-only', 'HEAD', '--', '04-Projects/Huge').split('\n').length, 180);
});

test('ZIP installs and in-progress merges refuse without creating a half-topology', () => {
  const zipVault = makeFixture('--no-git');
  const zipResult = migrate(zipVault, '--auto');
  assert.match(zipResult.stdout, /downloaded as a ZIP/i);
  assert.match(zipResult.stdout, /No conversion was started/i);
  assert.equal(fs.existsSync(path.join(zipVault, '.git')), false);
  assert.equal(fs.existsSync(path.join(zipVault, '.dex')), false);

  fs.mkdirSync(path.join(zipVault, '.dex', 'brain.git'), { recursive: true });
  const invalidHalfState = migrate(zipVault, '--auto', { expectedStatus: 1 });
  assert.match(invalidHalfState.stdout + invalidHalfState.stderr, /incomplete.*archive is missing/i);

  const mergingVault = makeFixture('--with-merge-in-progress');
  const mergeResult = migrate(mergingVault, '--auto', { expectedStatus: 1 });
  assert.match(mergeResult.stdout + mergeResult.stderr, /finish or abort the merge/i);
  assert.equal(fs.existsSync(path.join(mergingVault, '.dex', 'brain.git')), false);
  assert.equal(fs.existsSync(path.join(mergingVault, '.dex', 'pre-split-archive.git')), false);
});
