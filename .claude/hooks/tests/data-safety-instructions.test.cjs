'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const REPO_ROOT = path.resolve(__dirname, '../../..');
const ROLLBACK_SKILL = fs.readFileSync(
  path.join(REPO_ROOT, '.claude', 'skills', 'dex-rollback', 'SKILL.md'),
  'utf-8',
);
const UPDATE_SKILL = fs.readFileSync(
  path.join(REPO_ROOT, '.claude', 'skills', 'dex-update', 'SKILL.md'),
  'utf-8',
);

const USER_DATA_PATHS = [
  '00-Inbox/',
  '01-Quarter_Goals/',
  '02-Week_Priorities/',
  '03-Tasks/',
  '04-Projects/',
  '05-Areas/',
  '06-Resources/',
  '07-Archives/',
];

const MANUAL_RESOURCE_COPY = '06-Resources/ (copy the entire folder, including root-level files)';
const MANUAL_RESOURCE_RESTORE = 'replace 06-Resources/Dex_System/ with the copy from the downloaded Dex';

function executableResetMatches(document) {
  return [...document.matchAll(/^(?:if ! )?git reset --hard\s+.+$/gm)];
}

function assertEveryHardResetProtectsUserData(document, label) {
  const resets = executableResetMatches(document);
  assert.ok(resets.length > 0, `${label} must contain at least one hard reset`);

  for (const [index, reset] of resets.entries()) {
    const previousResetIndex = index === 0 ? 0 : resets[index - 1].index;
    const nextResetIndex = index + 1 < resets.length ? resets[index + 1].index : document.length;
    const stashIndex = document.lastIndexOf('git stash push --all', reset.index);
    const popIndex = document.indexOf('git stash pop', reset.index);

    assert.ok(
      stashIndex > previousResetIndex,
      `${label} reset ${reset[0]} must create its own user-data stash first`,
    );
    assert.ok(
      popIndex > reset.index && popIndex < nextResetIndex,
      `${label} reset ${reset[0]} must restore its own user-data stash afterward`,
    );

    const protectedBlock = document.slice(previousResetIndex, popIndex);
    for (const userPath of USER_DATA_PATHS) {
      assert.ok(
        protectedBlock.includes(userPath),
        `${label} reset ${reset[0]} does not protect ${userPath}`,
      );
    }

    const recoveryBlock = document.slice(stashIndex, nextResetIndex);
    assert.match(
      recoveryBlock,
      /System\/rollback-rescue\//,
      `${label} reset ${reset[0]} needs a timestamped conflict-rescue branch`,
    );
  }
}

function sectionBetween(document, start, end) {
  const startIndex = document.indexOf(start);
  const endIndex = document.indexOf(end, startIndex + start.length);
  assert.notEqual(startIndex, -1, `missing manual-copy section start: ${start}`);
  assert.notEqual(endIndex, -1, `missing manual-copy section end: ${end}`);
  return document.slice(startIndex, endIndex);
}

function bashBlocks(document) {
  return [...document.matchAll(/```bash\n([\s\S]*?)```/g)].map((match) => match[1]);
}

function bashBlockContaining(document, needle) {
  const block = bashBlocks(document).find((candidate) => candidate.includes(needle));
  assert.ok(block, `missing bash block containing ${needle}`);
  return block;
}

function runGit(cwd, args) {
  const result = spawnSync('git', args, { cwd, encoding: 'utf-8' });
  assert.equal(result.status, 0, `git ${args.join(' ')} failed:\n${result.stderr}`);
  return result.stdout.trim();
}

test('every hard reset snapshots and restores all user data with conflict rescue', () => {
  assertEveryHardResetProtectsUserData(ROLLBACK_SKILL, 'dex-rollback');
  assertEveryHardResetProtectsUserData(UPDATE_SKILL, 'dex-update');
});

