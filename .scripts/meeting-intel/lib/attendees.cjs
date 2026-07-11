'use strict';

const SERVICE_ACCOUNT_PATTERNS = [
  'room',
  'resource',
  'group',
  'noreply',
];

function normalizeEmail(value) {
  if (typeof value !== 'string') return null;
  return value.trim().toLowerCase() || null;
}

function normalizeName(value) {
  if (typeof value !== 'string') return '';
  return value.trim().replace(/\s+/g, ' ');
}

function prettifyEmailLocalPart(email) {
  const localPart = email.split('@', 1)[0];
  return localPart
    .replace(/[._-]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(' ');
}

function isServiceAccount({ name, email } = {}) {
  const normalizedEmail = normalizeEmail(email) || '';
  const localPart = normalizedEmail.includes('@')
    ? normalizedEmail.split('@', 1)[0]
    : normalizedEmail;
  const searchable = `${normalizeName(name)} ${localPart}`.toLowerCase();
  return SERVICE_ACCOUNT_PATTERNS.some(pattern => searchable.includes(pattern));
}

function extractAttendees(detailData = {}) {
  const records = Array.isArray(detailData.attendees)
    ? [...detailData.attendees]
    : [];
  if (detailData.owner && (detailData.owner.name || detailData.owner.email)) {
    records.push(detailData.owner);
  }

  const attendees = [];
  const seen = new Set();
  for (const record of records) {
    if (!record || typeof record !== 'object') continue;
    const email = normalizeEmail(record.email);
    const name = normalizeName(record.name) || (email ? prettifyEmailLocalPart(email) : '');
    if (!name || isServiceAccount({ name, email })) continue;

    const key = email
      ? `email:${email}`
      : `name:${name.toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    attendees.push({ name, email });
  }
  return attendees;
}

function getInternalDomains(profile = {}) {
  const rawDomains = typeof profile.email_domain === 'string'
    ? profile.email_domain
    : '';
  const domains = new Set(
    rawDomains
      .split(',')
      .map(domain => domain.trim().toLowerCase())
      .filter(Boolean)
  );

  const workEmail = normalizeEmail(profile.work_email);
  if (workEmail && workEmail.includes('@')) {
    const domain = workEmail.split('@', 2)[1];
    if (domain) domains.add(domain);
  }
  return domains;
}

function classifyAttendee(attendee, internalDomains) {
  const email = normalizeEmail(attendee && attendee.email);
  const domains = new Set(
    Array.from(internalDomains || [], domain => String(domain).trim().toLowerCase())
      .filter(Boolean)
  );
  if (!email || !email.includes('@') || domains.size === 0) return 'unknown';
  const domain = email.split('@', 2)[1];
  if (!domain) return 'unknown';
  return domains.has(domain) ? 'internal' : 'external';
}

function filterOwner(attendees, profile = {}, ownerData = {}) {
  const ownerEmails = new Set(
    [profile.work_email, ownerData && ownerData.email]
      .map(normalizeEmail)
      .filter(Boolean)
  );
  const ownerName = normalizeName((ownerData && ownerData.name) || profile.name);
  const ownerFirstName = ownerName.split(' ')[0].toLowerCase();

  return (Array.isArray(attendees) ? attendees : []).filter(attendee => {
    const attendeeEmail = normalizeEmail(attendee && attendee.email);
    if (attendeeEmail && ownerEmails.size > 0) {
      return !ownerEmails.has(attendeeEmail);
    }

    const attendeeName = normalizeName(attendee && attendee.name).toLowerCase();
    if (!attendeeName || !ownerName) return true;
    return attendeeName !== ownerName.toLowerCase()
      && (!ownerFirstName || !attendeeName.includes(ownerFirstName));
  });
}

module.exports = {
  extractAttendees,
  isServiceAccount,
  getInternalDomains,
  classifyAttendee,
  filterOwner,
};
