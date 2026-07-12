'use strict';

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

const CANONICAL_FIELDS = new Set([
  'type', 'name', 'role', 'company', 'company_page', 'emails', 'aliases',
  'location', 'last_interaction', 'domains', 'website', 'status',
]);
const LIST_FIELDS = new Set(['emails', 'aliases', 'domains']);
const LABELS = {
  type: 'type', name: 'name', role: 'role', company: 'company',
  'company page': 'company_page', email: 'emails', emails: 'emails', aliases: 'aliases',
  location: 'location', 'last interaction': 'last_interaction',
  'last interaction date': 'last_interaction', website: 'website', domain: 'domains',
  domains: 'domains', status: 'status', stage: 'status',
};

function emptyResult() {
  return {
    type: null, name: null, role: null, company: null, company_page: null,
    emails: [], aliases: [], location: null, last_interaction: null,
    domains: [], website: null, status: null, quarantined: false, source_formats: [],
  };
}

function normaliseScalar(value) {
  if (value instanceof Date && !Number.isNaN(value.valueOf())) return value.toISOString().slice(0, 10);
  if (value === null || value === undefined || Array.isArray(value) || typeof value === 'object') return null;
  const text = String(value).trim();
  return text || null;
}

function normaliseList(value, lowercase = false) {
  if (value === null || value === undefined) return null;
  const values = Array.isArray(value) ? value : String(value).split(',');
  return values.map(normaliseScalar).filter(Boolean).map(item => lowercase ? item.toLowerCase() : item);
}

