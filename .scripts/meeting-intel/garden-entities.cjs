#!/usr/bin/env node
'use strict';

const fs = require('fs');
const yaml = require('js-yaml');
const { generateContent, isConfigured } = require('../lib/llm-client.cjs');
const { gardenEntities } = require('./lib/gardener.cjs');
const { runtimePaths } = require('./lib/contacts-state.cjs');

function loadProfile() {
  const profilePath = runtimePaths().USER_PROFILE_FILE;
  try {
    const profile = yaml.load(fs.readFileSync(profilePath, 'utf8'));
    return profile && typeof profile === 'object' ? profile : {};
  } catch (_) {
    return {};
  }
}

function parseLimit(args) {
  const index = args.indexOf('--limit');
  if (index < 0) return 5;
  const value = Number(args[index + 1]);
  return Number.isInteger(value) && value >= 0 ? value : 5;
}

async function main() {
  const args = process.argv.slice(2);
  if (!isConfigured()) {
    console.log('Gardener skipped: no LLM key configured.');
    return;
  }
  if (loadProfile().entity_gardener?.enabled === false) {
    console.log('Gardener skipped: disabled in user profile.');
    return;
  }
  const result = await gardenEntities({
    generate: generateContent,
    dryRun: args.includes('--dry-run'),
    limit: parseLimit(args),
    log: console.log,
  });
  for (const page of result.gardened) console.log(`Gardened: ${page}`);
  for (const failure of result.errors) {
    console.log(`Gardener error${failure.page ? ` (${failure.page})` : ''}: ${failure.error}`);
  }
  console.log(
    `Gardener summary: ${result.gardened.length} gardened, ${result.skipped} skipped, `
    + `${result.locked} locked, ${result.errors.length} errors.`,
  );
}

if (require.main === module) {
  main().catch(error => {
    console.error(`Gardener error: ${error.message}`);
    process.exitCode = 1;
  });
}

module.exports = { main };
