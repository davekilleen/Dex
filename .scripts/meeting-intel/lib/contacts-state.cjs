'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { loadPaths } = require('../../../.claude/hooks/paths.cjs');

const LOCK_RETRIES = 5;
const LOCK_DELAY_MS = 50;
const LOCK_STALE_MS = 30_000;

function emptyState() {
  return { version: 1, contacts: {}, email_index: {}, observations: {} };
}

function normalizeEmail(value) {
  return typeof value === 'string' && value.trim() ? value.trim().toLowerCase() : null;
}

function normalizeName(value) {
  return typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : '';
}

function contactIdFor(attendee) {
  const email = normalizeEmail(attendee && attendee.email);
  if (email) return crypto.createHash('sha1').update(email).digest('hex');
  return `name:${normalizeName(attendee && attendee.name).toLowerCase()}`;
}

function statePath() {
  return runtimePaths().CONTACTS_STATE_FILE;
}

function runtimePaths() {
  const configured = loadPaths();
  const overrideRoot = process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH;
  if (!overrideRoot || path.resolve(overrideRoot) === path.resolve(configured.VAULT_ROOT)) return configured;
  const remapped = {};
  for (const [key, value] of Object.entries(configured)) {
    remapped[key] = typeof value === 'string' && path.isAbsolute(value)
      ? path.join(path.resolve(overrideRoot), path.relative(configured.VAULT_ROOT, value))
      : value;
  }
  remapped.VAULT_ROOT = path.resolve(overrideRoot);
  return remapped;
}

function normalizeState(candidate) {
  const state = candidate && typeof candidate === 'object' ? candidate : {};
  return {
    version: 1,
    contacts: state.contacts && typeof state.contacts === 'object' ? state.contacts : {},
    email_index: state.email_index && typeof state.email_index === 'object' ? state.email_index : {},
    observations: state.observations && typeof state.observations === 'object' ? state.observations : {},
  };
}

function loadState(filePath = statePath()) {
  try {
    return normalizeState(JSON.parse(fs.readFileSync(filePath, 'utf8')));
  } catch (error) {
    if (error.code === 'ENOENT' || error instanceof SyntaxError) return emptyState();
    throw error;
  }
}

