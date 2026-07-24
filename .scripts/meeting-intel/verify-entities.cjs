#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const { contactIdFor, deriveStats, loadState, runtimePaths } = require('./lib/contacts-state.cjs');
const { creationMode, loadSuggestions } = require('./lib/entity-creation.cjs');
const { getInternalDomains } = require('./lib/attendees.cjs');
const { isFreemail, registrableDomain } = require('./lib/company-domains.cjs');
const { parseEntityPage } = require('../lib/entity-pages.cjs');

const OUTCOMES = [
  'page', 'suggested', 'dismissed', 'suppressed', 'tracking',
  'unverified_identity', 'disabled',
];

function walkMarkdown(directory) {
  if (!fs.existsSync(directory)) return [];
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const filePath = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walkMarkdown(filePath));
    else if (entry.isFile() && entry.name.endsWith('.md')) files.push(filePath);
  }
  return files;
}

function frontmatter(filePath) {
  const text = fs.readFileSync(filePath, 'utf8');
  const match = /^---[ \t]*\r?\n([\s\S]*?)^---[ \t]*$/m.exec(text);
  if (!match || match.index !== 0) return null;
  try {
    const value = yaml.load(match[1]);
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  } catch (_) {
    return null;
  }
}

function readProfile(profilePath) {
  try {
    return yaml.load(fs.readFileSync(profilePath, 'utf8')) || {};
  } catch (_) {
    return {};
  }
}

function attendeeKey(attendee) {
  const email = typeof attendee.email === 'string' && attendee.email.trim()
    ? attendee.email.trim().toLowerCase()
    : null;
  return email ? `email:${email}` : `name:${String(attendee.name || '').trim().toLowerCase()}`;
}

function pageExists(contact, attendee, paths) {
  if (contact?.page_path) {
    const candidate = path.isAbsolute(contact.page_path)
      ? contact.page_path
      : path.join(paths.VAULT_ROOT, contact.page_path);
    if (fs.existsSync(candidate)) return true;
  }
  const filename = `${String(attendee.name || '').trim().replace(/\s+/g, '_')}.md`;
  return ['Internal', 'External'].some(folder => fs.existsSync(path.join(paths.PEOPLE_DIR, folder, filename)));
}

function companyPage(domain, paths) {
  for (const filePath of walkMarkdown(paths.COMPANIES_DIR)) {
    if (path.basename(filePath) === 'README.md') continue;
    try {
      if (parseEntityPage(filePath).domains.map(registrableDomain).includes(domain)) {
        return path.relative(paths.VAULT_ROOT, filePath).split(path.sep).join('/');
      }
    } catch (_) { /* malformed pages cannot resolve a domain */ }
  }
  return null;
}

function plural(count, singular, pluralForm = `${singular}s`) {
  return count === 1 ? singular : pluralForm;
}

function readDeadLetters(paths) {
  const filePath = path.join(
    path.dirname(paths.ENTITY_PENDING_FILE),
    'entity-dead-letter.jsonl',
  );
  try {
    const entries = fs.readFileSync(filePath, 'utf8')
      .split(/\r?\n/)
      .filter(line => line.trim())
      .flatMap((line) => {
        try {
          return [JSON.parse(line)];
        } catch (_) {
          return [];
        }
      });
    return { entries, error: null };
  } catch (error) {
    if (error.code === 'ENOENT') return { entries: [], error: null };
    return { entries: [], error };
  }
}

function summaryLine(report) {
  const counts = report.counts;
  const parts = [];
  if (counts.page) parts.push(`${counts.page} ${plural(counts.page, 'page')}`);
  if (counts.suggested) parts.push(`${counts.suggested} suggested`);
  if (counts.dismissed) parts.push(`${counts.dismissed} dismissed`);
  if (counts.suppressed) parts.push(`${counts.suppressed} suppressed`);
  if (counts.tracking) parts.push(`${counts.tracking} tracking`);
  if (counts.unverified_identity) parts.push(`${counts.unverified_identity} no-email`);
  if (counts.disabled) parts.push(`${counts.disabled} disabled`);
  if (parts.length === 0) parts.push('0 pages');
  const companyParts = [];
  const companyCounts = report.companies?.counts || {};
  if (companyCounts.page) companyParts.push(`${companyCounts.page} ${plural(companyCounts.page, 'page')}`);
  if (companyCounts.suggested) companyParts.push(`${companyCounts.suggested} suggested`);
  if (companyCounts.tracking) companyParts.push(`${companyCounts.tracking} tracking`);
  if (companyCounts.disabled) companyParts.push(`${companyCounts.disabled} disabled`);
  if (companyParts.length === 0) companyParts.push('0 pages');
  const deadLetter = report.dead_letter_count
    ? `; ${report.dead_letter_count} ${plural(
      report.dead_letter_count,
      'entity write',
    )} failed permanently`
    : '';
  return `entities: ${report.attendees} attendees -> ${parts.join(', ')}; ${report.unresolved.length} unresolved; companies: ${companyParts.join(', ')}${deadLetter}`;
}

