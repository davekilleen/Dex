'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const {
  atomicWrite: atomicWritePage,
  parseEntityPage,
  replaceMachineRegion,
} = require('../../lib/entity-pages.cjs');
const {
  atomicWrite,
  runtimePaths,
  withLock,
} = require('./contacts-state.cjs');

const REGION_SLUG = 'context-summary';
const REGION_START = `<!-- dex:auto:${REGION_SLUG} -->`;
const REGION_END = '<!-- /dex:auto -->';
const RESUME_MARKER = '<!-- dex:resume:context-summary -->';
const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const SIGNAL_LIMIT = 6000;

function sha1(value) {
  return crypto.createHash('sha1').update(value).digest('hex');
}

function emptyState() {
  return { version: 2, pages: {} };
}

function loadGardenerState(filePath) {
  try {
    const candidate = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    return {
      version: 2,
      pages: candidate && typeof candidate.pages === 'object' && candidate.pages ? candidate.pages : {},
    };
  } catch (error) {
    if (error.code === 'ENOENT' || error instanceof SyntaxError) return emptyState();
    throw error;
  }
}

function savePageState(filePath, relativePath, pageState) {
  withLock(filePath, () => {
    const state = loadGardenerState(filePath);
    state.pages[relativePath] = pageState;
    atomicWrite(filePath, state);
  });
}

function machineRegion(text, slug) {
  const start = `<!-- dex:auto:${slug} -->`;
  const startIndex = text.indexOf(start);
  if (startIndex < 0) return null;
  const contentStart = startIndex + start.length;
  const endIndex = text.indexOf(REGION_END, contentStart);
  if (endIndex < 0) return null;
  return text.slice(contentStart, endIndex).replace(/^[\r\n]+|[\r\n]+$/g, '');
}

function blockState(pageState) {
  return pageState.blocks && typeof pageState.blocks === 'object' && !Array.isArray(pageState.blocks)
    ? { ...pageState.blocks }
    : {};
}

function migratePageState(pageState, currentOutput) {
  const next = { ...pageState, blocks: blockState(pageState) };
  let migrated = false;
  if (Object.hasOwn(next, 'locked') || Object.hasOwn(next, 'locked_reason')) {
    const changedFromDex = Object.hasOwn(next, 'output_hash')
      && sha1(currentOutput || '') !== next.output_hash;
    if (next.locked && (next.locked_reason === 'user-edited' || changedFromDex)) {
      next.blocks[REGION_SLUG] = { owner: 'user', reason: 'user-edited' };
    }
    delete next.locked;
    delete next.locked_reason;
    migrated = true;
  }
  return { pageState: next, migrated };
}

function removeResumeMarker(output) {
  return String(output || '')
    .split(/\r?\n/)
    .filter(line => line.trim() !== RESUME_MARKER)
    .join('\n')
    .replace(/^[\r\n]+|[\r\n]+$/g, '');
}

function ensureSummaryRegion(text) {
  if (machineRegion(text, REGION_SLUG) !== null) return text;
  const region = `${REGION_START}\n${REGION_END}`;
  const heading = /^## Key Context[ \t]*$/m.exec(text);
  if (heading) {
    const lineEnd = text.indexOf('\n', heading.index + heading[0].length);
    const insertionPoint = lineEnd < 0 ? text.length : lineEnd + 1;
    return `${text.slice(0, insertionPoint)}\n${region}\n${text.slice(insertionPoint)}`;
  }
  return `${text.replace(/\s*$/, '')}\n\n## Key Context\n\n${region}\n`;
}

function sectionLines(text, heading, maximum) {
  const match = new RegExp(`^## ${heading}[ \\t]*$`, 'mi').exec(text);
  if (!match) return [];
  const after = text.slice(match.index + match[0].length).replace(/^\r?\n/, '');
  const end = /^##\s+/m.exec(after);
  return (end ? after.slice(0, end.index) : after)
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
    .slice(0, maximum);
}

function splitMarkdown(text) {
  if (!text.startsWith('---')) return { frontmatter: {}, body: text };
  const match = /^---[ \t]*\r?\n([\s\S]*?)^---[ \t]*\r?$(?:\r?\n)?/m.exec(text);
  if (!match || match.index !== 0) return { frontmatter: {}, body: text };
  try {
    const frontmatter = yaml.load(match[1]);
    return {
      frontmatter: frontmatter && typeof frontmatter === 'object' ? frontmatter : {},
      body: text.slice(match[0].length),
    };
  } catch (_) {
    return { frontmatter: {}, body: text.slice(match[0].length) };
  }
}

function markdownFiles(root) {
  if (!fs.existsSync(root)) return [];
  const results = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) results.push(...markdownFiles(fullPath));
    else if (entry.isFile() && entry.name.endsWith('.md')) results.push(fullPath);
  }
  return results;
}

