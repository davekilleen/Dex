#!/usr/bin/env node

import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { readJson, validateAgainstSchema } from './connections-contract-validation.mjs';

const require = createRequire(import.meta.url);
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = require(path.join(REPO, 'core/integrations/connection-manager/contract.cjs'));
const DIST = path.join(REPO, 'packages/dex-contracts/dist');
const FIXTURES = path.join(REPO, 'packages/dex-contracts/fixtures/connections');

const contract = readJson(path.join(DIST, 'connections.contract.json'));
const schema = readJson(path.join(DIST, 'connections.schema.json'));
assert.deepStrictEqual(contract, source.buildConnectionsContract(), 'connections.contract.json drifted; run scripts/generate-connections-contract.mjs');
assert.deepStrictEqual(schema, source.buildConnectionsSchema(), 'connections.schema.json drifted; run scripts/generate-connections-contract.mjs');

for (const [name, expected] of Object.entries(source.buildConnectionsFixtures())) {
  const file = path.join(FIXTURES, name);
  assert.equal(fs.existsSync(file), true, `missing fixture ${name}`);
  const actual = readJson(file);
  assert.deepStrictEqual(actual, expected, `fixture drift: ${name}`);
  const definition = name.startsWith('status.')
    ? 'statusOutput'
    : name === 'token.least-privilege.json'
      ? 'leastPrivilegeToken'
      : name === 'token.class-b-envelope.json'
        ? 'classBEnvelope'
        : 'tokenEnvelopeV2';
  validateAgainstSchema(actual, schema.$defs[definition], schema);
}
console.log(`Connections contract v${contract.version}: dist and ${Object.keys(source.buildConnectionsFixtures()).length} fixtures conform`);
