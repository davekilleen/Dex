'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { getMeetingProcessingMode } = require('../lib/config.cjs');
const { getGranolaApiKey } = require('../lib/granola-api-key.cjs');

test('meeting processing mode accepts the canonical object shape', () => {
  assert.equal(getMeetingProcessingMode({ mode: 'manual' }), 'manual');
  assert.equal(getMeetingProcessingMode({ mode: 'automatic' }), 'automatic');
});

test('meeting processing mode accepts the legacy string shape', () => {
  assert.equal(getMeetingProcessingMode('manual'), 'manual');
  assert.equal(getMeetingProcessingMode('automatic'), 'automatic');
});

test('meeting processing mode defaults malformed or missing values to automatic', () => {
  assert.equal(getMeetingProcessingMode(), 'automatic');
  assert.equal(getMeetingProcessingMode({}), 'automatic');
  assert.equal(getMeetingProcessingMode(42), 'automatic');
});

test('Granola API key uses environment before the vault .env file', t => {
  const vaultRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-granola-key-'));
  t.after(() => fs.rmSync(vaultRoot, { recursive: true, force: true }));
  fs.writeFileSync(path.join(vaultRoot, '.env'), 'GRANOLA_API_KEY="grn_file"\n');

  assert.equal(
    getGranolaApiKey({ env: { GRANOLA_API_KEY: ' grn_environment ' }, vaultRoot }),
    'grn_environment',
  );
  assert.equal(getGranolaApiKey({ env: {}, vaultRoot }), 'grn_file');
});
