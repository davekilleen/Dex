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
    'https://example.com/davekilleen/Dex.git',
    'https://github.com/attacker/Dex.git',
    'file:///tmp/Dex.git',
    'https://github.com/davekilleen/Dex.git.evil',
  ]) {
    assert.equal(updater.isOfficialRemote(url), false, url);
  }
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
