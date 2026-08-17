#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const childProcess = require('node:child_process');
const crypto = require('node:crypto');
const yaml = require('js-yaml');
const contract = require('./provision-contract.json');
const portableContract = require('../packages/dex-contracts/dist/portable-vault.contract.json');

const PROFILE_KEYS = new Set([
  'name', 'role', 'company', 'company_size', 'email_domain', 'work_email',
  'obsidian_mode', 'pillars', 'working_week', 'communication', 'capabilities',
]);

const CAPABILITY_CATALOG = path.join(
  __dirname, '..', '.claude', 'skills', '_available', 'capabilities',
);

function parseArgs(argv) {
  const options = { adopt: false, dryRun: false, json: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--path' || arg === '--profile' || arg === '--session-file') {
      if (!argv[index + 1]) throw new Error(`${arg} requires a value`);
      if (arg === '--session-file') options.sessionFile = argv[index + 1];
      else options[arg.slice(2)] = argv[index + 1];
      index += 1;
    } else if (arg === '--adopt') options.adopt = true;
    else if (arg === '--onboard') options.onboard = true;
    else if (arg === '--install-config-only') options.installConfigOnly = true;
    else if (arg === '--lifecycle-only') options.lifecycleOnly = true;
    else if (arg === '--enable-qmd') options.enableQmd = true;
    else if (arg === '--dry-run') options.dryRun = true;
    else if (arg === '--json') options.json = true;
    else if (arg === '--help' || arg === '-h') options.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  if (!options.help && !options.path) throw new Error('--path is required');
  return options;
}

function contentBytes(content) {
  return Buffer.isBuffer(content) ? Buffer.from(content) : Buffer.from(content, 'utf8');
}

function reportPath(vaultRoot, filePath) {
  return path.relative(vaultRoot, filePath).split(path.sep).join('/') || '.';
}

function treePaths(vaultRoot, relativeRoot) {
  const absoluteRoot = path.join(vaultRoot, ...relativeRoot.split('/'));
  const paths = new Set();
  function walk(candidate) {
    const metadata = fs.lstatSync(candidate);
    paths.add(reportPath(vaultRoot, candidate));
    if (!metadata.isDirectory() || metadata.isSymbolicLink()) return;
    for (const entry of fs.readdirSync(candidate)) walk(path.join(candidate, entry));
  }
  if (fs.existsSync(absoluteRoot)) walk(absoluteRoot);
  return paths;
}

function createReporter(vaultRoot, dryRun) {
  const summary = {
    ok: true,
    path: vaultRoot,
    dry_run: dryRun,
    created: [],
    removed: [],
    'skipped-existing': [],
    errors: [],
  };
  return {
    summary,
    created(filePath) {
      const relative = reportPath(vaultRoot, filePath);
      if (!summary.created.includes(relative)) summary.created.push(relative);
    },
    removed(filePath) {
      const relative = reportPath(vaultRoot, filePath);
      if (!summary.removed.includes(relative)) summary.removed.push(relative);
    },
    skipped(filePath) {
      const relative = reportPath(vaultRoot, filePath);
      if (!summary['skipped-existing'].includes(relative)) {
        summary['skipped-existing'].push(relative);
      }
    },
    error(message) { summary.ok = false; summary.errors.push(message); },
  };
}

class ProvisionTransaction {
  constructor(vaultRoot) {
    this.vaultRoot = path.resolve(vaultRoot);
    this.actions = [];
    this.plannedKinds = new Map();
    this.transactionPathsBefore = treePaths(this.vaultRoot, 'System/.dex');
  }

  relative(target) {
    const absolute = path.resolve(target);
    const relative = path.relative(this.vaultRoot, absolute);
    if (
      relative === ''
      || relative === '..'
      || relative.startsWith(`..${path.sep}`)
      || path.isAbsolute(relative)
    ) {
      if (relative === '') return null;
      throw new Error(`Provision transaction target escapes the vault: ${target}`);
    }
    return relative.split(path.sep).join('/');
  }

  lstat(target) {
    try {
      return fs.lstatSync(target);
    } catch (error) {
      if (error.code === 'ENOENT') return null;
      throw error;
    }
  }

  registerKind(target, kind) {
    const absolute = path.resolve(target);
    const previous = this.plannedKinds.get(absolute);
    if (previous && previous !== kind) {
      throw new Error(`Provision transaction has conflicting plans for ${this.relative(target)}`);
    }
    this.plannedKinds.set(absolute, kind);
    return previous === kind;
  }

  stageDirectory(directory) {
    const relative = this.relative(directory);
    if (relative === null) return;
    let cursor = path.resolve(directory);
    while (cursor !== this.vaultRoot) {
      const metadata = this.lstat(cursor);
      if (metadata && (metadata.isSymbolicLink() || !metadata.isDirectory())) {
        throw new Error(`Provision transaction directory is unsafe: ${relative}`);
      }
      cursor = path.dirname(cursor);
    }
  }

  stageWrite(filePath, content) {
    const expected = contentBytes(content);
    this.stageDirectory(path.dirname(filePath));
    const repeated = this.registerKind(filePath, 'write-file');
    if (repeated) {
      const previous = this.actions.find(action => (
        action.kind === 'write-file' && action.path === path.resolve(filePath)
      ));
      if (!previous || !previous.expected.equals(expected)) {
        throw new Error(`Provision transaction has conflicting writes for ${this.relative(filePath)}`);
      }
      return;
    }
    const metadata = this.lstat(filePath);
    if (metadata && (metadata.isSymbolicLink() || !metadata.isFile())) {
      throw new Error(`Provision transaction file is unsafe: ${this.relative(filePath)}`);
    }
    this.actions.push({
      kind: 'write-file',
      path: path.resolve(filePath),
      expected,
      mode: metadata ? metadata.mode & 0o777 : 0o644,
      expectedCurrentSha256: metadata
        ? crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex')
        : null,
      expectedAbsent: metadata === null,
    });
  }

  stageDeleteFile(filePath) {
    const metadata = this.lstat(filePath);
    if (!metadata) return;
    if (metadata.isSymbolicLink() || !metadata.isFile()) {
      throw new Error(`Provision transaction deletion target is unsafe: ${this.relative(filePath)}`);
    }
    if (this.registerKind(filePath, 'delete-file')) return;
    this.actions.push({
      kind: 'delete-file',
      path: path.resolve(filePath),
      mode: metadata.mode & 0o777,
      expectedCurrentSha256: crypto
        .createHash('sha256')
        .update(fs.readFileSync(filePath))
        .digest('hex'),
    });
  }

