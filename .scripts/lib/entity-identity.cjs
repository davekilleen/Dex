'use strict';

const fs = require('node:fs');
const path = require('node:path');

const { registrableDomain } = require('../meeting-intel/lib/company-domains.cjs');
const { parseEntityPage } = require('./entity-pages.cjs');
const { loadPaths } = require('../../.claude/hooks/paths.cjs');

// Vault-relative PARA segments derived from the canonical path constants, so the
// path-contract gate is satisfied while resolveEntityPath still honours a runtime root.
const _paths = loadPaths();
const PEOPLE_REL = path.relative(_paths.VAULT_ROOT, _paths.PEOPLE_DIR);
const COMPANIES_REL = path.relative(_paths.VAULT_ROOT, _paths.COMPANIES_DIR);

function markdownFiles(directory) {
  if (!fs.existsSync(directory)) return [];
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const filePath = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...markdownFiles(filePath));
    else if (entry.isFile() && entry.name.endsWith('.md')
        && entry.name.toLowerCase() !== 'readme.md') {
      files.push(filePath);
    }
  }
  return files;
}

function normalizedName(value) {
  return String(value || '').trim().toLocaleLowerCase();
}

function normalizedEmails(values) {
  return new Set(
    (Array.isArray(values) ? values : [])
      .map(value => String(value || '').trim().toLowerCase())
      .filter(Boolean),
  );
}

function normalizedDomains(values) {
  return new Set(
    (Array.isArray(values) ? values : [])
      .map(registrableDomain)
      .filter(Boolean),
  );
}

function identityForEntity(entity) {
  if (!entity || !['person', 'company'].includes(entity.type)) return null;
  if (entity.type === 'person') {
    return {
      kind: 'person',
      name: entity.name || null,
      emails: [...normalizedEmails(entity.emails)],
    };
  }
  return {
    kind: 'company',
    name: entity.name || null,
    domains: [...normalizedDomains(entity.domains)],
  };
}

function identityForPage(filePath) {
  return identityForEntity(parseEntityPage(filePath));
}

function resolveEntityPath(vaultRoot, identity) {
  if (!identity || !['person', 'company'].includes(identity.kind)) return null;
  const root = path.resolve(vaultRoot);
  const directory = identity.kind === 'person'
    ? path.join(root, PEOPLE_REL)
    : path.join(root, COMPANIES_REL);
  const wantedEmails = normalizedEmails(identity.emails);
  const wantedDomains = normalizedDomains(identity.domains);
  const wantedName = normalizedName(identity.name);
  const strongMatches = [];
  const nameMatches = [];

  for (const filePath of markdownFiles(directory)) {
    let entity;
    try {
      entity = parseEntityPage(filePath);
    } catch (_) {
      continue;
    }
    if (entity.quarantined || entity.type !== identity.kind) continue;
    if (identity.kind === 'person' && wantedEmails.size > 0) {
      const pageEmails = normalizedEmails(entity.emails);
      if ([...wantedEmails].some(email => pageEmails.has(email))) {
        strongMatches.push(filePath);
        continue;
      }
    }
    if (identity.kind === 'company' && wantedDomains.size > 0) {
      const pageDomains = normalizedDomains(entity.domains);
      if ([...wantedDomains].some(domain => pageDomains.has(domain))) {
        strongMatches.push(filePath);
        continue;
      }
    }
    if (wantedName && normalizedName(entity.name) === wantedName) {
      nameMatches.push(filePath);
    }
  }

  if (strongMatches.length === 1) return strongMatches[0];
  if (strongMatches.length > 1) return null;
  if (identity.kind === 'person' && wantedEmails.size > 0) return null;
  if (identity.kind === 'company' && wantedDomains.size > 0) return null;
  return nameMatches.length === 1 ? nameMatches[0] : null;
}

module.exports = {
  identityForEntity,
  identityForPage,
  markdownFiles,
  resolveEntityPath,
};
