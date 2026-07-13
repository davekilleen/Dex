#!/usr/bin/env node
'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const ownership = require('./ownership.cjs');
const migrator = require('../migrations/v1-to-v2-brain-vault-split.cjs');

const OFFICIAL_REMOTE = 'https://github.com/davekilleen/Dex.git';
const JOURNAL_RELATIVE = 'System/.dex/update-state.json';
const LOCK_RELATIVE = 'System/.dex/.migration-lock';
const HISTORY_RELATIVE = 'System/.dex/installed-history.json';
const TOPOLOGY_RELATIVE = 'System/.dex/topology.json';
const REPORT_RELATIVE = 'System/.dex/update-report.md';
const STAGING_RELATIVE = '.dex/staging';
const MANIFEST_RELATIVE = 'System/.installed-files.manifest';
const RESUME_EXIT = 75;

function exists(candidate) {
  try {
    fs.lstatSync(candidate);
    return true;
  } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw error;
  }
}

function slashPath(value) {
  return String(value).split(path.sep).join('/');
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

function sleep(milliseconds) {
  const waitBuffer = new SharedArrayBuffer(4);
  Atomics.wait(new Int32Array(waitBuffer), 0, 0, milliseconds);
}

function renameWithRetry(source, destination) {
  let lastError;
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    try {
      fs.renameSync(source, destination);
      fsyncDirectory(path.dirname(destination));
      return;
    } catch (error) {
      lastError = error;
      if (!['EACCES', 'EBUSY', 'EPERM', 'EXDEV'].includes(error.code)) throw error;
      sleep(attempt * 40);
    }
  }
  throw lastError;
}

function modesCompatible(expected, actual, platform = process.platform) {
  return platform === 'win32' || expected === actual;
}

