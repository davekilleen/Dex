'use strict';

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const portableContract = require('../../../packages/dex-contracts/dist/portable-vault.contract.json');
const { parseEntityPage, renderCompanyPage, renderPersonPage } = require('../../lib/entity-pages.cjs');
const { identityForEntity, resolveEntityPath } = require('../../lib/entity-identity.cjs');
const {
  fingerprintText,
  flushEntityOps,
  resultApplied,
} = require('../../lib/entity-engine-client.cjs');
const { getInternalDomains } = require('./attendees.cjs');
const { companyNameFromDomain, isFreemail, registrableDomain } = require('./company-domains.cjs');
const { entityWriteMessage } = require('./entity-phase.cjs');
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

function capabilityEnabled(profile, room) {
  const definition = portableContract.capabilities?.[room];
  if (!definition) return false;
  const explicit = profile?.capabilities?.[room]?.enabled;
  if (typeof explicit === 'boolean') return explicit;
  if (typeof definition.config === 'string') {
    const legacy = profile?.[definition.config]?.enabled;
    if (typeof legacy === 'boolean') return legacy;
  }
  // Legacy bridge (mirrors core/capabilities.py migrate_legacy_room_state):
  // vaults onboarded before rooms existed had every room's surfaces active,
  // so an onboarded profile with NO capabilities state keeps its status quo
  // until the one-time migration stamps explicit answers. Without this,
  // background company creation silently stops for months-old installs.
  const onboardingMarker = path.join(
    runtimePaths().VAULT_ROOT || process.cwd(),
    'System',
    '.onboarding-complete',
  );
  if (
    profile
    && typeof profile === 'object'
    && !('capabilities' in profile)
    && fs.existsSync(onboardingMarker)
  ) {
    return true;
  }
  return definition.default_enabled === true;
}

