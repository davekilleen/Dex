#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const ownership = require('../update/ownership.cjs');

const START_MARKER = '## USER_EXTENSIONS_START';
const END_MARKER = '## USER_EXTENSIONS_END';
const JOURNAL_RELATIVE = path.join('System', '.dex', 'migration-v2-state.json');
const LOCK_RELATIVE = path.join('System', '.dex', '.migration-lock');
const TOPOLOGY_RELATIVE = path.join('System', '.dex', 'topology.json');
const P3_FILES_RELATIVE = path.join('System', '.dex', 'migration-v2-p3-files.json');
const HELD_BACK_RELATIVE = path.join('System', '.dex', 'held-back-paths.json');
const REPORT_RELATIVE = path.join('System', 'migration-report-v2.md');
const SNAPSHOT_RELATIVE = path.join('System', 'backups', 'pre-split');
const VAULT_MARKER = 'dex-vault-v2';
const BRAIN_MARKER = 'dex-brain-v2';
const ARCHIVE_MARKER = 'dex-pre-split-v2-archive.json';
const OFFICIAL_REMOTE = 'https://github.com/davekilleen/Dex.git';
const RESUME_EXIT = 75;
const P3_BATCH_SIZE = 64;
const SNAPSHOT_PATHS = [
  'CLAUDE.md',
  '.gitignore',
  'CLAUDE-custom.md',
  REPORT_RELATIVE,
  'System/user-profile.yaml',
  'package.json',
];

function extensionBlock(source) {
  const startPattern = /^## USER_EXTENSIONS_START[^\r\n]*(?:\r?\n|$)/m;
  const start = startPattern.exec(source);
  if (!start) throw new Error(`CLAUDE.md is missing ${START_MARKER}`);

  const afterStart = start.index + start[0].length;
  const endPattern = /^## USER_EXTENSIONS_END[^\r\n]*(?:\r?\n|$)/m;
  const end = endPattern.exec(source.slice(afterStart));
  if (!end) throw new Error(`CLAUDE.md is missing ${END_MARKER}`);
  const endIndex = afterStart + end.index;
  return {
    before: source.slice(0, start.index),
    startLine: start[0],
    content: source.slice(afterStart, endIndex),
    endLine: end[0],
    after: source.slice(endIndex + end[0].length),
  };
}

function extractLegacyExtensions(source) {
  return extensionBlock(source).content;
}

function emptyLegacyExtensionBlock(source) {
  const block = extensionBlock(source);
  return `${block.before}${block.startLine}${block.endLine}${block.after}`;
}

function regenerateClaude(template, customContent) {
  const block = extensionBlock(template);
  return `${block.before}${customContent}${block.after}`;
}