function meetingSignals(meetingsDir) {
  const meetings = [];
  for (const filePath of markdownFiles(meetingsDir)) {
    try {
      const { frontmatter, body } = splitMarkdown(fs.readFileSync(filePath, 'utf8'));
      const attendees = Array.isArray(frontmatter.attendees) ? frontmatter.attendees : [];
      const emails = new Set(attendees
        .map(attendee => attendee && typeof attendee.email === 'string' ? attendee.email.toLowerCase() : null)
        .filter(Boolean));
      if (emails.size === 0) continue;
      const withoutTranscript = body.split(/^##\s+Transcript\b.*$/im, 1)[0];
      const titleMatch = /^#\s+(.+?)\s*$/m.exec(body);
      const pathDate = filePath.match(/(?:^|[\\/])(\d{4}-\d{2}-\d{2})(?:[\\/]|$)/);
      const rawDate = frontmatter.date || pathDate?.[1] || '';
      const date = rawDate instanceof Date && !Number.isNaN(rawDate.getTime())
        ? rawDate.toISOString().slice(0, 10)
        : String(rawDate).slice(0, 10);
      meetings.push({
        date,
        title: String(frontmatter.title || titleMatch?.[1] || path.basename(filePath, '.md')),
        excerpt: withoutTranscript.trim().slice(0, 600),
        emails,
      });
    } catch (_) {
      // One malformed or unreadable meeting must not stop other signals.
    }
  }
  return meetings.sort((a, b) => b.date.localeCompare(a.date));
}

function buildSignal(entity, pageText, meetings) {
  const fields = ['name', 'role', 'company', 'emails', 'location', 'last_interaction'];
  const lines = ['PERSON:'];
  for (const field of fields) {
    const value = entity[field];
    if (Array.isArray(value)) lines.push(`${field}: ${value.join(', ')}`);
    else if (value !== null && value !== undefined && value !== '') lines.push(`${field}: ${value}`);
  }

  const recent = machineRegion(pageText, 'recent-interactions');
  if (recent) lines.push('', 'RECENT INTERACTIONS:', ...recent.split(/\r?\n/).filter(Boolean));

  const emails = new Set((entity.emails || []).map(email => email.toLowerCase()));
  const matchingMeetings = meetings
    .filter(meeting => [...meeting.emails].some(email => emails.has(email)))
    .slice(0, 5);
  if (matchingMeetings.length) {
    lines.push('', 'MEETINGS:');
    for (const meeting of matchingMeetings) {
      lines.push(`${meeting.date} — ${meeting.title}`);
      if (meeting.excerpt) lines.push(meeting.excerpt);
    }
  }

  const tasks = sectionLines(pageText, 'Related Tasks', 10);
  if (tasks.length) lines.push('', 'RELATED TASKS:', ...tasks);
  return lines.join('\n').slice(0, SIGNAL_LIMIT);
}

function promptFor(signal) {
  return `You maintain a short factual summary on a person page in a personal knowledge vault.
Write 3-6 plain bullet points ("- ") capturing who this person is to the vault owner and what currently matters: role and company, what you've been meeting about, open threads or commitments, and anything that changed recently.
Rules: only state facts present in the signal below — never speculate or embellish. Most recent information wins. No dates older than 90 days unless still clearly relevant. No pleasantries, no headers, no bold, just bullets. Maximum 6 bullets, each under 25 words.

SIGNAL:
${signal}`;
}

function cleanOutput(response) {
  return String(response || '')
    .split(/\r?\n/)
    .filter(line => line.startsWith('- '))
    .slice(0, 6)
    .map(line => line.slice(0, 200).trimEnd())
    .join('\n');
}

function personPages(peopleDir) {
  return ['Internal', 'External', 'CPO_Network']
    .flatMap(folder => markdownFiles(path.join(peopleDir, folder)))
    .filter(filePath => path.basename(filePath) !== 'README.md');
}

async function gardenEntities({
  generate,
  now = new Date(),
  limit = 5,
  dryRun = false,
  log = () => {},
} = {}) {
  const result = { gardened: [], skipped: 0, preserved: 0, migrated: 0, errors: [] };
  try {
    if (typeof generate !== 'function') throw new Error('generate must be a function');
    const paths = runtimePaths();
    const nowDate = now instanceof Date ? now : new Date(now);
    if (Number.isNaN(nowDate.getTime())) throw new Error('now must be a valid date');
    const maximum = Number.isInteger(Number(limit)) && Number(limit) >= 0 ? Number(limit) : 5;
    const state = withLock(paths.GARDENER_STATE_FILE, () => loadGardenerState(paths.GARDENER_STATE_FILE));
    const meetings = meetingSignals(paths.MEETINGS_DIR);
    const candidates = [];

    for (const filePath of personPages(paths.PEOPLE_DIR)) {
      try {
        const entity = parseEntityPage(filePath);
        if (entity.quarantined) { result.skipped += 1; continue; }
        const relativePath = path.relative(paths.VAULT_ROOT, filePath).split(path.sep).join('/');
        let pageText = fs.readFileSync(filePath, 'utf8');
        let currentOutput = machineRegion(pageText, REGION_SLUG);
        const observedOutputHash = sha1(currentOutput || '');
        const migration = migratePageState(state.pages[relativePath] || {}, currentOutput);
        const saved = migration.pageState;
        if (migration.migrated) result.migrated += 1;

        let stateChanged = migration.migrated;
        let owner = saved.blocks[REGION_SLUG]?.owner;
        const resumeRequested = Boolean(currentOutput?.includes(RESUME_MARKER));
        if (resumeRequested) {
          currentOutput = removeResumeMarker(currentOutput);
          pageText = replaceMachineRegion(pageText, REGION_SLUG, currentOutput);
          saved.blocks[REGION_SLUG] = { owner: 'dex' };
          saved.output_hash = sha1(currentOutput);
          delete saved.last_gardened;
          delete saved.input_hash;
          owner = 'dex';
          stateChanged = true;
          log(`Gardener resumed ${relativePath}: ${REGION_SLUG}`);
        }

        const outputChanged = Object.hasOwn(saved, 'output_hash')
          ? sha1(currentOutput || '') !== saved.output_hash
          : Boolean(currentOutput?.trim());
        if (owner !== 'user' && outputChanged) {
          saved.blocks[REGION_SLUG] = { owner: 'user', reason: 'user-edited' };
          owner = 'user';
          stateChanged = true;
        }
        if (owner === 'user') {
          state.pages[relativePath] = saved;
          if (!dryRun && stateChanged) savePageState(paths.GARDENER_STATE_FILE, relativePath, saved);
          result.preserved += 1;
          result.skipped += 1;
          log(`Gardener preserved ${relativePath}: user-owned ${REGION_SLUG}`);
          continue;
        }
        state.pages[relativePath] = saved;
        if (!dryRun && stateChanged) savePageState(paths.GARDENER_STATE_FILE, relativePath, saved);
        const signal = buildSignal(entity, pageText, meetings);
        const inputHash = sha1(signal);
        const lastGardened = saved.last_gardened ? new Date(saved.last_gardened) : null;
        if (lastGardened && !Number.isNaN(lastGardened.getTime()) && nowDate - lastGardened < WEEK_MS) {
          result.skipped += 1;
          continue;
        }
        if (saved.input_hash === inputHash) { result.skipped += 1; continue; }
        candidates.push({
          filePath,
          relativePath,
          pageText,
          signal,
          inputHash,
          expectedOutputHash: observedOutputHash,
          resumeOutput: resumeRequested ? currentOutput : null,
          saved,
        });
      } catch (error) {
        result.errors.push({ page: filePath, error: error.message });
      }
    }

    candidates.sort((a, b) => {
      const parsedA = a.saved.last_gardened ? new Date(a.saved.last_gardened).getTime() : NaN;
      const parsedB = b.saved.last_gardened ? new Date(b.saved.last_gardened).getTime() : NaN;
      const aTime = Number.isNaN(parsedA) ? -Infinity : parsedA;
      const bTime = Number.isNaN(parsedB) ? -Infinity : parsedB;
      return aTime - bTime || a.relativePath.localeCompare(b.relativePath);
    });

    const selected = candidates.slice(0, maximum);
    result.skipped += candidates.length - selected.length;
    for (const candidate of selected) {
      try {
        const output = cleanOutput(await generate(promptFor(candidate.signal)));
        if (!output) { result.skipped += 1; continue; }
        if (!dryRun) {
          const latestText = fs.readFileSync(candidate.filePath, 'utf8');
          const latestOutput = machineRegion(latestText, REGION_SLUG);
          if (sha1(latestOutput || '') !== candidate.expectedOutputHash) {
            candidate.saved.blocks = blockState(candidate.saved);
            candidate.saved.blocks[REGION_SLUG] = { owner: 'user', reason: 'user-edited' };
            savePageState(paths.GARDENER_STATE_FILE, candidate.relativePath, candidate.saved);
            result.preserved += 1;
            result.skipped += 1;
            log(`Gardener preserved ${candidate.relativePath}: user-owned ${REGION_SLUG}`);
            continue;
          }
          const resumedText = candidate.resumeOutput === null
            ? latestText
            : replaceMachineRegion(latestText, REGION_SLUG, candidate.resumeOutput);
          const withRegion = ensureSummaryRegion(resumedText);
          atomicWritePage(candidate.filePath, replaceMachineRegion(withRegion, REGION_SLUG, output));
          const nextState = {
            ...candidate.saved,
            last_gardened: nowDate.toISOString(),
            input_hash: candidate.inputHash,
            output_hash: sha1(output),
            blocks: {
              ...blockState(candidate.saved),
              [REGION_SLUG]: { owner: 'dex' },
            },
          };
          savePageState(paths.GARDENER_STATE_FILE, candidate.relativePath, nextState);
        }
        result.gardened.push(candidate.relativePath);
      } catch (error) {
        result.errors.push({ page: candidate.relativePath, error: error.message });
      }
    }
  } catch (error) {
    result.errors.push({ page: null, error: error.message });
  }
  return result;
}

module.exports = { gardenEntities };
