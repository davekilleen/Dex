#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const config = require('./ownership.json');
const VALID_CLASSES = new Set(['brain', 'vault', 'seed', 'generated', 'runtime']);
const PARA_ROOT = /^0[0-7]-/;

function slashPath(value) {
  return String(value).replaceAll('\\', '/').replace(/^\.\//, '');
}

function ruleMatches(candidate, prefix) {
  return candidate === prefix || (prefix.endsWith('/') && candidate.startsWith(prefix));
}

function isCustomOwned(candidate) {
  const parts = candidate.split('/');
  return (
    parts.length >= 3
    && parts[0] === '.claude'
    && parts[1] === 'skills'
    && parts[2].endsWith('-custom')
  );
}

function classificationDetails(input) {
  const candidate = slashPath(input);
  if (isCustomOwned(candidate)) {
    return { className: 'vault', matches: [{ prefix: '.claude/skills/*-custom/', class: 'vault' }] };
  }

  const matches = config.rules.filter((rule) => ruleMatches(candidate, rule.prefix));
  if (matches.length === 0) {
    return { className: config.defaultClass, matches: [] };
  }
  const longest = Math.max(...matches.map((rule) => rule.prefix.length));
  const mostSpecific = matches.filter((rule) => rule.prefix.length === longest);
  const classes = new Set(mostSpecific.map((rule) => rule.class));
  return {
    className: classes.size === 1 ? mostSpecific[0].class : null,
    matches: mostSpecific,
  };
}

function classify(input) {
  const details = classificationDetails(input);
  if (details.className === null) {
    throw new Error(`Ambiguous ownership rules for ${input}`);
  }
  return details.className;
}

function brainPaths(manifestLines) {
  if (!Array.isArray(manifestLines)) {
    throw new TypeError('manifestLines must be an array of release manifest paths');
  }
  return manifestLines
    .map((line) => slashPath(line).trim())
    .filter(Boolean)
    .filter((manifestPath) => classify(manifestPath) === 'brain');
}

function seedEntries() {
  return config.rules
    .filter((rule) => rule.class === 'seed')
    .map((rule) => ({ path: rule.prefix, class: 'seed' }))
    .sort((left, right) => left.path.localeCompare(right.path));
}

function vaultExcludeLines() {
  const lines = [];
  for (const rule of config.rules) {
    if (!['brain', 'generated', 'runtime'].includes(rule.class)) continue;
    if (rule.prefix === '.claude/') continue;
    if (rule.prefix === 'core/') continue;
    if (rule.prefix === '.dex/') continue;
    const rendered = `/${rule.prefix}`;
    if (!lines.includes(rendered)) lines.push(rendered);
  }

  lines.push(
    '/.claude/*',
    '!/.claude/skills/',
    '/.claude/skills/*',
    '!/.claude/skills/*-custom/',
    '!/.claude/skills/*-custom/**',
    '!/.claude/skills-custom/',
    '!/.claude/skills-custom/**',
    '/core/*',
    '!/core/mcp-custom/',
    '!/core/mcp-custom/**',
    '!/core/mcp-premium/',
    '!/core/mcp-premium/**',
    '/.dex/',
  );
  return lines;
}

function vaultGitignoreContent() {
  return [
    '# Private and machine-local files',
    '.env*',
    '.secrets',
    '.secrets.*',
    '*.key',
    '*.pem',
    '*token.json',
    '*credentials.json',
    'System/credentials/',
    '',
    '# Dependencies and Dex runtime state',
    'node_modules/',
    '.venv/',
    '.dex/',
    'System/.dex/',
    '',
    '# Obsidian keeps personal window state here',
    '.obsidian/workspace*',
    '',
  ].join('\n');
}

function isDenied(input, root) {
  if (typeof input !== 'string' || input.length === 0 || input.includes('\0')) return true;
  if (
    input.startsWith('/')
    || input.startsWith('\\\\')
    || /^[A-Za-z]:[\\/]/.test(input)
  ) return true;

  const candidate = input.replaceAll('\\', '/');
  const parts = candidate.split('/');
  if (parts.some((part) => part === '' || part === '.' || part === '..')) return true;
  const lower = parts.map((part) => part.toLowerCase());
  if (lower.includes('.git')) return true;
  if (lower[0] === '.dex' && lower.slice(1).some((part) => part.endsWith('.git'))) return true;
  if (PARA_ROOT.test(parts[0])) return true;
  if (lower[0] === 'system' && lower[1] === 'credentials') return true;
  if (lower.some((part) => part.startsWith('.env'))) return true;
  if (root !== undefined) {
    let current = path.resolve(root);
    for (const part of parts.slice(0, -1)) {
      current = path.join(current, part);
      try {
        if (fs.lstatSync(current).isSymbolicLink()) return true;
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
    }
  }
  return false;
}

function validateConfig() {
  const errors = [];
  if (!VALID_CLASSES.has(config.defaultClass)) {
    errors.push(`unknown default class: ${config.defaultClass}`);
  }
  const seen = new Map();
  for (const rule of config.rules) {
    if (!VALID_CLASSES.has(rule.class)) errors.push(`unknown class for ${rule.prefix}: ${rule.class}`);
    if (path.isAbsolute(rule.prefix) || rule.prefix.includes('..') || rule.prefix.includes('\\')) {
      errors.push(`unsafe ownership prefix: ${rule.prefix}`);
    }
    if (seen.has(rule.prefix) && seen.get(rule.prefix) !== rule.class) {
      errors.push(`ambiguous ownership prefix: ${rule.prefix}`);
    }
    seen.set(rule.prefix, rule.class);
  }
  return errors;
}

function validateManifest(manifestLines) {
  const errors = validateConfig();
  const counts = Object.fromEntries([...VALID_CLASSES].map((className) => [className, 0]));
  const seen = new Set();
  const grandfathered = [];

  for (const rawLine of manifestLines) {
    const manifestPath = slashPath(rawLine).trim();
    if (!manifestPath) continue;
    if (seen.has(manifestPath)) {
      errors.push(`duplicate manifest path: ${manifestPath}`);
      continue;
    }
    seen.add(manifestPath);
    const details = classificationDetails(manifestPath);
    if (details.className === null) {
      errors.push(`ambiguous ownership for: ${manifestPath}`);
      continue;
    }
    counts[details.className] += 1;
    if (PARA_ROOT.test(manifestPath)) grandfathered.push(manifestPath);
  }
  return { errors, counts, grandfathered, pathCount: seen.size };
}

function runValidator(manifestPath) {
  const resolved = path.resolve(manifestPath || 'System/.installed-files.manifest');
  if (!fs.existsSync(resolved)) {
    console.error(`Release manifest not found at ${resolved}. Build or check out the release artifact, or pass its path after --validate.`);
    return 1;
  }

  const manifestLines = fs.readFileSync(resolved, 'utf8').split(/\r?\n/);
  const result = validateManifest(manifestLines);
  if (result.errors.length > 0) {
    console.error('Ownership validation failed:');
    for (const error of result.errors) console.error(`- ${error}`);
    return 1;
  }

  console.log(`Validated ${result.pathCount} release paths.`);
  console.log(
    [...VALID_CLASSES].map((className) => `${className}: ${result.counts[className]}`).join(', '),
  );
  console.log(`${result.grandfathered.length} delivery-sensitive tracked paths (kept for the bridge release):`);
  for (const manifestPath of result.grandfathered) console.log(`- ${manifestPath}`);
  return 0;
}

module.exports = {
  brainPaths,
  classify,
  isDenied,
  seedEntries,
  validateManifest,
  vaultExcludeLines,
  vaultGitignoreContent,
};

if (require.main === module) {
  if (process.argv[2] !== '--validate' || process.argv.length > 4) {
    console.error('Usage: node core/update/ownership.cjs --validate [System/.installed-files.manifest]');
    process.exitCode = 2;
  } else {
    process.exitCode = runValidator(process.argv[3]);
  }
}