function verifyEntities({ days = 7, now = new Date() } = {}) {
  const paths = runtimePaths();
  const numericDays = Number.isFinite(Number(days)) && Number(days) >= 0 ? Number(days) : 7;
  const cutoff = new Date(now);
  cutoff.setUTCHours(0, 0, 0, 0);
  cutoff.setUTCDate(cutoff.getUTCDate() - numericDays);
  const profile = readProfile(paths.USER_PROFILE_FILE);
  const mode = creationMode(profile);
  const state = loadState(paths.CONTACTS_STATE_FILE);
  const suggestions = new Map(
    loadSuggestions(paths.ENTITY_SUGGESTIONS_FILE).suggestions.map(item => [item.id, item]),
  );
  const identities = new Map();
  const windowDomains = new Map();
  const internalDomains = new Set(Array.from(getInternalDomains(profile), registrableDomain));
  const deadLetters = readDeadLetters(paths);

  for (const filePath of walkMarkdown(paths.MEETINGS_DIR)) {
    const data = frontmatter(filePath);
    if (!data || !Array.isArray(data.attendees)) continue;
    const noteDate = new Date(`${String(data.date || '').slice(0, 10)}T00:00:00Z`);
    if (Number.isNaN(noteDate.getTime()) || noteDate < cutoff || noteDate > now) continue;
    for (const attendee of data.attendees) {
      if (!attendee || !attendee.name) continue;
      const key = attendeeKey(attendee);
      const existing = identities.get(key);
      if (existing) existing.meetings += 1;
      else identities.set(key, {
        name: String(attendee.name).trim(),
        email: typeof attendee.email === 'string' && attendee.email.trim()
          ? attendee.email.trim().toLowerCase()
          : null,
        location: attendee.location || 'unknown',
        meetings: 1,
      });
      const rawDomain = typeof attendee.email === 'string' && attendee.email.includes('@')
        ? attendee.email.trim().toLowerCase().split('@', 2)[1]
        : null;
      const domain = registrableDomain(rawDomain);
      if (domain && !isFreemail(domain) && !internalDomains.has(domain)
          && attendee.location !== 'internal') {
        if (!windowDomains.has(domain)) windowDomains.set(domain, { contacts: new Set(), meetings: new Set() });
        windowDomains.get(domain).contacts.add(key);
        windowDomains.get(domain).meetings.add(filePath);
      }
    }
  }

  const counts = Object.fromEntries(OUTCOMES.map(outcome => [outcome, 0]));
  const unresolved = [];
  const companyCounts = { page: 0, suggested: 0, tracking: 0, disabled: 0 };
  const companyDomains = [];
  for (const [domain, windowStats] of windowDomains) {
    const page = companyPage(domain, paths);
    const suggestion = suggestions.get(`domain:${domain}`);
    let outcome;
    if (page) outcome = 'page';
    else if (mode === 'off') outcome = 'disabled';
    else if (suggestion?.status === 'suggested') outcome = 'suggested';
    else outcome = 'tracking';
    companyCounts[outcome] += 1;

    const observationIds = new Set();
    const contactIds = new Set();
    for (const [meetingId, observation] of Object.entries(state.observations || {})) {
      for (const contactId of observation.contact_ids || []) {
        const contact = state.contacts[contactId];
        if (contact?.location !== 'unknown' && registrableDomain(contact?.domain) === domain) {
          observationIds.add(meetingId);
          contactIds.add(contactId);
        }
      }
    }
    const entry = {
      domain,
      outcome,
      contacts: contactIds.size || windowStats.contacts.size,
      meetings: observationIds.size || windowStats.meetings.size,
    };
    if (page) entry.path = page;
    companyDomains.push(entry);
    if (mode === 'auto' && observationIds.size >= 2 && !page && !suggestion) {
      unresolved.push({
        kind: 'company',
        domain,
        meetings: observationIds.size,
        why: 'qualified company domain has no company page or suggestion',
      });
    }
  }

  for (const attendee of identities.values()) {
    const id = attendee.email
      ? state.email_index[attendee.email] || contactIdFor(attendee)
      : contactIdFor(attendee);
    const contact = state.contacts[id];
    const suggestion = suggestions.get(id);
    let outcome;
    if (pageExists(contact, attendee, paths)) outcome = 'page';
    else if (!attendee.email) outcome = 'unverified_identity';
    else if (mode === 'off') outcome = 'disabled';
    else if (['suggested', 'dismissed', 'suppressed'].includes(suggestion?.status)) outcome = suggestion.status;
    else outcome = 'tracking';
    counts[outcome] += 1;

    const stats = contact ? deriveStats(state, id) : {
      tracked_meetings: attendee.meetings,
      distinct_weeks: 0,
      has_transcript: false,
    };
    const qualified = contact && contact.emails?.length > 0
      && stats.tracked_meetings >= 2
      && (stats.distinct_weeks >= 2 || stats.has_transcript);
    const routable = ['internal', 'external'].includes(contact?.location || attendee.location);
    if (mode === 'auto' && qualified && routable && outcome !== 'page') {
      unresolved.push({
        name: attendee.name,
        email: attendee.email,
        meetings: attendee.meetings,
        why: `qualified ${contact.location} contact has no person page`,
      });
    } else if (!attendee.email && attendee.meetings >= 2) {
      unresolved.push({
        name: attendee.name,
        email: null,
        meetings: attendee.meetings,
        why: 'identity has no email',
      });
    }
  }

  const report = {
    generated_at: now.toISOString(),
    window_days: numericDays,
    mode,
    counts,
    companies: { counts: companyCounts, domains: companyDomains },
    unresolved,
    dead_letter_count: deadLetters.entries.length,
  };
  Object.defineProperty(report, 'attendees', { value: identities.size, enumerable: false });
  fs.mkdirSync(path.dirname(paths.ENTITY_VERIFICATION_FILE), { recursive: true });
  const tempPath = path.join(
    path.dirname(paths.ENTITY_VERIFICATION_FILE),
    `.${path.basename(paths.ENTITY_VERIFICATION_FILE)}.${process.pid}.${Date.now()}.tmp`,
  );
  fs.writeFileSync(tempPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  fs.renameSync(tempPath, paths.ENTITY_VERIFICATION_FILE);
  const summary = summaryLine(report);
  if (deadLetters.error) {
    return {
      success: false,
      feature: 'Entity engine',
      feature_status: 'unknown',
      user_message: 'Entity write failures could not be checked. Run /dex-doctor and '
        + 'inspect System/.dex/entity-dead-letter.jsonl.',
      detail: deadLetters.error.message,
      report,
      summary,
    };
  }
  if (deadLetters.entries.length > 0) {
    const count = deadLetters.entries.length;
    return {
      success: false,
      feature: 'Entity engine',
      feature_status: 'broken',
      user_message: `${count} ${plural(count, 'entity write')} failed permanently. `
        + 'Run /dex-doctor to re-queue the failed write with fresh retries; '
        + 'details remain in System/.dex/entity-dead-letter.jsonl until then.',
      report,
      summary,
    };
  }
  return {
    success: true,
    feature: 'Entity engine',
    feature_status: 'ok',
    user_message: 'Entity verification completed with no dead-lettered writes.',
    report,
    summary,
  };
}

function parseDays(argv) {
  const index = argv.indexOf('--days');
  if (index === -1) return 7;
  const days = Number(argv[index + 1]);
  if (!Number.isInteger(days) || days < 0) throw new Error('--days requires a non-negative integer');
  return days;
}

if (require.main === module) {
  try {
    const result = verifyEntities({ days: parseDays(process.argv.slice(2)) });
    console.log(result.summary);
  } catch (error) {
    console.error(`entities: verification failed: ${error.message}`);
    process.exitCode = 1;
  }
}

module.exports = { frontmatter, parseDays, summaryLine, verifyEntities };
