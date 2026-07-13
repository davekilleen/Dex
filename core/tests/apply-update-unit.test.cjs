'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const UPDATER_PATH = path.resolve(__dirname, '..', 'update', 'apply-update.cjs');

test('official release URLs accept only the Dex repository identity', () => {
  const updater = require(UPDATER_PATH);
  for (const url of [
    'https://github.com/davekilleen/Dex.git',
    'https://github.com/davekilleen/Dex',
    'git@github.com:davekilleen/Dex.git',
    'ssh://git@github.com/davekilleen/Dex.git',
  ]) {
    assert.equal(updater.isOfficialRemote(url), true, url);
  }
  for (const url of [
    'http://github.com/davekilleen/Dex.git',
    'git://github.com/davekilleen/Dex.git',
    'https://example.com/davekilleen/Dex.git',
    'https://github.com/attacker/Dex.git',
    'file:///tmp/Dex.git',
    'https://github.com/davekilleen/Dex.git.evil',
  ]) {
    assert.equal(updater.isOfficialRemote(url), false, url);
  }
});

test('origin verification rejects repository-local transport rewrites', () => {
  const updater = require(UPDATER_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-origin-'));
  const brain = path.join(root, '.dex', 'brain.git');
  fs.mkdirSync(path.dirname(brain), { recursive: true });
  const { spawnSync } = require('node:child_process');
  const git = (...args) => {
    const result = spawnSync('git', [`--git-dir=${brain}`, ...args], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr);
  };
  git('init', '--bare', '--quiet');
  git('remote', 'add', 'origin', 'https://github.com/davekilleen/Dex.git');
  git('config', 'url.file:///tmp/attacker.git.insteadOf', 'https://github.com/davekilleen/Dex.git');

  assert.throws(() => updater.verifyOfficialOrigin(root), /redirected|official/i);
});

test('automatic release selection ignores prerelease and malformed tags', () => {
  const updater = require(UPDATER_PATH);
  assert.equal(updater.selectLatestStableTag([
    'dist-v2.0.0',
    'dist-v2.1.0-rc.1',
    'dist-v2.0.9',
    'dist-vgarbage',
    'dist-v10.0.0',
  ]), 'dist-v10.0.0');
  assert.throws(() => updater.selectLatestStableTag(['dist-v2.1.0-rc.1']), /stable/i);
});

test('worktree replacement retries Windows locks and verifies fallback bytes', () => {
  const updater = require(UPDATER_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-replace-'));
  fs.writeFileSync(path.join(root, 'README.md'), 'old\n');
  const originalRename = fs.renameSync;
  let blocked = 0;
  fs.renameSync = (source, destination) => {
    if (source.includes('.writing-') && destination.endsWith('README.md') && blocked < 5) {
      blocked += 1;
      const error = new Error('simulated Windows lock');
      error.code = 'EACCES';
      throw error;
    }
    return originalRename(source, destination);
  };
  try {
    updater.writeWorktreeFile(root, 'README.md', Buffer.from('new\n'), 0o644);
  } finally {
    fs.renameSync = originalRename;
  }
  assert.equal(blocked, 5);
  assert.equal(fs.readFileSync(path.join(root, 'README.md'), 'utf8'), 'new\n');
  assert.equal(fs.existsSync(path.join(root, 'README.md.dex-update-previous')), false);
});

test('Windows mode normalization is not mistaken for corrupt replacement bytes', () => {
  const updater = require(UPDATER_PATH);
  assert.equal(updater.modesCompatible(0o644, 0o666, 'win32'), true);
  assert.equal(updater.modesCompatible(0o644, 0o666, 'darwin'), false);
});

test('direct Git metadata writes use the same locked-file fallback', () => {
  const updater = require(UPDATER_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-metadata-'));
  const destination = path.join(root, '.git', 'info', 'exclude');
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, 'old metadata\n');
  const originalRename = fs.renameSync;
  let blocked = 0;
  fs.renameSync = (source, target) => {
    if (source.includes('.writing-') && target === destination && blocked < 5) {
      blocked += 1;
      const error = new Error('simulated locked metadata');
      error.code = 'EBUSY';
      throw error;
    }
    return originalRename(source, target);
  };
  try {
    updater.writeDirectFile(destination, 'new metadata\n', 0o600);
  } finally {
    fs.renameSync = originalRename;
  }
  assert.equal(blocked, 5);
  assert.equal(fs.readFileSync(destination, 'utf8'), 'new metadata\n');
  assert.equal(fs.existsSync(`${destination}.dex-update-previous`), false);
});

test('direct metadata fallback reconciles a completed prior write before bytes change', () => {
  const updater = require(UPDATER_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-direct-resume-'));
  const destination = path.join(root, '.git', 'info', 'exclude');
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, 'old\n');
  const originalRename = fs.renameSync;
  let blocked = 0;
  fs.renameSync = (source, target) => {
    if (source.includes('.writing-') && target === destination && blocked < 5) {
      blocked += 1;
      const error = new Error('simulated locked metadata');
      error.code = 'EBUSY';
      throw error;
    }
    return originalRename(source, target);
  };
  process.env.DEX_UPDATE_TEST_THROW_AFTER_DIRECT_FALLBACK = destination;
  try {
    assert.throws(() => updater.writeDirectFile(destination, 'first\n'), /Simulated crash/);
  } finally {
    fs.renameSync = originalRename;
    delete process.env.DEX_UPDATE_TEST_THROW_AFTER_DIRECT_FALLBACK;
  }
  assert.equal(fs.readFileSync(destination, 'utf8'), 'first\n');

  updater.writeDirectFile(destination, 'second\n');
  assert.equal(fs.readFileSync(destination, 'utf8'), 'second\n');
  assert.equal(fs.existsSync(`${destination}.dex-update-previous`), false);
  assert.equal(fs.existsSync(`${destination}.dex-update-intent`), false);
});

test('a crash after fallback install reconciles quarantine before a changing journal write', () => {
  const updater = require(UPDATER_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-fallback-resume-'));
  fs.mkdirSync(path.join(root, 'System', '.dex'), { recursive: true });
  const relative = 'System/.dex/update-state.json';
  fs.writeFileSync(path.join(root, relative), '{"updatedAt":"old"}\n');
  const originalRename = fs.renameSync;
  let blocked = 0;
  fs.renameSync = (source, destination) => {
    if (source.includes('.writing-') && destination.endsWith('update-state.json') && blocked < 5) {
      blocked += 1;
      const error = new Error('simulated Windows lock');
      error.code = 'EACCES';
      throw error;
    }
    return originalRename(source, destination);
  };
  process.env.DEX_UPDATE_TEST_THROW_AFTER_FALLBACK_INSTALL = relative;
  try {
    assert.throws(
      () => updater.writeRuntimeFile(root, relative, '{"updatedAt":"first"}\n'),
      /Simulated crash/,
    );
  } finally {
    fs.renameSync = originalRename;
    delete process.env.DEX_UPDATE_TEST_THROW_AFTER_FALLBACK_INSTALL;
  }

  assert.equal(fs.readFileSync(path.join(root, relative), 'utf8'), '{"updatedAt":"first"}\n');
  updater.writeRuntimeFile(root, relative, '{"updatedAt":"second"}\n');
  assert.equal(fs.readFileSync(path.join(root, relative), 'utf8'), '{"updatedAt":"second"}\n');
  assert.equal(fs.existsSync(path.join(root, '.dex', 'staging', '.swap')), true);
  assert.deepEqual(fs.readdirSync(path.join(root, '.dex', 'staging', '.swap')), []);
});

test('target manifests are deterministic, complete staging inventories', () => {
  const updater = require(UPDATER_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-manifest-'));
  fs.mkdirSync(path.join(root, 'System'), { recursive: true });
  fs.mkdirSync(path.join(root, 'core'), { recursive: true });
  const manifest = 'System/.installed-files.manifest\ncore/example.cjs\n';
  fs.writeFileSync(path.join(root, 'System', '.installed-files.manifest'), manifest);
  fs.writeFileSync(path.join(root, 'core', 'example.cjs'), 'module.exports = 1;\n');

  const result = updater.verifyStagedManifest(root, Buffer.from(manifest));

  assert.equal(result.manifestHash, crypto.createHash('sha256').update(manifest).digest('hex'));
  assert.deepEqual(result.manifestLines, [
    'System/.installed-files.manifest',
    'core/example.cjs',
  ]);

  fs.writeFileSync(path.join(root, 'unlisted.txt'), 'not in manifest\n');
  assert.throws(
    () => updater.verifyStagedManifest(root, Buffer.from(manifest)),
    /does not match the staged release tree/i,
  );
});

test('safe worktree writes refuse denied paths and final symlinks', () => {
  const updater = require(UPDATER_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-deny-'));
  fs.mkdirSync(path.join(root, '04-Projects'), { recursive: true });
  assert.throws(() => updater.assertWorktreeWrite(root, '04-Projects/user.md'), /refused/i);

  const outside = path.join(root, 'outside.txt');
  fs.writeFileSync(outside, 'outside\n');
  fs.mkdirSync(path.join(root, 'core'), { recursive: true });
  fs.symlinkSync(outside, path.join(root, 'core', 'linked.cjs'));
  assert.throws(() => updater.assertWorktreeWrite(root, 'core/linked.cjs'), /symlink/i);
});

test('worktree writes require a positive ownership class and runtime writes stay separate', () => {
  const updater = require(UPDATER_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-positive-write-'));
  fs.mkdirSync(path.join(root, 'System'), { recursive: true });
  fs.writeFileSync(path.join(root, 'System', 'update-report.md'), 'user-owned report\n');

  assert.throws(
    () => updater.writeWorktreeFile(root, 'System/update-report.md', 'user file\n'),
    /ownership|vault|refused/i,
  );
  assert.equal(fs.readFileSync(path.join(root, 'System', 'update-report.md'), 'utf8'), 'user-owned report\n');
  assert.throws(
    () => updater.writeWorktreeFile(root, 'System/.dex/update-report.md', 'runtime file\n'),
    /ownership|runtime|refused/i,
  );
  updater.writeRuntimeFile(root, 'System/.dex/update-report.md', 'runtime file\n');
  assert.equal(
    fs.readFileSync(path.join(root, 'System', '.dex', 'update-report.md'), 'utf8'),
    'runtime file\n',
  );
  assert.throws(
    () => updater.writeRuntimeFile(root, 'README.md', 'brain file\n'),
    /ownership|brain|refused/i,
  );
});

test('updater lock recovery and release never unlink a different owner', () => {
  const updater = require(UPDATER_PATH);
  const releaseRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-lock-release-'));
  const releaseLock = path.join(releaseRoot, 'System', '.dex', '.migration-lock');
  const release = updater.acquireLock(releaseRoot);
  fs.writeFileSync(
    releaseLock,
    `${JSON.stringify({ pid: process.pid, kind: 'other', token: 'foreign-release-owner' })}\n`,
  );
  release();
  assert.equal(JSON.parse(fs.readFileSync(releaseLock, 'utf8')).token, 'foreign-release-owner');

  const staleRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-lock-stale-'));
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
    assert.throws(() => updater.acquireLock(staleRoot), /another Dex migration or update/i);
  } finally {
    fs.openSync = originalOpen;
  }
  assert.equal(JSON.parse(fs.readFileSync(staleLock, 'utf8')).token, 'race-winner');
});

test('status identifies migration-pending and post-split topologies', () => {
  const updater = require(UPDATER_PATH);
  const pending = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-status-pending-'));
  fs.mkdirSync(path.join(pending, '.git'));
  fs.mkdirSync(path.join(pending, 'core', 'migrations'), { recursive: true });
  fs.writeFileSync(
    path.join(pending, 'core', 'migrations', 'v1-to-v2-brain-vault-split.cjs'),
    'module.exports = {};\n',
  );
  assert.equal(updater.inspectUpdateTopology(pending).state, 'migration-pending');

  const split = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-update-status-split-'));
  fs.mkdirSync(path.join(split, '.git'), { recursive: true });
  fs.mkdirSync(path.join(split, '.dex', 'brain.git'), { recursive: true });
  fs.mkdirSync(path.join(split, 'System', '.dex'), { recursive: true });
  fs.writeFileSync(path.join(split, '.git', 'dex-vault-v2'), '{"role":"vault"}\n');
  fs.writeFileSync(path.join(split, '.dex', 'brain.git', 'dex-brain-v2'), '{"role":"brain"}\n');
  fs.writeFileSync(
    path.join(split, 'System', '.dex', 'topology.json'),
    JSON.stringify({ topology: 'brain-vault-split' }),
  );
  assert.equal(updater.inspectUpdateTopology(split).state, 'post-split');
});
