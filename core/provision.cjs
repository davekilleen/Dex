#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const yaml = require('js-yaml');
const contract = require('./provision-contract.json');
const portableContract = require('../packages/dex-contracts/dist/portable-vault.contract.json');

const PROFILE_KEYS = new Set([
  'name', 'role', 'company', 'company_size', 'email_domain', 'work_email',
  'obsidian_mode', 'pillars', 'communication', 'capabilities',
]);

const CAPABILITY_CATALOG = path.join(
  __dirname, '..', '.claude', 'skills', '_available', 'capabilities',
);

function parseArgs(argv) {
  const options = { adopt: false, dryRun: false, json: false };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--path' || arg === '--profile') {
      if (!argv[index + 1]) throw new Error(`${arg} requires a value`);
      options[arg.slice(2)] = argv[index + 1];
      index += 1;
    } else if (arg === '--adopt') options.adopt = true;
    else if (arg === '--dry-run') options.dryRun = true;
    else if (arg === '--json') options.json = true;
    else if (arg === '--help' || arg === '-h') options.help = true;
    else throw new Error(`Unknown argument: ${arg}`);
  }
  if (!options.help && !options.path) throw new Error('--path is required');
  return options;
}

function atomicWrite(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tempPath = path.join(
    path.dirname(filePath),
    `.${path.basename(filePath)}.${process.pid}.${Date.now()}.tmp`,
  );
  try {
    fs.writeFileSync(tempPath, content, 'utf8');
    fs.renameSync(tempPath, filePath);
  } catch (error) {
    try { fs.unlinkSync(tempPath); } catch (_) { /* absent */ }
    throw error;
  }
}

function reportPath(vaultRoot, filePath) {
  return path.relative(vaultRoot, filePath).split(path.sep).join('/') || '.';
}

function createReporter(vaultRoot, dryRun) {
  const summary = {
    ok: true,
    path: vaultRoot,
    dry_run: dryRun,
    created: [],
    'skipped-existing': [],
    errors: [],
  };
  return {
    summary,
    created(filePath) { summary.created.push(reportPath(vaultRoot, filePath)); },
    skipped(filePath) { summary['skipped-existing'].push(reportPath(vaultRoot, filePath)); },
    error(message) { summary.ok = false; summary.errors.push(message); },
  };
}

function ensureDirectory(directory, reporter, dryRun) {
  if (fs.existsSync(directory)) {
    if (!fs.statSync(directory).isDirectory()) throw new Error(`${directory} exists but is not a directory`);
    reporter.skipped(directory);
    return;
  }
  if (!dryRun) fs.mkdirSync(directory, { recursive: true });
  reporter.created(directory);
}

function writeIfMissing(filePath, content, reporter, dryRun) {
  if (fs.existsSync(filePath)) {
    reporter.skipped(filePath);
    return false;
  }
  if (!dryRun) atomicWrite(filePath, content);
  reporter.created(filePath);
  return true;
}

