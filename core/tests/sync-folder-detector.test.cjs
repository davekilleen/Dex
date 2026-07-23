'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const DETECTOR_PATH = path.join(
  REPO_ROOT,
  'core',
  'migrations',
  'sync-folder-detector.cjs',
);
const VECTOR_PATH = path.join(
  REPO_ROOT,
  'core',
  'tests',
  'fixtures',
  'sync-folder-vectors.json',
);

function vectors() {
  const document = JSON.parse(fs.readFileSync(VECTOR_PATH, 'utf8'));
  assert.equal(document.schema_version, 1);
  return document.vectors;
}

function buildVector(vector, index) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), `dex-sync-vector-${index}-`));
  const vault = path.join(root, ...vector.relative_path);
  fs.mkdirSync(vault, { recursive: true });
  for (const ancestor of vector.ancestor_children) {
    const directory = path.join(root, ...ancestor.relative_path);
    fs.mkdirSync(directory, { recursive: true });
    for (const name of ancestor.names) {
      fs.mkdirSync(path.join(directory, name));
    }
  }
  return vault;
}

test('shared sync-folder vectors cover the data table and CommonJS reader', () => {
  const detector = require(DETECTOR_PATH);
  const { markers, cloudstorageProviderPrefixes } = detector.loadSyncFolderMarkers();
  const expectedProviders = new Set(
    vectors()
      .map((vector) => vector.expected_provider)
      .filter((provider) => provider !== null),
  );
  const declaredProviders = new Set(markers.map((marker) => marker.provider));
  for (const entry of cloudstorageProviderPrefixes) {
    declaredProviders.add(entry.provider);
  }
  assert.deepEqual([...expectedProviders].sort(), [...declaredProviders].sort());

  for (const [index, vector] of vectors().entries()) {
    assert.equal(
      detector.detectSyncFolder(buildVector(vector, index)),
      vector.expected_provider,
      vector.name,
    );
  }
});

test('CommonJS sync-folder marker loader fails closed on missing or malformed data', () => {
  const detector = require(DETECTOR_PATH);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-sync-marker-data-'));
  const malformed = path.join(root, 'malformed.json');
  fs.writeFileSync(malformed, '{"schema_version":2,"markers":[]}');

  assert.throws(
    () => detector.loadSyncFolderMarkers(path.join(root, 'missing.json')),
    /sync-folder marker data/i,
  );
  assert.throws(
    () => detector.loadSyncFolderMarkers(malformed),
    /sync-folder marker data/i,
  );
});