function fsyncDirectory(directory) {
  let descriptor;
  try {
    descriptor = fs.openSync(directory, 'r');
    fs.fsyncSync(descriptor);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
}

function writeFileFsynced(destination, content, mode = 0o600) {
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  const temporary = `${destination}.writing-${process.pid}`;
  let descriptor;
  try {
    descriptor = fs.openSync(temporary, 'w', mode);
    fs.writeFileSync(descriptor, content);
    fs.fsyncSync(descriptor);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
  fs.renameSync(temporary, destination);
  fsyncDirectory(path.dirname(destination));
}

function journalPath(root) {
  return path.join(root, JOURNAL_RELATIVE);
}

function writeJournal(root, state) {
  const destination = journalPath(root);
  const previous = `${destination}.previous`;
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  if (fs.existsSync(destination)) {
    const current = fs.readFileSync(destination);
    writeFileFsynced(previous, current);
  }
  writeFileFsynced(destination, `${JSON.stringify(state, null, 2)}\n`);
}

function readJournal(root) {
  const destination = journalPath(root);
  for (const [candidate, recovered] of [[destination, false], [`${destination}.previous`, true]]) {
    try {
      const state = JSON.parse(fs.readFileSync(candidate, 'utf8'));
      if (recovered) state.recoveredFromPrevious = true;
      return state;
    } catch (error) {
      if (!['ENOENT', 'EISDIR'].includes(error.code) && !(error instanceof SyntaxError)) throw error;
    }
  }
  return null;
}

function topologyDecision(topology) {
  const {
    rootGit,
    vaultStaging,
    brainGit,
    archiveGit,
    rootIsVault,
  } = topology;

  if (!rootGit && !vaultStaging && !brainGit && !archiveGit) return 'zip';
  if (archiveGit) {
    if (brainGit && vaultStaging) return 'continue-swap';
    if (rootGit && rootIsVault && brainGit) return 'post-split';
    return 'restore-archive';
  }
  if (rootGit) return 'pre-split';
  return 'invalid';
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

function assertSafeMutationRoots(root) {
  const checks = [
    [root, 'root'],
    [path.join(root, 'System'), 'System'],
    [path.join(root, '.dex'), '.dex'],
    [path.join(root, 'System', '.dex'), 'System/.dex'],
    [path.join(root, 'System', 'backups'), 'System/backups'],
  ];
  for (const [candidate, label] of checks) {
    try {
      if (fs.lstatSync(candidate).isSymbolicLink()) {
        throw new Error(`Dex stopped because the migration path ${label} is a symlink. Move the vault to normal folders, then try again.`);
      }
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    encoding: options.encoding === undefined ? 'utf8' : options.encoding,
    maxBuffer: options.maxBuffer || 16 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (!options.allowFailure && result.status !== 0) {
    const detail = `${result.stdout || ''}${result.stderr || ''}`.trim();
    throw new Error(detail || `${command} ${args.join(' ')} failed`);
  }
  return result;
}

function gitWorktree(root, args, options = {}) {
  return run('git', ['-c', 'commit.gpgsign=false', '-C', root, ...args], options);
}

function gitDir(root, gitDirectory, args, options = {}) {
  return run(
    'git',
    [
      '-c',
      'commit.gpgsign=false',
      `--git-dir=${gitDirectory}`,
      `--work-tree=${root}`,
      ...args,
    ],
    options,
  );
}

function gitOutput(root, gitDirectory, args, options = {}) {
  return gitDir(root, gitDirectory, args, options).stdout.trim();
}

function ensureIdentity(root, gitDirectory) {
  const name = gitDir(root, gitDirectory, ['config', '--get', 'user.name'], { allowFailure: true });
  if (name.status !== 0 || !name.stdout.trim()) {
    gitDir(root, gitDirectory, ['config', 'user.name', 'Dex Vault']);
  }
  const email = gitDir(root, gitDirectory, ['config', '--get', 'user.email'], { allowFailure: true });
  if (email.status !== 0 || !email.stdout.trim()) {
    gitDir(root, gitDirectory, ['config', 'user.email', 'vault@dex.local']);
  }
}

function markerExists(gitDirectory, marker) {
  return exists(path.join(gitDirectory, marker));
}

function inspectTopology(root) {
  const rootGitPath = path.join(root, '.git');
  const vaultStagingPath = path.join(root, '.dex', 'vault-staging.git');
  const brainGitPath = path.join(root, '.dex', 'brain.git');
  const archiveGitPath = path.join(root, '.dex', 'pre-split-archive.git');
  return {
    rootGit: exists(rootGitPath),
    vaultStaging: exists(vaultStagingPath),
    brainGit: exists(brainGitPath),
    archiveGit: exists(archiveGitPath),
    rootIsVault: markerExists(rootGitPath, VAULT_MARKER),
  };
}

function sleep(milliseconds) {
  const waitBuffer = new SharedArrayBuffer(4);
  Atomics.wait(new Int32Array(waitBuffer), 0, 0, milliseconds);
}

function removePath(candidate) {
  if (!exists(candidate)) return;
  fs.rmSync(candidate, { recursive: true, force: true });
}

function moveWithFallback(source, destination) {
  if (!exists(source)) return;
  let lastError;
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    try {
      fs.renameSync(source, destination);
      fsyncDirectory(path.dirname(destination));
      return;
    } catch (error) {
      lastError = error;
      if (!['EACCES', 'EBUSY', 'EPERM', 'EXDEV'].includes(error.code)) throw error;
      sleep(attempt * 80);
    }
  }

  const copying = `${destination}.copying-${process.pid}`;
  removePath(copying);
  fs.cpSync(source, copying, { recursive: true, preserveTimestamps: true, errorOnExist: true });
  fs.renameSync(copying, destination);
  fsyncDirectory(path.dirname(destination));
  removePath(source);
  if (!exists(destination)) throw lastError || new Error(`Could not move ${source}`);
}

function processIsRunning(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

function acquireLock(root) {
  const lock = path.join(root, LOCK_RELATIVE);
  fs.mkdirSync(path.dirname(lock), { recursive: true });
  if (exists(lock)) {
    let holder = null;
    try {
      holder = JSON.parse(fs.readFileSync(lock, 'utf8'));
    } catch {
      // A malformed lock is treated as stale because an atomic writer never leaves one.
    }
    if (holder && processIsRunning(holder.pid)) {
      throw new Error(`Another Dex migration is still running (process ${holder.pid}). Wait for it to finish, then try again.`);
    }
    fs.unlinkSync(lock);
  }
  const descriptor = fs.openSync(lock, 'wx', 0o600);
  try {
    fs.writeFileSync(descriptor, `${JSON.stringify({ pid: process.pid, startedAt: new Date().toISOString() })}\n`);
    fs.fsyncSync(descriptor);
  } finally {
    fs.closeSync(descriptor);
  }
  fsyncDirectory(path.dirname(lock));
  return () => {
    if (exists(lock)) fs.unlinkSync(lock);
    try {
      fsyncDirectory(path.dirname(lock));
    } catch {
      // The restore path may have removed the now-empty journal directory.
    }
  };
}

function directorySize(root) {
  let total = 0;
  const skippedNames = new Set(['.git', '.dex', 'node_modules', '.venv']);
  function visit(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.isDirectory() && skippedNames.has(entry.name)) continue;
      const candidate = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) visit(candidate);
      else if (entry.isFile()) total += fs.statSync(candidate).size;
    }
  }
  visit(root);
  return total;
}

function availableBytes(root) {
  if (typeof fs.statfsSync !== 'function') return Number.MAX_SAFE_INTEGER;
  const stats = fs.statfsSync(root, { bigint: true });
  return Number(stats.bavail * stats.bsize);
}

function findReleaseRef(root, gitDirectory) {
  const officialUrl = /^(?:(?:https?|ssh|git):\/\/(?:git@)?github\.com\/|git@github\.com:)davekilleen\/Dex(?:\.git)?\/?$/i;
  for (const remote of safeRemoteNames(root, gitDirectory)) {
    const url = gitDir(root, gitDirectory, ['remote', 'get-url', remote], { allowFailure: true });
    if (url.status !== 0 || !officialUrl.test(url.stdout.trim())) continue;
    const candidate = `refs/remotes/${remote}/release`;
    const result = gitDir(root, gitDirectory, ['rev-parse', '--verify', `${candidate}^{commit}`], {
      allowFailure: true,
    });
    if (result.status === 0) {
      return { ref: candidate, commit: result.stdout.trim() };
    }
  }

  const localRef = 'refs/heads/release';
  const local = gitDir(root, gitDirectory, ['rev-parse', '--verify', `${localRef}^{commit}`], {
    allowFailure: true,
  });
  if (local.status === 0) {
    const tip = local.stdout.trim();
    const head = gitOutput(root, gitDirectory, ['rev-parse', 'HEAD']);
    const reachesWorkingHead = gitDir(
      root,
      gitDirectory,
      ['merge-base', '--is-ancestor', tip, head],
      { allowFailure: true },
    ).status === 0;
    const backupTags = gitDir(root, gitDirectory, ['tag', '--list', 'backup-before-*'], {
      allowFailure: true,
    }).stdout.split(/\r?\n/).filter(Boolean);
    const containsBackupCommit = backupTags.some((tag) => (
      gitDir(root, gitDirectory, ['merge-base', '--is-ancestor', tag, tip], {
        allowFailure: true,
      }).status === 0
    ));
    if (!reachesWorkingHead && !containsBackupCommit) {
      return { ref: localRef, commit: tip };
    }
  }

  throw new Error('Dex could not prove that the local release branch contains only official release history. Restore the official upstream remote, fetch its release branch, then try again.');
}

function safeRemoteNames(root, gitDirectory) {
  const result = gitDir(root, gitDirectory, ['remote'], { allowFailure: true });
  return result.status === 0 ? result.stdout.split(/\r?\n/).filter(Boolean) : [];
}

function mergeInProgress(root) {
  const gitPathResult = gitWorktree(root, ['rev-parse', '--git-path', 'MERGE_HEAD'], { allowFailure: true });
  if (gitPathResult.status !== 0) return false;
  const mergeHead = path.resolve(root, gitPathResult.stdout.trim());
  if (exists(mergeHead)) return true;
  for (const name of ['rebase-merge', 'rebase-apply', 'CHERRY_PICK_HEAD', 'REVERT_HEAD']) {
    const result = gitWorktree(root, ['rev-parse', '--git-path', name], { allowFailure: true });
    if (result.status === 0 && exists(path.resolve(root, result.stdout.trim()))) return true;
  }
  return false;
}

function modifiedBrainPaths(root, gitDirectory, releaseRef) {
  const tags = gitDir(
    root,
    gitDirectory,
    ['tag', '--list', 'backup-before-*', '--sort=-creatordate'],
    { allowFailure: true },
  ).stdout.split(/\r?\n/).filter(Boolean);
  if (tags.length === 0) return { backupTag: null, mergeBase: null, paths: [] };
  const backupTag = tags[0];
  const mergeBaseResult = gitDir(root, gitDirectory, ['merge-base', backupTag, releaseRef], {
    allowFailure: true,
  });
  if (mergeBaseResult.status !== 0) return { backupTag, mergeBase: null, paths: [] };
  const mergeBase = mergeBaseResult.stdout.trim();
  const changed = gitDir(root, gitDirectory, ['diff', '--name-only', '-z', mergeBase, backupTag], {
    encoding: null,
  }).stdout.toString('utf8').split('\0').filter(Boolean);
  return {
    backupTag,
    mergeBase,
    paths: changed.filter((candidate) => ownership.classify(candidate) === 'brain'),
  };
}

function renderReport(report) {
  const modeLine = report.complete
    ? 'The split is complete. Your files stayed where they were; only their Git ownership changed.'
    : report.zip
      ? 'This folder was downloaded as a ZIP, so Dex left it exactly as it was.'
      : report.dryRun
        ? 'This was a preview. Only this report was written; the split has not started.'
        : 'The split is in progress. If it was interrupted, run the migrator with --resume.';
  const modified = report.modifiedBrainPaths || [];
  const remotes = report.remoteNames || [];
  const findings = report.secretFindings || [];
  const heldBack = report.heldBackPaths || [...new Set(findings.map((finding) => finding.path))];
  return [
    '# Your Dex brain and vault split',
    '',
    modeLine,
    '',
    '## What Dex found',
    '',
    `- ${modified.length} shipped ${modified.length === 1 ? 'file has' : 'files have'} your own edits. Dex only listed them; it did not replace them.`,
    `- ${remotes.length} old ${remotes.length === 1 ? 'remote was' : 'remotes were'} found${remotes.length ? ` (${remotes.join(', ')})` : ''}. None will be carried into your private vault repository.`,
    `- The secret check found ${findings.length} possible ${findings.length === 1 ? 'match' : 'matches'} in files eligible for vault history. It never copied the matching text.`,
    `- ${heldBack.length} ${heldBack.length === 1 ? 'file was' : 'files were'} held back from the initial vault history for review. The files remain in place.`,
    '',
    ...(modified.length ? ['### Shipped files with your edits', '', ...modified.map((item) => `- ${item}`), ''] : []),
    ...(findings.length ? ['### Secret-check warnings', '', ...findings.map((item) => `- ${item.path} (${item.kind})`), ''] : []),
    ...(heldBack.length ? ['### Held back from the initial vault history', '', ...heldBack.map((item) => `- ${item}`), ''] : []),
    ...(report.liftedInlineExtensions ? [
      '### Preserved instruction sources',
      '',
      '- CLAUDE-custom.md already existed, so Dex appended the distinct inline USER_EXTENSIONS block under a labelled migration heading.',
      '',
    ] : []),
    ...(report.failure ? ['## Why Dex stopped', '', report.failure, ''] : []),
    '## What stays yours',
    '',
    '- Notes, tasks, projects, people, archives, custom skills, and custom connections stay in place.',
    '- Secret files and machine-only state are excluded from vault history.',
    '- The new vault repository has no remote. Dex will not upload it anywhere.',
    '',
    'If you want an off-device backup later, add a private Git remote deliberately after reviewing what it contains.',
    '',
    '## Optional local history after each session',
    '',
    'Vault auto-commit is off by default. To enable local SessionEnd snapshots, set this in System/user-profile.yaml:',
    '',
    '```yaml',
    'vault:',
    '  auto_commit: true',
    '```',
    '',
    'This creates local commits only and never pushes them anywhere.',
    '',
    ...(report.zip ? [
      '## ZIP install next step',
      '',
      'No conversion was started. To use automatic updates, install Dex from a Git clone, copy your vault files into it, and run this preview again. Staying on the manual-update path is also safe.',
      '',
    ] : []),
  ].join('\n');
}

function writeReport(root, report) {
  ensureReportSnapshot(root);
  writeFileFsynced(path.join(root, REPORT_RELATIVE), renderReport(report), 0o644);
}

function fileSha256(candidate) {
  return crypto.createHash('sha256').update(fs.readFileSync(candidate)).digest('hex');
}

function ensureReportSnapshot(root) {
  const backupRoot = path.join(root, SNAPSHOT_RELATIVE);
  const manifestPath = path.join(backupRoot, 'snapshot.json');
  if (exists(manifestPath)) return;
  const planPath = path.join(backupRoot, '.snapshot-plan.json');
  if (!exists(planPath)) {
    snapshotFiles(root, 'preflight');
    return;
  }

  const plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));
  const entry = plan.entries.find((candidate) => candidate.path === REPORT_RELATIVE);
  if (!entry || !entry.existed) return;
  const destination = path.join(backupRoot, 'files', REPORT_RELATIVE);
  if (exists(destination)) return;
  const source = path.join(root, REPORT_RELATIVE);
  if (!exists(source) || fileSha256(source) !== entry.sha256) {
    throw new Error('Dex could not safely preserve the existing migration report before writing a new one. The report was left unchanged.');
  }
  writeFileFsynced(destination, fs.readFileSync(source), entry.mode);
  fs.chmodSync(destination, entry.mode);
}