function loadProfile() {
  try {
    const profilePath = runtimePaths().USER_PROFILE_FILE;
    const parsed = yaml.load(fs.readFileSync(profilePath, 'utf8'));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch (_) {
    return {};
  }
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

function updateCompanySuggestion(domain, companyName, contactCount, meetingCount, { newEvidence = false } = {}) {
  const filePath = runtimePaths().ENTITY_SUGGESTIONS_FILE;
  return withLock(filePath, () => {
    const store = loadSuggestions(filePath);
    const id = `domain:${domain}`;
    const index = store.suggestions.findIndex(item => item.id === id);
    const existing = index >= 0 ? store.suggestions[index] : null;
    if (existing?.status === 'suppressed') return { suggestion: existing, changed: false };
    if (existing?.status === 'dismissed' && !newEvidence) return { suggestion: existing, changed: false };
    if (existing?.status === 'suggested' && !newEvidence) return { suggestion: existing, changed: false };
    const now = new Date().toISOString();
    const suggestion = {
      id,
      kind: 'company',
      name: companyName,
      domains: [domain],
      reason: `${contactCount} contacts across ${meetingCount} meetings`,
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

function planPersonPage(contact, reserved = new Set()) {
  const paths = runtimePaths();
  const folder = contact.location === 'internal' ? 'Internal' : 'External';
  const directory = path.join(paths.PEOPLE_DIR, folder);
  fs.mkdirSync(directory, { recursive: true });
  const email = contact.emails[0];
  const baseName = safeFilename(contact.name);
  const basePath = path.join(directory, `${baseName}.md`);
  const existingByIdentity = resolveEntityPath(paths.VAULT_ROOT, {
    kind: 'person',
    name: contact.name,
    emails: contact.emails,
  });
  if (existingByIdentity && !reserved.has(existingByIdentity)) {
    return { filePath: existingByIdentity, created: false, adopted: true };
  }

  if (!reserved.has(basePath) && fs.existsSync(basePath) && pageHasEmail(basePath, email)) {
    return { filePath: basePath, created: false, adopted: true };
  }

  let targetPath = basePath;
  if (reserved.has(targetPath) || fs.existsSync(targetPath)) {
    const domain = safeFilename(contact.domain || email.split('@', 2)[1] || 'contact');
    targetPath = path.join(directory, `${baseName}_(${domain}).md`);
    if (!reserved.has(targetPath) && fs.existsSync(targetPath) && pageHasEmail(targetPath, email)) {
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
  reserved.add(targetPath);
  return {
    filePath: targetPath,
    created: true,
    adopted: false,
    op: {
      op: 'create',
      path: targetPath,
      content,
      allowed_root: paths.VAULT_ROOT,
      target_fingerprint: fingerprintText(content),
    },
  };
}

function executeCreatePlan(plan, paths = runtimePaths()) {
  if (!plan.op) return plan;
  const write = flushEntityOps({
    vaultRoot: paths.VAULT_ROOT,
    ops: [plan.op],
    scope: 'suggestion',
  });
  if (!write.ok || !resultApplied(plan.op, write.results[0])) {
    throw new Error(write.error || 'Entity engine did not create the person page');
  }
  return plan;
}

function createOrAdoptPerson(contact) {
  return executeCreatePlan(planPersonPage(contact));
}

function walkMarkdown(directory) {
  if (!fs.existsSync(directory)) return [];
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const filePath = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walkMarkdown(filePath));
    else if (entry.isFile() && entry.name.endsWith('.md') && entry.name !== 'README.md') files.push(filePath);
  }
  return files;
}

function companyPageForDomain(domain) {
  const paths = runtimePaths();
  const candidates = new Set();
  try {
    const index = JSON.parse(fs.readFileSync(paths.COMPANY_INDEX_FILE, 'utf8'));
    for (const company of Array.isArray(index?.companies) ? index.companies : []) {
      if ((company.domains || []).map(registrableDomain).includes(domain) && company.path) {
        candidates.add(path.isAbsolute(company.path) ? company.path : path.join(paths.VAULT_ROOT, company.path));
      }
    }
  } catch (_) { /* an absent or malformed index is advisory only */ }
  const resolved = resolveEntityPath(paths.VAULT_ROOT, {
    kind: 'company',
    domains: [domain],
  });
  if (resolved) candidates.add(resolved);
  for (const filePath of walkMarkdown(paths.COMPANIES_DIR)) candidates.add(filePath);
  for (const filePath of candidates) {
    try {
      if (parseEntityPage(filePath).domains.map(registrableDomain).includes(domain)) return filePath;
    } catch (_) { /* scan remains authoritative over stale entries */ }
  }
  return null;
}

function planCompanyPage(domain, profile = null, reserved = new Set()) {
  if (!capabilityEnabled(profile || loadProfile(), 'companies')) {
    throw new Error('Companies room is off');
  }
  const paths = runtimePaths();
  const existing = companyPageForDomain(domain);
  if (existing) return { filePath: existing, created: false, adopted: true };
  fs.mkdirSync(paths.COMPANIES_DIR, { recursive: true });
  const name = companyNameFromDomain(domain);
  const basePath = path.join(paths.COMPANIES_DIR, `${safeFilename(name)}.md`);
  let targetPath = basePath;
  if (reserved.has(targetPath) || fs.existsSync(targetPath)) {
    targetPath = path.join(paths.COMPANIES_DIR, `${safeFilename(name)}_(${safeFilename(domain)}).md`);
    if (!reserved.has(targetPath)
        && fs.existsSync(targetPath)
        && parseEntityPage(targetPath).domains.map(registrableDomain).includes(domain)) {
      return { filePath: targetPath, created: false, adopted: true };
    }
  }
  const content = renderCompanyPage(name, [domain], null, 'Prospect');
  reserved.add(targetPath);
  return {
    filePath: targetPath,
    created: true,
    adopted: false,
    op: {
      op: 'create',
      path: targetPath,
      content,
      allowed_root: paths.VAULT_ROOT,
      target_fingerprint: fingerprintText(content),
    },
  };
}

function createOrAdoptCompany(domain, profile = null) {
  return executeCreatePlan(planCompanyPage(domain, profile));
}

function qualifiedCompanyDomains(state, profile) {
  const internal = new Set(Array.from(getInternalDomains(profile), registrableDomain));
  const qualifiedIds = new Set(qualifiedContacts(state).map(contact => contact.id));
  const eligible = new Set(Object.values(state.contacts || {}).filter(contact => {
    if (contact.location === 'unknown' || !contact.domain) return false;
    return contact.state === 'created' || qualifiedIds.has(contact.id);
  }).map(contact => contact.id));
  const domains = new Map();
  for (const [meetingId, observation] of Object.entries(state.observations || {})) {
    const seen = new Set();
    for (const contactId of observation.contact_ids || []) {
      const contact = state.contacts[contactId];
      const domain = registrableDomain(contact?.domain);
      if (!eligible.has(contactId) || !domain || isFreemail(domain) || internal.has(domain)) continue;
      if (!domains.has(domain)) domains.set(domain, { contacts: new Set(), meetings: new Set() });
      domains.get(domain).contacts.add(contactId);
      seen.add(domain);
    }
    for (const domain of seen) domains.get(domain).meetings.add(meetingId);
  }
  return [...domains.entries()].filter(([, stats]) => stats.meetings.size >= 2);
}

function meetingAttendees(meeting) {
  return Array.isArray(meeting?.filteredAttendees)
    ? meeting.filteredAttendees
    : (Array.isArray(meeting?.attendees) ? meeting.attendees : []);
}

function buildTouchOperations(
  meetings,
  profile,
  created,
  companiesCreated,
  creationEffects,
  paths,
) {
  const internalDomains = new Set(
    Array.from(getInternalDomains(profile), registrableDomain).filter(Boolean),
  );
  const createdPeopleByEmail = new Map();
  const createdPeopleByName = new Map();
  for (const page of created) {
    for (const email of page.contact?.emails || []) {
      createdPeopleByEmail.set(String(email).trim().toLowerCase(), page.filePath);
    }
    const name = String(page.contact?.name || '').trim().toLowerCase();
    if (name) createdPeopleByName.set(name, page.filePath);
  }
  const createdCompaniesByDomain = new Map(
    companiesCreated.map(page => [registrableDomain(page.domain), page.filePath]),
  );
  const confirmedCreationPaths = new Set([
    ...created.map(page => page.filePath),
    ...companiesCreated.map(page => page.filePath),
  ]);
  const unconfirmedCreationPaths = new Set(
    creationEffects
      .map(effect => effect.file_path)
      .filter(filePath => !confirmedCreationPaths.has(filePath)),
  );
  const grouped = new Map();

  function addTouch(filePath, touch) {
    if (!filePath || unconfirmedCreationPaths.has(filePath) || !fs.existsSync(filePath)) return;
    let entity;
    try {
      entity = parseEntityPage(filePath);
    } catch (_) {
      return;
    }
    const entityIdentity = identityForEntity(entity);
    if (!entityIdentity || entity.quarantined) return;
    if (!grouped.has(filePath)) {
      grouped.set(filePath, { entityIdentity, touches: [] });
    }
    grouped.get(filePath).touches.push(touch);
  }

  for (const meeting of Array.isArray(meetings) ? meetings : []) {
    const date = String(meeting?.createdAt || meeting?.date || '').slice(0, 10);
    if (!meeting?.id || !/^\d{4}-\d{2}-\d{2}$/.test(date)) continue;
    const touch = {
      ts: date,
      type: 'meeting',
      direction: 'none',
      source: {
        id: meeting.id,
        title: meeting.title || `Meeting ${date}`,
      },
    };
    const touchedPeople = new Set();
    const touchedCompanies = new Set();
    for (const attendee of meetingAttendees(meeting)) {
      const name = String(attendee?.name || '').trim();
      if (!name) continue;
      const email = typeof attendee?.email === 'string'
        ? attendee.email.trim().toLowerCase()
        : '';
      const personPath = createdPeopleByEmail.get(email)
        || createdPeopleByName.get(name.toLowerCase())
        || resolveEntityPath(paths.VAULT_ROOT, {
          kind: 'person',
          name,
          emails: email ? [email] : [],
        });
      if (personPath && !touchedPeople.has(personPath)) {
        touchedPeople.add(personPath);
        addTouch(personPath, touch);
      }

      if (attendee?.location !== 'external' || !email.includes('@')) continue;
      const domain = registrableDomain(email.split('@', 2)[1]);
      if (!domain || isFreemail(domain) || internalDomains.has(domain)) continue;
      const companyPath = createdCompaniesByDomain.get(domain)
        || companyPageForDomain(domain);
      if (companyPath && !touchedCompanies.has(companyPath)) {
        touchedCompanies.add(companyPath);
        addTouch(companyPath, touch);
      }
    }
  }

  return [...grouped.entries()].map(([filePath, entry]) => ({
    op: 'mutate',
    path: filePath,
    entity_identity: entry.entityIdentity,
    intent: {
      kind: 'touch-log',
      touches: entry.touches,
    },
  }));
}

function processEntityCreation(
  meetings,
  profile = {},
  logger = () => {},
  { now = new Date() } = {},
) {
  const paths = runtimePaths();
  const mode = creationMode(profile);
  const evidenceContacts = new Set();
  const errors = [];
  const meetingIds = (Array.isArray(meetings) ? meetings : [])
    .map(meeting => meeting?.id)
    .filter(Boolean);

  for (const meeting of Array.isArray(meetings) ? meetings : []) {
    try {
      const result = recordObservations(meeting.id, {
        date: String(meeting.createdAt || meeting.date || '').slice(0, 10),
        hasTranscript: Boolean(
          meeting.hasTranscript
          || (meeting.transcript && String(meeting.transcript).trim()),
        ),
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

  const state = loadState(paths.CONTACTS_STATE_FILE);
  const created = [];
  const suggested = [];
  const companiesCreated = [];
  const companiesSuggested = [];
  const reserved = new Set();
  const operations = [];
  const effects = [];
  for (const contact of mode === 'off' ? [] : qualifiedContacts(state)) {
    try {
      const stats = deriveStats(state, contact.id);
      if (mode === 'auto' && ['internal', 'external'].includes(contact.location)) {
        const page = planPersonPage(contact, reserved);
        const pagePath = relativeVaultPath(page.filePath, paths.VAULT_ROOT);
        if (page.op) {
          operations.push(page.op);
          effects.push({
            kind: 'person',
            contact_id: contact.id,
            contact,
            file_path: page.filePath,
            page_path: pagePath,
          });
        } else {
          updateContact(paths.CONTACTS_STATE_FILE, contact.id, { state: 'created', page_path: pagePath });
          markSuggestionAccepted(contact.id);
          created.push({ ...page, contact, page_path: pagePath });
        }
      } else {
        const result = updateSuggestion(contact, stats, { newEvidence: evidenceContacts.has(contact.id) });
        suggested.push(result.suggestion);
      }
    } catch (error) {
      errors.push({ contact_id: contact.id, error: error.message });
      logger(`Could not create or suggest ${contact.name}: ${error.message}`);
    }
  }
  const companyState = loadState(paths.CONTACTS_STATE_FILE);
  const companyDomains = mode !== 'off' && capabilityEnabled(profile, 'companies')
    ? qualifiedCompanyDomains(companyState, profile)
    : [];
  for (const [domain, stats] of companyDomains) {
    try {
      const existing = companyPageForDomain(domain);
      if (existing) {
        const companyPage = relativeVaultPath(existing, paths.VAULT_ROOT);
        for (const contactId of stats.contacts) {
          updateContact(paths.CONTACTS_STATE_FILE, contactId, { company_page: companyPage });
        }
        continue;
      }
      const companyName = companyNameFromDomain(domain);
      if (mode === 'auto') {
        const page = planCompanyPage(domain, profile, reserved);
        const pagePath = relativeVaultPath(page.filePath, paths.VAULT_ROOT);
        if (page.op) {
          operations.push(page.op);
          effects.push({
            kind: 'company',
            contact_ids: [...stats.contacts],
            domain,
            name: companyName,
            file_path: page.filePath,
            page_path: pagePath,
          });
        } else {
          for (const contactId of stats.contacts) {
            updateContact(paths.CONTACTS_STATE_FILE, contactId, { company_page: pagePath });
          }
          companiesCreated.push({ ...page, name: companyName, domain, page_path: pagePath });
          markSuggestionAccepted(`domain:${domain}`);
        }
      } else {
        const result = updateCompanySuggestion(
          domain, companyName, stats.contacts.size, stats.meetings.size,
          { newEvidence: [...stats.contacts].some(id => evidenceContacts.has(id)) },
        );
        companiesSuggested.push(result.suggestion);
      }
    } catch (error) {
      errors.push({ domain, error: error.message });
      logger(`Could not create or suggest company ${domain}: ${error.message}`);
    }
  }
  const entityWrite = flushEntityOps({
    vaultRoot: paths.VAULT_ROOT,
    ops: operations,
    meetingIds,
    scope: 'creation',
    scopes: ['creation', 'hook', 'suggestion'],
    metadata: { effects },
    now,
  });
  const reportedEffects = new Set([
    ...created.map(page => `person:${page.page_path}`),
    ...companiesCreated.map(page => `company:${page.page_path}`),
  ]);
  for (const batch of entityWrite.completed_batches) {
    if (batch.scope !== 'creation') continue;
    for (const effect of batch.metadata?.effects || []) {
      const effectId = `${effect.kind}:${effect.page_path}`;
      if (effect.kind === 'person') {
        updateContact(paths.CONTACTS_STATE_FILE, effect.contact_id, {
          state: 'created',
          page_path: effect.page_path,
        });
        markSuggestionAccepted(effect.contact_id);
        if (reportedEffects.has(effectId)) continue;
        reportedEffects.add(effectId);
        created.push({
          filePath: effect.file_path,
          created: true,
          adopted: false,
          contact: effect.contact,
          page_path: effect.page_path,
        });
        logger(`Created person page: ${effect.page_path}`);
      } else if (effect.kind === 'company') {
        for (const contactId of effect.contact_ids) {
          updateContact(paths.CONTACTS_STATE_FILE, contactId, {
            company_page: effect.page_path,
          });
        }
        markSuggestionAccepted(`domain:${effect.domain}`);
        if (reportedEffects.has(effectId)) continue;
        reportedEffects.add(effectId);
        companiesCreated.push({
          filePath: effect.file_path,
          created: true,
          adopted: false,
          name: effect.name,
          domain: effect.domain,
          page_path: effect.page_path,
        });
        logger(`Created company page: ${effect.page_path}`);
      }
    }
  }
  if (!entityWrite.ok) {
    const writeMessage = entityWriteMessage(entityWrite)
      || 'Entity writes remain pending';
    errors.push({
      entity_write: true,
      error: writeMessage,
    });
    logger(writeMessage);
  }
  const touchOps = buildTouchOperations(
    meetings,
    profile,
    created,
    companiesCreated,
    effects,
    paths,
  );
  const touchWrite = flushEntityOps({
    vaultRoot: paths.VAULT_ROOT,
    ops: touchOps,
    meetingIds,
    scope: 'touch',
    scopes: ['touch'],
    metadata: { source: 'meeting-intel' },
    now,
  });
  if (!touchWrite.ok) {
    const writeMessage = entityWriteMessage(touchWrite)
      || 'Entity touch writes remain pending';
    errors.push({
      entity_write: true,
      scope: 'touch',
      error: writeMessage,
    });
    logger(writeMessage);
  }
  entityWrite.completed_meeting_ids = [...new Set([
    ...(entityWrite.completed_meeting_ids || []),
    ...(entityWrite.completed_batches || [])
      .filter(batch => batch.scope === 'creation')
      .flatMap(batch => batch.meeting_ids || []),
    ...(touchWrite.completed_meeting_ids || []),
  ])].sort();
  return {
    mode, created, suggested, companies_created: companiesCreated,
    companies_suggested: companiesSuggested, errors, entity_write: entityWrite,
  };
}

module.exports = {
  createOrAdoptPerson,
  createOrAdoptCompany,
  capabilityEnabled,
  creationMode,
  loadSuggestions,
  markSuggestionAccepted,
  processEntityCreation,
  updateSuggestion,
  updateCompanySuggestion,
};
