#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const { contactIdFor, deriveStats, loadState, runtimePaths } = require('./lib/contacts-state.cjs');
const { creationMode, loadSuggestions } = require('./lib/entity-creation.cjs');

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

function plural(count, singular, pluralForm = `${singular}s`) {
  return count === 1 ? singular : pluralForm;
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
  return `entities: ${report.attendees} attendees -> ${parts.join(', ')}; ${report.unresolved.length} unresolved`;
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
    }
  }

  const counts = Object.fromEntries(OUTCOMES.map(outcome => [outcome, 0]));
  const unresolved = [];
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
    unresolved,
  };
  Object.defineProperty(report, 'attendees', { value: identities.size, enumerable: false });
  fs.mkdirSync(path.dirname(paths.ENTITY_VERIFICATION_FILE), { recursive: true });
  const tempPath = path.join(
    path.dirname(paths.ENTITY_VERIFICATION_FILE),
    `.${path.basename(paths.ENTITY_VERIFICATION_FILE)}.${process.pid}.${Date.now()}.tmp`,
  );
  fs.writeFileSync(tempPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  fs.renameSync(tempPath, paths.ENTITY_VERIFICATION_FILE);
  return { report, summary: summaryLine(report) };
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