function snapshotFiles(root, migrationId = null) {
  const backupRoot = path.join(root, SNAPSHOT_RELATIVE);
  const manifestPath = path.join(backupRoot, 'snapshot.json');
  const planPath = path.join(backupRoot, '.snapshot-plan.json');
  let adoptedReport = null;
  if (exists(manifestPath)) {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    if (!migrationId || manifest.migrationId === migrationId) return manifest;
    if (
      ['dry-run', 'preflight'].includes(manifest.migrationId)
      && !['dry-run', 'preflight'].includes(migrationId)
    ) {
      const entry = manifest.entries.find((candidate) => candidate.path === REPORT_RELATIVE);
      if (entry) {
        adoptedReport = { entry: { ...entry }, bytes: null };
        if (entry.existed) {
          adoptedReport.bytes = fs.readFileSync(path.join(backupRoot, 'files', REPORT_RELATIVE));
        }
      }
    }
    removePath(backupRoot);
  }

  let plan;
  if (exists(planPath)) {
    plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));
    if (migrationId && plan.migrationId !== migrationId) {
      removePath(backupRoot);
      plan = null;
    }
  }
  if (!plan) {
    const entries = [];
    for (const relative of SNAPSHOT_PATHS) {
      if (relative === REPORT_RELATIVE && adoptedReport) {
        entries.push(adoptedReport.entry);
        continue;
      }
      const source = path.join(root, relative);
      const entry = { path: relative, existed: exists(source) };
      if (entry.existed) {
        const stat = fs.lstatSync(source);
        if (!stat.isFile() || stat.isSymbolicLink()) {
          throw new Error(`P2 cannot safely snapshot ${relative} because it is not a regular file.`);
        }
        entry.mode = stat.mode & 0o777;
        entry.sha256 = fileSha256(source);
      }
      entries.push(entry);
    }
    plan = {
      schemaVersion: 1,
      migrationId,
      createdAt: new Date().toISOString(),
      entries,
    };
    writeFileFsynced(planPath, `${JSON.stringify(plan, null, 2)}\n`);
  }

  if (adoptedReport?.entry.existed) {
    const destination = path.join(backupRoot, 'files', REPORT_RELATIVE);
    writeFileFsynced(destination, adoptedReport.bytes, adoptedReport.entry.mode);
    fs.chmodSync(destination, adoptedReport.entry.mode);
  }

  for (const entry of plan.entries) {
    if (!entry.existed) continue;
    const source = path.join(root, entry.path);
    const destination = path.join(backupRoot, 'files', entry.path);
    if (exists(destination)) {
      if (fileSha256(destination) !== entry.sha256) {
        throw new Error(`P2 stopped because its partial backup for ${entry.path} did not match the saved plan.`);
      }
    } else {
      if (!exists(source) || fileSha256(source) !== entry.sha256) {
        throw new Error(`P2 stopped because ${entry.path} changed while its backup was incomplete.`);
      }
      writeFileFsynced(destination, fs.readFileSync(source), entry.mode);
      fs.chmodSync(destination, entry.mode);
    }
    if (process.env.DEX_MIGRATION_STOP_AFTER_SNAPSHOT_FILE === entry.path) {
      throw new Error('Stopped safely while testing P2 snapshot recovery. Run --resume to continue.');
    }
  }
  writeFileFsynced(manifestPath, `${JSON.stringify(plan, null, 2)}\n`);
  return plan;
}

function restoreSnapshot(root) {
  const backupRoot = path.join(root, SNAPSHOT_RELATIVE);
  const manifestPath = path.join(backupRoot, 'snapshot.json');
  if (!exists(manifestPath)) return;
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  for (const entry of manifest.entries) {
    const destination = path.join(root, entry.path);
    if (!entry.existed) {
      removePath(destination);
      continue;
    }
    const source = path.join(backupRoot, 'files', entry.path);
    const bytes = fs.readFileSync(source);
    const digest = crypto.createHash('sha256').update(bytes).digest('hex');
    if (digest !== entry.sha256) throw new Error(`Backup verification failed for ${entry.path}`);
    writeFileFsynced(destination, bytes, entry.mode);
    fs.chmodSync(destination, entry.mode);
  }
}

function walkVaultFiles(root) {
  const files = [];
  const skipped = new Set(['.git', '.dex', 'node_modules', '.venv']);
  function visit(directory, relativeDirectory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.isDirectory() && skipped.has(entry.name)) continue;
      const relative = relativeDirectory ? `${relativeDirectory}/${entry.name}` : entry.name;
      const absolute = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) visit(absolute, relative);
      else if (entry.isFile()) files.push(relative);
    }
  }
  visit(root, '');
  return files;
}