  stageRemoveDirectory(directory) {
    const metadata = this.lstat(directory);
    if (!metadata) return;
    if (metadata.isSymbolicLink() || !metadata.isDirectory()) {
      throw new Error(`Provision transaction removal target is unsafe: ${this.relative(directory)}`);
    }
    // The file deletion is transaction-owned. Leaving its now-empty parent is
    // safer than introducing an unjournalled directory mutation.
  }

  rollback() {
    // Planning is read-only, and the lifecycle engine rolls back any failed
    // commit from its durable snapshot. This method keeps the existing caller
    // contract for reporting a completed rollback.
  }

  document() {
    return {
      schema_version: 1,
      entries: this.actions.map(action => ({
        path: this.relative(action.path),
        action: action.kind === 'delete-file' ? 'delete' : 'write',
        content_base64: action.kind === 'write-file'
          ? action.expected.toString('base64')
          : null,
        mode: action.mode,
        expected_current_sha256: action.expectedCurrentSha256,
        expected_absent: action.kind === 'write-file' && action.expectedAbsent,
      })),
    };
  }

  commit() {
    return routeProvisionTransaction(this.vaultRoot, { document: this.document() });
  }

  failureReceipt() {
    const after = treePaths(this.vaultRoot, 'System/.dex');
    const declaredPaths = [...after]
      .filter(relative => !this.transactionPathsBefore.has(relative))
      .sort();
    const transactionIds = [...new Set(declaredPaths.map(relative => {
      const match = /^System\/\.dex\/tx\/([^/]+)/.exec(relative);
      return match?.[1] || null;
    }).filter(Boolean))];
    const terminal = transactionIds.every(transactionId => {
      const journal = path.join(
        this.vaultRoot,
        'System',
        '.dex',
        'tx',
        transactionId,
        'journal.jsonl',
      );
      if (!fs.existsSync(journal)) return false;
      const events = fs.readFileSync(journal, 'utf8');
      return /"event":"(?:COMMITTED|ROLLED-BACK)"/.test(events);
    });
    return {
      declared_paths: declaredPaths,
      transaction_ids: transactionIds,
      terminal,
    };
  }

}

function rollbackProvision(transaction, reporter, cause) {
  reporter.error(cause.message);
  try {
    transaction.rollback();
    reporter.summary.provision_transaction_failure = transaction.failureReceipt();
    reporter.summary.rolled_back = reporter.summary.provision_transaction_failure.terminal;
    reporter.summary.created = [];
    reporter.summary.removed = [];
  } catch (rollbackError) {
    reporter.summary.rolled_back = false;
    reporter.error(rollbackError.message);
  }
}

function ensureDirectory(directory, reporter, dryRun, transaction = null) {
  if (fs.existsSync(directory)) {
    if (!fs.statSync(directory).isDirectory()) throw new Error(`${directory} exists but is not a directory`);
    reporter.skipped(directory);
    return;
  }
  const missing = [];
  let candidate = directory;
  while (!fs.existsSync(candidate)) {
    missing.push(candidate);
    const parent = path.dirname(candidate);
    if (parent === candidate) break;
    candidate = parent;
  }
  if (!dryRun && !transaction) {
    throw new Error('Directory planning requires the provision transaction service');
  }
  if (!dryRun) transaction.stageDirectory(directory);
  for (const created of missing.reverse()) reporter.created(created);
}

function reportMissingAncestors(filePath, reporter) {
  const missing = [];
  let candidate = path.dirname(filePath);
  while (!fs.existsSync(candidate)) {
    missing.push(candidate);
    const parent = path.dirname(candidate);
    if (parent === candidate) break;
    candidate = parent;
  }
  for (const created of missing.reverse()) reporter.created(created);
}

function writeIfMissing(filePath, content, reporter, dryRun, transaction = null) {
  if (fs.existsSync(filePath)) {
    reporter.skipped(filePath);
    return false;
  }
  reportMissingAncestors(filePath, reporter);
  if (!dryRun) {
    if (!transaction) {
      throw new Error('Provision writes require the provision transaction service');
    }
    transaction.stageWrite(filePath, content);
  }
  reporter.created(filePath);
  return true;
}

function writeIfChanged(filePath, content, reporter, dryRun, transaction = null) {
  if (fs.existsSync(filePath) && fs.readFileSync(filePath, 'utf8') === content) {
    reporter.skipped(filePath);
    return false;
  }
  if (!fs.existsSync(filePath)) reportMissingAncestors(filePath, reporter);
  if (!dryRun) {
    if (!transaction) {
      throw new Error('Provision writes require the provision transaction service');
    }
    transaction.stageWrite(filePath, content);
  }
  reporter.created(filePath);
  return true;
}

function deepFillMissing(existing, defaults) {
  if (!existing || typeof existing !== 'object' || Array.isArray(existing)) return existing;
  let changed = false;
  for (const [key, value] of Object.entries(defaults || {})) {
    if (!Object.prototype.hasOwnProperty.call(existing, key) || existing[key] === undefined) {
      existing[key] = value;
      changed = true;
    } else if (
      existing[key] && value
      && typeof existing[key] === 'object' && typeof value === 'object'
      && !Array.isArray(existing[key]) && !Array.isArray(value)
    ) {
      changed = deepFillMissing(existing[key], value) || changed;
    }
  }
  return changed;
}

function loadProfileOverlay(profilePath) {
  if (!profilePath) return {};
  const parsed = JSON.parse(fs.readFileSync(path.resolve(profilePath), 'utf8'));
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Profile JSON must contain an object');
  }
  const overlay = {};
  for (const [key, value] of Object.entries(parsed)) {
    if (PROFILE_KEYS.has(key)) overlay[key] = value;
  }
  if (overlay.pillars !== undefined && !Array.isArray(overlay.pillars)) {
    throw new Error('Profile JSON pillars must be an array');
  }
  if (overlay.working_week !== undefined && (
    !overlay.working_week
    || typeof overlay.working_week !== 'object'
    || Array.isArray(overlay.working_week)
    || !Array.isArray(overlay.working_week.days)
    || overlay.working_week.days.length === 0
  )) throw new Error('Profile JSON working_week must be an object with days as a non-empty array');
  if (overlay.communication !== undefined && (
    !overlay.communication || typeof overlay.communication !== 'object' || Array.isArray(overlay.communication)
  )) throw new Error('Profile JSON communication must be an object');
  if (overlay.capabilities !== undefined) {
    if (!overlay.capabilities || typeof overlay.capabilities !== 'object' || Array.isArray(overlay.capabilities)) {
      throw new Error('Profile JSON capabilities must be an object');
    }
    for (const [room, state] of Object.entries(overlay.capabilities)) {
      if (!Object.prototype.hasOwnProperty.call(portableContract.capabilities || {}, room)) {
        throw new Error(`Unknown capability room: ${room}`);
      }
      if (!state || typeof state !== 'object' || Array.isArray(state) || typeof state.enabled !== 'boolean') {
        throw new Error(`Profile JSON capabilities.${room}.enabled must be true or false`);
      }
    }
  }
  return overlay;
}

