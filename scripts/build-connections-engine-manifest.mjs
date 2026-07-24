#!/usr/bin/env node

import assert from 'node:assert';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SOURCE_REL = 'core/integrations/connection-manager';
const SOURCE = path.join(REPO, SOURCE_REL);
const OUTPUT = path.join(REPO, 'packages/dex-contracts/dist/connections-engine.manifest.json');
const { CONTRACT_VERSION, ENGINE_VERSION } = require(path.join(SOURCE, 'contract.cjs'));

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function collect(dir) {
  const output = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
    const absolute = path.join(dir, entry.name);
    if (entry.isSymbolicLink()) continue;
    if (entry.isDirectory()) output.push(...collect(absolute));
    else if (entry.isFile() && !entry.name.endsWith('.test.cjs') && entry.name !== 'hardening.child.cjs') output.push(absolute);
  }
  return output;
}

const files = collect(SOURCE).map((absolute) => {
  const bytes = fs.readFileSync(absolute);
  return {
    path: path.relative(SOURCE, absolute).split(path.sep).join('/'),
    bytes: bytes.length,
    sha256: sha256(bytes),
  };
});
const treeHash = crypto.createHash('sha256');
for (const file of files) {
  treeHash.update(file.path);
  treeHash.update('\0');
  treeHash.update(String(file.bytes));
  treeHash.update('\0');
  treeHash.update(file.sha256);
  treeHash.update('\n');
}
const manifest = {
  version: 1,
  engineVersion: ENGINE_VERSION,
  contractVersion: CONTRACT_VERSION,
  trees: {
    connectionsEngine: {
      sourcePath: SOURCE_REL,
      vendorPath: 'vendor/dex-core-connections-engine',
      entryCount: 1,
      entries: ['connection-manager'],
      fileCount: files.length,
      totalBytes: files.reduce((sum, file) => sum + file.bytes, 0),
      treeHash: treeHash.digest('hex'),
      files,
    },
  },
};

if (process.argv.includes('--check')) {
  assert.deepStrictEqual(JSON.parse(fs.readFileSync(OUTPUT, 'utf8')), manifest, 'connections engine manifest drifted; run scripts/build-connections-engine-manifest.mjs');
  console.log(`Connections engine manifest verified (${files.length} files, ${manifest.trees.connectionsEngine.treeHash})`);
} else {
  fs.mkdirSync(path.dirname(OUTPUT), { recursive: true });
  fs.writeFileSync(OUTPUT, `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(`Built connections engine manifest (${files.length} files, ${manifest.trees.connectionsEngine.treeHash})`);
}