function scanForSecrets(root) {
  const findings = [];
  for (const relative of walkVaultFiles(root)) {
    const className = ownership.classify(relative);
    if (!['vault', 'seed'].includes(className)) continue;
    if (ownership.isSecretPath(relative)) {
      findings.push({ path: relative, kind: 'secret file path' });
      continue;
    }
    const absolute = path.join(root, relative);
    if (fs.statSync(absolute).size > 1024 * 1024) continue;
    const bytes = fs.readFileSync(absolute);
    if (bytes.includes(0)) continue;
    if (ownership.containsSecretContent(bytes)) findings.push({ path: relative, kind: 'secret-shaped content' });
  }
  return findings;
}

function persistHeldBackPaths(root, paths) {
  const normalized = ownership.normalizeHeldBackPaths(paths);
  writeFileFsynced(
    path.join(root, HELD_BACK_RELATIVE),
    `${JSON.stringify({ schemaVersion: 1, paths: normalized }, null, 2)}\n`,
  );
  return normalized;
}

function writeVaultExcludes(root, gitDirectory, heldBackPaths) {
  fs.mkdirSync(path.join(gitDirectory, 'info'), { recursive: true });
  writeFileFsynced(
    path.join(gitDirectory, 'info', 'exclude'),
    `${ownership.vaultExcludeLines(heldBackPaths).join('\n')}\n`,
    0o644,
  );
}

function writeGitdirMarker(gitDirectory, marker, payload) {
  writeFileFsynced(path.join(gitDirectory, marker), `${JSON.stringify(payload, null, 2)}\n`);
}

function initializeVaultGitdir(root, gitDirectory, heldBackPaths = []) {
  if (!exists(gitDirectory)) {
    fs.mkdirSync(path.dirname(gitDirectory), { recursive: true });
    run('git', ['init', '--bare', '--quiet', gitDirectory]);
    gitDir(root, gitDirectory, ['config', 'core.bare', 'false']);
    gitDir(root, gitDirectory, ['config', '--unset-all', 'core.worktree'], { allowFailure: true });
  }
  ensureIdentity(root, gitDirectory);
  const remotes = safeRemoteNames(root, gitDirectory);
  for (const remote of remotes) gitDir(root, gitDirectory, ['remote', 'remove', remote]);
  writeVaultExcludes(root, gitDirectory, heldBackPaths);
  writeGitdirMarker(gitDirectory, VAULT_MARKER, { schemaVersion: 1, role: 'vault' });
}

function p3CandidateFiles(root, gitDirectory) {
  const result = gitDir(root, gitDirectory, ['-c', 'core.excludesFile=/dev/null', 'ls-files', '--others', '--exclude-standard', '-z'], {
    encoding: null,
  });
  return result.stdout.toString('utf8').split('\0').filter(Boolean).sort();
}

function independentVaultInventory(root, heldBackPaths = []) {
  const heldBack = new Set(heldBackPaths);
  return walkVaultFiles(root)
    .filter((relative) => ['vault', 'seed'].includes(ownership.classify(relative)))
    .filter((relative) => !ownership.isVaultIgnoredPath(relative))
    .filter((relative) => !heldBack.has(relative))
    .sort()
    .map((relative) => ({ path: relative, sha256: fileSha256(path.join(root, relative)) }));
}

function phase3BuildVault(root, state) {
  const gitDirectory = path.join(root, '.dex', 'vault-staging.git');
  initializeVaultGitdir(root, gitDirectory, state.analysis?.heldBackPaths || []);
  writeFileFsynced(path.join(root, '.gitignore'), ownership.vaultGitignoreContent(), 0o644);

  const planPath = path.join(root, P3_FILES_RELATIVE);
  let plan;
  if (exists(planPath)) {
    plan = JSON.parse(fs.readFileSync(planPath, 'utf8'));
  } else {
    const heldBackPaths = state.analysis?.heldBackPaths || [];
    plan = {
      schemaVersion: 2,
      gitCandidates: p3CandidateFiles(root, gitDirectory),
      expected: independentVaultInventory(root, heldBackPaths),
      heldBackPaths,
    };
    writeFileFsynced(planPath, `${JSON.stringify(plan, null, 2)}\n`);
  }
  const files = Array.isArray(plan) ? plan : plan.expected.map((entry) => entry.path);
  state.p3 = state.p3 || { nextIndex: 0, total: files.length };
  state.p3.total = files.length;

  const start = state.p3.nextIndex;
  const end = Math.min(start + P3_BATCH_SIZE, files.length);
  const batch = files.slice(start, end);
  if (batch.length > 0) {
    gitDir(root, gitDirectory, ['-c', 'core.excludesFile=/dev/null', 'add', '-f', '--', ...batch]);
  }
  state.p3.nextIndex = end;
  console.log(`P3 indexed batch ${start + 1}-${end} of ${files.length}.`);

  if (end < files.length) return { needsResume: true };
  const head = gitDir(root, gitDirectory, ['rev-parse', '--verify', 'HEAD'], { allowFailure: true });
  if (head.status !== 0) {
    gitDir(root, gitDirectory, ['commit', '--quiet', '-m', 'Your vault — everything here is yours']);
  }
  state.p3.initialCommit = gitOutput(root, gitDirectory, ['rev-parse', 'HEAD']);
  console.log(`P3 vault snapshot complete with ${files.length} files.`);
  return { needsResume: false };
}

function phase0Preflight(root, state) {
  console.log('P0 preflight: checking that this vault is ready.');
  if (!exists(path.join(root, '.git'))) return { zip: true };
  if (!fs.lstatSync(path.join(root, '.git')).isDirectory()) {
    throw new Error('P0 needs a normal Dex Git folder. Linked-worktree .git files are not migrated automatically.');
  }
  if (mergeInProgress(root)) {
    throw new Error('P0 stopped because a Git operation is in progress. Please finish or abort the merge, rebase, or cherry-pick, then run the migration again.');
  }
  fs.accessSync(root, fs.constants.R_OK | fs.constants.W_OK);
  const vaultBytes = directorySize(root);
  const freeBytes = availableBytes(root);
  if (freeBytes < vaultBytes * 2) {
    throw new Error(`P0 needs about ${vaultBytes * 2} free bytes to build the two safe histories; only ${freeBytes} are available.`);
  }

  const oldGitDirectory = path.join(root, '.git');
  const release = findReleaseRef(root, oldGitDirectory);
  const head = gitOutput(root, oldGitDirectory, ['rev-parse', 'HEAD']);
  const branch = gitOutput(root, oldGitDirectory, ['symbolic-ref', '--short', '-q', 'HEAD'], {
    allowFailure: true,
  });
  const stashes = gitDir(root, oldGitDirectory, ['stash', 'list', '--format=%H'], {
    allowFailure: true,
  }).stdout.split(/\r?\n/).filter(Boolean);
  state.preflight = {
    head,
    branch: branch || null,
    remoteNames: safeRemoteNames(root, oldGitDirectory),
    stashOids: stashes,
    releaseRef: release.ref,
    releaseCommit: release.commit,
    vaultBytes,
    freeBytes,
  };
  return { zip: false };
}

function phase1Report(root, state, dryRun = false) {
  console.log('P1 report: describing the split before anything moves.');
  snapshotFiles(root, state.startedAt || 'dry-run');
  const oldGitDirectory = path.join(root, '.git');
  const modified = modifiedBrainPaths(root, oldGitDirectory, state.preflight.releaseRef);
  state.analysis = {
    backupTag: modified.backupTag,
    mergeBase: modified.mergeBase,
    modifiedBrainPaths: modified.paths,
    secretFindings: state.analysis?.secretFindings || [],
  };
  writeReport(root, {
    dryRun,
    modifiedBrainPaths: modified.paths,
    remoteNames: state.preflight.remoteNames,
    secretFindings: state.analysis.secretFindings,
  });
}

