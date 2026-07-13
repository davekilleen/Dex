'use strict';

const path = require('node:path');
const {
  createOrAdoptCompany,
  createOrAdoptPerson,
  loadSuggestions,
} = require('./entity-creation.cjs');
const {
  atomicWrite,
  loadState,
  runtimePaths,
  updateContact,
  withLock,
} = require('./contacts-state.cjs');

function failure(code, message) {
  return { ok: false, error: { code, message } };
}

function vaultRelative(filePath, vaultRoot) {
  return path.relative(vaultRoot, filePath).split(path.sep).join('/');
}

function listSuggestions() {
  try {
    const filePath = runtimePaths().ENTITY_SUGGESTIONS_FILE;
    return withLock(filePath, () => loadSuggestions(filePath).suggestions
      .filter(item => item.status === 'suggested')
      .map(item => ({
        id: item.id,
        kind: item.kind,
        name: item.name,
        emails: Array.isArray(item.emails) ? item.emails : [],
        domains: Array.isArray(item.domains) ? item.domains : [],
        reason: item.reason,
      })));
  } catch (error) {
    return failure('read_failed', error.message);
  }
}

function mutateStatus(id, status) {
  try {
    const filePath = runtimePaths().ENTITY_SUGGESTIONS_FILE;
    return withLock(filePath, () => {
      const store = loadSuggestions(filePath);
      const suggestion = store.suggestions.find(item => item.id === id);
      if (!suggestion) return failure('not_found', `Unknown suggestion id: ${id}`);
      suggestion.status = status;
      suggestion.updated_at = new Date().toISOString();
      atomicWrite(filePath, store);
      return { id, status };
    });
  } catch (error) {
    return failure('update_failed', error.message);
  }
}

function acceptSuggestion(id) {
  try {
    const paths = runtimePaths();
    const suggestionsPath = paths.ENTITY_SUGGESTIONS_FILE;
    return withLock(suggestionsPath, () => {
      const store = loadSuggestions(suggestionsPath);
      const suggestion = store.suggestions.find(item => item.id === id);
      if (!suggestion) return failure('not_found', `Unknown suggestion id: ${id}`);
      if (suggestion.status !== 'suggested') {
        return failure('not_suggested', `Suggestion ${id} has status ${suggestion.status}`);
      }

      let page;
      if (suggestion.kind === 'person') {
        if (!Array.isArray(suggestion.emails) || !suggestion.emails.length) {
          return failure('invalid_suggestion', `Person suggestion ${id} has no email`);
        }
        page = createOrAdoptPerson(suggestion);
        const pagePath = vaultRelative(page.filePath, paths.VAULT_ROOT);
        if (!updateContact(paths.CONTACTS_STATE_FILE, id, { state: 'created', page_path: pagePath })) {
          return failure('contact_not_found', `No contact state found for suggestion ${id}`);
        }
        suggestion.status = 'accepted';
        suggestion.updated_at = new Date().toISOString();
        atomicWrite(suggestionsPath, store);
        return { page_path: pagePath };
      }

      if (suggestion.kind === 'company') {
        const domain = Array.isArray(suggestion.domains) ? suggestion.domains[0] : null;
        if (!domain) return failure('invalid_suggestion', `Company suggestion ${id} has no domain`);
        page = createOrAdoptCompany(domain);
        const pagePath = vaultRelative(page.filePath, paths.VAULT_ROOT);
        const state = loadState(paths.CONTACTS_STATE_FILE);
        for (const contact of Object.values(state.contacts || {})) {
          if (contact.domain === domain) {
            updateContact(paths.CONTACTS_STATE_FILE, contact.id, { company_page: pagePath });
          }
        }
        suggestion.status = 'accepted';
        suggestion.updated_at = new Date().toISOString();
        atomicWrite(suggestionsPath, store);
        return { page_path: pagePath };
      }

      return failure('invalid_suggestion', `Unsupported suggestion kind: ${suggestion.kind}`);
    });
  } catch (error) {
    return failure('accept_failed', error.message);
  }
}

function dismissSuggestion(id) {
  return mutateStatus(id, 'dismissed');
}

function suppressSuggestion(id) {
  return mutateStatus(id, 'suppressed');
}

module.exports = {
  acceptSuggestion,
  dismissSuggestion,
  listSuggestions,
  suppressSuggestion,
};