function buildFreshProfile(template, overlay) {
  const profile = structuredClone(template || {});
  for (const [key, value] of Object.entries(overlay)) {
    if (key === 'communication') {
      profile.communication = { ...(profile.communication || {}), ...value };
    } else if (key === 'capabilities') {
      profile.capabilities = { ...(profile.capabilities || {}) };
      for (const [room, state] of Object.entries(value)) {
        profile.capabilities[room] = {
          ...(profile.capabilities[room] || {}),
          ...state,
        };
      }
    } else profile[key] = value;
  }
  // Setup offers concrete, qualified pages before asking whether future
  // creation should be automatic. Until that explicit answer, suggest is the
  // safe fresh-vault default.
  profile.entity_creation = { mode: 'suggest' };
  for (const [room, definition] of Object.entries(portableContract.capabilities || {})) {
    const explicit = overlay.capabilities?.[room]?.enabled;
    if (typeof explicit === 'boolean' && typeof definition.config === 'string') {
      profile[definition.config] = { ...(profile[definition.config] || {}), enabled: explicit };
    }
  }
  return profile;
}

function capabilityEnabled(profile, room, definition) {
  const explicit = profile?.capabilities?.[room]?.enabled;
  if (typeof explicit === 'boolean') return explicit;
  if (typeof definition.config === 'string') {
    const legacy = profile?.[definition.config]?.enabled;
    if (typeof legacy === 'boolean') return legacy;
  }
  return definition.default_enabled === true;
}

function copyMissing(source, target, reporter, dryRun, transaction = null) {
  if (!fs.existsSync(source)) return;
  const stat = fs.statSync(source);
  if (stat.isDirectory()) {
    for (const entry of fs.readdirSync(source)) {
      copyMissing(path.join(source, entry), path.join(target, entry), reporter, dryRun, transaction);
    }
  } else writeIfMissing(target, fs.readFileSync(source), reporter, dryRun, transaction);
}

function stageCopyMissing(source, target, transaction) {
  const sourceMetadata = fs.lstatSync(source);
  if (sourceMetadata.isSymbolicLink()) {
    throw new Error(`Capability seed source is a symlink: ${source}`);
  }
  if (sourceMetadata.isDirectory()) {
    const targetMetadata = transaction.lstat(target);
    if (!targetMetadata) transaction.stageDirectory(target);
    else if (targetMetadata.isSymbolicLink() || !targetMetadata.isDirectory()) {
      throw new Error(`Capability seed target is unsafe: ${transaction.relative(target)}`);
    }
    for (const entry of fs.readdirSync(source)) {
      stageCopyMissing(path.join(source, entry), path.join(target, entry), transaction);
    }
    return;
  }
  if (!sourceMetadata.isFile()) {
    throw new Error(`Capability seed source is not a regular file: ${source}`);
  }
  if (!transaction.lstat(target)) transaction.stageWrite(target, fs.readFileSync(source));
}

function stageCapabilityReconciliation(vaultRoot, profile, authority, transaction) {
  for (const [room, definition] of Object.entries(portableContract.capabilities || {})) {
    const roomEnabled = capabilityEnabled(profile, room, definition);
    if (roomEnabled) {
      const roomSource = path.join(CAPABILITY_CATALOG, room);
      for (const relativeFolder of definition.folders || []) {
        stageCopyMissing(
          path.join(roomSource, 'folders', ...relativeFolder.split('/')),
          path.join(vaultRoot, ...relativeFolder.split('/')),
          transaction,
        );
      }
    }

    for (const skill of definition.skills || []) {
      const state = authority?.skill_targets?.[room]
        ?.find(item => item.skill === skill)?.state;
      if (typeof state !== 'string') {
        throw new Error(`Capability authority omitted transaction state for ${room}/${skill}`);
      }
      const pin = (definition.skill_sources || []).find(item => item.skill === skill);
      if (!pin || typeof pin.source_path !== 'string' || typeof pin.target_path !== 'string') {
        throw new Error(`Portable contract omitted the source authority for ${room}/${skill}`);
      }
      const source = path.resolve(__dirname, '..', ...pin.source_path.split('/'));
      const targetFile = path.join(vaultRoot, ...pin.target_path.split('/'));
      const targetDirectory = path.dirname(targetFile);
      if (roomEnabled) {
        if (state !== 'current') {
          transaction.stageDirectory(targetDirectory);
          transaction.stageWrite(targetFile, fs.readFileSync(source));
        }
      } else if (state !== 'missing') {
        transaction.stageDeleteFile(targetFile);
        transaction.stageRemoveDirectory(targetDirectory);
      }
    }
  }
}