test('rollback and update explain that tracked planning files require protection', () => {
  for (const [label, document] of [
    ['dex-rollback', ROLLBACK_SKILL],
    ['dex-update', UPDATE_SKILL],
  ]) {
    assert.match(document, /some files in 00-07 are tracked/i, `${label} must state the tracked-data truth`);
    assert.doesNotMatch(document, /they(?:'|’)re gitignored \(not tracked\)/i);
    assert.doesNotMatch(document, /data folders \(00-07\) are not affected/i);
    assert.doesNotMatch(document, /user data never at risk \(gitignored\)/i);
  }

  assert.doesNotMatch(ROLLBACK_SKILL, /notes, tasks, projects stay as they are/i);
  assert.doesNotMatch(ROLLBACK_SKILL, /no data loss ever/i);
  assert.doesNotMatch(UPDATE_SKILL, /never touches your notes, tasks, projects/i);
  assert.doesNotMatch(UPDATE_SKILL, /exactly as it was/i);
});

test('every manual copy list includes the full resources tree and session learnings', () => {
  const manualLists = [
    sectionBetween(UPDATE_SKILL, '3. Copy these folders', '[Show detailed guide]'),
    sectionBetween(UPDATE_SKILL, 'From OLD Dex folder', "3. **DON'T copy:**"),
    sectionBetween(ROLLBACK_SKILL, 'From CURRENT Dex', '3. **Replace folders:**'),
  ];

  for (const manualList of manualLists) {
    assert.ok(manualList.includes(MANUAL_RESOURCE_COPY), 'manual copy list omits the full 06-Resources tree');
    assert.ok(
      manualList.includes(MANUAL_RESOURCE_RESTORE),
      'manual copy list does not restore the downloaded Dex_System docs',
    );
    assert.ok(manualList.includes('System/Session_Learnings/'));
  }
});

test('documented shell blocks parse as bash and recovery never cleans untracked work', () => {
  for (const [label, document] of [
    ['dex-rollback', ROLLBACK_SKILL],
    ['dex-update', UPDATE_SKILL],
  ]) {
    const destructiveBlocks = bashBlocks(document).filter((block) => block.includes('git reset --hard'));
    for (const [index, block] of destructiveBlocks.entries()) {
      const parsed = spawnSync('/bin/bash', ['-n'], { input: block, encoding: 'utf-8' });
      assert.equal(
        parsed.status,
        0,
        `${label} protected-reset bash block ${index + 1} is invalid:\n${parsed.stderr}`,
      );
      assert.doesNotMatch(
        block,
        /^git (?:reset --hard|restore --source=)/gm,
        `${label} protected-reset bash block ${index + 1} has an unchecked reset/restore`,
      );
      assert.doesNotMatch(
        block,
        /^\s*git archive/gm,
        `${label} protected-reset bash block ${index + 1} has an unchecked rescue export`,
      );
      assert.match(
        block,
        /Automatic rescue export failed/,
        `${label} protected-reset bash block ${index + 1} needs an honest rescue failure branch`,
      );
    }
    assert.doesNotMatch(document, /^git clean\s+-[^\n]*f[^\n]*d/gm);
  }
});

test('update refuses to continue with a stale backup tag', () => {
  const backupBlock = bashBlockContaining(UPDATE_SKILL, 'git tag backup-before-v1.3.0');
  assert.match(backupBlock, /if ! git tag backup-before-v1\.3\.0; then/);
  assert.match(backupBlock, /exit 1/);
});

test('update captures local-only state before merge and applies it immediately afterward', () => {
  const capture = UPDATE_SKILL.indexOf('preserve_local_only_paths.py" capture');
  const merge = UPDATE_SKILL.indexOf('git merge upstream/release --no-edit');
  const apply = UPDATE_SKILL.indexOf('preserve_local_only_paths.py" apply');
  assert.ok(capture !== -1 && capture < merge, 'capture must precede the release merge');
  assert.ok(apply > merge, 'apply must follow the release merge');
  assert.match(UPDATE_SKILL, /System\/\.dex\/local-only-preservation/);
});

test('primary rollback captures newest local-only copies before reset and rewinds afterward', () => {
  const block = bashBlockContaining(ROLLBACK_SKILL, 'DEX_ROLLBACK_TARGET="backup-before-v1.3.0"');
  const capture = block.indexOf('preserve_local_only_paths.py" capture-rewind');
  const reset = block.indexOf('git reset --hard');
  const rewind = block.indexOf('preserve_local_only_paths.py" rewind');
  assert.ok(capture !== -1 && capture < reset, 'rewind capture must precede hard reset');
  assert.ok(rewind > reset, 'rewind must follow hard reset and user-data restoration');
  assert.match(block, /System\/Session_Learnings\/2026-01-29\.md/);
  assert.match(block, /System\/Session_Learnings\/2026-01-30\.md/);
});

test('rollback manifest cleanup removes newer core files but never user data', (t) => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-manifest-cleanup-'));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));

  runGit(repo, ['init', '-q']);
  runGit(repo, ['config', 'user.email', 'test@example.com']);
  runGit(repo, ['config', 'user.name', 'Dex Test']);

  fs.mkdirSync(path.join(repo, '.claude'), { recursive: true });
  fs.mkdirSync(path.join(repo, 'System'), { recursive: true });
  fs.writeFileSync(path.join(repo, '.claude', 'keep'), 'old release\n');
  fs.writeFileSync(path.join(repo, 'package.json'), '{}\n');
  fs.writeFileSync(
    path.join(repo, 'System', '.installed-files.manifest'),
    '.claude/keep\nSystem/.installed-files.manifest\npackage.json\n',
  );
  runGit(repo, ['add', '.']);
  runGit(repo, ['commit', '-qm', 'old release']);
  const oldRelease = runGit(repo, ['rev-parse', 'HEAD']);

  const protectedFiles = [
    '03-Tasks/new-task-data.md',
    '06-Resources/root-reference.md',
    'System/Session_Learnings/new-learning.md',
  ];
  const newerCoreFile = 'core/new-feature.py';
  for (const relativePath of [...protectedFiles, newerCoreFile]) {
    const filepath = path.join(repo, relativePath);
    fs.mkdirSync(path.dirname(filepath), { recursive: true });
    fs.writeFileSync(filepath, `${relativePath}\n`);
  }

  const newManifest = [
    '.claude/keep',
    'System/.installed-files.manifest',
    'package.json',
    ...protectedFiles,
    newerCoreFile,
  ].sort().join('\n') + '\n';
  fs.writeFileSync(path.join(repo, 'System', '.installed-files.manifest'), newManifest);
  runGit(repo, ['add', '.']);
  runGit(repo, ['commit', '-qm', 'new release']);
  const newRelease = runGit(repo, ['rev-parse', 'HEAD']);
  runGit(repo, ['update-ref', 'refs/remotes/upstream/release', newRelease]);

  runGit(repo, ['reset', '--hard', oldRelease]);
  for (const relativePath of [...protectedFiles, newerCoreFile]) {
    const filepath = path.join(repo, relativePath);
    fs.mkdirSync(path.dirname(filepath), { recursive: true });
    fs.writeFileSync(filepath, `${relativePath}\n`);
  }

  const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-rollback-state-'));
  fs.writeFileSync(path.join(stateDir, 'new.manifest'), newManifest);
  fs.writeFileSync(path.join(stateDir, 'new-release'), `${newRelease}\n`);

  const cleanupBlock = bashBlockContaining(ROLLBACK_SKILL, 'comm -23')
    .replace(
      'ROLLBACK_STATE_DIR="[exact private temp path printed in Step 3]"',
      `ROLLBACK_STATE_DIR=${JSON.stringify(stateDir)}`,
    );
  const result = spawnSync('/bin/bash', ['-c', cleanupBlock], {
    cwd: repo,
    encoding: 'utf-8',
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.existsSync(path.join(repo, newerCoreFile)), false);
  for (const relativePath of protectedFiles) {
    assert.equal(fs.existsSync(path.join(repo, relativePath)), true, relativePath);
  }
});

function setupProtectedResetRepo(t) {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-protected-reset-'));
  t.after(() => fs.rmSync(repo, { recursive: true, force: true }));

  const protectedFiles = [
    ['00-Inbox/', 'data.md'],
    ['01-Quarter_Goals/', 'Quarter_Goals.md'],
    ['02-Week_Priorities/', 'Week_Priorities.md'],
    ['03-Tasks/', 'Tasks.md'],
    ['04-Projects/', 'data.md'],
    ['05-Areas/', 'data.md'],
    ['06-Resources/', 'data.md'],
    ['07-Archives/', 'data.md'],
    ['System/', 'user-profile.yaml'],
    ['System/', 'pillars.yaml'],
    ['System/Session_Learnings/', 'learning.md'],
  ].map(([directory, filename]) => path.join(repo, directory, filename));

  for (const filepath of protectedFiles) {
    fs.mkdirSync(path.dirname(filepath), { recursive: true });
    fs.writeFileSync(filepath, 'backup version\n');
  }
  const rollbackCollision = path.join(repo, '04-Projects', 'old-only.md');
  fs.writeFileSync(rollbackCollision, 'old release version\n');
  fs.writeFileSync(path.join(repo, 'core.txt'), 'backup core\n');
  fs.writeFileSync(
    path.join(repo, '.gitignore'),
    ['00-Inbox/', '01-Quarter_Goals/', '02-Week_Priorities/', '03-Tasks/',
      '04-Projects/', '05-Areas/', '07-Archives/'].join('\n') + '\n',
  );

  runGit(repo, ['init', '-q']);
  runGit(repo, ['config', 'user.email', 'test@example.com']);
  runGit(repo, ['config', 'user.name', 'Dex Test']);
  runGit(repo, ['add', '-f', '.']);
  runGit(repo, ['commit', '-qm', 'backup release']);
  runGit(repo, ['tag', 'backup-before-v1.3.0']);

  fs.rmSync(rollbackCollision);
  for (const filepath of protectedFiles) fs.writeFileSync(filepath, 'committed current version\n');
  fs.writeFileSync(path.join(repo, 'core.txt'), 'newer core\n');
  runGit(repo, ['add', '-f', '.']);
  runGit(repo, ['commit', '-qm', 'current release']);

  return { repo, protectedFiles, rollbackCollision };
}

function rollbackTestEnv(repo) {
  const journal = path.join(repo, 'System', '.dex', 'local-only-preservation', 'journal');
  const runtimeScript = path.join(
    repo,
    'System',
    '.dex',
    'local-only-preservation',
    'runtime',
    'core',
    'migrations',
    'preserve_local_only_paths.py',
  );
  fs.mkdirSync(journal, { recursive: true });
  fs.mkdirSync(path.dirname(runtimeScript), { recursive: true });
  fs.writeFileSync(path.join(journal, 'journal.json'), '{}\n');
  fs.writeFileSync(runtimeScript, '# fixture; intercepted by fake python3\n');
  const bin = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-fake-python-'));
  fs.writeFileSync(path.join(bin, 'python3'), '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  return { ...process.env, PATH: `${bin}:${process.env.PATH}` };
}

test('the primary rollback block preserves committed, uncommitted, and untracked user data', (t) => {
  const { repo, protectedFiles, rollbackCollision } = setupProtectedResetRepo(t);

  for (const filepath of protectedFiles) fs.writeFileSync(filepath, 'latest user version\n');
  fs.writeFileSync(rollbackCollision, 'ignored user version\n');
  const untrackedResource = path.join(repo, '06-Resources', 'private.md');
  const ignoredProject = path.join(repo, '04-Projects', 'private.md');
  fs.writeFileSync(untrackedResource, 'private resource\n');
  fs.writeFileSync(ignoredProject, 'private project\n');

  const rollbackBlock = bashBlockContaining(
    ROLLBACK_SKILL,
    'DEX_ROLLBACK_TARGET="backup-before-v1.3.0"',
  );
  const result = spawnSync('/bin/bash', ['-c', rollbackBlock], {
    cwd: repo,
    encoding: 'utf-8',
    env: rollbackTestEnv(repo),
  });
  assert.equal(
    result.status,
    0,
    `protected rollback failed\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
  );

  assert.equal(fs.readFileSync(path.join(repo, 'core.txt'), 'utf-8'), 'backup core\n');
  for (const filepath of protectedFiles) {
    assert.equal(fs.readFileSync(filepath, 'utf-8'), 'latest user version\n', filepath);
  }
  assert.equal(fs.readFileSync(untrackedResource, 'utf-8'), 'private resource\n');
  assert.equal(fs.readFileSync(ignoredProject, 'utf-8'), 'private project\n');
  assert.equal(fs.readFileSync(rollbackCollision, 'utf-8'), 'ignored user version\n');
  assert.equal(runGit(repo, ['stash', 'list']), '');
});

test('a restore conflict exports both tracked and untracked snapshots and retains the stash', (t) => {
  const { repo, protectedFiles } = setupProtectedResetRepo(t);

  for (const filepath of protectedFiles) fs.writeFileSync(filepath, 'latest user version\n');
  const untrackedResource = path.join(repo, '06-Resources', 'private.md');
  fs.writeFileSync(untrackedResource, 'private resource\n');

  const popNeedle = 'if [ -n "$DEX_DATA_STASH_REF" ] && ! git stash pop "$DEX_DATA_STASH_REF"; then';
  const rollbackBlock = bashBlockContaining(
    ROLLBACK_SKILL,
    'DEX_ROLLBACK_TARGET="backup-before-v1.3.0"',
  ).replace(
    popNeedle,
    `printf 'concurrent edit\\n' > 03-Tasks/Tasks.md\n${popNeedle}`,
  );
  const result = spawnSync('/bin/bash', ['-c', rollbackBlock], {
    cwd: repo,
    encoding: 'utf-8',
    env: rollbackTestEnv(repo),
  });

  assert.equal(result.status, 2, `stdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
  const rescueRoot = path.join(repo, 'System', 'rollback-rescue');
  const rescueDirs = fs.readdirSync(rescueRoot);
  assert.equal(rescueDirs.length, 1);
  const rescueDir = path.join(rescueRoot, rescueDirs[0]);
  assert.equal(
    fs.readFileSync(path.join(rescueDir, 'committed-before-reset', '03-Tasks', 'Tasks.md'), 'utf-8'),
    'committed current version\n',
  );
  assert.equal(
    fs.readFileSync(path.join(rescueDir, 'stashed-tracked', '03-Tasks', 'Tasks.md'), 'utf-8'),
    'latest user version\n',
  );
  assert.equal(
    fs.readFileSync(path.join(rescueDir, 'stashed-untracked', '06-Resources', 'private.md'), 'utf-8'),
    'private resource\n',
  );
  assert.match(runGit(repo, ['stash', 'list']), /dex-user-data-before-rollback/);
});