function normaliseField(key, value) {
  if (LIST_FIELDS.has(key)) return normaliseList(value, key === 'emails' || key === 'domains');
  value = normaliseScalar(value);
  if (key === 'type') return value === 'person' || value === 'company' ? value : null;
  if (key === 'location') return ['internal', 'external', 'unknown'].includes(value) ? value : null;
  if (key === 'last_interaction' && value && !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  return value;
}

function splitFrontmatter(text) {
  if (!text.startsWith('---')) return { frontmatter: null, body: text, had: false, quarantined: false };
  const match = /^---[ \t]*\r?\n([\s\S]*?)^---[ \t]*\r?$(?:\r?\n)?/m.exec(text);
  if (!match || match.index !== 0) {
    const newline = text.indexOf('\n');
    return { frontmatter: null, body: newline >= 0 ? text.slice(newline + 1) : '', had: true, quarantined: true };
  }
  try {
    const loaded = yaml.load(match[1]) ?? {};
    if (!loaded || Array.isArray(loaded) || typeof loaded !== 'object') throw new Error('frontmatter must be a mapping');
    return { frontmatter: loaded, body: text.slice(match[0].length), had: true, quarantined: false };
  } catch (_) {
    return { frontmatter: null, body: text.slice(match[0].length), had: true, quarantined: true };
  }
}

function legacyFields(body) {
  const pipe = {};
  const inline = {};
  const formats = [];
  for (const line of body.split(/\r?\n/)) {
    let match = /^\s*\|\s*(?:\*\*)?([^|*]+?)(?:\*\*)?\s*\|\s*(.*?)\s*\|\s*$/.exec(line);
    if (match) {
      const key = LABELS[match[1].replace(/\s+/g, ' ').trim().toLowerCase().replace(/:$/, '')];
      if (key && match[2].trim() && !(key in pipe)) {
        pipe[key] = match[2].trim();
        if (!formats.includes('pipe_table')) formats.push('pipe_table');
      }
      continue;
    }
    match = /^\s*\*\*([^*:\n]+):\*\*\s*(.*?)\s*$/.exec(line);
    if (match) {
      const key = LABELS[match[1].replace(/\s+/g, ' ').trim().toLowerCase()];
      if (key && match[2].trim() && !(key in inline)) {
        inline[key] = match[2].trim();
        if (!formats.includes('inline_bold')) formats.push('inline_bold');
      }
    }
  }
  return { pipe, inline, formats };
}

function inferType(filePath, values) {
  if (values.type === 'person' || values.type === 'company') return values.type;
  const parts = filePath.split(path.sep).map(part => part.toLowerCase());
  if (parts.includes('people')) return 'person';
  if (parts.includes('companies')) return 'company';
  if (['role', 'company', 'company_page', 'emails', 'last_interaction'].some(key => values[key] && values[key].length !== 0)) return 'person';
  if (['domains', 'website', 'status'].some(key => values[key] && values[key].length !== 0)) return 'company';
  return null;
}

function parseEntityPage(filePath) {
  let text = fs.readFileSync(filePath, 'utf8');
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const split = splitFrontmatter(text);
  const legacy = legacyFields(split.body);
  const result = emptyResult();
  result.quarantined = split.quarantined;
  if (split.had) result.source_formats.push('frontmatter');
  result.source_formats.push(...legacy.formats);
  for (const key of CANONICAL_FIELDS) {
    const candidates = [];
    if (split.frontmatter && Object.hasOwn(split.frontmatter, key)) candidates.push(split.frontmatter[key]);
    if (Object.hasOwn(legacy.pipe, key)) candidates.push(legacy.pipe[key]);
    if (Object.hasOwn(legacy.inline, key)) candidates.push(legacy.inline[key]);
    for (const candidate of candidates) {
      const value = normaliseField(key, candidate);
      if (value !== null) { result[key] = value; break; }
    }
  }
  result.type = inferType(filePath, result);
  if (result.type && !result.name) {
    const heading = /^#\s+(.+?)\s*$/m.exec(split.body);
    result.name = heading ? heading[1].trim() : path.basename(filePath, path.extname(filePath)).replace(/_/g, ' ');
  }
  return result;
}

function atomicWrite(filePath, text) {
  const temp = path.join(path.dirname(filePath), `.${path.basename(filePath)}.${process.pid}.${Date.now()}.tmp`);
  const existingMode = fs.existsSync(filePath) ? fs.statSync(filePath).mode : null;
  try {
    fs.writeFileSync(temp, text, 'utf8');
    if (existingMode !== null) fs.chmodSync(temp, existingMode);
    fs.renameSync(temp, filePath);
  } catch (error) {
    try { fs.unlinkSync(temp); } catch (_) { /* already absent */ }
    throw error;
  }
}

function upsertFrontmatter(filePath, fields) {
  let original = fs.readFileSync(filePath, 'utf8');
  if (original.charCodeAt(0) === 0xfeff) original = original.slice(1);
  const split = splitFrontmatter(original);
  if (split.quarantined) return false;
  const merged = { ...(split.frontmatter || {}) };
  for (const [key, candidate] of Object.entries(fields)) {
    if (!CANONICAL_FIELDS.has(key)) continue;
    if (candidate === null && !LIST_FIELDS.has(key)) { merged[key] = null; continue; }
    const value = normaliseField(key, candidate);
    if (value !== null) merged[key] = value;
  }
  const dumped = yaml.dump(merged, { noRefs: true, noCompatMode: true, lineWidth: -1, sortKeys: false }).trimEnd();
  const updated = `---\n${dumped}\n---\n${split.body}`;
  if (updated === original) return false;
  atomicWrite(filePath, updated);
  return true;
}

const quoted = value => JSON.stringify(value);
function stringList(values, lowercase = false) {
  return `[${(normaliseList(values || [], lowercase) || []).map(quoted).join(', ')}]`;
}

function renderPersonPage(name, role = null, company = null, emails = null, aliases = null, location = 'unknown', notes = null) {
  if (!['internal', 'external', 'unknown'].includes(location)) location = 'unknown';
  const lines = [
    '---', 'type: person', `name: ${quoted(name)}`, `role: ${role ? quoted(role) : 'null'}`,
    `company: ${company ? quoted(company) : 'null'}`, 'company_page: null',
    `emails: ${stringList(emails, true)}`, `aliases: ${stringList(aliases)}`,
    `location: ${location}`, 'last_interaction: null', '---', `# ${name}`, '', '## Notes', '',
  ];
  if (notes) lines.push(notes, '');
  lines.push('## Recent Interactions', '', '<!-- dex:auto:recent-interactions -->',
    '<!-- /dex:auto -->', '', '## Key Context', '',
  );
  return lines.join('\n') + '\n';
}

function renderCompanyPage(name, domains = null, website = null, status = 'Prospect') {
  return [
    '---', 'type: company', `name: ${quoted(name)}`, `domains: ${stringList(domains, true)}`,
    `website: ${website ? quoted(website) : 'null'}`, `status: ${quoted(status)}`, '---', `# ${name}`, '',
    '## Key Contacts', '', '<!-- dex:auto:key-contacts -->', '<!-- /dex:auto -->', '',
    '## Meeting History', '', '<!-- dex:auto:meeting-history -->', '<!-- /dex:auto -->', '',
    '## Notes', '', '',
  ].join('\n');
}

function replaceMachineRegion(text, slug, newContent) {
  const start = `<!-- dex:auto:${slug} -->`;
  const end = '<!-- /dex:auto -->';
  const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`${escape(start)}[\\s\\S]*?${escape(end)}`);
  if (!pattern.test(text)) throw new Error(`machine region not found: ${slug}`);
  const content = newContent.replace(/^[\r\n]+|[\r\n]+$/g, '');
  return text.replace(pattern, content ? `${start}\n${content}\n${end}` : `${start}\n${end}`);
}

function replaceMachineRegionInFile(filePath, slug, newContent) {
  const original = fs.readFileSync(filePath, 'utf8');
  const updated = replaceMachineRegion(original, slug, newContent);
  if (updated === original) return false;
  atomicWrite(filePath, updated);
  return true;
}

module.exports = {
  atomicWrite,
  parseEntityPage, upsertFrontmatter, renderPersonPage, renderCompanyPage,
  replaceMachineRegion, replaceMachineRegionInFile,
};