function phase2SnapshotAndScan(root, state) {
  console.log('P2 snapshot and secret check: saving only the files this migration rewrites.');
  snapshotFiles(root, state.startedAt);
  state.analysis.secretFindings = scanForSecrets(root);
  state.analysis.heldBackPaths = persistHeldBackPaths(
    root,
    state.analysis.secretFindings.map((finding) => finding.path),
  );
  writeReport(root, {
    modifiedBrainPaths: state.analysis.modifiedBrainPaths,
    remoteNames: state.preflight.remoteNames,
    secretFindings: state.analysis.secretFindings,
    heldBackPaths: state.analysis.heldBackPaths,
  });
}

function phase4BuildBrain(root, state) {
  console.log('P4 brain history: building a fresh release-only Git store.');
  const brainGit = path.join(root, '.dex', 'brain.git');
  if (markerExists(brainGit, BRAIN_MARKER)) return;
  removePath(brainGit);
  fs.mkdirSync(path.dirname(brainGit), { recursive: true });
  run('git', ['init', '--bare', '--quiet', brainGit]);
  const oldGit = path.join(root, '.git');
  run('git', [
    '-c',
    'protocol.file.allow=always',
    `--git-dir=${brainGit}`,
    'fetch',
    '--quiet',
    '--no-tags',
    oldGit,
    `+${state.preflight.releaseRef}:refs/heads/release`,
  ]);
  gitDir(root, brainGit, ['read-tree', `${state.preflight.releaseCommit}^{tree}`]);
  gitDir(root, brainGit, ['update-ref', 'refs/dex/installed', state.preflight.releaseCommit]);
  gitDir(root, brainGit, ['remote', 'add', 'origin', OFFICIAL_REMOTE]);
  gitDir(root, brainGit, ['config', '--unset-all', 'core.worktree'], { allowFailure: true });
  writeGitdirMarker(brainGit, BRAIN_MARKER, {
    schemaVersion: 1,
    role: 'brain',
    installed: state.preflight.releaseCommit,
  });
}

function writeTopologySentinel(root, releaseCommit) {
  writeFileFsynced(
    path.join(root, TOPOLOGY_RELATIVE),
    `${JSON.stringify({
      schemaVersion: 1,
      topology: 'brain-vault-split',
      vaultGitDir: '.git',
      brainGitDir: '.dex/brain.git',
      archiveGitDir: '.dex/pre-split-archive.git',
      installedRelease: releaseCommit,
    }, null, 2)}\n`,
  );
}

function phase5Swap(root, state) {
  console.log('P5 swap: making the prepared vault history active.');
  const rootGit = path.join(root, '.git');
  const archive = path.join(root, '.dex', 'pre-split-archive.git');
  const staging = path.join(root, '.dex', 'vault-staging.git');

  if (markerExists(rootGit, VAULT_MARKER) && exists(archive)) {
    writeTopologySentinel(root, state.preflight.releaseCommit);
    return;
  }
  if (!exists(archive)) {
    writeGitdirMarker(rootGit, ARCHIVE_MARKER, {
      schemaVersion: 1,
      migrationId: state.startedAt,
      preSplitHead: state.preflight.head,
      releaseCommit: state.preflight.releaseCommit,
    });
    moveWithFallback(rootGit, archive);
    state.swapStage = 'archive-moved';
    writeJournal(root, state);
    if (process.env.DEX_MIGRATION_STOP_DURING_P5 === 'archive-moved') {
      return { stopped: true };
    }
  }
  if (!exists(rootGit)) moveWithFallback(staging, rootGit);
  if (!markerExists(rootGit, VAULT_MARKER)) {
    throw new Error('P5 stopped because the new root Git folder has no vault marker. Run --restore.');
  }
  state.swapStage = 'vault-active';
  writeJournal(root, state);
  writeTopologySentinel(root, state.preflight.releaseCommit);
}

function stampVaultSchema(source) {
  if (/^vault_schema:\s*/m.test(source)) {
    return source.replace(/^vault_schema:\s*.*$/m, 'vault_schema: 1');
  }
  return `${source.replace(/\s*$/, '')}\n\nvault_schema: 1\n`;
}

function stampPackageSupport(source) {
  const packageJson = JSON.parse(source);
  packageJson.dex = {
    ...(packageJson.dex || {}),
    vault_schema: 1,
    brain_support: '>=2.0.0 <3.0.0',
  };
  return `${JSON.stringify(packageJson, null, 2)}\n`;
}

function mergedCustomInstructions(existingCustom, inlineExtensions) {
  if (existingCustom === inlineExtensions) {
    return { content: existingCustom, appended: false };
  }
  const heading = '## Lifted from CLAUDE.md during v2 migration';
  const separator = existingCustom.endsWith('\n') ? '\n' : '\n\n';
  const liftedSection = `${heading}\n\n${inlineExtensions}`;
  if (existingCustom.includes(liftedSection)) {
    return { content: existingCustom, appended: false };
  }
  return {
    content: `${existingCustom}${separator}${liftedSection}`,
    appended: true,
  };
}

function phase6Rematerialize(root, state = {}) {
  console.log('P6 instructions: lifting your extension block into CLAUDE-custom.md.');
  const claudePath = path.join(root, 'CLAUDE.md');
  const customPath = path.join(root, 'CLAUDE-custom.md');
  const legacy = fs.readFileSync(claudePath, 'utf8');
  const hasLegacyMarkers = legacy.includes(START_MARKER);
  let custom = exists(customPath) ? fs.readFileSync(customPath, 'utf8') : null;
  let appended = false;

  if (!hasLegacyMarkers && custom !== null) {
    // P6 already completed its destructive-to-markers step before the phase journal advanced.
  } else {
    const inlineExtensions = extractLegacyExtensions(legacy);
    if (custom === null) {
      custom = inlineExtensions;
    } else {
      const merged = mergedCustomInstructions(custom, inlineExtensions);
      custom = merged.content;
      appended = merged.appended;
    }
    writeFileFsynced(customPath, custom, 0o644);
    const template = emptyLegacyExtensionBlock(legacy);
    writeFileFsynced(claudePath, regenerateClaude(template, custom), 0o644);
  }

  state.analysis = state.analysis || {};
  if (appended) {
    state.analysis.liftedInlineExtensions = true;
    console.log('P6 preserved both instruction sources in CLAUDE-custom.md under a labelled migration heading.');
  }
  state.p6 = {
    liftComplete: true,
    claudeSha256: fileSha256(claudePath),
    customSha256: fileSha256(customPath),
  };
  if (state.schemaVersion) writeJournal(root, state);
  if (process.env.DEX_MIGRATION_STOP_DURING_P6 === 'lift-complete') {
    throw new Error('Stopped safely inside P6 after preserving the lifted instructions. Run --resume to continue.');
  }

  const profilePath = path.join(root, 'System', 'user-profile.yaml');
  if (exists(profilePath)) {
    writeFileFsynced(profilePath, stampVaultSchema(fs.readFileSync(profilePath, 'utf8')), 0o644);
  }
  const packagePath = path.join(root, 'package.json');
  if (exists(packagePath)) {
    writeFileFsynced(packagePath, stampPackageSupport(fs.readFileSync(packagePath, 'utf8')), 0o644);
  }
}

function phase7ReportOnly(state) {
  const count = state.analysis?.modifiedBrainPaths?.length || 0;
  console.log(`P7 report only: ${count} modified shipped ${count === 1 ? 'file was' : 'files were'} left untouched.`);
}