function atomicWrite(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tempPath = path.join(
    path.dirname(filePath),
    `.${path.basename(filePath)}.${process.pid}.${Date.now()}.tmp`,
  );
  try {
    fs.writeFileSync(tempPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
    fs.renameSync(tempPath, filePath);
  } catch (error) {
    try { fs.unlinkSync(tempPath); } catch (_) { /* absent */ }
    throw error;
  }
}

function wait(milliseconds) {
  const buffer = new SharedArrayBuffer(4);
  Atomics.wait(new Int32Array(buffer), 0, 0, milliseconds);
}

function withLock(filePath, callback) {
  const lockPath = `${filePath}.lock`;
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  let handle;
  for (let attempt = 0; attempt <= LOCK_RETRIES; attempt += 1) {
    try {
      handle = fs.openSync(lockPath, 'wx');
      fs.writeFileSync(handle, `${process.pid}\n${new Date().toISOString()}\n`);
      break;
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      try {
        if (Date.now() - fs.statSync(lockPath).mtimeMs > LOCK_STALE_MS) {
          fs.unlinkSync(lockPath);
          continue;
        }
      } catch (statError) {
        if (statError.code === 'ENOENT') continue;
        throw statError;
      }
      if (attempt === LOCK_RETRIES) throw new Error(`Timed out waiting for lock: ${lockPath}`);
      wait(LOCK_DELAY_MS);
    }
  }

  try {
    return callback();
  } finally {
    if (handle !== undefined) fs.closeSync(handle);
    try { fs.unlinkSync(lockPath); } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
}

function isoWeek(dateText) {
  const date = new Date(`${dateText}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return null;
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((date - yearStart) / 86400000) + 1) / 7);
  return `${date.getUTCFullYear()}-W${String(week).padStart(2, '0')}`;
}

function deriveStats(state, contactId) {
  const observations = Object.values(state.observations || {}).filter(observation => {
    if (!Array.isArray(observation.contact_ids) || !observation.contact_ids.includes(contactId)) return false;
    // A meeting is tracked only when at least one attendee is external or unknown.
    // Internal-only meetings remain observations, mirroring classify semantics, but
    // cannot move anybody towards creation.
    return observation.contact_ids.some(id => state.contacts[id]?.location !== 'internal');
  });
  const weeks = new Set(observations.map(item => isoWeek(item.date)).filter(Boolean));
  return {
    tracked_meetings: observations.length,
    distinct_weeks: weeks.size,
    has_transcript: observations.some(item => item.has_transcript === true),
  };
}

function qualifiedContacts(state) {
  return Object.values(state.contacts || {}).filter(contact => {
    if (contact.state !== 'active' || !Array.isArray(contact.emails) || contact.emails.length === 0) return false;
    const stats = deriveStats(state, contact.id);
    return stats.tracked_meetings >= 2
      && (stats.distinct_weeks >= 2 || stats.has_transcript);
  });
}

function recordObservations(meetingId, { date, hasTranscript, attendees }) {
  if (!meetingId) throw new Error('meetingId is required');
  const filePath = statePath();
  return withLock(filePath, () => {
    const state = loadState(filePath);
    const now = new Date().toISOString();
    const contactIds = [];
    for (const raw of Array.isArray(attendees) ? attendees : []) {
      const name = normalizeName(raw && raw.name);
      if (!name) continue;
      const email = normalizeEmail(raw.email);
      const id = contactIdFor({ name, email });
      const existing = state.contacts[id];
      const emails = [...new Set([...(existing?.emails || []), ...(email ? [email] : [])])];
      const domain = email && email.includes('@') ? email.split('@', 2)[1] : (existing?.domain || null);
      state.contacts[id] = {
        id,
        name: existing?.name || name,
        emails,
        domain,
        location: raw.location && raw.location !== 'unknown'
          ? raw.location
          : (existing?.location || 'unknown'),
        page_path: existing?.page_path || null,
        state: existing?.state || 'active',
        created_at: existing?.created_at || now,
        updated_at: existing?.updated_at || now,
      };
      if (email) state.email_index[email] = id;
      contactIds.push(id);
    }

    const nextObservation = {
      date: String(date || '').slice(0, 10),
      has_transcript: hasTranscript === true,
      contact_ids: [...new Set(contactIds)].sort(),
    };
    const previous = state.observations[meetingId];
    const changed = JSON.stringify(previous) !== JSON.stringify(nextObservation);
    state.observations[meetingId] = nextObservation;
    if (changed) {
      for (const id of nextObservation.contact_ids) state.contacts[id].updated_at = now;
    }
    atomicWrite(filePath, state);
    return { state, changed, contact_ids: nextObservation.contact_ids };
  });
}

function updateContact(stateOrPath, id, fields) {
  if (typeof stateOrPath === 'string') {
    return withLock(stateOrPath, () => {
      const state = loadState(stateOrPath);
      if (!state.contacts[id]) return null;
      state.contacts[id] = { ...state.contacts[id], ...fields, id, updated_at: new Date().toISOString() };
      atomicWrite(stateOrPath, state);
      return state.contacts[id];
    });
  }
  const state = stateOrPath;
  if (!state?.contacts?.[id]) return null;
  state.contacts[id] = { ...state.contacts[id], ...fields, id, updated_at: new Date().toISOString() };
  return state.contacts[id];
}

module.exports = {
  atomicWrite,
  contactIdFor,
  deriveStats,
  loadState,
  qualifiedContacts,
  recordObservations,
  runtimePaths,
  updateContact,
  withLock,
};
