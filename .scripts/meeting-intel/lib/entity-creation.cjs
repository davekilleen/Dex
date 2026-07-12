'use strict';

const fs = require('fs');
const path = require('path');
const { parseEntityPage, renderPersonPage } = require('../../lib/entity-pages.cjs');
const {
  atomicWrite,
  deriveStats,
  loadState,
  qualifiedContacts,
  recordObservations,
  runtimePaths,
  updateContact,
  withLock,
} = require('./contacts-state.cjs');

function creationMode(profile) {
  const mode = profile?.entity_creation?.mode;
  return ['auto', 'suggest', 'off'].includes(mode) ? mode : 'suggest';
}

function emptySuggestions() {
  return { version: 1, suggestions: [] };
}

function loadSuggestions(filePath = runtimePaths().ENTITY_SUGGESTIONS_FILE) {
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    if (Array.isArray(parsed)) return { version: 1, suggestions: parsed };
    if (Array.isArray(parsed?.suggestions)) return { version: 1, suggestions: parsed.suggestions };
    return emptySuggestions();
  } catch (error) {
    if (error.code === 'ENOENT' || error instanceof SyntaxError) return emptySuggestions();
    throw error;
  }
}

function updateSuggestion(contact, stats, { newEvidence = false } = {}) {
  const filePath = runtimePaths().ENTITY_SUGGESTIONS_FILE;
  return withLock(filePath, () => {
    const store = loadSuggestions(filePath);
    const index = store.suggestions.findIndex(item => item.id === contact.id);
    const existing = index >= 0 ? store.suggestions[index] : null;
    if (existing?.status === 'suppressed') return { suggestion: existing, changed: false };
    if (existing?.status === 'dismissed' && !newEvidence) return { suggestion: existing, changed: false };
    if (existing?.status === 'suggested' && !newEvidence) return { suggestion: existing, changed: false };

    const now = new Date().toISOString();
    const suggestion = {
      id: contact.id,
      kind: 'person',
      name: contact.name,
      emails: contact.emails,
      location: contact.location || 'unknown',
      reason: `Seen in ${stats.tracked_meetings} meetings across ${stats.distinct_weeks} weeks`,
      status: 'suggested',
      created_at: existing?.created_at || now,
      updated_at: now,
    };
    if (index >= 0) store.suggestions[index] = suggestion;
    else store.suggestions.push(suggestion);
    atomicWrite(filePath, store);
    return { suggestion, changed: JSON.stringify(existing) !== JSON.stringify(suggestion) };
  });
}

function markSuggestionAccepted(contactId) {
  const filePath = runtimePaths().ENTITY_SUGGESTIONS_FILE;
  return withLock(filePath, () => {
    const store = loadSuggestions(filePath);
    const suggestion = store.suggestions.find(item => item.id === contactId);
    if (!suggestion) return false;
    suggestion.status = 'accepted';
    suggestion.updated_at = new Date().toISOString();
    atomicWrite(filePath, store);
    return true;
  });
}

function safeFilename(name) {
  return String(name || 'Unknown')
    .trim()
    .replace(/[\\/:*?"<>|]/g, '')
    .replace(/\s+/g, '_') || 'Unknown';
}

function relativeVaultPath(filePath, vaultRoot) {
  return path.relative(vaultRoot, filePath).split(path.sep).join('/');
}

function pageHasEmail(filePath, email) {
  try {
    return parseEntityPage(filePath).emails.includes(email.toLowerCase());
  } catch (_) {
    return false;
  }
}

function createOrAdoptPerson(contact) {
  const paths = runtimePaths();
  const folder = contact.location === 'internal' ? 'Internal' : 'External';
  const directory = path.join(paths.PEOPLE_DIR, folder);
  fs.mkdirSync(directory, { recursive: true });
  const email = contact.emails[0];
  const baseName = safeFilename(contact.name);
  const basePath = path.join(directory, `${baseName}.md`);

  if (fs.existsSync(basePath) && pageHasEmail(basePath, email)) {
    return { filePath: basePath, created: false, adopted: true };
  }

  let targetPath = basePath;
  if (fs.existsSync(targetPath)) {
    const domain = safeFilename(contact.domain || email.split('@', 2)[1] || 'contact');
    targetPath = path.join(directory, `${baseName}_(${domain}).md`);
    if (fs.existsSync(targetPath) && pageHasEmail(targetPath, email)) {
      return { filePath: targetPath, created: false, adopted: true };
    }
  }

  const content = renderPersonPage(
    contact.name,
    null,
    null,
    contact.emails,
    [],
    contact.location,
  );
  fs.writeFileSync(targetPath, content, { encoding: 'utf8', flag: 'wx' });
  return { filePath: targetPath, created: true, adopted: false };
}

function processEntityCreation(meetings, profile = {}, logger = () => {}) {
  const paths = runtimePaths();
  const mode = creationMode(profile);
  const evidenceContacts = new Set();
  const errors = [];

  for (const meeting of Array.isArray(meetings) ? meetings : []) {
    try {
      const result = recordObservations(meeting.id, {
        date: String(meeting.createdAt || meeting.date || '').slice(0, 10),
        hasTranscript: Boolean(meeting.transcript && String(meeting.transcript).trim()),
        attendees: Array.isArray(meeting.filteredAttendees)
          ? meeting.filteredAttendees
          : (Array.isArray(meeting.attendees) ? meeting.attendees : []),
      });
      if (result.changed) result.contact_ids.forEach(id => evidenceContacts.add(id));
    } catch (error) {
      errors.push({ meeting_id: meeting.id, error: error.message });
      logger(`Could not record entity observations for ${meeting.id}: ${error.message}`);
    }
  }

  if (mode === 'off') return { mode, created: [], suggested: [], errors };

  const state = loadState(paths.CONTACTS_STATE_FILE);
  const created = [];
  const suggested = [];
  for (const contact of qualifiedContacts(state)) {
    try {
      const stats = deriveStats(state, contact.id);
      if (mode === 'auto' && ['internal', 'external'].includes(contact.location)) {
        const page = createOrAdoptPerson(contact);
        const pagePath = relativeVaultPath(page.filePath, paths.VAULT_ROOT);
        updateContact(paths.CONTACTS_STATE_FILE, contact.id, { state: 'created', page_path: pagePath });
        markSuggestionAccepted(contact.id);
        created.push({ ...page, contact, page_path: pagePath });
        if (page.created) logger(`Created person page: ${pagePath}`);
      } else {
        const result = updateSuggestion(contact, stats, { newEvidence: evidenceContacts.has(contact.id) });
        suggested.push(result.suggestion);
      }
    } catch (error) {
      errors.push({ contact_id: contact.id, error: error.message });
      logger(`Could not create or suggest ${contact.name}: ${error.message}`);
    }
  }
  return { mode, created, suggested, errors };
}

module.exports = {
  createOrAdoptPerson,
  creationMode,
  loadSuggestions,
  markSuggestionAccepted,
  processEntityCreation,
  updateSuggestion,
};
