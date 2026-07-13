'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const OWNERSHIP_PATH = path.join(REPO_ROOT, 'core', 'update', 'ownership.cjs');
const VALID_CLASSES = new Set(['brain', 'vault', 'seed', 'generated', 'runtime']);

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || REPO_ROOT,
    encoding: 'utf8',
    ...options,
  });
  assert.equal(
    result.status,
    options.expectedStatus ?? 0,
    `${command} ${args.join(' ')}\n${result.stdout}\n${result.stderr}`,
  );
  return result.stdout;
}

function buildCurrentReleaseManifest() {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-ownership-release-'));
  const clone = path.join(tempRoot, 'repo');
  run('git', ['clone', '--local', '--no-hardlinks', '--quiet', REPO_ROOT, clone]);
  run('git', ['checkout', '-B', 'main', 'HEAD', '--quiet'], { cwd: clone });
  run('git', ['config', 'user.name', 'Dex Ownership Tests'], { cwd: clone });
  run('git', ['config', 'user.email', 'ownership-tests@dex.local'], { cwd: clone });
  run('bash', ['scripts/build-release.sh'], { cwd: clone });
  return run('git', ['show', 'release:System/.installed-files.manifest'], { cwd: clone })
    .split('\n')
    .filter(Boolean);
}

test('the current release manifest has one ownership class per path', () => {
  const ownership = require(OWNERSHIP_PATH);
  const manifestLines = buildCurrentReleaseManifest();

  assert.ok(manifestLines.length > 700, 'expected the real stripped release manifest');
  for (const manifestPath of manifestLines) {
    assert.ok(VALID_CLASSES.has(ownership.classify(manifestPath)), manifestPath);
  }

  const expectedBrain = manifestLines.filter(
    (manifestPath) => ownership.classify(manifestPath) === 'brain',
  );
  assert.deepEqual(ownership.brainPaths(manifestLines), expectedBrain);

  const grandfathered = manifestLines.filter((manifestPath) => /^0[0-7]-/.test(manifestPath));
  assert.equal(grandfathered.length, 38);
  assert.ok(grandfathered.every((manifestPath) => !ownership.brainPaths(manifestLines).includes(manifestPath)));
});

test('the hard deny boundary cannot be reclassified into a writable path', () => {
  const ownership = require(OWNERSHIP_PATH);
  const denied = [
    '.git',
    '.git/objects/abc',
    '.dex/brain.git/config',
    '.dex/vault-staging.git/index',
    '00-Inbox/note.md',
    '03-Tasks/Tasks.md',
    '07-Archives/old.md',
    'System/credentials/token.json',
    '.env',
    '.env.local',
    'core/../.env',
    '../outside.txt',
    '/absolute/path',
    'C:\\absolute\\path',
    '\\\\server\\share\\file',
  ];
  for (const candidate of denied) {
    assert.equal(ownership.isDenied(candidate), true, candidate);
  }

  for (const candidate of ['core/update/ownership.cjs', 'docs/guide.md', '.dex/staging/file']) {
    assert.equal(ownership.isDenied(candidate), false, candidate);
  }
  assert.equal(ownership.classify('03-Tasks/Tasks.md'), 'seed');

  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-ownership-symlink-'));
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-ownership-outside-'));
  fs.mkdirSync(path.join(tempRoot, 'core'), { recursive: true });
  fs.symlinkSync(outside, path.join(tempRoot, 'core', 'linked-parent'));
  assert.equal(ownership.isDenied('core/linked-parent/file.cjs', tempRoot), true);
});

test('vault ignore layers protect secrets while keeping user custom skills visible', () => {
  const ownership = require(OWNERSHIP_PATH);
  const gitignore = ownership.vaultGitignoreContent();
  for (const required of [
    '.env*',
    'System/credentials/',
    'node_modules/',
    '.venv/',
    '.dex/',
    '.obsidian/workspace*',
  ]) {
    assert.match(gitignore, new RegExp(required.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  const excludeLines = ownership.vaultExcludeLines();
  assert.ok(excludeLines.includes('/core/*'));
  assert.ok(excludeLines.includes('/CLAUDE.md'));
  assert.ok(excludeLines.includes('!/.claude/skills/*-custom/**'));

  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-ownership-excludes-'));
  run('git', ['init', '--quiet'], { cwd: tempRoot });
  fs.mkdirSync(path.join(tempRoot, '.claude', 'skills', 'foo-custom'), { recursive: true });
  fs.mkdirSync(path.join(tempRoot, '.claude', 'skills', 'daily-plan'), { recursive: true });
  fs.mkdirSync(path.join(tempRoot, '.claude', 'skills-custom', 'legacy'), { recursive: true });
  fs.mkdirSync(path.join(tempRoot, 'core', 'mcp-custom'), { recursive: true });
  fs.writeFileSync(path.join(tempRoot, '.claude', 'skills', 'foo-custom', 'SKILL.md'), 'mine\n');
  fs.writeFileSync(path.join(tempRoot, '.claude', 'skills', 'daily-plan', 'SKILL.md'), 'shipped\n');
  fs.writeFileSync(path.join(tempRoot, '.claude', 'skills-custom', 'legacy', 'SKILL.md'), 'mine\n');
  fs.writeFileSync(path.join(tempRoot, 'core', 'mcp-custom', 'server.py'), 'mine\n');
  fs.writeFileSync(path.join(tempRoot, '.git', 'info', 'exclude'), `${excludeLines.join('\n')}\n`);
  run('git', ['check-ignore', '--quiet', '.claude/skills/daily-plan/SKILL.md'], { cwd: tempRoot });
  run('git', ['check-ignore', '--quiet', '.claude/skills/foo-custom/SKILL.md'], {
    cwd: tempRoot,
    expectedStatus: 1,
  });
  run('git', ['check-ignore', '--quiet', '.claude/skills-custom/legacy/SKILL.md'], {
    cwd: tempRoot,
    expectedStatus: 1,
  });
  run('git', ['check-ignore', '--quiet', 'core/mcp-custom/server.py'], {
    cwd: tempRoot,
    expectedStatus: 1,
  });

  const seeds = ownership.seedEntries();
  assert.deepEqual(
    seeds.map((entry) => entry.path),
    [
      '01-Quarter_Goals/Quarter_Goals.md',
      '02-Week_Priorities/Week_Priorities.md',
      '03-Tasks/Tasks.md',
    ],
  );
});

test('validator CLI prints the 38 delivery-sensitive paths', () => {
  const manifestLines = buildCurrentReleaseManifest();
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-ownership-validator-'));
  const manifestPath = path.join(tempRoot, 'installed-files.manifest');
  fs.writeFileSync(manifestPath, `${manifestLines.join('\n')}\n`);

  const result = spawnSync(process.execPath, [OWNERSHIP_PATH, '--validate', manifestPath], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.match(result.stdout, /38 delivery-sensitive tracked paths/);
  assert.match(result.stdout, /03-Tasks\/Tasks\.md/);
  assert.match(result.stdout, /06-Resources\/Dex_System\/Updating_Dex\.md/);
});
