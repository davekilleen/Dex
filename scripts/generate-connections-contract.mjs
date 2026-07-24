#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = require(path.join(REPO, 'core/integrations/connection-manager/contract.cjs'));
const DIST = path.join(REPO, 'packages/dex-contracts/dist');
const FIXTURES = path.join(REPO, 'packages/dex-contracts/fixtures/connections');

fs.mkdirSync(DIST, { recursive: true });
fs.mkdirSync(FIXTURES, { recursive: true });

function writeJson(file, value) {
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`);
}

writeJson(path.join(DIST, 'connections.contract.json'), source.buildConnectionsContract());
writeJson(path.join(DIST, 'connections.schema.json'), source.buildConnectionsSchema());
for (const [name, fixture] of Object.entries(source.buildConnectionsFixtures())) {
  writeJson(path.join(FIXTURES, name), fixture);
}
console.log(`Generated connections contract v${source.CONTRACT_VERSION} and ${Object.keys(source.buildConnectionsFixtures()).length} fixtures`);
