'use strict';

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

const CANONICAL_FIELDS = new Set([
  'type', 'name', 'role', 'company', 'company_page', 'emails', 'aliases',
  'location', 'last_interaction', 'domains', 'website', 'status',
]);
const V2_FIELDS = new Set(['dex_pinned', 'dex_last_written', 'last_touched', 'touches']);
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

function normaliseV2Field(key, value) {
  if (key === 'dex_pinned' || key === 'dex_last_written') {
    return value && !Array.isArray(value) && typeof value === 'object' ? { ...value } : null;
  }
  if (key === 'touches') return Array.isArray(value) ? [...value] : null;
  return normaliseScalar(value);
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
  const rawOriginal = fs.readFileSync(filePath, 'utf8');
  const bom = rawOriginal.charCodeAt(0) === 0xfeff ? '\ufeff' : '';
  const original = bom ? rawOriginal.slice(1) : rawOriginal;
  const split = splitFrontmatter(original);
  if (split.quarantined) return false;
  const merged = { ...(split.frontmatter || {}) };

  const hadPins = Boolean(merged.dex_pinned && !Array.isArray(merged.dex_pinned)
    && typeof merged.dex_pinned === 'object');
  const hadLastWritten = Boolean(merged.dex_last_written && !Array.isArray(merged.dex_last_written)
    && typeof merged.dex_last_written === 'object');
  const pinned = hadPins ? { ...merged.dex_pinned } : {};
  const lastWritten = hadLastWritten ? { ...merged.dex_last_written } : {};
  const ownershipEnabled = hadPins || hadLastWritten
    || Object.keys(fields).some(key => V2_FIELDS.has(key));

  const suppliedPins = normaliseV2Field('dex_pinned', fields.dex_pinned);
  if (suppliedPins) {
    for (const [key, value] of Object.entries(suppliedPins)) {
      if (CANONICAL_FIELDS.has(key) && normaliseScalar(value)) pinned[key] = value;
    }
  }
  const suppliedLastWritten = normaliseV2Field('dex_last_written', fields.dex_last_written);
  if (suppliedLastWritten) {
    for (const [key, candidate] of Object.entries(suppliedLastWritten)) {
      if (!CANONICAL_FIELDS.has(key)) continue;
      const value = normaliseField(key, candidate);
      if (value !== null || (candidate === null && !LIST_FIELDS.has(key))) lastWritten[key] = value;
    }
  }

  const legacy = legacyFields(split.body);
  const explicitCurrentValue = key => {
    const candidates = [];
    if (split.frontmatter && Object.hasOwn(split.frontmatter, key)) candidates.push(split.frontmatter[key]);
    if (Object.hasOwn(legacy.pipe, key)) candidates.push(legacy.pipe[key]);
    if (Object.hasOwn(legacy.inline, key)) candidates.push(legacy.inline[key]);
    for (const candidate of candidates) {
      const value = normaliseField(key, candidate);
      if (value !== null || (candidate === null && !LIST_FIELDS.has(key))) return value;
    }
    return LIST_FIELDS.has(key) ? [] : null;
  };
  const effectiveCurrent = {};
  for (const key of CANONICAL_FIELDS) effectiveCurrent[key] = explicitCurrentValue(key);
  effectiveCurrent.type = inferType(filePath, effectiveCurrent);
  if (effectiveCurrent.type && !effectiveCurrent.name) {
    const heading = /^#\s+(.+?)\s*$/m.exec(split.body);
    effectiveCurrent.name = heading
      ? heading[1].trim()
      : path.basename(filePath, path.extname(filePath)).replace(/_/g, ' ');
  }
  const currentValue = key => effectiveCurrent[key];
  const hasNonemptyRawValue = key => {
    const candidates = [];
    if (split.frontmatter && Object.hasOwn(split.frontmatter, key)) candidates.push(split.frontmatter[key]);
    if (Object.hasOwn(legacy.pipe, key)) candidates.push(legacy.pipe[key]);
    if (Object.hasOwn(legacy.inline, key)) candidates.push(legacy.inline[key]);
    for (const candidate of candidates) {
      if (candidate === null || candidate === undefined) continue;
      if (typeof candidate === 'string' && !candidate.trim()) continue;
      if (Array.isArray(candidate) && candidate.length === 0) continue;
      if (!Array.isArray(candidate) && typeof candidate === 'object'
        && Object.keys(candidate).length === 0) continue;
      return true;
    }
    return false;
  };
  const implicitBootstrap = ownershipEnabled && !hadPins && !hadLastWritten
    && suppliedLastWritten === null;
  if (implicitBootstrap) {
    for (const key of CANONICAL_FIELDS) {
      if (hasNonemptyRawValue(key) && !Object.hasOwn(pinned, key)) pinned[key] = 'user';
    }
  }
  for (const [key, previous] of Object.entries(lastWritten)) {
    if (!CANONICAL_FIELDS.has(key) || Object.hasOwn(pinned, key)) continue;
    const normalisedPrevious = normaliseField(key, previous);
    if (normalisedPrevious === null && !(previous === null && !LIST_FIELDS.has(key))) continue;
    if (JSON.stringify(currentValue(key)) !== JSON.stringify(normalisedPrevious)) pinned[key] = 'user';
  }

  for (const [key, candidate] of Object.entries(fields)) {
    if (!CANONICAL_FIELDS.has(key) || Object.hasOwn(pinned, key)) continue;
    if (candidate === null && !LIST_FIELDS.has(key)) {
      merged[key] = null;
      if (ownershipEnabled) lastWritten[key] = null;
      continue;
    }
    const value = normaliseField(key, candidate);
    if (value !== null) {
      merged[key] = value;
      if (ownershipEnabled) lastWritten[key] = value;
    }
  }
  for (const key of ['last_touched', 'touches']) {
    if (!Object.hasOwn(fields, key)) continue;
    const value = normaliseV2Field(key, fields[key]);
    if (value !== null) merged[key] = value;
  }
  if (ownershipEnabled) {
    merged.dex_pinned = pinned;
    merged.dex_last_written = lastWritten;
  }
  const dumped = yaml.dump(merged, {
    noRefs: true, noCompatMode: true, noArrayIndent: true, lineWidth: -1, sortKeys: false,
  }).trimEnd();
  const updated = `${bom}---\n${dumped}\n---\n${split.body}`;
  if (updated === rawOriginal) return false;
  atomicWrite(filePath, updated);
  return true;
}