function phase8Verify(root, state) {
  console.log('P8 self-check: verifying both histories without installed dependencies.');
  const vaultGit = path.join(root, '.git');
  const brainGit = path.join(root, '.dex', 'brain.git');
  gitDir(root, vaultGit, ['fsck', '--no-progress']);
  gitDir(root, brainGit, ['fsck', '--no-progress']);
  if (safeRemoteNames(root, vaultGit).length !== 0) throw new Error('P8 found a remote in the new vault repository.');
  const coreWorktree = gitDir(root, brainGit, ['config', '--get', 'core.worktree'], { allowFailure: true });
  if (coreWorktree.status === 0 && coreWorktree.stdout.trim()) throw new Error('P8 found core.worktree set in brain.git.');
  if (!markerExists(vaultGit, VAULT_MARKER) || !markerExists(brainGit, BRAIN_MARKER)) {
    throw new Error('P8 could not find both topology markers.');
  }
  const plan = JSON.parse(fs.readFileSync(path.join(root, P3_FILES_RELATIVE), 'utf8'));
  const expectedEntries = Array.isArray(plan)
    ? plan.map((relative) => ({ path: relative, sha256: null }))
    : plan.expected;
  const initialCommit = state.p3?.initialCommit || 'HEAD';
  const treeOutput = gitDir(root, vaultGit, ['ls-tree', '-r', '-z', initialCommit], { encoding: null })
    .stdout.toString('utf8');
  const tree = new Map();
  for (const record of treeOutput.split('\0').filter(Boolean)) {
    const separator = record.indexOf('\t');
    const metadata = record.slice(0, separator).split(/\s+/);
    tree.set(record.slice(separator + 1), metadata[2]);
  }
  if (tree.size !== expectedEntries.length) {
    throw new Error(`P8 expected ${expectedEntries.length} files in the initial vault snapshot but found ${tree.size}.`);
  }
  for (const entry of expectedEntries) {
    const oid = tree.get(entry.path);
    if (!oid) throw new Error(`P8 expected ${entry.path} in the initial vault snapshot, but it was missing.`);
    if (entry.sha256) {
      const blob = gitDir(root, vaultGit, ['cat-file', 'blob', oid], { encoding: null }).stdout;
      const actualSha256 = crypto.createHash('sha256').update(blob).digest('hex');
      if (actualSha256 !== entry.sha256) throw new Error(`P8 byte check failed for ${entry.path}`);
    }
  }
}

function phase9Finalize(root, state) {
  const vaultGit = path.join(root, '.git');
  ensureIdentity(root, vaultGit);
  state.analysis = state.analysis || {};
  const finalFindings = scanForSecrets(root);
  const findingKeys = new Set();
  state.analysis.secretFindings = [
    ...(state.analysis?.secretFindings || []),
    ...finalFindings,
  ].filter((finding) => {
    const key = `${finding.path}\0${finding.kind}`;
    if (findingKeys.has(key)) return false;
    findingKeys.add(key);
    return true;
  });
  state.analysis.heldBackPaths = [
    ...new Set(state.analysis.secretFindings.map((finding) => finding.path)),
  ].sort();
  state.analysis.heldBackPaths = persistHeldBackPaths(root, state.analysis.heldBackPaths);
  writeVaultExcludes(root, vaultGit, state.analysis.heldBackPaths);
  const finalHeldBack = new Set(finalFindings.map((finding) => finding.path));
  const commitPaths = ['.gitignore', 'CLAUDE-custom.md', 'System/user-profile.yaml']
    .filter((relative) => exists(path.join(root, relative)) && !finalHeldBack.has(relative));
  if (commitPaths.length > 0) gitDir(root, vaultGit, ['add', '-f', '--', ...commitPaths]);
  const staged = gitDir(root, vaultGit, ['diff', '--cached', '--quiet'], { allowFailure: true });
  if (staged.status !== 0) {
    gitDir(root, vaultGit, ['commit', '--quiet', '-m', 'Dex vault migration settings']);
  }
  state.p9 = { finalCommit: gitOutput(root, vaultGit, ['rev-parse', 'HEAD']) };
  writeReport(root, {
    complete: true,
    modifiedBrainPaths: state.analysis?.modifiedBrainPaths || [],
    remoteNames: state.preflight?.remoteNames || [],
    secretFindings: state.analysis?.secretFindings || [],
    heldBackPaths: state.analysis?.heldBackPaths || [],
    liftedInlineExtensions: state.analysis?.liftedInlineExtensions || false,
  });
  console.log('P9 finalize complete: your vault and brain now have separate histories.');
}

function archiveValidationError(detail) {
  return new Error(`The pre-split archive ${detail}, so Dex refused to replace the current Git history. Restore the matching migration archive or contact Dex support; no Git folder was deleted.`);
}

function validatePreSplitArchive(root, state) {
  const archive = path.join(root, '.dex', 'pre-split-archive.git');
  const markerPath = path.join(archive, ARCHIVE_MARKER);
  if (!exists(markerPath)) {
    throw archiveValidationError('has no migration marker tied to this migration');
  }
  let marker;
  try {
    marker = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
  } catch {
    throw archiveValidationError('has an unreadable migration marker');
  }
  if (
    !state?.startedAt
    || marker.migrationId !== state.startedAt
    || marker.preSplitHead !== state.preflight?.head
    || marker.releaseCommit !== state.preflight?.releaseCommit
  ) {
    throw archiveValidationError('has a migration marker that does not match this migration and its recorded commits');
  }
  const fsck = gitDir(root, archive, ['fsck', '--no-progress'], { allowFailure: true });
  if (fsck.status !== 0) throw archiveValidationError('did not pass git fsck');
  for (const [label, commit] of [
    ['pre-split HEAD', marker.preSplitHead],
    ['recorded release', marker.releaseCommit],
  ]) {
    const resolved = gitDir(root, archive, ['rev-parse', '--verify', `${commit}^{commit}`], {
      allowFailure: true,
    });
    if (resolved.status !== 0) throw archiveValidationError(`cannot resolve the ${label} commit`);
  }
  return marker;
}

function uniqueDexPath(root, basename) {
  const dexRoot = path.join(root, '.dex');
  fs.mkdirSync(dexRoot, { recursive: true });
  let candidate = path.join(dexRoot, basename);
  let suffix = 1;
  while (exists(candidate)) {
    candidate = path.join(dexRoot, `${basename.replace(/\.git$/, '')}-${suffix}.git`);
    suffix += 1;
  }
  return candidate;
}

function renameAtomically(source, destination) {
  fs.renameSync(source, destination);
  fsyncDirectory(path.dirname(source));
  if (path.dirname(destination) !== path.dirname(source)) fsyncDirectory(path.dirname(destination));
}

function verifyRestoredGitdir(root, state) {
  const rootGit = path.join(root, '.git');
  const fsck = gitDir(root, rootGit, ['fsck', '--no-progress'], { allowFailure: true });
  if (fsck.status !== 0) throw new Error('The restored Git history did not pass git fsck.');
  for (const commit of [state.preflight.head, state.preflight.releaseCommit]) {
    const resolved = gitDir(root, rootGit, ['rev-parse', '--verify', `${commit}^{commit}`], {
      allowFailure: true,
    });
    if (resolved.status !== 0) throw new Error(`The restored Git history could not resolve recorded commit ${commit}.`);
  }
}

function restoreGitTopology(root, state, preservation = null) {
  const rootGit = path.join(root, '.git');
  const archive = path.join(root, '.dex', 'pre-split-archive.git');
  if (!exists(archive)) {
    if (!exists(rootGit) || markerExists(rootGit, VAULT_MARKER)) {
      throw new Error('The pre-split Git archive is unavailable, so Dex cannot restore automatically.');
    }
    return;
  }
  validatePreSplitArchive(root, state);

  let quarantined = null;
  if (exists(rootGit)) {
    const basename = preservation?.preserveGitdir
      ? 'post-split-archive.git'
      : `superseded-${Date.now()}.git`;
    quarantined = uniqueDexPath(root, basename);
    renameAtomically(rootGit, quarantined);
  }
  try {
    renameAtomically(archive, rootGit);
    verifyRestoredGitdir(root, state);
  } catch (error) {
    if (exists(rootGit)) {
      const failed = uniqueDexPath(root, `failed-restore-${Date.now()}.git`);
      renameAtomically(rootGit, failed);
    }
    if (quarantined && exists(quarantined)) renameAtomically(quarantined, rootGit);
    throw new Error(`Dex could not verify the restored Git history, so it put the previous Git folder back. ${error.message}`);
  }
  if (quarantined && !preservation?.preserveGitdir) removePath(quarantined);
  return { archivedGitdir: preservation?.preserveGitdir ? quarantined : null };
}

