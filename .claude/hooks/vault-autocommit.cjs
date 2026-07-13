#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const FEATURE = 'Vault auto-commit';

function status(state, userMessage) {
  return {
    success: state === 'ok',
    feature: FEATURE,
    feature_status: state,
    user_message: userMessage,
  };
}

function exists(candidate) {
  try {
    fs.lstatSync(candidate);
    return true;
  } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

function regularFileWithoutSymlinkedParents(root, relative) {
  try {
    let current = path.resolve(root);
    for (const part of relative.split('/')) {
      current = path.join(current, part);
      const stat = fs.lstatSync(current);
      if (stat.isSymbolicLink()) return null;
    }
    return fs.lstatSync(current).isFile() ? current : null;
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

function parseVaultAutoCommit(source) {
  const lines = String(source).split(/\r?\n/);
  const blocks = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!/^vault:\s*(?:#.*)?$/.test(line)) continue;
    const vaultIndent = line.match(/^\s*/)[0].length;
    const block = [];
    for (index += 1; index < lines.length; index += 1) {
      const child = lines[index];
      if (!child.trim() || child.trimStart().startsWith('#')) continue;
      const indent = child.match(/^\s*/)[0].length;
      if (indent <= vaultIndent) {
        index -= 1;
        break;
      }
      block.push({ line: child, indent });
    }
    blocks.push(block);
  }
  if (blocks.length !== 1 || blocks[0].length === 0) return false;
  const directIndent = Math.min(...blocks[0].map((entry) => entry.indent));
  const values = blocks[0].filter((entry) => entry.indent === directIndent).flatMap((entry) => {
    const match = /^\s*auto_commit:\s*([^#\s]+)\s*(?:#.*)?$/.exec(entry.line);
    return match ? [match[1].replace(/^['"]|['"]$/g, '').toLowerCase()] : [];
  });
  return values.length === 1 && values[0] === 'true';
}

function acquireSharedLock(root) {
  const system = path.join(root, 'System');
  const stateDirectory = path.join(system, '.dex');
  for (const candidate of [system, stateDirectory]) {
    if (exists(candidate) && (fs.lstatSync(candidate).isSymbolicLink() || !fs.lstatSync(candidate).isDirectory())) {
      return null;
    }
  }
  fs.mkdirSync(stateDirectory, { recursive: true });
  const lock = path.join(stateDirectory, '.migration-lock');
  const token = `${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  let descriptor;
  try {
    descriptor = fs.openSync(lock, 'wx', 0o600);
    const payload = `${JSON.stringify({ pid: process.pid, kind: 'vault-auto-commit', token, at: new Date().toISOString() })}\n`;
    fs.writeFileSync(descriptor, payload);
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor);
    descriptor = undefined;
    return () => {
      try {
        const current = JSON.parse(fs.readFileSync(lock, 'utf8'));
        if (current.token === token) fs.unlinkSync(lock);
      } catch {
        // Another owner or a vanished lock is left alone.
      }
    };
  } catch (error) {
    if (descriptor !== undefined) fs.closeSync(descriptor);
    if (error.code === 'EEXIST') return null;
    throw error;
  }
}

function git(root, args) {
  return spawnSync('git', [
    '-c', 'commit.gpgsign=false',
    '-c', 'core.excludesFile=/dev/null',
    '-C', root,
    ...args,
  ], {
    encoding: 'utf8',
    env: { ...process.env, GIT_TERMINAL_PROMPT: '0' },
  });
}

function localDate(now) {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function operationInProgress(gitDirectory) {
  return ['MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply']
    .some((name) => exists(path.join(gitDirectory, name)));
}

function ensureLocalIdentity(root) {
  for (const [key, value] of [['user.name', 'Dex Vault'], ['user.email', 'vault@dex.local']]) {
    const current = git(root, ['config', '--local', '--get', key]);
    if (current.status === 0 && current.stdout.trim()) continue;
    if (git(root, ['config', '--local', key, value]).status !== 0) return false;
  }
  return true;
}

function run(options = {}) {
  let releaseLock = null;
  try {
    const root = path.resolve(options.root || process.env.CLAUDE_PROJECT_DIR || process.cwd());
    const profile = regularFileWithoutSymlinkedParents(root, 'System/user-profile.yaml');
    if (!profile || !parseVaultAutoCommit(fs.readFileSync(profile, 'utf8'))) {
      return status('off', 'Vault auto-commit is off by default. Set vault.auto_commit to true when you want local session snapshots.');
    }
    const gitDirectory = path.join(root, '.git');
    if (!exists(gitDirectory) || fs.lstatSync(gitDirectory).isSymbolicLink() || !fs.lstatSync(gitDirectory).isDirectory()) {
      return status('broken', 'Vault auto-commit is enabled, but the local vault Git repository is unavailable.');
    }
    const marker = regularFileWithoutSymlinkedParents(root, '.git/dex-vault-v2');
    let markerValue = null;
    try {
      markerValue = marker ? JSON.parse(fs.readFileSync(marker, 'utf8')) : null;
    } catch {
      markerValue = null;
    }
    if (markerValue?.role !== 'vault') {
      return status('off', 'Vault auto-commit waits until the one-time brain/vault upgrade is complete.');
    }
    releaseLock = acquireSharedLock(root);
    if (!releaseLock) {
      return status('off', 'Vault auto-commit paused because a migration or update is running.');
    }
    if (typeof options.onLockAcquired === 'function') options.onLockAcquired();
    if (operationInProgress(gitDirectory)) {
      return status('off', 'Vault auto-commit paused because a Git operation is in progress.');
    }
    if (!ensureLocalIdentity(root)) {
      return status('broken', 'Vault auto-commit could not set a local-only commit identity.');
    }
    const added = git(root, [
      'add', '-A', '--', '.',
      ':(exclude)System/.dex/**',
      ':(exclude).dex/**',
    ]);
    if (added.status !== 0) {
      return status('broken', 'Vault auto-commit could not prepare the local snapshot. Your files are unchanged.');
    }
    const staged = git(root, ['diff', '--cached', '--quiet']);
    if (staged.status === 0) {
      return status('ok', 'Your vault was already saved; there were no new changes to commit.');
    }
    if (staged.status !== 1) {
      return status('unknown', 'Vault auto-commit could not determine whether a local snapshot was needed.');
    }
    const now = options.now instanceof Date ? options.now : new Date();
    const committed = git(root, ['commit', '-m', `Dex vault ${localDate(now)}`]);
    if (committed.status !== 0) {
      return status('broken', 'Vault auto-commit could not create the local snapshot. Your files remain in the vault.');
    }
    return status('ok', 'Dex saved this session to your local vault history. No network action was taken.');
  } catch {
    return status('unknown', 'Vault auto-commit could not check this session, so it left the vault alone.');
  } finally {
    if (releaseLock) releaseLock();
  }
}

module.exports = { parseVaultAutoCommit, run };

if (require.main === module) {
  run();
  process.exitCode = 0;
}