function writeIfChanged(filePath, content, reporter, dryRun) {
  if (fs.existsSync(filePath) && fs.readFileSync(filePath, 'utf8') === content) {
    reporter.skipped(filePath);
    return false;
  }
  if (!dryRun) atomicWrite(filePath, content);
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
  profile.entity_creation = { mode: 'auto' };
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

function copyMissing(source, target, reporter, dryRun) {
  if (!fs.existsSync(source)) return;
  const stat = fs.statSync(source);
  if (stat.isDirectory()) {
    ensureDirectory(target, reporter, dryRun);
    for (const entry of fs.readdirSync(source)) {
      copyMissing(path.join(source, entry), path.join(target, entry), reporter, dryRun);
    }
  } else if (!fs.existsSync(target)) {
    if (!dryRun) {
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.copyFileSync(source, target);
    }
    reporter.created(target);
  } else reporter.skipped(target);
}

function reconcileCapabilities(vaultRoot, profile, reporter, dryRun) {
  for (const [room, definition] of Object.entries(portableContract.capabilities || {})) {
    const roomEnabled = capabilityEnabled(profile, room, definition);
    const roomSource = path.join(CAPABILITY_CATALOG, room);
    if (roomEnabled) {
      for (const relativeFolder of definition.folders || []) {
        const target = path.join(vaultRoot, ...relativeFolder.split('/'));
        ensureDirectory(target, reporter, dryRun);
        copyMissing(
          path.join(roomSource, 'folders', ...relativeFolder.split('/')),
          target,
          reporter,
          dryRun,
        );
      }
      for (const skill of definition.skills || []) {
        const source = path.join(roomSource, 'skills', skill);
        const target = path.join(vaultRoot, '.claude', 'skills', skill);
        if (!fs.existsSync(source)) throw new Error(`Dormant skill is missing for ${room}: ${skill}`);
        if (!dryRun) {
          fs.rmSync(target, { recursive: true, force: true });
          fs.cpSync(source, target, { recursive: true });
        }
        reporter.created(target);
      }
    } else {
      // Room folders contain user content and are never deleted. Only release-owned
      // active skill copies are hidden when a room is switched off.
      for (const skill of definition.skills || []) {
        const target = path.join(vaultRoot, '.claude', 'skills', skill);
        if (fs.existsSync(target)) {
          if (!dryRun) fs.rmSync(target, { recursive: true, force: true });
          reporter.skipped(target);
        }
      }
    }
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
  const source = fs.readFileSync(examplePath, 'utf8').replaceAll('{{VAULT_PATH}}', vaultRoot);
  const config = JSON.parse(source);
  if (config.mcpServers && typeof config.mcpServers === 'object') {
    for (const [name, server] of Object.entries(config.mcpServers)) {
      const unresolved = Object.values(server?.env || {}).some(value => String(value).includes('{{'));
      if (name.startsWith('_') || unresolved) delete config.mcpServers[name];
    }
  }
  return config;
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

function provision(options) {
  const vaultRoot = path.resolve(options.path);
  const reporter = createReporter(vaultRoot, options.dryRun === true);
  const missing = verifyShipped(vaultRoot);
  if (missing.length) {
    reporter.error(`Missing required shipped paths: ${missing.join(', ')}`);
    return reporter.summary;
  }

  try {
    const overlay = loadProfileOverlay(options.profile);
    const templatePath = path.join(vaultRoot, 'System', 'user-profile-template.yaml');
    const template = yaml.load(fs.readFileSync(templatePath, 'utf8')) || {};
    const freshProfile = buildFreshProfile(template, overlay);
    const profilePath = path.join(vaultRoot, 'System', 'user-profile.yaml');
    let profile = freshProfile;

    if (fs.existsSync(profilePath)) {
      profile = yaml.load(fs.readFileSync(profilePath, 'utf8')) || {};
      if (options.adopt) {
        // Never inject entity_creation into an existing vault: a vault that
        // predates this key must keep the engine's suggest default, not be
        // flipped to auto-create. Only fresh provisions opt into auto.
        const gapDefaults = structuredClone(freshProfile);
        delete gapDefaults.entity_creation;
        for (const [room, definition] of Object.entries(portableContract.capabilities || {})) {
          if (!profile.capabilities?.[room] && typeof definition.config === 'string') {
            gapDefaults.capabilities[room].enabled = capabilityEnabled(profile, room, definition);
          }
        }
        if (deepFillMissing(profile, gapDefaults)) {
          writeIfChanged(profilePath, yaml.dump(profile, { sortKeys: false, lineWidth: -1 }), reporter, options.dryRun);
        } else reporter.skipped(profilePath);
      } else reporter.skipped(profilePath);
    } else {
      writeIfMissing(
        profilePath,
        yaml.dump(freshProfile, { sortKeys: false, lineWidth: -1 }),
        reporter,
        options.dryRun,
      );
    }

    for (const relativePath of contract.para_directories) {
      ensureDirectory(path.join(vaultRoot, ...relativePath.split('/')), reporter, options.dryRun);
    }

    reconcileCapabilities(vaultRoot, profile, reporter, options.dryRun);

    const tasksPath = path.join(vaultRoot, ...contract.seed_files.tasks.split('/'));
    writeIfMissing(tasksPath, tasksContent(profile.pillars), reporter, options.dryRun);
    const prioritiesPath = path.join(vaultRoot, ...contract.seed_files.week_priorities.split('/'));
    writeIfMissing(prioritiesPath, weekPrioritiesContent(), reporter, options.dryRun);

    const pillarsPath = path.join(vaultRoot, 'System', 'pillars.yaml');
    const pillars = (profile.pillars || []).map(pillar => {
      const name = pillarName(pillar);
      return { id: pillarId(name), name, description: pillarDescription(pillar) };
    }).filter(pillar => pillar.name);
    writeIfMissing(
      pillarsPath,
      yaml.dump({ pillars }, { sortKeys: false, lineWidth: -1 }),
      reporter,
      options.dryRun,
    );

    const claudePath = path.join(vaultRoot, 'CLAUDE.md');
    if (fs.existsSync(claudePath)) {
      const current = fs.readFileSync(claudePath, 'utf8');
      writeIfChanged(claudePath, updateClaudeContent(current, profile), reporter, options.dryRun);
    }

    const mcpPath = path.join(vaultRoot, '.mcp.json');
    let mcp = configuredMcp(vaultRoot);
    if (fs.existsSync(mcpPath)) {
      const existing = JSON.parse(fs.readFileSync(mcpPath, 'utf8'));
      mcp = mergeMcp(existing, mcp);
    }
    writeIfChanged(mcpPath, `${JSON.stringify(mcp, null, 2)}\n`, reporter, options.dryRun);

    const pathsPath = path.join(vaultRoot, 'core', 'paths.json');
    writeIfChanged(
      pathsPath,
      `${JSON.stringify(pathExports(vaultRoot), null, 2)}\n`,
      reporter,
      options.dryRun,
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
      }, null, 2)}\n`,
      reporter,
      options.dryRun,
    );
  } catch (error) {
    reporter.error(error.message);
  }

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
}

function usage() {
  return 'Usage: node core/provision.cjs --path <vault> [--profile <file.json>] [--adopt] [--dry-run] [--json]\n';
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
  provision,
  reconcileCapabilities,
  updateClaudeContent,
};