function reconcileTopology(root, state) {
  const topology = inspectTopology(root);
  const decision = topologyDecision(topology);
  if (decision === 'continue-swap') {
    const rootGit = path.join(root, '.git');
    const staging = path.join(root, '.dex', 'vault-staging.git');
    const archive = path.join(root, '.dex', 'pre-split-archive.git');
    let superseded = null;
    if (exists(rootGit) && !markerExists(rootGit, VAULT_MARKER)) {
      if (!exists(archive)) throw new Error('Reconciler cannot verify the old Git archive. Run --restore.');
      superseded = uniqueDexPath(root, `superseded-reconcile-${Date.now()}.git`);
      renameAtomically(rootGit, superseded);
    }
    if (!exists(rootGit)) moveWithFallback(staging, rootGit);
    else if (exists(staging) && markerExists(rootGit, VAULT_MARKER)) removePath(staging);
    if (!markerExists(rootGit, VAULT_MARKER)) {
      if (exists(rootGit)) {
        renameAtomically(rootGit, uniqueDexPath(root, `failed-reconcile-${Date.now()}.git`));
      }
      if (superseded && exists(superseded)) renameAtomically(superseded, rootGit);
      throw new Error('Reconciler could not verify the prepared vault Git folder. The previous Git folder was preserved.');
    }
    if (superseded) removePath(superseded);
    writeTopologySentinel(root, state.preflight?.releaseCommit || null);
    state.nextPhase = Math.max(state.nextPhase || 0, 6);
    state.swapStage = 'vault-active';
    writeJournal(root, state);
    console.log('Startup check completed the interrupted P5 swap.');
    return;
  }
  if (decision === 'restore-archive') {
    restoreGitTopology(root, state);
    state.nextPhase = Math.min(state.nextPhase || 0, 3);
    state.swapStage = 'restored-before-swap';
    writeJournal(root, state);
    console.log('Startup check reversed an incomplete swap to the safe pre-split state.');
    return;
  }
  if (decision === 'post-split') {
    state.nextPhase = Math.max(state.nextPhase || 0, 6);
    return;
  }
  if (decision === 'invalid') {
    throw new Error('The migration folders are incomplete and the old Git archive is missing. Dex stopped without guessing; restore the folder from backup.');
  }
}

function removeMigrationRuntime(root) {
  const dexRoot = path.join(root, '.dex');
  removePath(path.join(dexRoot, 'brain.git'));
  removePath(path.join(dexRoot, 'vault-staging.git'));
  for (const entry of exists(dexRoot) ? fs.readdirSync(dexRoot) : []) {
    if (entry.startsWith('vault-staging.git.restore-') || entry.includes('.copying-')) {
      removePath(path.join(dexRoot, entry));
    }
  }
  if (exists(dexRoot) && fs.readdirSync(dexRoot).length === 0) fs.rmdirSync(dexRoot);

  const stateDirectory = path.join(root, 'System', '.dex');
  for (const relative of [
    'migration-v2-state.json',
    'migration-v2-state.json.previous',
    '.migration-lock',
    'topology.json',
    'migration-v2-p3-files.json',
  ]) removePath(path.join(stateDirectory, relative));
  if (exists(stateDirectory) && fs.readdirSync(stateDirectory).length === 0) fs.rmdirSync(stateDirectory);
}

function changedVaultPaths(root, gitDirectory, migrationCommit = null) {
  const paths = new Set();
  const commands = [
    ['diff', '--name-only', '-z', 'HEAD'],
    ['diff', '--cached', '--name-only', '-z', 'HEAD'],
    ['-c', 'core.excludesFile=/dev/null', 'ls-files', '--others', '--exclude-standard', '-z'],
  ];
  if (migrationCommit) commands.push(['diff', '--name-only', '-z', migrationCommit, 'HEAD']);
  for (const args of commands) {
    const result = gitDir(root, gitDirectory, args, { encoding: null, allowFailure: true });
    if (result.status !== 0) continue;
    for (const relative of result.stdout.toString('utf8').split('\0').filter(Boolean)) paths.add(relative);
  }
  return [...paths].filter((relative) => ['vault', 'seed'].includes(ownership.classify(relative)));
}

function preflightRestorePreservation(root, state) {
  const vaultGit = path.join(root, '.git');
  if (!markerExists(vaultGit, VAULT_MARKER)) return { preserveGitdir: false, dirty: false, diverged: false };
  const head = gitOutput(root, vaultGit, ['rev-parse', 'HEAD']);
  const migrationCommit = state.p9?.finalCommit || state.p3?.initialCommit;
  const status = gitDir(root, vaultGit, ['status', '--porcelain=v1', '-z', '--untracked-files=all'], {
    encoding: null,
  }).stdout;
  const dirty = status.length > 0;
  const diverged = !migrationCommit || head !== migrationCommit;
  if (!dirty && !diverged) return { preserveGitdir: false, dirty, diverged };

  const backupRelative = path.join('System', 'backups', `pre-restore-${Date.now()}`);
  const backupRoot = path.join(root, backupRelative);
  const scannerPositive = new Set(scanForSecrets(root).map((finding) => finding.path));
  const changed = new Set(changedVaultPaths(root, vaultGit, migrationCommit));
  const customPath = path.join(root, 'CLAUDE-custom.md');
  if (
    exists(customPath)
    && state.p6?.customSha256
    && fileSha256(customPath) !== state.p6.customSha256
  ) changed.add('CLAUDE-custom.md');

  const unsafeRestorePaths = [...changed].filter((relative) => (
    SNAPSHOT_PATHS.includes(relative)
    && (ownership.isSecretPath(relative) || scannerPositive.has(relative))
  ));
  if (unsafeRestorePaths.length > 0) {
    throw new Error(`Restore stopped before changing ${unsafeRestorePaths.join(', ')} because the changed file may contain secret material and cannot be copied into a backup. Move that content to a safe private location, then run --restore again.`);
  }

  const entries = [];
  for (const relative of [...changed].sort()) {
    const source = path.join(root, relative);
    const entry = { path: relative, existed: exists(source), preserved: false };
    if (ownership.isSecretPath(relative) || scannerPositive.has(relative)) {
      entry.reason = 'secret-like file left in place and not copied into a backup';
    } else if (entry.existed) {
      const stat = fs.lstatSync(source);
      if (stat.isFile() && !stat.isSymbolicLink()) {
        writeFileFsynced(path.join(backupRoot, 'files', relative), fs.readFileSync(source), stat.mode & 0o777);
        entry.preserved = true;
        entry.sha256 = fileSha256(source);
      } else {
        entry.reason = 'non-regular file left in place and not copied';
      }
    }
    entries.push(entry);
  }
  writeFileFsynced(
    path.join(backupRoot, 'manifest.json'),
    `${JSON.stringify({
      schemaVersion: 1,
      createdAt: new Date().toISOString(),
      vaultHead: head,
      migrationCommit,
      dirty,
      diverged,
      entries,
    }, null, 2)}\n`,
  );
  return {
    preserveGitdir: true,
    dirty,
    diverged,
    backupRelative: backupRelative.split(path.sep).join('/'),
  };
}

