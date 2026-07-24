'use strict';

const fs = require('node:fs');
const path = require('node:path');

const DATA_PATH = path.resolve(__dirname, '..', 'data', 'sync-folder-markers.json');
const SCHEMA_VERSION = 1;
const MARKER_KINDS = new Set([
  'path-segment',
  'cloudstorage-provider',
  'child',
  'paired-children',
  'icloud-materialization',
]);

function markerDataError(message) {
  return new Error(`Could not safely read sync-folder marker data: ${message}`);
}

function asciiFold(value, context) {
  if (typeof value !== 'string' || !value || !/^[\x00-\x7f]+$/.test(value)) {
    throw markerDataError(`${context} must be a non-empty ASCII string`);
  }
  return value.toLowerCase();
}

function loadSyncFolderMarkers(dataPath = DATA_PATH) {
  let document;
  try {
    document = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
  } catch (error) {
    throw markerDataError(`${dataPath}: ${error.message}`);
  }
  if (
    !document
    || typeof document !== 'object'
    || Array.isArray(document)
    || Object.keys(document).sort().join(',') !== [
      'cloudstorage_provider_prefixes',
      'markers',
      'schema_version',
    ].join(',')
    || document.schema_version !== SCHEMA_VERSION
    || !Array.isArray(document.markers)
    || document.markers.length === 0
    || !Array.isArray(document.cloudstorage_provider_prefixes)
  ) {
    throw markerDataError(`${dataPath} has an unsupported schema or shape`);
  }

  const markers = document.markers.map((marker, index) => {
    if (
      !marker
      || typeof marker !== 'object'
      || Array.isArray(marker)
      || Object.keys(marker).sort().join(',') !== ['kind', 'provider', 'values'].join(',')
      || typeof marker.provider !== 'string'
      || !marker.provider
      || !MARKER_KINDS.has(marker.kind)
      || !Array.isArray(marker.values)
      || marker.values.length === 0
    ) {
      throw markerDataError(`${dataPath} marker ${index} is invalid`);
    }
    const values = marker.values.map((value, valueIndex) => (
      asciiFold(value, `marker ${index} value ${valueIndex}`)
    ));
    if (marker.kind === 'path-segment' && values.length !== 2) {
      throw markerDataError(`${dataPath} path-segment marker ${index} needs exactly two values`);
    }
    if (
      marker.kind === 'icloud-materialization'
      && (values.length !== 1 || values[0] !== '.icloud')
    ) {
      throw markerDataError(`${dataPath} iCloud marker ${index} is invalid`);
    }
    return Object.freeze({ provider: marker.provider, kind: marker.kind, values });
  });

  const cloudstorageProviderPrefixes = document.cloudstorage_provider_prefixes.map(
    (entry, index) => {
      if (
        !entry
        || typeof entry !== 'object'
        || Array.isArray(entry)
        || Object.keys(entry).sort().join(',') !== ['prefix', 'provider'].join(',')
        || typeof entry.provider !== 'string'
        || !entry.provider
      ) {
        throw markerDataError(`${dataPath} CloudStorage prefix ${index} is invalid`);
      }
      return Object.freeze({
        prefix: asciiFold(entry.prefix, `CloudStorage prefix ${index}`),
        provider: entry.provider,
      });
    },
  );
  return Object.freeze({
    markers: Object.freeze(markers),
    cloudstorageProviderPrefixes: Object.freeze(cloudstorageProviderPrefixes),
  });
}

const SYNC_FOLDER_MARKERS = loadSyncFolderMarkers();

function ancestors(candidate) {
  const result = [];
  let current = path.resolve(candidate);
  while (true) {
    result.push(current);
    const parent = path.dirname(current);
    if (parent === current) return result;
    current = parent;
  }
}

function childNames(directory) {
  try {
    return new Set(fs.readdirSync(directory).map((name) => name.toLowerCase()));
  } catch {
    return new Set();
  }
}

function absolutePathParts(candidate) {
  const absolute = path.resolve(candidate);
  const root = path.parse(absolute).root;
  const relative = path.relative(root, absolute);
  return [root, ...(relative ? relative.split(path.sep) : [])].map((part) => part.toLowerCase());
}

function cloudstorageProvider(foldedParts, sequence, providerPrefixes) {
  for (let index = 0; index < foldedParts.length; index += 1) {
    if (!sequence.every((value, offset) => foldedParts[index + offset] === value)) continue;
    const providerIndex = index + sequence.length;
    if (providerIndex >= foldedParts.length) return 'a cloud-synced folder';
    const providerDirectory = foldedParts[providerIndex];
    for (const { prefix, provider } of providerPrefixes) {
      if (providerDirectory.startsWith(prefix)) return provider;
    }
    return 'a cloud-synced folder';
  }
  return null;
}

function detectSyncFolder(candidate, markerData = SYNC_FOLDER_MARKERS) {
  const candidateAncestors = ancestors(candidate);
  // JavaScript has no exact equivalent of Python str.casefold(). The shared
  // marker values are therefore validated as ASCII, where toLowerCase() and
  // casefold() agree. Path names still use the platform's Unicode lowercase.
  const foldedParts = absolutePathParts(candidate);
  const namesByDirectory = new Map();

  for (const marker of markerData.markers) {
    if (marker.kind === 'path-segment') {
      const [exact, tenantPrefix] = marker.values;
      if (foldedParts.some((part) => part === exact || part.startsWith(tenantPrefix))) {
        return marker.provider;
      }
      continue;
    }
    if (marker.kind === 'cloudstorage-provider') {
      const provider = cloudstorageProvider(
        foldedParts,
        marker.values,
        markerData.cloudstorageProviderPrefixes,
      );
      if (provider !== null) return provider;
      continue;
    }

    for (const directory of candidateAncestors) {
      if (!namesByDirectory.has(directory)) {
        namesByDirectory.set(directory, childNames(directory));
      }
      const names = namesByDirectory.get(directory);
      if (marker.kind === 'child' && marker.values.some((value) => names.has(value))) {
        return marker.provider;
      }
      if (
        marker.kind === 'paired-children'
        && marker.values.every((value) => names.has(value))
      ) {
        return marker.provider;
      }
      if (
        marker.kind === 'icloud-materialization'
        && [...names].some((name) => name === '.icloud' || name.endsWith('.icloud'))
      ) {
        return marker.provider;
      }
    }
  }
  return null;
}

module.exports = {
  detectSyncFolder,
  loadSyncFolderMarkers,
};