function assertSafePath(root, relative) {
  const portable = slashPath(relative);
  if (ownership.isDenied(portable, root)) {
    throw new Error(`Dex refused to write protected path ${portable}. The update has stopped safely.`);
  }
  const destination = path.join(root, portable);
  const resolvedRoot = path.resolve(root);
  const resolved = path.resolve(destination);
  if (resolved !== resolvedRoot && !resolved.startsWith(`${resolvedRoot}${path.sep}`)) {
    throw new Error(`Dex refused to write ${portable} because it leaves the vault.`);
  }
  try {
    if (fs.lstatSync(destination).isSymbolicLink()) {
      throw new Error(`Dex refused to replace symlink ${portable}. Move it aside, then run --resume.`);
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  return destination;
}

function assertClassifiedWrite(root, relative, allowedClasses) {
  const portable = slashPath(relative);
  const className = ownership.classify(portable);
  if (!allowedClasses.has(className)) {
    throw new Error(`Dex refused to write ${portable} because its ownership class is ${className}.`);
  }
  return assertSafePath(root, portable);
}

function assertWorktreeWrite(root, relative) {
  return assertClassifiedWrite(root, relative, new Set(['brain', 'generated', 'seed']));
}

function assertRuntimeWrite(root, relative) {
  return assertClassifiedWrite(root, relative, new Set(['runtime']));
}

function writeOwnedFile(root, relative, content, mode, assertDestinationWrite) {
  const portable = slashPath(relative);
  const destination = assertDestinationWrite(root, portable);
  assertDestinationWrite(root, portable);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  const swapKey = crypto.createHash('sha256').update(portable).digest('hex');
  const temporaryRelative = `${STAGING_RELATIVE}/.swap/${swapKey}.writing-${process.pid}`;
  const temporary = assertRuntimeWrite(root, temporaryRelative);
  fs.mkdirSync(path.dirname(temporary), { recursive: true });
  let descriptor;
  try {
    descriptor = fs.openSync(temporary, 'w', mode);
    fs.writeFileSync(descriptor, content);
    fs.fchmodSync(descriptor, mode);
    fs.fsyncSync(descriptor);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
  const expected = Buffer.isBuffer(content) ? content : Buffer.from(content);
  const quarantineRelative = `${STAGING_RELATIVE}/.swap/${swapKey}.previous`;
  const copyingRelative = `${STAGING_RELATIVE}/.swap/${swapKey}.copying`;
  const intentRelative = `${STAGING_RELATIVE}/.swap/${swapKey}.intent.json`;
  const quarantine = assertRuntimeWrite(root, quarantineRelative);
  const copying = assertRuntimeWrite(root, copyingRelative);
  const intent = assertRuntimeWrite(root, intentRelative);
  const expectedHash = crypto.createHash('sha256').update(expected).digest('hex');

  function installedFileMatches(bytes, expectedMode) {
    if (!exists(destination) || fs.lstatSync(destination).isSymbolicLink() || !fs.lstatSync(destination).isFile()) return false;
    const installedMode = fs.statSync(destination).mode & 0o777;
    return modesCompatible(expectedMode, installedMode) && fs.readFileSync(destination).equals(bytes);
  }

  function readIntent() {
    try {
      const parsed = JSON.parse(fs.readFileSync(intent, 'utf8'));
      return parsed?.sha256 && Number.isInteger(parsed.mode) ? parsed : null;
    } catch {
      return null;
    }
  }

  function destinationMatchesIntent(candidateIntent) {
    if (!candidateIntent || !exists(destination) || fs.lstatSync(destination).isSymbolicLink() || !fs.lstatSync(destination).isFile()) return false;
    const installedMode = fs.statSync(destination).mode & 0o777;
    const installedHash = crypto.createHash('sha256').update(fs.readFileSync(destination)).digest('hex');
    return modesCompatible(candidateIntent.mode, installedMode) && installedHash === candidateIntent.sha256;
  }

  if (exists(quarantine) && !exists(destination)) {
    assertRuntimeWrite(root, quarantineRelative);
    assertDestinationWrite(root, portable);
    renameWithRetry(quarantine, destination);
    if (exists(intent)) removeRuntimePath(root, intentRelative);
    if (exists(copying)) removeRuntimePath(root, copyingRelative);
  }
  const previousIntent = readIntent();
  const matchesCurrentWrite = installedFileMatches(expected, mode);
  if (exists(quarantine) && (matchesCurrentWrite || destinationMatchesIntent(previousIntent))) {
    removeRuntimePath(root, quarantineRelative);
    if (exists(intent)) removeRuntimePath(root, intentRelative);
    if (matchesCurrentWrite) {
      removeRuntimePath(root, temporaryRelative);
      return;
    }
  }
  if (exists(quarantine)) {
    throw new Error(`Dex found an ambiguous interrupted file swap for ${relative}. Run --resume without editing that file.`);
  }
  if (exists(intent)) removeRuntimePath(root, intentRelative);

  try {
    assertDestinationWrite(root, portable);
    renameWithRetry(temporary, destination);
    if (!installedFileMatches(expected, mode)) throw new Error(`Dex could not verify the replacement bytes for ${relative}.`);
    return;
  } catch (error) {
    if (!['EACCES', 'EBUSY', 'EPERM', 'EXDEV'].includes(error.code)) throw error;
  }

  fs.mkdirSync(path.dirname(quarantine), { recursive: true });
  writeDirectFile(intent, `${JSON.stringify({ sha256: expectedHash, mode })}\n`, 0o600);
  if (exists(destination)) {
    assertDestinationWrite(root, portable);
    assertRuntimeWrite(root, quarantineRelative);
    renameWithRetry(destination, quarantine);
  }
  if (exists(copying)) removeRuntimePath(root, copyingRelative);
  assertRuntimeWrite(root, temporaryRelative);
  assertRuntimeWrite(root, copyingRelative);
  fs.copyFileSync(temporary, copying, fs.constants.COPYFILE_EXCL);
  fs.chmodSync(copying, mode);
  let copyingDescriptor;
  try {
    copyingDescriptor = fs.openSync(copying, 'r');
    fs.fsyncSync(copyingDescriptor);
  } finally {
    if (copyingDescriptor !== undefined) fs.closeSync(copyingDescriptor);
  }
  assertRuntimeWrite(root, copyingRelative);
  assertDestinationWrite(root, portable);
  renameWithRetry(copying, destination);
  if (!installedFileMatches(expected, mode)) {
    throw new Error(`Dex stopped because the fallback swap for ${relative} did not verify.`);
  }
  if (process.env.DEX_UPDATE_TEST_THROW_AFTER_FALLBACK_INSTALL === portable) {
    throw new Error(`Simulated crash after fallback install for ${relative}`);
  }
  removeRuntimePath(root, temporaryRelative);
  if (exists(quarantine)) removeRuntimePath(root, quarantineRelative);
  if (exists(intent)) removeRuntimePath(root, intentRelative);
}

function writeWorktreeFile(root, relative, content, mode = 0o600) {
  writeOwnedFile(root, relative, content, mode, assertWorktreeWrite);
}

function writeRuntimeFile(root, relative, content, mode = 0o600) {
  writeOwnedFile(root, relative, content, mode, assertRuntimeWrite);
}

function removeOwnedPath(root, relative, recursive, assertDestinationWrite) {
  const destination = assertDestinationWrite(root, relative);
  if (!exists(destination)) return;
  assertDestinationWrite(root, relative);
  if (recursive) fs.rmSync(destination, { recursive: true, force: false });
  else fs.unlinkSync(destination);
  fsyncDirectory(path.dirname(destination));
}

function removeWorktreePath(root, relative, recursive = false) {
  removeOwnedPath(root, relative, recursive, assertWorktreeWrite);
}

function removeRuntimePath(root, relative, recursive = false) {
  removeOwnedPath(root, relative, recursive, assertRuntimeWrite);
}

function writeDirectFile(destination, content, mode = 0o600) {
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  if (exists(destination) && fs.lstatSync(destination).isSymbolicLink()) {
    throw new Error(`Dex refused to replace symlinked metadata ${destination}.`);
  }
  const temporary = `${destination}.writing-${process.pid}`;
  const quarantine = `${destination}.dex-update-previous`;
  const copying = `${destination}.dex-update-copying`;
  const intent = `${destination}.dex-update-intent`;
  let descriptor;
  try {
    descriptor = fs.openSync(temporary, 'w', mode);
    fs.writeFileSync(descriptor, content);
    fs.fchmodSync(descriptor, mode);
    fs.fsyncSync(descriptor);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
  const expected = Buffer.isBuffer(content) ? content : Buffer.from(content);
  const expectedHash = crypto.createHash('sha256').update(expected).digest('hex');
  const destinationMatches = () => (
    exists(destination)
    && !fs.lstatSync(destination).isSymbolicLink()
    && fs.lstatSync(destination).isFile()
    && modesCompatible(mode, fs.statSync(destination).mode & 0o777)
    && fs.readFileSync(destination).equals(expected)
  );
  const readIntent = () => {
    try {
      const parsed = JSON.parse(fs.readFileSync(intent, 'utf8'));
      return parsed?.sha256 && Number.isInteger(parsed.mode) ? parsed : null;
    } catch {
      return null;
    }
  };
  const destinationMatchesIntent = (candidateIntent) => {
    if (!candidateIntent || !exists(destination) || fs.lstatSync(destination).isSymbolicLink() || !fs.lstatSync(destination).isFile()) return false;
    const actualHash = crypto.createHash('sha256').update(fs.readFileSync(destination)).digest('hex');
    return actualHash === candidateIntent.sha256
      && modesCompatible(candidateIntent.mode, fs.statSync(destination).mode & 0o777);
  };
  if (exists(quarantine) && !exists(destination)) {
    renameWithRetry(quarantine, destination);
    if (exists(intent)) fs.unlinkSync(intent);
    if (exists(copying)) fs.unlinkSync(copying);
  }
  const matchesCurrentWrite = destinationMatches();
  if (exists(quarantine) && (matchesCurrentWrite || destinationMatchesIntent(readIntent()))) {
    fs.unlinkSync(quarantine);
    if (exists(intent)) fs.unlinkSync(intent);
    fsyncDirectory(path.dirname(destination));
    if (matchesCurrentWrite) {
      if (exists(temporary)) fs.unlinkSync(temporary);
      return;
    }
  }
  if (exists(quarantine)) {
    throw new Error(`Dex found an ambiguous interrupted metadata swap for ${destination}. Run --resume.`);
  }
  if (exists(intent)) fs.unlinkSync(intent);
  try {
    renameWithRetry(temporary, destination);
    if (!destinationMatches()) throw new Error(`Dex could not verify metadata ${destination}.`);
    return;
  } catch (error) {
    if (!['EACCES', 'EBUSY', 'EPERM', 'EXDEV'].includes(error.code)) throw error;
  }
  const intentTemporary = `${intent}.writing-${process.pid}`;
  let intentDescriptor;
  try {
    intentDescriptor = fs.openSync(intentTemporary, 'w', 0o600);
    fs.writeFileSync(intentDescriptor, `${JSON.stringify({ sha256: expectedHash, mode })}\n`);
    fs.fsyncSync(intentDescriptor);
  } finally {
    if (intentDescriptor !== undefined) fs.closeSync(intentDescriptor);
  }
  renameWithRetry(intentTemporary, intent);
  if (exists(destination)) renameWithRetry(destination, quarantine);
  if (exists(copying)) fs.unlinkSync(copying);
  fs.copyFileSync(temporary, copying, fs.constants.COPYFILE_EXCL);
  fs.chmodSync(copying, mode);
  let copyingDescriptor;
  try {
    copyingDescriptor = fs.openSync(copying, 'r');
    fs.fsyncSync(copyingDescriptor);
  } finally {
    if (copyingDescriptor !== undefined) fs.closeSync(copyingDescriptor);
  }
  renameWithRetry(copying, destination);
  if (!destinationMatches()) throw new Error(`Dex could not verify fallback metadata ${destination}.`);
  if (process.env.DEX_UPDATE_TEST_THROW_AFTER_DIRECT_FALLBACK === destination) {
    throw new Error(`Simulated crash after direct fallback install for ${destination}`);
  }
  if (exists(temporary)) fs.unlinkSync(temporary);
  if (exists(quarantine)) fs.unlinkSync(quarantine);
  if (exists(intent)) fs.unlinkSync(intent);
  fsyncDirectory(path.dirname(destination));
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    encoding: options.encoding === undefined ? 'utf8' : options.encoding,
    env: {
      ...process.env,
      GIT_CONFIG_GLOBAL: '/dev/null',
      GIT_CONFIG_NOSYSTEM: '1',
      GIT_TERMINAL_PROMPT: '0',
      ...(options.env || {}),
    },
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (!options.allowFailure && result.status !== 0) {
    const stdout = Buffer.isBuffer(result.stdout) ? result.stdout.toString('utf8') : result.stdout;
    const stderr = Buffer.isBuffer(result.stderr) ? result.stderr.toString('utf8') : result.stderr;
    throw new Error(`${stdout || ''}${stderr || ''}`.trim() || `${command} ${args.join(' ')} failed`);
  }
  return result;
}

function brainGit(root, args, options = {}) {
  return run('git', [
    '-c', 'commit.gpgsign=false',
    '-c', 'core.excludesFile=/dev/null',
    `--git-dir=${path.join(root, '.dex', 'brain.git')}`,
    ...args,
  ], options);
}

function brainOutput(root, args, options = {}) {
  return brainGit(root, args, options).stdout.trim();
}

function brainBuffer(root, args, options = {}) {
  return brainGit(root, args, { ...options, encoding: null }).stdout;
}

function isOfficialRemote(url) {
  return /^(?:https:\/\/github\.com\/|ssh:\/\/git@github\.com\/|git@github\.com:)davekilleen\/Dex(?:\.git)?\/?$/i.test(String(url).trim());
}

function inspectUpdateTopology(root) {
  const vaultGit = path.join(root, '.git');
  const brain = path.join(root, '.dex', 'brain.git');
  const topologyPath = path.join(root, TOPOLOGY_RELATIVE);
  const migratorPath = path.join(root, 'core', 'migrations', 'v1-to-v2-brain-vault-split.cjs');
  const vaultMarker = path.join(vaultGit, 'dex-vault-v2');
  const brainMarker = path.join(brain, 'dex-brain-v2');
  let sentinel = null;
  try {
    sentinel = JSON.parse(fs.readFileSync(topologyPath, 'utf8'));
  } catch (error) {
    if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
  }
  function markerHasRole(candidate, role) {
    try {
      if (!fs.lstatSync(candidate).isFile()) return false;
      return JSON.parse(fs.readFileSync(candidate, 'utf8')).role === role;
    } catch {
      return false;
    }
  }
  if (
    sentinel?.topology === 'brain-vault-split'
    && exists(vaultGit)
    && exists(brain)
    && fs.lstatSync(vaultGit).isDirectory()
    && fs.lstatSync(brain).isDirectory()
    && markerHasRole(vaultMarker, 'vault')
    && markerHasRole(brainMarker, 'brain')
  ) {
    return { state: 'post-split', sentinel };
  }
  const migrationJournal = path.join(root, 'System', '.dex', 'migration-v2-state.json');
  const archive = path.join(root, '.dex', 'pre-split-archive.git');
  const vaultStaging = path.join(root, '.dex', 'vault-staging.git');
  if (exists(migrationJournal) || exists(archive) || exists(vaultStaging)) {
    return { state: 'migration-in-progress', sentinel };
  }
  if (exists(vaultGit) && exists(migratorPath)) return { state: 'migration-pending', sentinel };
  if (!exists(vaultGit)) return { state: 'zip-or-manual', sentinel };
  return { state: 'invalid', sentinel };
}

function assertSafeMutationRoots(root) {
  for (const relative of ['.git', 'System', '.dex', '.dex/brain.git', 'System/.dex', 'System/backups']) {
    const candidate = path.join(root, relative);
    try {
      if (fs.lstatSync(candidate).isSymbolicLink()) {
        throw new Error(`Dex stopped because ${relative} is a symlink. Move the vault to normal folders, then try again.`);
      }
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
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
  assertRuntimeWrite(root, LOCK_RELATIVE);
  fs.mkdirSync(path.dirname(lock), { recursive: true });
  if (exists(lock)) {
    let holder = null;
    try {
      holder = JSON.parse(fs.readFileSync(lock, 'utf8'));
    } catch {
      // Atomic lock writers do not leave partial files, so malformed locks are stale.
    }
    if (holder && processIsRunning(holder.pid)) {
      throw new Error(`Another Dex migration or update is still running (process ${holder.pid}). Wait for it, then retry.`);
    }
    assertRuntimeWrite(root, LOCK_RELATIVE);
    fs.unlinkSync(lock);
  }
  assertRuntimeWrite(root, LOCK_RELATIVE);
  const descriptor = fs.openSync(lock, 'wx', 0o600);
  try {
    fs.writeFileSync(descriptor, `${JSON.stringify({ pid: process.pid, kind: 'update', at: new Date().toISOString() })}\n`);
    fs.fsyncSync(descriptor);
  } finally {
    fs.closeSync(descriptor);
  }
  fsyncDirectory(path.dirname(lock));
  return () => {
    if (exists(lock)) {
      assertRuntimeWrite(root, LOCK_RELATIVE);
      fs.unlinkSync(lock);
      fsyncDirectory(path.dirname(lock));
    }
  };
}

function writeJournal(root, state) {
  const destination = path.join(root, JOURNAL_RELATIVE);
  if (exists(destination)) {
    writeRuntimeFile(root, `${JOURNAL_RELATIVE}.previous`, fs.readFileSync(destination));
  }
  writeRuntimeFile(root, JOURNAL_RELATIVE, `${JSON.stringify(state, null, 2)}\n`);
}

function readJournal(root) {
  for (const relative of [JOURNAL_RELATIVE, `${JOURNAL_RELATIVE}.previous`]) {
    try {
      return JSON.parse(fs.readFileSync(path.join(root, relative), 'utf8'));
    } catch (error) {
      if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
    }
  }
  return null;
}

function beforeMutation(root, state, description) {
  state.pendingMutation = description;
  state.updatedAt = new Date().toISOString();
  writeJournal(root, state);
}

function afterMutation(root, state) {
  state.pendingMutation = null;
  state.updatedAt = new Date().toISOString();
  writeJournal(root, state);
}

function walkRegularFiles(root) {
  const files = [];
  function visit(relative) {
    const absolute = path.join(root, relative);
    for (const entry of fs.readdirSync(absolute, { withFileTypes: true })) {
      const child = relative ? path.join(relative, entry.name) : entry.name;
      const portable = slashPath(child);
      const childAbsolute = path.join(root, child);
      if (entry.isSymbolicLink()) throw new Error(`Release staging contains unsupported symlink ${portable}.`);
      if (entry.isDirectory()) visit(child);
      else if (entry.isFile()) files.push(portable);
      else throw new Error(`Release staging contains unsupported filesystem entry ${portable}.`);
    }
  }
  visit('');
  return files.sort();
}

function verifyStagedManifest(stagingRoot, expectedManifestBytes) {
  const stagedManifest = fs.readFileSync(path.join(stagingRoot, MANIFEST_RELATIVE));
  if (!stagedManifest.equals(expectedManifestBytes)) {
    throw new Error('The staged manifest hash does not match the target release commit. Dex did not touch the live tree.');
  }
  const source = stagedManifest.toString('utf8');
  const manifestLines = source.split(/\r?\n/).filter(Boolean);
  if (`${manifestLines.join('\n')}\n` !== source || [...manifestLines].sort().join('\n') !== manifestLines.join('\n')) {
    throw new Error('The target release manifest is not a sorted newline path list.');
  }
  const validation = ownership.validateManifest(manifestLines);
  if (validation.errors.length > 0) {
    throw new Error(`The target release manifest is unsafe: ${validation.errors.join('; ')}`);
  }
  const stagedFiles = walkRegularFiles(stagingRoot);
  if (stagedFiles.length !== manifestLines.length || stagedFiles.some((value, index) => value !== manifestLines[index])) {
    throw new Error('The target manifest does not match the staged release tree. Dex did not touch the live tree.');
  }
  return {
    manifestLines,
    manifestHash: crypto.createHash('sha256').update(stagedManifest).digest('hex'),
  };
}

function verifyOfficialOrigin(root) {
  const urlResult = brainGit(root, ['config', '--get', 'remote.origin.url'], { allowFailure: true });
  const url = urlResult.status === 0 ? urlResult.stdout.trim() : '';
  if (!isOfficialRemote(url)) {
    throw new Error(`Dex refused the update because brain origin is not the official repository (${OFFICIAL_REMOTE}).`);
  }
  const effectiveResult = brainGit(root, ['remote', 'get-url', 'origin'], { allowFailure: true });
  const effective = effectiveResult.status === 0 ? effectiveResult.stdout.trim() : '';
  if (!isOfficialRemote(effective)) {
    throw new Error('Dex refused the update because a local Git rule redirected the official release URL. Remove that rewrite, then try again.');
  }
  return url;
}

function semverParts(tag) {
  const match = /^dist-v(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/.exec(tag);
  return match ? match.slice(1, 4).map(Number) : null;
}

function compareTags(left, right) {
  const a = semverParts(left);
  const b = semverParts(right);
  if (!a || !b) return left.localeCompare(right);
  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return left.localeCompare(right);
}

function selectLatestStableTag(tags) {
  const stable = tags.filter((tag) => /^dist-v\d+\.\d+\.\d+$/.test(tag));
  if (stable.length === 0) throw new Error('Dex could not find a stable official dist-vX.Y.Z release tag. Try again when one is published.');
  return stable.sort(compareTags).at(-1);
}

function resolveAndFetchTarget(root, requested) {
  const officialUrl = verifyOfficialOrigin(root);
  let target = requested;
  if (!target) {
    const listed = brainGit(root, ['ls-remote', '--refs', '--tags', officialUrl, 'refs/tags/dist-v*']);
    const tags = listed.stdout.split(/\r?\n/).filter(Boolean).map((line) => line.split(/\s+/)[1])
      .filter((ref) => ref?.startsWith('refs/tags/dist-v')).map((ref) => ref.slice('refs/tags/'.length));
    target = selectLatestStableTag(tags);
  }
  let destination;
  if (/^[a-f0-9]{40}(?:[a-f0-9]{24})?$/i.test(target)) {
    destination = `refs/dex/releases/${target.slice(0, 16)}`;
    brainGit(root, ['fetch', '--no-tags', officialUrl, `+${target}:${destination}`]);
  } else {
    if (!/^dist-v[0-9A-Za-z.+-]+$/.test(target)) {
      throw new Error('Update targets must be an official dist-v tag or full commit OID.');
    }
    destination = `refs/dex/releases/${target}`;
    brainGit(root, ['fetch', '--no-tags', officialUrl, `+refs/tags/${target}:${destination}`]);
  }
  const oid = brainOutput(root, ['rev-parse', '--verify', `${destination}^{commit}`]);
  if (/^[a-f0-9]{40}(?:[a-f0-9]{24})?$/i.test(target) && oid.toLowerCase() !== target.toLowerCase()) {
    throw new Error('The official remote did not return the requested release commit.');
  }
  return { target, oid };
}

function gitObjectExists(root, oid) {
  return brainGit(root, ['cat-file', '-e', `${oid}^{commit}`], { allowFailure: true }).status === 0;
}

function readTargetFile(root, oid, relative, allowMissing = false) {
  const result = brainGit(root, ['show', `${oid}:${relative}`], {
    allowFailure: allowMissing,
    encoding: null,
  });
  if (allowMissing && result.status !== 0) return null;
  return result.stdout;
}

function worktreeMatchesBlob(root, oid, relative) {
  const expected = readTargetFile(root, oid, relative, true);
  const destination = path.join(root, relative);
  if (expected === null || !exists(destination)) return false;
  assertWorktreeWrite(root, relative);
  if (!fs.lstatSync(destination).isFile()) return false;
  return fs.readFileSync(destination).equals(expected);
}

function targetVersion(root, oid) {
  try {
    const packageJson = JSON.parse(readTargetFile(root, oid, 'package.json').toString('utf8'));
    return String(packageJson.version || oid.slice(0, 12));
  } catch {
    return oid.slice(0, 12);
  }
}

function safeVersion(value) {
  return String(value).replace(/[^0-9A-Za-z._-]/g, '-');
}

function dependencySignals(root, oldOid, newOid) {
  function changed(paths) {
    return paths.some((relative) => {
      const before = readTargetFile(root, oldOid, relative, true);
      const after = readTargetFile(root, newOid, relative, true);
      if (before === null || after === null) return before !== after;
      return !before.equals(after);
    });
  }
  return {
    npm: changed(['package.json', 'package-lock.json']),
    pip: changed(['requirements.txt', 'uv.lock']),
  };
}

function stageTarget(root, state) {
  beforeMutation(root, state, `stage release ${state.targetOid}`);
  if (exists(path.join(root, STAGING_RELATIVE))) removeRuntimePath(root, STAGING_RELATIVE, true);
  assertRuntimeWrite(root, STAGING_RELATIVE);
  fs.mkdirSync(path.join(root, STAGING_RELATIVE), { recursive: true });
  brainGit(root, ['read-tree', `${state.targetOid}^{tree}`]);
  brainGit(root, [
    `--work-tree=${path.join(root, STAGING_RELATIVE)}`,
    'checkout-index', '-a', '-f',
  ]);
  const expectedManifest = readTargetFile(root, state.targetOid, MANIFEST_RELATIVE);
  const verified = verifyStagedManifest(path.join(root, STAGING_RELATIVE), expectedManifest);
  state.targetManifest = verified.manifestLines;
  state.targetBrainPaths = ownership.brainPaths(verified.manifestLines);
  state.manifestHash = verified.manifestHash;
  state.version = targetVersion(root, state.targetOid);
  state.dependencies = dependencySignals(root, state.previousOid, state.targetOid);
  afterMutation(root, state);
}

function readManifestAt(root, oid) {
  const bytes = readTargetFile(root, oid, MANIFEST_RELATIVE);
  const lines = bytes.toString('utf8').split(/\r?\n/).filter(Boolean);
  const validation = ownership.validateManifest(lines);
  if (validation.errors.length > 0) throw new Error(`Installed release manifest is invalid: ${validation.errors.join('; ')}`);
  return lines;
}

function writeReport(root, state, completed = false) {
  const backedUp = state.backedUp || [];
  const pruned = state.pruned || [];
  const kept = state.kept || [];
  const lines = [
    '# Dex update report',
    '',
    completed
      ? `Dex ${state.mode === 'rollback' ? 'rolled back' : 'updated'} to ${state.version} (${state.targetOid}).`
      : `Dex is preparing ${state.mode === 'rollback' ? 'a rollback' : 'an update'} to ${state.version}.`,
    '',
    'Your PARA notes and edited seed files were left alone.',
    '',
    '## Backed up before replacement',
    '',
    ...(backedUp.length ? backedUp.map((relative) => `- ${relative} — backed up`) : ['- None']),
    '',
    '## Removed because the installed copy was unchanged',
    '',
    ...(pruned.length ? pruned.map((relative) => `- ${relative}`) : ['- None']),
    '',
    '## Kept because your copy differed',
    '',
    ...(kept.length ? kept.map((relative) => `- ${relative}`) : ['- None']),
    '',
  ];
  writeRuntimeFile(root, REPORT_RELATIVE, `${lines.join('\n')}\n`);
}

function backupModifiedBrain(root, state) {
  state.backupChecked = state.backupChecked || [];
  state.backedUp = state.backedUp || [];
  const checked = new Set(state.backupChecked);
  for (const relative of state.targetBrainPaths) {
    if (checked.has(relative)) continue;
    const destination = path.join(root, relative);
    if (exists(destination) && !worktreeMatchesBlob(root, state.previousOid, relative)) {
      const backupRelative = `System/backups/pre-update-${safeVersion(state.version)}/${relative}`;
      beforeMutation(root, state, `back up modified brain file ${relative}`);
      const source = assertWorktreeWrite(root, relative);
      if (!fs.lstatSync(source).isFile()) throw new Error(`Dex cannot back up non-file brain path ${relative}.`);
      const bytes = fs.readFileSync(source);
      const mode = fs.statSync(source).mode & 0o777;
      const backup = path.join(root, backupRelative);
      if (exists(backup) && !fs.readFileSync(backup).equals(bytes)) {
        throw new Error(`Existing update backup differs at ${backupRelative}. Move it aside, then run --resume.`);
      }
      if (!exists(backup)) writeRuntimeFile(root, backupRelative, bytes, mode);
      if (!state.backedUp.includes(relative)) state.backedUp.push(relative);
      afterMutation(root, state);
    }
    state.backupChecked.push(relative);
  }
  beforeMutation(root, state, 'write the pre-swap update report');
  writeReport(root, state, false);
  afterMutation(root, state);
}

function copyStagedFile(root, state, relative) {
  const source = path.join(root, STAGING_RELATIVE, relative);
  if (!fs.lstatSync(source).isFile()) throw new Error(`Staged brain path is not a regular file: ${relative}`);
  const bytes = fs.readFileSync(source);
  const mode = fs.statSync(source).mode & 0o777;
  writeWorktreeFile(root, relative, bytes, mode);
}

function swapBrainFiles(root, state) {
  state.swapped = state.swapped || [];
  const complete = new Set(state.swapped);
  const stopAfter = Number(process.env.DEX_UPDATE_STOP_AFTER_FILES || 0);
  for (const relative of state.targetBrainPaths) {
    if (complete.has(relative)) continue;
    beforeMutation(root, state, `replace brain file ${relative}`);
    copyStagedFile(root, state, relative);
    if (process.env.DEX_UPDATE_TEST_SIGKILL_AFTER_MUTATION === `replace brain file ${relative}`) {
      process.kill(process.pid, 'SIGKILL');
    }
    state.swapped.push(relative);
    afterMutation(root, state);
    if (stopAfter > 0 && state.swapped.length >= stopAfter) {
      console.log('Stopped safely during the file swap. Run the same script with --resume.');
      return { stopped: true };
    }
  }
  return { stopped: false };
}

function pruneDroppedBrain(root, state) {
  state.pruneChecked = state.pruneChecked || [];
  state.pruned = state.pruned || [];
  state.kept = state.kept || [];
  const target = new Set(state.targetBrainPaths);
  const dropped = ownership.brainPaths(state.previousManifest).filter((relative) => !target.has(relative));
  const checked = new Set(state.pruneChecked);
  for (const relative of dropped) {
    if (checked.has(relative)) continue;
    const destination = path.join(root, relative);
    if (exists(destination)) {
      if (worktreeMatchesBlob(root, state.previousOid, relative)) {
        beforeMutation(root, state, `remove unchanged dropped brain file ${relative}`);
        removeWorktreePath(root, relative);
        state.pruned.push(relative);
        afterMutation(root, state);
      } else {
        if (!state.kept.includes(relative)) state.kept.push(relative);
      }
    } else if (state.pendingMutation === `remove unchanged dropped brain file ${relative}`) {
      state.pruned.push(relative);
    }
    state.pruneChecked.push(relative);
  }
}

function seedMissingFiles(root, state) {
  state.seeded = state.seeded || [];
  const manifest = new Set(state.targetManifest);
  for (const entry of ownership.seedEntries()) {
    const relative = entry.path;
    if (!manifest.has(relative) || state.seeded.includes(relative)) continue;
    const destination = path.join(root, relative);
    if (!exists(destination)) {
      beforeMutation(root, state, `create missing seed ${relative}`);
      copyStagedFile(root, state, relative);
      afterMutation(root, state);
    }
    state.seeded.push(relative);
    afterMutation(root, state);
  }
}

function regenerateClaude(root, state) {
  const template = fs.readFileSync(path.join(root, STAGING_RELATIVE, 'CLAUDE.md'), 'utf8');
  const customPath = path.join(root, 'CLAUDE-custom.md');
  const custom = exists(customPath) ? fs.readFileSync(customPath, 'utf8') : '';
  const rendered = migrator.regenerateClaude(template, custom);
  beforeMutation(root, state, 'regenerate CLAUDE.md');
  writeWorktreeFile(root, 'CLAUDE.md', rendered, 0o644);
  afterMutation(root, state);
}

function regeneratePaths(root, state) {
  beforeMutation(root, state, 'regenerate core/paths.json');
  assertWorktreeWrite(root, 'core/paths.json');
  const vaultPython = path.join(root, '.venv', 'bin', 'python');
  const python = process.env.DEX_UPDATE_PYTHON || (exists(vaultPython) ? vaultPython : 'python3');
  run(python, [path.join(root, 'core', 'paths.py')], {
    cwd: root,
    env: { VAULT_PATH: root },
  });
  afterMutation(root, state);
}

function substituteVaultPath(value, root) {
  if (typeof value === 'string') return value.replaceAll('{{VAULT_PATH}}', root);
  if (Array.isArray(value)) return value.map((item) => substituteVaultPath(item, root));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, substituteVaultPath(item, root)]));
  }
  return value;
}

function writeMcpAdditions(root, before, after, additions) {
  const destination = assertSafePath(root, '.mcp.json');
  if (ownership.classify('.mcp.json') !== 'vault') {
    throw new Error('Dex refused MCP synchronization because .mcp.json ownership is not vault.');
  }
  const expectedNames = new Set(additions);
  const beforeServers = before.mcpServers && typeof before.mcpServers === 'object' ? before.mcpServers : {};
  const afterServers = after.mcpServers && typeof after.mcpServers === 'object' ? after.mcpServers : {};
  for (const [name, entry] of Object.entries(beforeServers)) {
    if (!Object.hasOwn(afterServers, name) || JSON.stringify(afterServers[name]) !== JSON.stringify(entry)) {
      throw new Error(`Dex refused MCP synchronization because existing server ${name} changed.`);
    }
  }
  const actualAdditions = Object.keys(afterServers).filter((name) => !Object.hasOwn(beforeServers, name));
  if (
    actualAdditions.length !== expectedNames.size
    || actualAdditions.some((name) => !expectedNames.has(name))
    || Object.keys(before).some((key) => key !== 'mcpServers' && JSON.stringify(before[key]) !== JSON.stringify(after[key]))
  ) {
    throw new Error('Dex refused MCP synchronization because the change was not add-only.');
  }
  writeDirectFile(destination, `${JSON.stringify(after, null, 2)}\n`, 0o600);
}

function syncMcpAddOnly(root, state) {
  const example = JSON.parse(fs.readFileSync(path.join(root, 'System', '.mcp.json.example'), 'utf8'));
  const target = path.join(root, '.mcp.json');
  const current = exists(target) ? JSON.parse(fs.readFileSync(target, 'utf8')) : { mcpServers: {} };
  const before = JSON.parse(JSON.stringify(current));
  current.mcpServers = current.mcpServers && typeof current.mcpServers === 'object' ? current.mcpServers : {};
  const additions = [];
  for (const [name, entry] of Object.entries(example.mcpServers || {})) {
    if (Object.hasOwn(current.mcpServers, name)) continue;
    current.mcpServers[name] = substituteVaultPath(entry, root);
    additions.push(name);
  }
  state.mcpAdded = additions;
  if (additions.length > 0 || !exists(target)) {
    beforeMutation(root, state, `add missing MCP servers: ${additions.join(', ') || 'initial config'}`);
    writeMcpAdditions(root, before, current, additions);
    afterMutation(root, state);
  }
}

function refreshVaultExclude(root, state) {
  const marker = path.join(root, '.git', 'dex-vault-v2');
  if (!exists(marker)) throw new Error('Dex refused to edit vault Git metadata because its v2 marker is missing.');
  for (const candidate of [path.join(root, '.git'), path.join(root, '.git', 'info')]) {
    if (exists(candidate) && (!fs.lstatSync(candidate).isDirectory() || fs.lstatSync(candidate).isSymbolicLink())) {
      throw new Error('Dex refused to edit vault Git metadata through an unsafe .git/info path.');
    }
  }
  const content = `${ownership.vaultExcludeLines(ownership.readHeldBackPaths(root)).join('\n')}\n`;
  beforeMutation(root, state, 'refresh vault Git excludes');
  writeDirectFile(path.join(root, '.git', 'info', 'exclude'), content, 0o600);
  afterMutation(root, state);
}

function readHistory(root) {
  try {
    const history = JSON.parse(fs.readFileSync(path.join(root, HISTORY_RELATIVE), 'utf8'));
    if (!Array.isArray(history)) throw new Error('installed history must be a JSON array');
    return history;
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}

function chooseRollbackTarget(root, requested) {
  const history = readHistory(root);
  const installed = brainOutput(root, ['rev-parse', '--verify', 'refs/dex/installed^{commit}']);
  const known = new Set(history.flatMap((entry) => [entry.oid, entry.previous]).filter(Boolean));
  if (requested) {
    if (!/^[a-f0-9]{40}(?:[a-f0-9]{24})?$/i.test(requested) || !known.has(requested)) {
      throw new Error('Rollback --to must be a full OID recorded in System/.dex/installed-history.json.');
    }
    return requested;
  }
  for (let index = history.length - 1; index >= 0; index -= 1) {
    if (history[index].oid === installed && history[index].previous) return history[index].previous;
  }
  const fallback = history.at(-1)?.previous;
  if (!fallback) throw new Error('There is no earlier installed release in System/.dex/installed-history.json.');
  return fallback;
}

function updateTopologySentinel(root, state) {
  const topologyPath = path.join(root, TOPOLOGY_RELATIVE);
  const topology = JSON.parse(fs.readFileSync(topologyPath, 'utf8'));
  topology.installedRelease = state.targetOid;
  writeRuntimeFile(root, TOPOLOGY_RELATIVE, `${JSON.stringify(topology, null, 2)}\n`);
}

function finalizeInstalledRelease(root, state) {
  const current = brainOutput(root, ['rev-parse', '--verify', 'refs/dex/installed^{commit}']);
  if (current !== state.targetOid) {
    beforeMutation(root, state, `advance refs/dex/installed to ${state.targetOid}`);
    brainGit(root, ['update-ref', 'refs/dex/installed', state.targetOid, state.previousOid]);
    afterMutation(root, state);
  }
  beforeMutation(root, state, 'refresh the brain Git marker');
  const brainDirectory = path.join(root, '.dex', 'brain.git');
  if (!fs.lstatSync(brainDirectory).isDirectory() || fs.lstatSync(brainDirectory).isSymbolicLink()) {
    throw new Error('Dex refused to refresh an unsafe brain Git folder.');
  }
  writeDirectFile(
    path.join(brainDirectory, 'dex-brain-v2'),
    `${JSON.stringify({ schemaVersion: 1, role: 'brain', installed: state.targetOid }, null, 2)}\n`,
  );
  afterMutation(root, state);
  const history = readHistory(root);
  const entry = {
    version: state.version,
    oid: state.targetOid,
    manifestHash: state.manifestHash,
    previous: state.previousOid,
    at: state.startedAt,
  };
  const duplicate = history.some((item) => item.oid === entry.oid && item.previous === entry.previous && item.at === entry.at);
  if (!duplicate) {
    beforeMutation(root, state, 'append installed release history');
    history.push(entry);
    writeRuntimeFile(root, HISTORY_RELATIVE, `${JSON.stringify(history, null, 2)}\n`);
    afterMutation(root, state);
  }
  beforeMutation(root, state, 'refresh topology installed release');
  updateTopologySentinel(root, state);
  afterMutation(root, state);
}

function runPhases(root, state) {
  while (state.phase <= 10) {
    if (state.phase === 1) {
      if (state.mode === 'apply') {
        const resolved = resolveAndFetchTarget(root, state.targetSpec);
        state.targetSpec = resolved.target;
        state.targetOid = resolved.oid;
      } else if (!gitObjectExists(root, state.targetOid)) {
        throw new Error('The rollback release is no longer present in the sanitized brain history.');
      }
      state.previousOid = state.previousOid || brainOutput(root, ['rev-parse', '--verify', 'refs/dex/installed^{commit}']);
      if (state.targetOid === state.previousOid) {
        throw new Error('That release is already installed. No files were changed.');
      }
      state.previousManifest = readManifestAt(root, state.previousOid);
      state.phase = 2;
      afterMutation(root, state);
    } else if (state.phase === 2) {
      stageTarget(root, state);
      state.phase = 3;
      afterMutation(root, state);
    } else if (state.phase === 3) {
      backupModifiedBrain(root, state);
      state.phase = 4;
      afterMutation(root, state);
    } else if (state.phase === 4) {
      const swap = swapBrainFiles(root, state);
      if (swap.stopped) return RESUME_EXIT;
      state.phase = 5;
      afterMutation(root, state);
    } else if (state.phase === 5) {
      pruneDroppedBrain(root, state);
      state.phase = 6;
      afterMutation(root, state);
    } else if (state.phase === 6) {
      seedMissingFiles(root, state);
      state.phase = 7;
      afterMutation(root, state);
    } else if (state.phase === 7) {
      regenerateClaude(root, state);
      state.phase = 8;
      afterMutation(root, state);
    } else if (state.phase === 8) {
      regeneratePaths(root, state);
      refreshVaultExclude(root, state);
      syncMcpAddOnly(root, state);
      state.phase = 9;
      afterMutation(root, state);
    } else if (state.phase === 9) {
      finalizeInstalledRelease(root, state);
      state.phase = 10;
      afterMutation(root, state);
    } else if (state.phase === 10) {
      beforeMutation(root, state, 'write the completed update report');
      writeReport(root, state, true);
      afterMutation(root, state);
      if (exists(path.join(root, STAGING_RELATIVE))) {
        beforeMutation(root, state, 'remove verified release staging');
        removeRuntimePath(root, STAGING_RELATIVE, true);
        afterMutation(root, state);
      }
      state.status = 'complete';
      state.completedAt = new Date().toISOString();
      state.phase = 11;
      afterMutation(root, state);
    }
  }
  console.log(`DEX_DEPENDENCIES npm=${state.dependencies.npm ? 1 : 0} pip=${state.dependencies.pip ? 1 : 0}`);
  console.log(state.mode === 'rollback' ? 'DEX_ROLLBACK_COMPLETE' : 'DEX_UPDATE_COMPLETE');
  return 0;
}

function ensurePostSplit(root, mode) {
  let topology = inspectUpdateTopology(root);
  if (topology.state === 'post-split') return 0;
  if (topology.state === 'migration-pending' && ['apply', 'resume'].includes(mode)) {
    console.log('Dex needs its one-time brain/vault upgrade before this update. Starting the safe migrator now.');
    const result = migrator.main(['--auto'], root);
    if (result !== 0) return result;
    topology = inspectUpdateTopology(root);
  } else if (topology.state === 'migration-in-progress' && ['apply', 'resume'].includes(mode)) {
    console.log('Dex found an interrupted one-time upgrade and is resuming it before the update.');
    const result = migrator.main(['--resume'], root);
    if (result !== 0) return result;
    topology = inspectUpdateTopology(root);
  }
  if (topology.state === 'migration-pending') {
    throw new Error('Dex needs a one-time upgrade first. Run /dex-update; no update files were changed.');
  }
  if (topology.state === 'zip-or-manual') {
    throw new Error('This Dex folder has no Git history. Choose conversion or the ZIP/manual update path; Dex did not create a half-topology.');
  }
  if (topology.state !== 'post-split') {
    throw new Error(`Dex cannot safely update this ${topology.state} topology. Use the migrator's --resume or --restore recovery.`);
  }
  return 0;
}

function parseArguments(argumentsList) {
  if (argumentsList.length === 0) throw new Error('Use --check, --apply, --resume, --rollback, or --status.');
  const modeToken = argumentsList[0];
  const modeMap = new Map([
    ['--check', 'check'], ['--apply', 'apply'], ['--resume', 'resume'],
    ['--rollback', 'rollback'], ['--status', 'status'],
  ]);
  if (!modeMap.has(modeToken)) throw new Error('Use --check, --apply, --resume, --rollback, or --status.');
  const parsed = { mode: modeMap.get(modeToken), target: null, to: null };
  for (let index = 1; index < argumentsList.length; index += 1) {
    const token = argumentsList[index];
    if (token === '--target' && index + 1 < argumentsList.length) parsed.target = argumentsList[++index];
    else if (token === '--to' && index + 1 < argumentsList.length) parsed.to = argumentsList[++index];
    else throw new Error(`Unknown update option ${token}.`);
  }
  if (parsed.target && !['apply', 'check'].includes(parsed.mode)) throw new Error('--target is only valid with --check or --apply.');
  if (parsed.to && parsed.mode !== 'rollback') throw new Error('--to is only valid with --rollback.');
  return parsed;
}

function status(root) {
  const topology = inspectUpdateTopology(root);
  const journal = readJournal(root);
  console.log(`DEX_UPDATE_STATUS topology=${topology.state} update=${journal?.status || 'idle'}`);
  if (topology.state === 'migration-pending') console.log('Dex needs a one-time upgrade — run /dex-update.');
  if (journal?.status === 'active') console.log(`Resume phase ${journal.phase}: ${journal.pendingMutation || 'ready'}`);
  return 0;
}

function main(argumentsList = process.argv.slice(2), root = process.cwd()) {
  let releaseLock = null;
  try {
    assertSafeMutationRoots(root);
    const args = parseArguments(argumentsList);
    if (args.mode === 'status') return status(root);
    const startingTopology = inspectUpdateTopology(root);
    let pendingState = readJournal(root);
    if (
      args.mode === 'resume'
      && startingTopology.state !== 'post-split'
      && !['active', 'waiting-for-migration'].includes(pendingState?.status)
    ) {
      throw new Error('There is no interrupted Dex update to resume. Use the migrator command shown in its report.');
    }
    if (
      args.mode === 'apply'
      && ['migration-pending', 'migration-in-progress'].includes(startingTopology.state)
      && pendingState?.status !== 'waiting-for-migration'
    ) {
      pendingState = {
        schemaVersion: 1,
        status: 'waiting-for-migration',
        mode: 'apply',
        targetSpec: args.target,
        targetOid: null,
        previousOid: null,
        phase: 1,
        startedAt: new Date().toISOString(),
        pendingMutation: 'complete the one-time brain/vault migration',
      };
      writeJournal(root, pendingState);
    }
    const topologyResult = ensurePostSplit(root, args.mode);
    if (topologyResult !== 0) return topologyResult;
    releaseLock = acquireLock(root);
    verifyOfficialOrigin(root);
    if (args.mode === 'check') {
      const installed = brainOutput(root, ['rev-parse', '--verify', 'refs/dex/installed^{commit}']);
      const target = resolveAndFetchTarget(root, args.target);
      console.log(target.oid === installed
        ? `DEX_UPDATE_CURRENT target=${target.target} oid=${target.oid}`
        : `DEX_UPDATE_AVAILABLE target=${target.target} oid=${target.oid} installed=${installed}`);
      return 0;
    }
    let state;
    if (args.mode === 'resume') {
      state = readJournal(root);
      if (!state || !['active', 'waiting-for-migration'].includes(state.status)) {
        throw new Error('There is no interrupted Dex update to resume.');
      }
      if (state.status === 'waiting-for-migration') {
        state.status = 'active';
        state.previousOid = brainOutput(root, ['rev-parse', '--verify', 'refs/dex/installed^{commit}']);
        state.pendingMutation = null;
        writeJournal(root, state);
      }
    } else {
      const existing = readJournal(root);
      if (existing?.status === 'active') {
        throw new Error('An update is already in progress. Run this script with --resume; do not use raw Git recovery.');
      }
      const installed = brainOutput(root, ['rev-parse', '--verify', 'refs/dex/installed^{commit}']);
      if (args.mode === 'apply' && existing?.status === 'waiting-for-migration') {
        if (args.target && existing.targetSpec && args.target !== existing.targetSpec) {
          throw new Error(`The interrupted update was targeting ${existing.targetSpec}. Run --resume before choosing another release.`);
        }
        state = { ...existing, status: 'active', previousOid: installed, pendingMutation: null };
      } else {
        state = {
          schemaVersion: 1,
          status: 'active',
          mode: args.mode,
          targetSpec: args.target,
          targetOid: args.mode === 'rollback' ? chooseRollbackTarget(root, args.to) : null,
          previousOid: installed,
          phase: 1,
          startedAt: new Date().toISOString(),
          pendingMutation: 'initialize update journal',
        };
      }
      writeJournal(root, state);
    }
    return runPhases(root, state);
  } catch (error) {
    console.error(error.message);
    return 1;
  } finally {
    if (releaseLock) releaseLock();
  }
}

module.exports = {
  assertWorktreeWrite,
  inspectUpdateTopology,
  isOfficialRemote,
  main,
  modesCompatible,
  selectLatestStableTag,
  verifyStagedManifest,
  verifyOfficialOrigin,
  writeWorktreeFile,
  writeRuntimeFile,
  writeDirectFile,
};

if (require.main === module) process.exitCode = main();
