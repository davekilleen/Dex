#!/usr/bin/env node
'use strict';

// Fail-safe lock policy: any existing mutation.lock, including a stale lock
// left by a crashed updater, pauses auto-commit until recovery removes it.
// This hook never takes over a stale lock and never risks racing a vault mutation.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const FEATURE = 'Vault auto-commit';
// spawnSync defaults to 1 MiB. A vault note larger than that used to fail
// `git show` and get counted with protected files. Raise the cap, and keep
// unread/too-large distinct from a secret hold.
const GIT_SPAWN_MAX_BUFFER = 64 * 1024 * 1024;
const CONTRACT_RELATIVE = path.join(
  'packages',
  'dex-contracts',
  'dist',
  'portable-vault.contract.json',
);
const SECRET_CONTENT_PATTERNS = [
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  /\bgh[pousr]_[A-Za-z0-9]{20,}\b/,
  /\bsk-[A-Za-z0-9_-]{20,}\b/,
  /\bAKIA[A-Z0-9]{16}\b/,
  /"(?:access[_-]?token|refresh[_-]?token|client[_-]?secret|api[_-]?key|private[_-]?key)"\s*:\s*"[^"\s]{8,}"/i,
  /^\s*[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY|CREDENTIAL)[A-Z0-9_]*\s*=\s*\S+/m,
];

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
  const values = blocks[0]
    .filter((entry) => entry.indent === directIndent)
    .flatMap((entry) => {
      const match = /^\s*auto_commit:\s*([^#\s]+)\s*(?:#.*)?$/.exec(entry.line);
      return match ? [match[1].replace(/^['"]|['"]$/g, '').toLowerCase()] : [];
    });
  return values.length === 1 && values[0] === 'true';
}

function loadContract(root) {
  const contractPath = regularFileWithoutSymlinkedParents(root, CONTRACT_RELATIVE.replaceAll(path.sep, '/'));
  if (!contractPath) throw new Error('portable ownership contract is unavailable');
  const contract = JSON.parse(fs.readFileSync(contractPath, 'utf8'));
  if (
    !contract
    || contract.source !== 'core/portable_contract.py'
    || !Array.isArray(contract.rules)
    || !Array.isArray(contract.hard_deny)
  ) {
    throw new Error('portable ownership contract is invalid');
  }
  return contract;
}

function normalizeRelative(input) {
  const candidate = String(input).replaceAll('\\', '/').replace(/^\.\//, '');
  const parts = candidate.split('/');
  if (
    !candidate
    || candidate.startsWith('/')
    || /^[A-Za-z]:\//.test(candidate)
    || parts.some((part) => !part || part === '.' || part === '..')
  ) return null;
  return candidate;
}

function globMatches(candidate, pattern) {
  const escaped = pattern
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    .replaceAll('*', '[^/]*')
    .replaceAll('?', '[^/]');
  const expression = new RegExp(`^${escaped}$`, 'i');
  if (expression.test(candidate)) return true;
  return !pattern.includes('/') && candidate.split('/').some((part) => expression.test(part));
}

function classify(contract, input) {
  const candidate = normalizeRelative(input);
  if (!candidate) return { ownership: null, denied: true };
  if (contract.hard_deny.some((pattern) => globMatches(candidate, pattern))) {
    return { ownership: 'vault', denied: true };
  }
  const exact = contract.rules.find((rule) => rule.kind === 'file' && rule.path === candidate);
  if (exact) return { ownership: exact.ownership, denied: false };
  const matches = contract.rules.filter(
    (rule) => rule.kind === 'dir' && (candidate === rule.path || candidate.startsWith(`${rule.path}/`)),
  );
  if (matches.length === 0) return { ownership: null, denied: false };
  const longest = Math.max(...matches.map((rule) => rule.path.length));
  const mostSpecific = matches.filter((rule) => rule.path.length === longest);
  const classes = new Set(mostSpecific.map((rule) => rule.ownership));
  return { ownership: classes.size === 1 ? mostSpecific[0].ownership : null, denied: false };
}

function containsSecretContent(content) {
  const source = Buffer.isBuffer(content) ? content : Buffer.from(String(content));
  const text = source.toString('utf8');
  return SECRET_CONTENT_PATTERNS.some((expression) => expression.test(text));
}

function eligiblePath(contract, relative) {
  const verdict = classify(contract, relative);
  return !verdict.denied && ['vault', 'seed'].includes(verdict.ownership);
}

function acquireSharedLock(root) {
  const stateDirectory = path.join(root, 'System', '.dex');
  if (
    exists(stateDirectory)
    && (fs.lstatSync(stateDirectory).isSymbolicLink() || !fs.lstatSync(stateDirectory).isDirectory())
  ) return null;
  fs.mkdirSync(stateDirectory, { recursive: true });
  const lock = path.join(stateDirectory, 'mutation.lock');
  const token = `${process.pid}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  let descriptor;
  try {
    descriptor = fs.openSync(lock, 'wx', 0o600);
    fs.writeFileSync(
      descriptor,
      `${JSON.stringify({ pid: process.pid, kind: 'vault-auto-commit', token, at: new Date().toISOString() })}\n`,
    );
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor);
    descriptor = undefined;
    return () => {
      try {
        const current = JSON.parse(fs.readFileSync(lock, 'utf8'));
        if (current.token === token) fs.unlinkSync(lock);
      } catch {
        // A vanished lock or a new owner is left alone.
      }
    };
  } catch (error) {
    if (descriptor !== undefined) fs.closeSync(descriptor);
    if (error.code === 'EEXIST') return null;
    throw error;
  }
}

function trustedGit(root) {
  for (const candidate of ['/usr/bin/git', '/bin/git', '/usr/local/bin/git', '/opt/homebrew/bin/git']) {
    try {
      const resolved = fs.realpathSync(candidate);
      const stat = fs.statSync(resolved);
      if (!stat.isFile() || !(stat.mode & 0o111)) continue;
      if (resolved === path.resolve(root) || resolved.startsWith(`${path.resolve(root)}${path.sep}`)) continue;
      return resolved;
    } catch {
      // Try the next fixed system location.
    }
  }
  return null;
}

function git(root, args, options = {}) {
  const executable = trustedGit(root);
  if (!executable) return { status: 127, stdout: '', stderr: 'trusted system Git unavailable' };
  return spawnSync(executable, [
    '-c', 'commit.gpgsign=false',
    '-c', 'core.excludesFile=/dev/null',
    '-c', 'core.hooksPath=/dev/null',
    '-c', 'credential.helper=',
    '-C', root,
    ...args,
  ], {
    encoding: options.encoding === undefined ? 'utf8' : options.encoding,
    maxBuffer: options.maxBuffer || GIT_SPAWN_MAX_BUFFER,
    env: {
      PATH: `${path.dirname(executable)}:/usr/bin:/bin`,
      HOME: fs.existsSync('/var/empty') ? '/var/empty' : os.tmpdir(),
      GIT_CONFIG_GLOBAL: '/dev/null',
      GIT_CONFIG_NOSYSTEM: '1',
      GIT_TERMINAL_PROMPT: '0',
      GIT_OPTIONAL_LOCKS: '0',
    },
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
  for (const [key, value] of [['user.name', 'Dex Vault'], ['user.email', 'vault@example.com']]) {
    const current = git(root, ['config', '--local', '--get', key]);
    if (current.status === 0 && current.stdout.trim()) continue;
    if (git(root, ['config', '--local', key, value]).status !== 0) return false;
  }
  return true;
}

function nulPaths(result) {
  if (result.status !== 0) return null;
  return result.stdout.toString('utf8').split('\0').filter(Boolean);
}

function candidateWorktreePaths(root, contract) {
  const commands = [
    ['diff', '--name-only', '-z'],
    ['diff', '--cached', '--name-only', '-z'],
    ['ls-files', '--others', '--exclude-standard', '-z'],
  ];
  // The shipped .gitignore ignores the PARA folders wholesale, so the sweep above cannot
  // see a note the user wrote today — it would report a healthy snapshot that saved
  // nothing new (#485). Look inside the contract's own vault regions for ignored-but-
  // untracked content as well. Scoped deliberately to those regions: other ignored paths
  // (the Pipedrive cache, trusted-mcps.yaml, per-user integration settings) are ignored
  // because they should stay out of history, and this must not start sweeping them in.
  const regions = Array.isArray(contract.vault_regions) ? contract.vault_regions : [];
  if (regions.length > 0) {
    commands.push(['ls-files', '--others', '--ignored', '--exclude-standard', '-z', '--', ...regions]);
  }
  const paths = [];
  for (const command of commands) {
    const result = nulPaths(git(root, command, { encoding: null }));
    if (result === null) return null;
    paths.push(...result);
  }
  return [...new Set(paths)].sort();
}

function blobMaxBuffer(options = {}) {
  const requested = options.gitShowMaxBuffer;
  if (Number.isSafeInteger(requested) && requested > 0) return requested;
  return GIT_SPAWN_MAX_BUFFER;
}

function stagedBlobKind(root, relative, maxBuffer) {
  const sizeResult = git(root, ['cat-file', '-s', `:${relative}`]);
  if (sizeResult.status !== 0) return 'unread';
  const size = Number.parseInt(String(sizeResult.stdout).trim(), 10);
  if (!Number.isSafeInteger(size) || size < 0 || size > maxBuffer) return 'unread';
  const blob = git(root, ['show', `:${relative}`], { encoding: null, maxBuffer });
  if (blob.error || blob.status !== 0) return 'unread';
  if (containsSecretContent(blob.stdout)) return 'protected';
  return 'ok';
}

function stagedRejectedPaths(root, contract, maxBuffer) {
  const staged = nulPaths(
    git(root, ['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'], { encoding: null }),
  );
  if (staged === null) return null;
  const protectedPaths = [];
  const unreadPaths = [];
  for (const relative of staged) {
    if (!eligiblePath(contract, relative)) {
      protectedPaths.push(relative);
      continue;
    }
    const kind = stagedBlobKind(root, relative, maxBuffer);
    if (kind === 'protected') protectedPaths.push(relative);
    else if (kind === 'unread') unreadPaths.push(relative);
  }
  return { protectedPaths, unreadPaths };
}

function counted(noun, count) {
  return `${count} ${noun}${count === 1 ? '' : 's'}`;
}

function snapshotMessage(committed, protectedCount, unreadCount) {
  const held = protectedCount > 0
    ? `held back ${counted('protected file', protectedCount)}`
    : '';
  const unread = unreadCount > 0
    ? `could not read ${counted('file', unreadCount)}`
    : '';
  if (!committed && protectedCount === 0 && unreadCount === 0) {
    return 'Your vault was already saved; there were no new changes to commit.';
  }
  if (committed && protectedCount === 0 && unreadCount === 0) {
    return 'Dex saved this session to local vault history. It did not run a push.';
  }
  if (!committed) {
    if (protectedCount > 0 && unreadCount > 0) {
      return `Dex ${held} and ${unread}; there were no other changes to save.`;
    }
    return `Dex ${held || unread}; there were no other changes to save.`;
  }
  if (protectedCount > 0 && unreadCount > 0) {
    return `Dex saved eligible changes locally, ${held}, and ${unread}. It did not run a push.`;
  }
  return `Dex saved eligible changes locally and ${held || unread}. It did not run a push.`;
}

function unstagePaths(root, paths) {
  if (paths.length === 0) return true;
  const hasHead = git(root, ['rev-parse', '--verify', 'HEAD']).status === 0;
  const result = hasHead
    ? git(root, ['restore', '--staged', '--', ...paths])
    : git(root, ['rm', '--cached', '-r', '--ignore-unmatch', '--', ...paths]);
  return result.status === 0;
}

function run(options = {}) {
  let releaseLock = null;
  try {
    const root = path.resolve(options.root || process.env.CLAUDE_PROJECT_DIR || process.cwd());
    const profile = regularFileWithoutSymlinkedParents(root, 'System/user-profile.yaml');
    if (!profile || !parseVaultAutoCommit(fs.readFileSync(profile, 'utf8'))) {
      return status(
        'off',
        'Vault auto-commit is off by default. Set vault.auto_commit to true for local snapshots.',
      );
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
      return status('off', 'Vault auto-commit waits until the brain/vault split is complete.');
    }
    const contract = loadContract(root);
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
    const candidates = candidateWorktreePaths(root, contract);
    if (candidates === null) {
      return status('unknown', 'Vault auto-commit could not determine eligible local files.');
    }
    const eligible = candidates.filter((relative) => eligiblePath(contract, relative));
    // The shipped .gitignore ignores the PARA folders, and a pathspec add that touches an
    // ignored directory hard-fails as a whole — so a vault whose PARA content is tracked
    // (what the v1-to-v2 migration leaves behind) could never stage anything, and every
    // run returned broken into the SessionEnd void (#485). Eligibility here is decided by
    // the ownership contract above and the protected-file sweep below, not by .gitignore,
    // so bypass the ignore objection for exactly these paths — the same way the migration
    // stages the vault's existing history.
    if (eligible.length > 0 && git(root, ['add', '-A', '-f', '--', ...eligible]).status !== 0) {
      return status('broken', 'Vault auto-commit could not prepare the local snapshot. Files are unchanged.');
    }
    const verdicts = stagedRejectedPaths(root, contract, blobMaxBuffer(options));
    if (verdicts === null) {
      return status('broken', 'Vault auto-commit could not inspect staged files. Files are unchanged.');
    }
    const heldBack = [...verdicts.protectedPaths, ...verdicts.unreadPaths];
    if (!unstagePaths(root, heldBack)) {
      return status('broken', 'Vault auto-commit could not unstage files safely. Files are unchanged.');
    }
    const protectedCount = verdicts.protectedPaths.length;
    const unreadCount = verdicts.unreadPaths.length;
    const staged = git(root, ['diff', '--cached', '--quiet']);
    if (staged.status === 0) {
      return status('ok', snapshotMessage(false, protectedCount, unreadCount));
    }
    if (staged.status !== 1) {
      return status('unknown', 'Vault auto-commit could not determine whether a snapshot was needed.');
    }
    const now = options.now instanceof Date ? options.now : new Date();
    const committed = git(root, ['commit', '-m', `Dex vault ${localDate(now)}`]);
    if (committed.status !== 0) {
      return status('broken', 'Vault auto-commit could not create the local snapshot. Files remain in the vault.');
    }
    return status('ok', snapshotMessage(true, protectedCount, unreadCount));
  } catch {
    return status('unknown', 'Vault auto-commit could not check this session, so it left the vault alone.');
  } finally {
    if (releaseLock) releaseLock();
  }
}

module.exports = { classify, parseVaultAutoCommit, run, GIT_SPAWN_MAX_BUFFER };

if (require.main === module) {
  run();
  process.exitCode = 0;
}