function reconcileCapabilities(
  vaultRoot,
  profile,
  reporter,
  dryRun,
  authority = null,
  transaction = null,
) {
  if (!dryRun) {
    if (!transaction) throw new Error('Capability reconciliation requires a provision transaction');
    const start = transaction.actions.length;
    stageCapabilityReconciliation(vaultRoot, profile, authority, transaction);
    for (const action of transaction.actions.slice(start)) {
      if (action.kind === 'delete-file') {
        reporter.removed(action.path);
        continue;
      }
      if (action.expectedAbsent) reportMissingAncestors(action.path, reporter);
      reporter.created(action.path);
    }
    return { preflight: 'passed', planned: transaction.actions.length - start };
  }

  // A dry run reports the intended surfaces after the shared Python authority
  // has validated all pins and targets. It never copies or removes a skill.
  for (const [room, definition] of Object.entries(portableContract.capabilities || {})) {
    const roomEnabled = capabilityEnabled(profile, room, definition);
    const roomSource = path.join(CAPABILITY_CATALOG, room);
    if (roomEnabled) {
      for (const relativeFolder of definition.folders || []) {
        const target = path.join(vaultRoot, ...relativeFolder.split('/'));
        ensureDirectory(target, reporter, dryRun, transaction);
        copyMissing(
          path.join(roomSource, 'folders', ...relativeFolder.split('/')),
          target,
          reporter,
          dryRun,
          transaction,
        );
      }
      for (const skill of definition.skills || []) {
        const target = path.join(vaultRoot, '.claude', 'skills', skill);
        const skillFile = path.join(target, 'SKILL.md');
        const state = authority?.skill_targets?.[room]
          ?.find(item => item.skill === skill)?.state;
        if (typeof state !== 'string') {
          throw new Error(`Capability authority omitted dry-run state for ${room}/${skill}`);
        }
        if (state === 'missing') {
          ensureDirectory(target, reporter, true);
          reporter.created(skillFile);
        } else if (state === 'current') {
          reporter.skipped(target);
          reporter.skipped(skillFile);
        } else {
          reporter.created(skillFile);
        }
      }
    } else {
      // Room folders contain user content and are never deleted. Only release-owned
      // active skill copies are hidden when a room is switched off.
      for (const skill of definition.skills || []) {
        const target = path.join(vaultRoot, '.claude', 'skills', skill);
        const skillFile = path.join(target, 'SKILL.md');
        const state = authority?.skill_targets?.[room]
          ?.find(item => item.skill === skill)?.state;
        if (typeof state !== 'string') {
          throw new Error(`Capability authority omitted dry-run state for ${room}/${skill}`);
        }
        if (state !== 'missing') {
          reporter.removed(skillFile);
          reporter.removed(target);
        }
      }
    }
  }
}

function addCapabilityFolderTargets(source, targetRelative, add) {
  const metadata = fs.lstatSync(source);
  if (metadata.isSymbolicLink()) {
    throw new Error(`Capability seed source is a symlink: ${source}`);
  }
  if (metadata.isDirectory()) {
    for (const entry of fs.readdirSync(source)) {
      addCapabilityFolderTargets(
        path.join(source, entry),
        path.posix.join(targetRelative, entry),
        add,
      );
    }
    return;
  }
  if (!metadata.isFile()) {
    throw new Error(`Capability seed source is not a regular file: ${source}`);
  }
  add(targetRelative, 'file');
}

function provisionMutationTargets(vaultRoot, options) {
  const targets = [];
  const add = (relativePath, kind) => targets.push({ path: relativePath, kind });

  if (options.installConfigOnly) {
    add('.mcp.json', 'file');
    add('core/paths.json', 'file');
  } else if (options.lifecycleOnly) {
    add('System/user-profile.yaml', 'file');
    add('System/.dex', 'directory');
  } else {
    for (const relativePath of Object.values(contract.seed_files || {})) add(relativePath, 'file');
    for (const [room, definition] of Object.entries(portableContract.capabilities || {})) {
      for (const relativePath of definition.folders || []) {
        addCapabilityFolderTargets(
          path.join(CAPABILITY_CATALOG, room, 'folders', ...relativePath.split('/')),
          relativePath,
          add,
        );
      }
      for (const source of definition.skill_sources || []) add(source.target_path, 'file');
    }
    for (const [relativePath, kind] of [
      ['System/user-profile.yaml', 'file'],
      ['System/pillars.yaml', 'file'],
      ['System/.onboarding-complete', 'file'],
      ['System/.dex', 'directory'],
      ['CLAUDE.md', 'file'],
      ['.mcp.json', 'file'],
      ['core/paths.json', 'file'],
    ]) add(relativePath, kind);
  }

  if (options.sessionFile) {
    const sessionPath = path.resolve(options.sessionFile);
    const canonicalSession = path.join(vaultRoot, 'System', '.onboarding-session.json');
    if (sessionPath !== canonicalSession) {
      throw new Error('--session-file must be System/.onboarding-session.json inside the vault');
    }
    add('System/.onboarding-session.json', 'file');
  }

  return targets.filter((target, index, all) => all.findIndex(
    candidate => candidate.path === target.path && candidate.kind === target.kind,
  ) === index);
}

function routeCapabilityAuthority(
  vaultRoot,
  { preflightOnly = true, mutationTargets = [], targetsOnly = false } = {},
) {
  const python = process.env.DEX_CAPABILITY_PYTHON
    || process.env.DEX_PYTHON
    || (process.platform === 'win32' ? 'python' : 'python3');
  const repoRoot = path.resolve(__dirname, '..');
  const separator = process.platform === 'win32' ? ';' : ':';
  const contractPath = process.env.DEX_CAPABILITY_CONTRACT_PATH
    || path.join(repoRoot, 'packages', 'dex-contracts', 'dist', 'portable-vault.contract.json');
  const result = childProcess.spawnSync(
    python,
    [
      path.join(repoRoot, 'core', 'capabilities.py'),
      targetsOnly ? '--preflight-mutation-targets' : (preflightOnly ? '--preflight' : '--reconcile'),
      '--vault',
      vaultRoot,
      '--contract',
      contractPath,
      '--mutation-targets-json',
      JSON.stringify(mutationTargets),
    ],
    {
      cwd: repoRoot,
      encoding: 'utf8',
      env: {
        ...process.env,
        PYTHONPATH: process.env.PYTHONPATH
          ? `${repoRoot}${separator}${process.env.PYTHONPATH}`
          : repoRoot,
      },
    },
  );
  if (result.error) {
    throw new Error(`Capability source authority could not start: ${result.error.message}`);
  }
  if (result.status !== 0) {
    throw new Error(`Capability source authority refused provisioning: ${(result.stderr || result.stdout).trim()}`);
  }
  try {
    return JSON.parse(result.stdout);
  } catch (_) {
    throw new Error('Capability source authority returned an invalid response');
  }
}

function routeProvisionTransaction(
  vaultRoot,
  { document = null, recoverOnly = false } = {},
) {
  if (recoverOnly === (document !== null)) {
    throw new Error('Provision transaction route requires exactly one mode');
  }
  const python = process.env.DEX_PROVISION_PYTHON
    || process.env.DEX_PYTHON
    || (process.platform === 'win32' ? 'python' : 'python3');
  const repoRoot = path.resolve(__dirname, '..');
  const separator = process.platform === 'win32' ? ';' : ':';
  const args = [
    path.join(repoRoot, 'core', 'provision_transaction.py'),
    '--vault',
    vaultRoot,
  ];
  if (recoverOnly) args.push('--recover');
  const result = childProcess.spawnSync(
    python,
    args,
    {
      cwd: repoRoot,
      encoding: 'utf8',
      input: recoverOnly ? '' : JSON.stringify(document),
      env: {
        ...process.env,
        PYTHONPATH: process.env.PYTHONPATH
          ? `${repoRoot}${separator}${process.env.PYTHONPATH}`
          : repoRoot,
      },
    },
  );
  if (result.error) {
    throw new Error(`Provision transaction service could not start: ${result.error.message}`);
  }
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || result.signal || 'unknown failure').trim();
    throw new Error(`Provision transaction service refused provisioning: ${detail}`);
  }
  try {
    const parsed = JSON.parse(result.stdout);
    if (!parsed || parsed.ok !== true) {
      throw new Error('Provision transaction service returned a non-success receipt');
    }
    return parsed;
  } catch (_) {
    throw new Error('Provision transaction service returned an invalid response');
  }
}