const quoted = value => JSON.stringify(value);
function stringList(values, lowercase = false) {
  return `[${(normaliseList(values || [], lowercase) || []).map(quoted).join(', ')}]`;
}

function renderPersonPage(name, role = null, company = null, emails = null, aliases = null, location = 'unknown', notes = null) {
  if (!['internal', 'external', 'unknown'].includes(location)) location = 'unknown';
  const cleanEmails = stringList(emails, true);
  const cleanAliases = stringList(aliases);
  const lines = [
    '---', 'type: person', `name: ${quoted(name)}`, `role: ${role ? quoted(role) : 'null'}`,
    `company: ${company ? quoted(company) : 'null'}`, 'company_page: null',
    `emails: ${cleanEmails}`, `aliases: ${cleanAliases}`,
    `location: ${location}`, 'last_interaction: null', 'dex_pinned: {}', 'dex_last_written:',
    '  type: person', `  name: ${quoted(name)}`, `  role: ${role ? quoted(role) : 'null'}`,
    `  company: ${company ? quoted(company) : 'null'}`, '  company_page: null',
    `  emails: ${cleanEmails}`, `  aliases: ${cleanAliases}`, `  location: ${location}`,
    '  last_interaction: null', '---', `# ${name}`, '', '## Notes', '',
  ];
  if (notes) lines.push(notes, '');
  lines.push('## Recent Interactions', '', '<!-- dex:auto:recent-interactions -->',
    '<!-- /dex:auto -->', '', '## Key Context', '', '## Relationships', '',
    '<!-- dex:auto:relationships -->', '<!-- /dex:auto -->', '', '## Update Log', '',
    '<!-- dex:auto:update-log -->', '<!-- /dex:auto -->',
  );
  return lines.join('\n') + '\n';
}

function renderCompanyPage(name, domains = null, website = null, status = 'Prospect') {
  const cleanDomains = stringList(domains, true);
  return [
    '---', 'type: company', `name: ${quoted(name)}`, `domains: ${cleanDomains}`,
    `website: ${website ? quoted(website) : 'null'}`, `status: ${quoted(status)}`,
    'dex_pinned: {}', 'dex_last_written:', '  type: company', `  name: ${quoted(name)}`,
    `  domains: ${cleanDomains}`, `  website: ${website ? quoted(website) : 'null'}`,
    `  status: ${quoted(status)}`, '---', `# ${name}`, '',
    '## Key Contacts', '', '<!-- dex:auto:key-contacts -->', '<!-- /dex:auto -->', '',
    '## Meeting History', '', '<!-- dex:auto:meeting-history -->', '<!-- /dex:auto -->', '',
    '## Notes', '', '## Relationships', '', '<!-- dex:auto:relationships -->',
    '<!-- /dex:auto -->', '', '## Update Log', '', '<!-- dex:auto:update-log -->',
    '<!-- /dex:auto -->', '',
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
