'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const {
  mergeFrontmatterText,
  replaceMachineRegion,
} = require('../entity-pages.cjs');

const REGION_HEADINGS = {
  'recent-interactions': 'Recent Interactions',
  'key-contacts': 'Key Contacts',
  'meeting-history': 'Meeting History',
  'context-summary': 'Key Context',
  'related-tasks': 'Related Tasks',
  relationships: 'Relationships',
  'update-log': 'Update Log',
};

function fingerprint(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

function ensureRegion(text, slug) {
  if (text.includes(`<!-- dex:auto:${slug} -->`)) return text;
  const heading = REGION_HEADINGS[slug] || slug.replace(/-/g, ' ')
    .replace(/\b\w/g, character => character.toUpperCase());
  const match = new RegExp(`^##[ \\t]+${heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[ \\t]*$`, 'm')
    .exec(text);
  const region = `<!-- dex:auto:${slug} -->\n<!-- /dex:auto -->`;
  if (match) {
    const prefix = text.slice(0, match.index + match[0].length).replace(/[\r\n]+$/, '');
    const suffix = text.slice(match.index + match[0].length).replace(/^[\r\n]+/, '');
    return suffix
      ? `${prefix}\n\n${region}\n\n${suffix}`
      : `${prefix}\n\n${region}\n`;
  }
  const prefix = text.replace(/[\r\n]+$/, '');
  return prefix
    ? `${prefix}\n\n## ${heading}\n\n${region}\n`
    : `## ${heading}\n\n${region}\n`;
}

function applyOperation(operation) {
  if (operation.op === 'create') {
    if (fs.existsSync(operation.path)) {
      const existing = fs.readFileSync(operation.path, 'utf8');
      return { path: operation.path, status: 'exists', fingerprint: fingerprint(existing) };
    }
    fs.mkdirSync(path.dirname(operation.path), { recursive: true });
    fs.writeFileSync(operation.path, operation.content, 'utf8');
    return {
      path: operation.path,
      status: 'created',
      fingerprint: fingerprint(operation.content),
    };
  }

  if (!fs.existsSync(operation.path)) {
    return { path: operation.path, status: 'missing', fingerprint: null };
  }
  const original = fs.readFileSync(operation.path, 'utf8');
  const originalFingerprint = fingerprint(original);
  if (originalFingerprint !== operation.base_fingerprint) {
    return {
      path: operation.path,
      status: 'conflict',
      fingerprint: originalFingerprint,
    };
  }

  let updated = operation.replacement_content ?? original;
  if (operation.field_changes) {
    updated = mergeFrontmatterText(operation.path, updated, operation.field_changes);
    if (updated === null) {
      return {
        path: operation.path,
        status: 'quarantined',
        fingerprint: originalFingerprint,
      };
    }
  }
  for (const slug of operation.ensure_regions || []) {
    updated = ensureRegion(updated, slug);
  }
  for (const [slug, projection] of Object.entries(operation.region_projections || {})) {
    updated = replaceMachineRegion(updated, slug, projection);
  }
  if (updated === original) {
    return { path: operation.path, status: 'noop', fingerprint: originalFingerprint };
  }
  fs.writeFileSync(operation.path, updated, 'utf8');
  return { path: operation.path, status: 'updated', fingerprint: fingerprint(updated) };
}

function runEntityEngineStub() {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  process.stdout.write(JSON.stringify({
    results: request.ops.map(applyOperation),
  }));
}

function installEntityEngineStub(vaultRoot) {
  const executable = path.join(vaultRoot, 'entity-engine-test-python');
  const source = [
    `#!${process.execPath}`,
    `'use strict';`,
    `if (process.argv[2] !== '-c') {`,
    `  require(${JSON.stringify(__filename)}).runEntityEngineStub();`,
    `}`,
    '',
  ].join('\n');
  fs.writeFileSync(executable, source, 'utf8');
  fs.chmodSync(executable, 0o755);
  return executable;
}

module.exports = { installEntityEngineStub, runEntityEngineStub };