function pillarName(pillar) {
  return typeof pillar === 'string' ? pillar : String(pillar?.name || '');
}

function pillarDescription(pillar) {
  return typeof pillar === 'object' && pillar ? String(pillar.description || '') : '';
}

function pillarId(name) {
  return name.toLowerCase().replace(/ /g, '-').replace(/_/g, '-');
}

function tasksContent(pillars) {
  let content = '# Tasks\n\n## Instructions\n- Tasks are organized by pillar and priority\n'
    + '- Use task IDs (^task-YYYYMMDD-XXX) for cross-file sync\n'
    + '- Priorities: P0 (urgent), P1 (important), P2 (normal), P3 (low)\n\n---\n\n';
  for (const pillar of pillars || []) {
    const name = pillarName(pillar);
    if (name) content += `## ${name} #${name.toLowerCase().replace(/ /g, '-')}\n\n`;
  }
  return content;
}

function weekPrioritiesContent() {
  return '# Week Priorities\n\n*Updated: Week of [date]*\n\n## This Week\'s Focus\n\n'
    + '### Top 3 Priorities\n\n1. \n2. \n3. \n\n---\n\n';
}

function updateClaudeContent(content, profile) {
  if (!content.includes('## User Profile')) return content;
  const names = (profile.pillars || []).map(pillarName).filter(Boolean);
  let section = '## User Profile\n\n<!-- Updated during onboarding -->\n'
    + `**Name:** ${profile.name || 'Not configured'}\n`
    + `**Role:** ${profile.role || 'Not configured'}\n`
    + `**Company Size:** ${profile.company_size || 'Not configured'}\n`
    + `**Working Style:** ${profile.communication?.formality || 'Not configured'}\n`
    + '**Pillars:**\n';
  for (const name of names) section += `- ${name}\n`;
  return content.replace(/## User Profile.*?---/s, `${section}\n---`);
}

function configuredMcp(vaultRoot) {
  const examplePath = path.join(vaultRoot, 'System', '.mcp.json.example');
  let source = fs.readFileSync(examplePath, 'utf8').replaceAll('{{VAULT_PATH}}', vaultRoot);
  if (process.platform === 'win32') {
    source = source.replaceAll('.venv/bin/python', '.venv/Scripts/python.exe');
  }
  const config = JSON.parse(source);
  if (config.mcpServers && typeof config.mcpServers === 'object') {
    for (const [name, server] of Object.entries(config.mcpServers)) {
      const unresolved = Object.values(server?.env || {}).some(value => String(value).includes('{{'));
      if (name.startsWith('_') || unresolved) delete config.mcpServers[name];
    }
  }
  return config;
}

const LIFECYCLE_ADOPTION = String.raw`
import json
import sys
from pathlib import Path

from core.lifecycle import service
from core.lifecycle.catalog import load_catalog_payload_sources

vault = Path(sys.argv[1])
preview_only = sys.argv[3] == "preview-only"
compatibility = (
    (
        service._preview_missing_companies_default(vault)
        if preview_only
        else service._pin_missing_companies_default(vault)
    )
    if sys.argv[2] == "pin-companies"
    else {"pinned": False, "receipt": None, "preview": None, "states": {}}
)
if preview_only:
    print(json.dumps({
        "ok": True,
        "api_version": service.api_version,
        "previewed": [],
        "receipt": None,
        "compatibility_pinned": compatibility["pinned"],
        "compatibility_receipt": None,
        "compatibility_preview": compatibility.get("preview"),
        "compatibility_states": compatibility["states"],
        "skipped": "dry-run",
    }))
    raise SystemExit(0)
catalog = vault / "System/.release-catalog.json"
if not catalog.is_file():
    print(json.dumps({
        "ok": True,
        "api_version": service.api_version,
        "previewed": [],
        "receipt": None,
        "compatibility_pinned": compatibility["pinned"],
        "compatibility_receipt": compatibility["receipt"],
        "compatibility_preview": None,
        "compatibility_states": compatibility["states"],
        "skipped": "no-release-catalog",
    }))
    raise SystemExit(0)

inventory = service.build_inventory_and_plan(vault)
payload_sources = load_catalog_payload_sources(vault)
optional_targets = {
    target
    for target, mapping in payload_sources.items()
    if mapping.source_path != target
}
requested = sorted(
    item["item_id"]
    for item in inventory["plan"]["items"]
    if item["action"] == "adopt"
    and not any(
        path in optional_targets
        for reason in item["reasons"]
        for path in reason["paths"]
    )
)
receipt = None
if requested:
    preview = service.build_and_preview_adoption(vault, vault, requested)
    receipt = service.execute_approved_adoption(
        vault,
        vault,
        preview["preview"],
        preview["approval_token"],
    )["receipt"]
print(json.dumps({
    "ok": True,
    "api_version": service.api_version,
    "previewed": requested,
    "receipt": receipt,
    "compatibility_pinned": compatibility["pinned"],
    "compatibility_receipt": compatibility["receipt"],
    "compatibility_preview": None,
    "compatibility_states": compatibility["states"],
}))
`;

function routeAdoptionThroughLifecycleService(
  vaultRoot,
  { pinCompanies = true, previewOnly = false } = {},
) {
  const python = process.env.DEX_LIFECYCLE_PYTHON
    || process.env.DEX_PYTHON
    || (process.platform === 'win32' ? 'python' : 'python3');
  const repoRoot = path.resolve(__dirname, '..');
  const separator = process.platform === 'win32' ? ';' : ':';
  const result = childProcess.spawnSync(
    python,
    [
      '-c',
      LIFECYCLE_ADOPTION,
      vaultRoot,
      pinCompanies ? 'pin-companies' : 'skip-companies',
      previewOnly ? 'preview-only' : 'execute',
    ],
    {
      cwd: repoRoot,
      encoding: 'utf8',
      env: {
        ...process.env,
        PYTHONPATH: process.env.PYTHONPATH
          ? `${repoRoot}${separator}${process.env.PYTHONPATH}`
          : repoRoot,
      },
    },
  );
  if (result.error) throw new Error(`Lifecycle service could not start: ${result.error.message}`);
  if (result.status !== 0) {
    throw new Error(`Lifecycle service refused adoption: ${(result.stderr || result.stdout).trim()}`);
  }
  try {
    const parsed = JSON.parse(result.stdout);
    if (!parsed || parsed.ok !== true) {
      throw new Error('Lifecycle service returned a non-success receipt');
    }
    return parsed;
  } catch (_) {
    throw new Error('Lifecycle service returned an invalid adoption receipt');
  }
}

function mergeMcp(existing, generated) {
  if (!existing || typeof existing !== 'object' || Array.isArray(existing)) {
    throw new Error('Existing .mcp.json must contain a JSON object');
  }
  if (existing.mcpServers === undefined) existing.mcpServers = {};
  if (!existing.mcpServers || typeof existing.mcpServers !== 'object' || Array.isArray(existing.mcpServers)) {
    throw new Error('Existing .mcp.json mcpServers must contain a JSON object');
  }
  for (const [name, server] of Object.entries(generated.mcpServers || {})) {
    if (!Object.prototype.hasOwnProperty.call(existing.mcpServers, name)) existing.mcpServers[name] = server;
  }
  return existing;
}

function pathExports(vaultRoot) {
  const result = {
    _comment: 'Generated by core/provision.cjs; python3 core/paths.py regenerates this file authoritatively.',
  };
  for (const [name, relativePath] of Object.entries(contract.path_exports)) {
    result[name] = relativePath ? path.join(vaultRoot, ...relativePath.split('/')) : vaultRoot;
  }
  return result;
}

function verifyShipped(vaultRoot) {
  return contract.minimal_shipped.filter(relativePath => {
    const clean = relativePath.endsWith('/') ? relativePath.slice(0, -1) : relativePath;
    const target = path.join(vaultRoot, ...clean.split('/'));
    if (!fs.existsSync(target)) return true;
    return relativePath.endsWith('/') && !fs.statSync(target).isDirectory();
  });
}

function provisionInstallerConfig(options, vaultRoot, reporter, transaction = null) {
  const mcpPath = path.join(vaultRoot, '.mcp.json');
  if (fs.existsSync(mcpPath)) {
    reporter.skipped(mcpPath);
  } else {
    const mcp = configuredMcp(vaultRoot);
    if (options.enableQmd === true) {
      mcp.mcpServers ||= {};
      mcp.mcpServers.qmd = { command: 'qmd', args: ['mcp'] };
    }
    writeIfMissing(
      mcpPath,
      `${JSON.stringify(mcp, null, 2)}\n`,
      reporter,
      options.dryRun,
      transaction,
    );
  }
  writeIfChanged(
    path.join(vaultRoot, 'core', 'paths.json'),
    `${JSON.stringify(pathExports(vaultRoot), null, 2)}\n`,
    reporter,
    options.dryRun,
    transaction,
  );
  reporter.summary.bootstrap_executor = 'provision-contract';
  return reporter.summary;
}

function buildMutationReceipt(reporter, options) {
  const lifecycleReceipts = [
    reporter.summary.lifecycle_executor?.compatibility_receipt,
    reporter.summary.lifecycle_executor?.receipt,
  ].filter(Boolean);
  const lifecycleTransactionIds = lifecycleReceipts
    .map(receipt => receipt.transaction_id)
    .filter(Boolean);
  const lifecycleDeclaredPaths = lifecycleReceipts.flatMap(
    receipt => receipt.declared_paths
      || (receipt.files_written || []).map(file => file.path),
  );
  const provisionReceipt = reporter.summary.provision_transaction?.receipt || null;
  const provisionDeclaredPaths = reporter.summary.provision_transaction?.declared_paths
    || provisionReceipt?.declared_paths
    || [];
  const failedProvisionDeclaredPaths = (
    reporter.summary.provision_transaction_failure?.declared_paths || []
  );
  const observedCommittedTransactionIds = (
    reporter.summary.provision_recovery?.committed_transaction_ids || []
  );
  const recoveredProvisionTransactionIds = (
    reporter.summary.provision_recovery?.committed_transactions || []
  )
    .filter(transaction => transaction.operation === 'onboarding-provision')
    .map(transaction => transaction.transaction_id);
  const provisionTransactionIds = [...new Set([
    ...recoveredProvisionTransactionIds,
    ...(provisionReceipt?.transaction_id ? [provisionReceipt.transaction_id] : []),
  ])];
  return {
    executor: options.adopt || options.onboard
      ? 'lifecycle-service+provision-contract'
      : 'provision-contract-bootstrap',
    declared_paths: [...new Set([
      ...reporter.summary.created,
      ...reporter.summary.removed,
      ...lifecycleDeclaredPaths,
      ...provisionDeclaredPaths,
      ...failedProvisionDeclaredPaths,
    ])].sort(),
    lifecycle_transaction_id: lifecycleTransactionIds[0] || null,
    lifecycle_transaction_ids: lifecycleTransactionIds,
    provision_transaction_id: provisionReceipt?.transaction_id
      || recoveredProvisionTransactionIds.at(-1)
      || null,
    provision_transaction_ids: provisionTransactionIds,
    observed_committed_transaction_ids: observedCommittedTransactionIds,
    transaction_ids: [...new Set([
      ...observedCommittedTransactionIds,
      ...lifecycleTransactionIds,
      ...(provisionReceipt?.transaction_id ? [provisionReceipt.transaction_id] : []),
    ])],
  };
}

function provision(options) {
  const vaultRoot = path.resolve(options.path);
  const reporter = createReporter(vaultRoot, options.dryRun === true);
  const missing = verifyShipped(vaultRoot);
  if (missing.length) {
    reporter.error(`Missing required shipped paths: ${missing.join(', ')}`);
    return reporter.summary;
  }

  let mutationTargets;
  try {
    mutationTargets = provisionMutationTargets(vaultRoot, options);
  } catch (error) {
    reporter.error(error.message);
    return reporter.summary;
  }

  if (!options.dryRun) {
    try {
      reporter.summary.provision_recovery = routeProvisionTransaction(
        vaultRoot,
        { recoverOnly: true },
      );
    } catch (error) {
      reporter.error(error.message);
      reporter.summary.mutation_receipt = buildMutationReceipt(reporter, options);
      return reporter.summary;
    }
  }

  if (options.installConfigOnly) {
    const transaction = options.dryRun ? null : new ProvisionTransaction(vaultRoot);
    try {
      reporter.summary.capability_authority = routeCapabilityAuthority(
        vaultRoot,
        { mutationTargets, targetsOnly: true },
      );
      const summary = provisionInstallerConfig(options, vaultRoot, reporter, transaction);
      if (transaction) summary.provision_transaction = transaction.commit();
      summary.mutation_receipt = buildMutationReceipt(reporter, options);
      return summary;
    } catch (error) {
      if (transaction) rollbackProvision(transaction, reporter, error);
      else reporter.error(error.message);
      reporter.summary.mutation_receipt = buildMutationReceipt(reporter, options);
      return reporter.summary;
    }
  }

  if (options.lifecycleOnly) {
    if (!options.adopt) {
      reporter.error('--lifecycle-only requires --adopt');
      return reporter.summary;
    }
    try {
      reporter.summary.capability_authority = routeCapabilityAuthority(
        vaultRoot,
        { preflightOnly: true, mutationTargets },
      );
      reporter.summary.lifecycle_executor = routeAdoptionThroughLifecycleService(
        vaultRoot,
        { previewOnly: options.dryRun },
      );
      const lifecycleReceipts = [
        reporter.summary.lifecycle_executor.compatibility_receipt,
        reporter.summary.lifecycle_executor.receipt,
      ].filter(Boolean);
      const lifecycleDeclaredPaths = lifecycleReceipts.flatMap(
        receipt => receipt.declared_paths
          || (receipt.files_written || []).map(file => file.path),
      );
      const compatibilityPreviewPaths = (
        reporter.summary.lifecycle_executor.compatibility_preview?.writes || []
      ).map(write => write.path);
      const lifecycleTransactionIds = lifecycleReceipts
        .map(receipt => receipt.transaction_id)
        .filter(Boolean);
      reporter.summary.mutation_receipt = {
        executor: 'lifecycle-service',
        declared_paths: [...lifecycleDeclaredPaths, ...compatibilityPreviewPaths]
          .filter((file, index, files) => files.indexOf(file) === index)
          .sort(),
        lifecycle_transaction_id: lifecycleTransactionIds[0] || null,
        lifecycle_transaction_ids: lifecycleTransactionIds,
      };
      reporter.summary.compatibility_pins = reporter.summary.lifecycle_executor.compatibility_pinned
        ? ['companies']
        : [];
    } catch (error) {
      reporter.error(error.message);
    }
    return reporter.summary;
  }

  let provisionTransaction = null;
  try {
    const capabilityAuthority = routeCapabilityAuthority(
      vaultRoot,
      { preflightOnly: true, mutationTargets },
    );
    reporter.summary.capability_authority = capabilityAuthority;
    if (options.adopt || options.onboard) {
      if (options.sessionFile) {
        const sessionPath = path.resolve(options.sessionFile);
        const markerPath = path.join(vaultRoot, 'System', '.onboarding-complete');
        if (!fs.existsSync(markerPath) && !fs.existsSync(sessionPath)) {
          throw new Error(
            'Onboarding finalization requires its session until the completion marker exists',
          );
        }
      }
      reporter.summary.lifecycle_executor = routeAdoptionThroughLifecycleService(
        vaultRoot,
        {
          pinCompanies: options.adopt === true,
          previewOnly: options.dryRun === true,
        },
      );
    }
    const overlay = loadProfileOverlay(options.profile);
    const templatePath = path.join(vaultRoot, 'System', 'user-profile-template.yaml');
    const template = yaml.load(fs.readFileSync(templatePath, 'utf8')) || {};
    const freshProfile = buildFreshProfile(template, overlay);
    const profilePath = path.join(vaultRoot, 'System', 'user-profile.yaml');
    let profile = freshProfile;
    provisionTransaction = options.dryRun ? null : new ProvisionTransaction(vaultRoot);

    if (fs.existsSync(profilePath)) {
      profile = yaml.load(fs.readFileSync(profilePath, 'utf8')) || {};
      if (options.adopt) {
        profile.capabilities ||= {};
        for (const [room, enabled] of Object.entries(
          reporter.summary.lifecycle_executor?.compatibility_states || {},
        )) {
          profile.capabilities[room] ||= {};
          profile.capabilities[room].enabled = enabled;
        }
      }
      if (options.onboard) {
        profile = freshProfile;
        writeIfChanged(
          profilePath,
          yaml.dump(profile, { sortKeys: false, lineWidth: -1 }),
          reporter,
          options.dryRun,
          provisionTransaction,
        );
      } else if (options.adopt) {
        // Never inject entity_creation into an existing vault: a vault that
        // predates this key must keep the engine's suggest default, not be
        // flipped to auto-create. Only fresh provisions opt into auto.
        const gapDefaults = structuredClone(freshProfile);
        delete gapDefaults.entity_creation;
        delete gapDefaults.working_week;
        for (const [room, definition] of Object.entries(portableContract.capabilities || {})) {
          const explicit = profile.capabilities?.[room]?.enabled;
          if (typeof explicit === 'boolean') continue;
          const legacy = typeof definition.config === 'string'
            ? profile?.[definition.config]?.enabled
            : undefined;
          if (typeof legacy === 'boolean') {
            gapDefaults.capabilities[room].enabled = legacy;
          }
        }
        if (deepFillMissing(profile, gapDefaults)) {
          writeIfChanged(
            profilePath,
            yaml.dump(profile, { sortKeys: false, lineWidth: -1 }),
            reporter,
            options.dryRun,
            provisionTransaction,
          );
        } else reporter.skipped(profilePath);
      } else reporter.skipped(profilePath);
    } else {
      writeIfMissing(
        profilePath,
        yaml.dump(freshProfile, { sortKeys: false, lineWidth: -1 }),
        reporter,
        options.dryRun,
        provisionTransaction,
      );
    }

    reconcileCapabilities(
      vaultRoot,
      profile,
      reporter,
      options.dryRun,
      capabilityAuthority,
      provisionTransaction,
    );

    const tasksPath = path.join(vaultRoot, ...contract.seed_files.tasks.split('/'));
    writeIfMissing(
      tasksPath,
      tasksContent(profile.pillars),
      reporter,
      options.dryRun,
      provisionTransaction,
    );
    const prioritiesPath = path.join(vaultRoot, ...contract.seed_files.week_priorities.split('/'));
    writeIfMissing(
      prioritiesPath,
      weekPrioritiesContent(),
      reporter,
      options.dryRun,
      provisionTransaction,
    );

    const pillarsPath = path.join(vaultRoot, 'System', 'pillars.yaml');
    const pillars = (profile.pillars || []).map(pillar => {
      const name = pillarName(pillar);
      return { id: pillarId(name), name, description: pillarDescription(pillar) };
    }).filter(pillar => pillar.name);
    const pillarsContent = yaml.dump({ pillars }, { sortKeys: false, lineWidth: -1 });
    if (options.onboard) {
      writeIfChanged(
        pillarsPath,
        pillarsContent,
        reporter,
        options.dryRun,
        provisionTransaction,
      );
    } else {
      writeIfMissing(
        pillarsPath,
        pillarsContent,
        reporter,
        options.dryRun,
        provisionTransaction,
      );
    }

    const claudePath = path.join(vaultRoot, 'CLAUDE.md');
    if (fs.existsSync(claudePath)) {
      const current = fs.readFileSync(claudePath, 'utf8');
      writeIfChanged(
        claudePath,
        updateClaudeContent(current, profile),
        reporter,
        options.dryRun,
        provisionTransaction,
      );
    }

    const mcpPath = path.join(vaultRoot, '.mcp.json');
    let mcp = configuredMcp(vaultRoot);
    if (fs.existsSync(mcpPath)) {
      const existing = JSON.parse(fs.readFileSync(mcpPath, 'utf8'));
      mcp = mergeMcp(existing, mcp);
    }
    writeIfChanged(
      mcpPath,
      `${JSON.stringify(mcp, null, 2)}\n`,
      reporter,
      options.dryRun,
      provisionTransaction,
    );

    const pathsPath = path.join(vaultRoot, 'core', 'paths.json');
    writeIfChanged(
      pathsPath,
      `${JSON.stringify(pathExports(vaultRoot), null, 2)}\n`,
      reporter,
      options.dryRun,
      provisionTransaction,
    );

    const markerPath = path.join(vaultRoot, 'System', '.onboarding-complete');
    const packagePath = path.join(vaultRoot, 'package.json');
    let version = null;
    try { version = JSON.parse(fs.readFileSync(packagePath, 'utf8')).version || null; } catch (_) { /* optional */ }
    writeIfMissing(
      markerPath,
      `${JSON.stringify({
        completed: true,
        completed_at: new Date().toISOString(),
        provisioned_by: 'core/provision.cjs',
        adopted: options.adopt === true,
        version,
        ...(options.onboard ? {
          user_name: profile.name || '',
          role: profile.role || '',
          email_domain: profile.email_domain || '',
          has_pillars: pillars.length > 0,
          phase2_completed: false,
          pre_analysis_deferred: true,
        } : {}),
      }, null, 2)}\n`,
      reporter,
      options.dryRun,
      provisionTransaction,
    );

    if (options.sessionFile) {
      const sessionPath = path.resolve(options.sessionFile);
      const relativeSession = path.relative(vaultRoot, sessionPath);
      if (
        relativeSession.startsWith(`..${path.sep}`)
        || relativeSession === '..'
        || path.isAbsolute(relativeSession)
      ) throw new Error('--session-file must stay inside the vault');
      if (fs.existsSync(sessionPath)) {
        if (fs.lstatSync(sessionPath).isSymbolicLink() || !fs.statSync(sessionPath).isFile()) {
          throw new Error('--session-file must name a regular file');
        }
        if (!options.dryRun) {
          provisionTransaction.stageDeleteFile(sessionPath);
        }
        reporter.removed(sessionPath);
      } else reporter.skipped(sessionPath);
    }

    if (provisionTransaction) {
      reporter.summary.provision_transaction = provisionTransaction.commit();
    }
  } catch (error) {
    if (provisionTransaction) rollbackProvision(provisionTransaction, reporter, error);
    else reporter.error(error.message);
  }

  reporter.summary.mutation_receipt = buildMutationReceipt(reporter, options);

  return reporter.summary;
}

function printSummary(summary, asJson) {
  if (asJson) {
    process.stdout.write(`${JSON.stringify(summary)}\n`);
    return;
  }
  process.stdout.write(`Dex vault provision ${summary.ok ? 'complete' : 'failed'}${summary.dry_run ? ' (dry run)' : ''}\n`);
  process.stdout.write(`  Path: ${summary.path}\n`);
  process.stdout.write(`  Created: ${summary.created.length}\n`);
  process.stdout.write(`  Skipped existing: ${summary['skipped-existing'].length}\n`);
  process.stdout.write(`  Errors: ${summary.errors.length}\n`);
  for (const error of summary.errors) process.stdout.write(`    - ${error}\n`);
  if (summary.lifecycle_executor) {
    const lifecycle = summary.lifecycle_executor;
    process.stdout.write(`  Lifecycle API: ${lifecycle.api_version || 'not activated'}\n`);
    process.stdout.write(`  Items previewed: ${(lifecycle.previewed || []).length}\n`);
    if (lifecycle.receipt) {
      process.stdout.write(`  Transaction receipt: ${lifecycle.receipt.transaction_id}\n`);
      process.stdout.write(`  Receipt-declared files: ${lifecycle.receipt.files_written.length}\n`);
    } else if (lifecycle.skipped) {
      process.stdout.write(`  Lifecycle route: ${lifecycle.skipped}\n`);
    }
  }
}

function usage() {
  return 'Usage: node core/provision.cjs --path <vault> [--profile <file.json>] [--adopt|--onboard] [--session-file <path>] [--install-config-only] [--lifecycle-only] [--enable-qmd] [--dry-run] [--json]\n';
}

if (require.main === module) {
  try {
    const options = parseArgs(process.argv.slice(2));
    if (options.help) {
      process.stdout.write(usage());
    } else {
      const summary = provision(options);
      printSummary(summary, options.json);
      if (!summary.ok) process.exitCode = 1;
    }
  } catch (error) {
    process.stderr.write(`${error.message}\n${usage()}`);
    process.exitCode = 1;
  }
}

module.exports = {
  contract,
  deepFillMissing,
  parseArgs,
  pathExports,
  provisionMutationTargets,
  provision,
  routeAdoptionThroughLifecycleService,
  routeCapabilityAuthority,
  reconcileCapabilities,
  updateClaudeContent,
};
