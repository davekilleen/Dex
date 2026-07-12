'use strict';

const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', '..', '..', 'core', 'data');
const FREEMAIL_DOMAINS = new Set(JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'freemail_domains.json'), 'utf8')));
const MULTI_PART_TLDS = new Set(JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'multi_part_tlds.json'), 'utf8')));

function normalise(domain) {
  return String(domain || '').trim().toLowerCase().replace(/^@+/, '').replace(/\.+$/, '');
}

function registrableDomain(domain) {
  const labels = normalise(domain).split('.').filter(Boolean);
  if (labels.length < 2) return labels.join('.');
  const suffix = labels.slice(-2).join('.');
  return MULTI_PART_TLDS.has(suffix) && labels.length >= 3
    ? labels.slice(-3).join('.')
    : suffix;
}

function isFreemail(domain) {
  return FREEMAIL_DOMAINS.has(registrableDomain(domain));
}

function companyNameFromDomain(domain) {
  const label = registrableDomain(domain).split('.', 1)[0] || '';
  return label.replace(/_/g, '-').split('-').filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase()).join(' ');
}

module.exports = { companyNameFromDomain, isFreemail, registrableDomain };