function restoreMigration(root) {
  const state = readJournal(root) || { nextPhase: 0 };
  const archive = path.join(root, '.dex', 'pre-split-archive.git');
  if (exists(archive)) validatePreSplitArchive(root, state);
  const preservation = preflightRestorePreservation(root, state);
  state.status = 'restoring';
  state.updatedAt = new Date().toISOString();
  state.restorePreservation = preservation;
  writeJournal(root, state);
  const topologyResult = restoreGitTopology(root, state, preservation);
  restoreSnapshot(root);
  removePath(path.join(root, SNAPSHOT_RELATIVE));
  removeMigrationRuntime(root);
  if (preservation.preserveGitdir) {
    const archived = path.relative(root, topologyResult.archivedGitdir).split(path.sep).join('/');
    console.log(`Restore preserved post-migration work: the live vault Git history is in ${archived}, and changed vault files were copied to ${preservation.backupRelative}/.`);
  }
  console.log('Restore complete: the pre-split files and Git history are active again.');
  return state;
}

function dryRun(root) {
  if (topologyDecision(inspectTopology(root)) === 'invalid') {
    throw new Error('The migration folders are incomplete and the old Git archive is missing. Dex stopped without guessing; restore the folder from backup.');
  }
  const state = { schemaVersion: 1, nextPhase: 0, mode: 'dry-run' };
  const p0 = phase0Preflight(root, state);
  if (p0.zip) {
    writeReport(root, { zip: true, dryRun: true, modifiedBrainPaths: [], remoteNames: [], secretFindings: [] });
    console.log('P0 found a folder downloaded as a ZIP. No conversion was started. Read System/migration-report-v2.md for the safe choices.');
    return 0;
  }
  phase1Report(root, state, true);
  state.analysis.secretFindings = scanForSecrets(root);
  writeReport(root, {
    dryRun: true,
    modifiedBrainPaths: state.analysis.modifiedBrainPaths,
    remoteNames: state.preflight.remoteNames,
    secretFindings: state.analysis.secretFindings,
  });
  return 0;
}

function journalBeforePhase(root, state, phase) {
  state.phase = `P${phase}`;
  state.status = 'starting';
  state.nextPhase = phase;
  state.updatedAt = new Date().toISOString();
  writeJournal(root, state);
}

function journalAfterPhase(root, state, phase) {
  state.lastCompleted = `P${phase}`;
  state.status = phase === 9 ? 'complete' : 'phase-complete';
  state.nextPhase = phase + 1;
  state.updatedAt = new Date().toISOString();
  writeJournal(root, state);
}

function runPhases(root, mode) {
  let state = readJournal(root);
  if (mode === 'resume' && !state) {
    throw new Error('There is no saved migration to resume. Run --dry-run first, then --auto when you are ready.');
  }
  if (state?.status === 'complete' && topologyDecision(inspectTopology(root)) === 'post-split') {
    console.log('The brain and vault split is already complete. Nothing changed.');
    return 0;
  }
  if (!state) {
    state = {
      schemaVersion: 1,
      mode,
      status: 'new',
      nextPhase: 0,
      startedAt: new Date().toISOString(),
    };
  }

  reconcileTopology(root, state);
  const phases = [
    () => phase0Preflight(root, state),
    () => phase1Report(root, state, false),
    () => phase2SnapshotAndScan(root, state),
    () => phase3BuildVault(root, state),
    () => phase4BuildBrain(root, state),
    () => phase5Swap(root, state),
    () => phase6Rematerialize(root, state),
    () => phase7ReportOnly(state),
    () => phase8Verify(root, state),
    () => phase9Finalize(root, state),
  ];

  for (let phase = state.nextPhase || 0; phase <= 9; phase += 1) {
    journalBeforePhase(root, state, phase);
    const result = phases[phase]();
    if (phase === 0 && result?.zip) {
      writeReport(root, { zip: true, modifiedBrainPaths: [], remoteNames: [], secretFindings: [] });
      console.log('P0 found a folder downloaded as a ZIP. No conversion was started. Read System/migration-report-v2.md for the safe choices.');
      return 0;
    }
    if (result?.needsResume) {
      state.status = 'needs-resume';
      state.nextPhase = phase;
      state.updatedAt = new Date().toISOString();
      writeJournal(root, state);
      console.log('P3 paused after a bounded batch. Run the same script with --resume to continue.');
      return RESUME_EXIT;
    }
    if (result?.stopped) {
      state.status = 'needs-resume';
      state.nextPhase = phase;
      state.updatedAt = new Date().toISOString();
      writeJournal(root, state);
      console.log('Stopped safely inside P5 after archiving the old Git folder. Run --resume to continue.');
      return RESUME_EXIT;
    }
    journalAfterPhase(root, state, phase);
    if (process.env.DEX_MIGRATION_STOP_AFTER === `P${phase}` && phase < 9) {
      console.log(`Stopped safely after P${phase}. Run --resume to continue.`);
      return RESUME_EXIT;
    }
  }
  return 0;
}

function statusMigration(root) {
  const state = readJournal(root);
  const topology = inspectTopology(root);
  console.log(`Migration status: ${state?.status || 'not started'}.`);
  console.log(`Topology: ${topologyDecision(topology)}.`);
  if (state?.nextPhase !== undefined && state.nextPhase <= 9) {
    console.log(`Next phase: P${state.nextPhase}.`);
  }
  return 0;
}

function writeFailureReport(root, error) {
  try {
    writeReport(root, {
      modifiedBrainPaths: [],
      remoteNames: [],
      secretFindings: [],
      failure: error.message,
    });
  } catch {
    // The original error is more useful if even the report path is not writable.
  }
}

function parseMode(argumentsList) {
  if (argumentsList.length === 0) return 'dry-run';
  if (argumentsList.length !== 1) throw new Error('Use one mode: --dry-run, --auto, --resume, --restore, or --status.');
  const value = argumentsList[0];
  if (value === '--auto=false') return 'dry-run';
  const modes = new Map([
    ['--dry-run', 'dry-run'],
    ['--auto', 'auto'],
    ['--resume', 'resume'],
    ['--restore', 'restore'],
    ['--status', 'status'],
  ]);
  if (!modes.has(value)) throw new Error('Use one mode: --dry-run, --auto, --resume, --restore, or --status.');
  return modes.get(value);
}

function main(argumentsList = process.argv.slice(2), root = process.cwd()) {
  let mode;
  let mutationRootsAreSafe = false;
  try {
    assertSafeMutationRoots(root);
    mutationRootsAreSafe = true;
    mode = parseMode(argumentsList);
    if (mode === 'status') return statusMigration(root);
    if (mode === 'dry-run') return dryRun(root);

    const startupTopology = inspectTopology(root);
    if (topologyDecision(startupTopology) === 'zip') {
      if (mode === 'restore') throw new Error('There is no pre-split Git archive to restore.');
      writeReport(root, { zip: true, modifiedBrainPaths: [], remoteNames: [], secretFindings: [] });
      console.log('P0 found a folder downloaded as a ZIP. No conversion was started. Read System/migration-report-v2.md for the safe choices.');
      return 0;
    }
    if (mode !== 'restore' && exists(path.join(root, '.git')) && mergeInProgress(root)) {
      throw new Error('P0 stopped because a Git operation is in progress. Please finish or abort the merge, rebase, or cherry-pick, then run the migration again.');
    }

    const releaseLock = acquireLock(root);
    try {
      if (mode === 'restore') {
        restoreMigration(root);
        return 0;
      }
      return runPhases(root, mode);
    } finally {
      releaseLock();
    }
  } catch (error) {
    if (mutationRootsAreSafe && mode !== 'restore') writeFailureReport(root, error);
    console.error(error.message);
    return 1;
  }
}

module.exports = {
  assertSafeMutationRoots,
  emptyLegacyExtensionBlock,
  extractLegacyExtensions,
  findReleaseRef,
  inspectTopology,
  main,
  phase6Rematerialize,
  readJournal,
  regenerateClaude,
  restoreMigration,
  restoreSnapshot,
  snapshotFiles,
  topologyDecision,
  writeJournal,
};

if (require.main === module) {
  process.exitCode = main();
}
