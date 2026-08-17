#!/usr/bin/env node
/**
 * PostToolUse hook: add written meeting notes to existing person pages.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const {
  parseEntityPage,
} = require('../../.scripts/lib/entity-pages.cjs');
const {
  flushEntityOps,
} = require('../../.scripts/lib/entity-engine-client.cjs');
const {
  identityForEntity,
} = require('../../.scripts/lib/entity-identity.cjs');
const { loadPaths } = require('./paths.cjs');

const DEBUG_SKIP = process.env.DEX_HOOK_DEBUG === '1';
function skip(reason) {
  if (DEBUG_SKIP) console.error(`[dex-hook-skip] ${reason}`);
  process.exit(0);
}

let input;
try {
  input = JSON.parse(fs.readFileSync(0, 'utf8'));
} catch (_) {
  skip('invalid-json-input');
}

const suppliedPath = input.tool_input?.file_path
  || input.tool_input?.path
  || input.toolInput?.filePath
  || input.toolInput?.file_path
  || input.toolInput?.path
  || '';
if (!suppliedPath || typeof suppliedPath !== 'string') skip('missing-file-path');

const paths = loadPaths();
const vaultRoot = paths.VAULT_ROOT || process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();
// loadPaths() always provides these (JSON and fallback alike); no literal
// fallback here — this hook is not on the path-contract allowlist.
const meetingsDir = paths.MEETINGS_DIR;
const peopleDir = paths.PEOPLE_DIR;
if (!meetingsDir || !peopleDir) skip('paths-unavailable');
const filePath = path.resolve(vaultRoot, suppliedPath);

function isWithin(candidate, directory) {
  const relative = path.relative(path.resolve(directory), candidate);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function configuredNotesDirectory() {
  const profilePath = path.join(vaultRoot, 'System', 'user-profile.yaml');
  try {
    const profile = yaml.load(fs.readFileSync(profilePath, 'utf8'));
    const folder = profile?.meeting_sources?.notes_folder;
    if (typeof folder !== 'string' || !folder.trim() || path.isAbsolute(folder)) return null;
    const parts = folder.trim().split(/[\\/]+/);
    if (parts.includes('..')) return null;
    const candidate = path.resolve(vaultRoot, folder.trim());
    if (candidate === path.resolve(vaultRoot) || !isWithin(candidate, vaultRoot)) return null;
    const realVault = fs.realpathSync(vaultRoot);
    const realCandidate = fs.realpathSync(candidate);
    return isWithin(realCandidate, realVault) ? realCandidate : null;
  } catch (_) {
    return null;
  }
}

const configuredNotesDir = configuredNotesDirectory();
let realFilePath = filePath;
try {
  realFilePath = fs.realpathSync(filePath);
} catch (_) {
  // The ordinary not-found check below owns missing or unreadable paths.
}
if (!isWithin(filePath, meetingsDir)
    && !(configuredNotesDir && isWithin(realFilePath, configuredNotesDir))
    && !filePath.includes('Meeting_Intel')
    && !filePath.includes('Meeting_Notes')) {
  skip('not-a-meeting-note');
}
if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) skip('meeting-note-not-found');

let content;
try {
  content = fs.readFileSync(filePath, 'utf8');
} catch (error) {
  skip(`meeting-note-read-failed:${error.message}`);
}

function frontmatter(text) {
  const match = /^---[ \t]*\r?\n([\s\S]*?)^---[ \t]*\r?$/m.exec(text);
  if (!match || match.index !== 0) return {};
  try {
    const parsed = yaml.load(match[1]);
    return parsed && !Array.isArray(parsed) && typeof parsed === 'object' ? parsed : {};
  } catch (_) {
    return {};
  }
}

function attendeeNames(metadata) {
  if (!Array.isArray(metadata.attendees)) return [];
  return metadata.attendees
    .map((attendee) => typeof attendee === 'string' ? attendee : attendee?.name)
    .filter((name) => typeof name === 'string' && name.trim())
    .map((name) => name.trim());
}

function wikilinkNames(text) {
  return [...text.matchAll(/\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]/g)]
    .map((match) => path.basename(match[1].trim(), '.md'))
    .filter((name) => name.includes('_'));
}

function plainNames(text) {
  const pattern = /(?:met with|attendee|participant|spoke to|with)\s*[:\-]?\s+([A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)+)/g;
  return [...text.matchAll(pattern)].map((match) => match[1].trim());
}

function personStem(name) {
  const stem = path.basename(name.trim(), '.md').replace(/\s+/g, '_');
  return /^[A-Za-z0-9_'’.-]+(?:_[A-Za-z0-9_'’.-]+)+$/.test(stem) ? stem : null;
}

function meetingDate(metadata) {
  const value = metadata.date;
  if (value instanceof Date && !Number.isNaN(value.valueOf())) return value.toISOString().slice(0, 10);
  const fromMetadata = typeof value === 'string' && value.match(/\d{4}-\d{2}-\d{2}/);
  if (fromMetadata) return fromMetadata[0];
  const fromPath = filePath.match(/\d{4}-\d{2}-\d{2}/);
  return fromPath ? fromPath[0] : new Date().toISOString().slice(0, 10);
}

function meetingTitle(metadata) {
  if (typeof metadata.title === 'string' && metadata.title.trim()) return metadata.title.trim();
  const heading = content.match(/^#\s+(.+?)\s*$/m);
  return heading ? heading[1].trim() : path.basename(filePath, '.md').replace(/_/g, ' ');
}

const metadata = frontmatter(content);
const extracted = attendeeNames(metadata);
const names = extracted.length > 0 ? extracted : wikilinkNames(content);
const fallbackNames = names.length > 0 ? names : plainNames(content);
if (fallbackNames.length === 0) skip('no-person-references-found');

const relativeMeetingPath = path.relative(vaultRoot, filePath).split(path.sep).join('/');
const date = meetingDate(metadata);
function captureSourceId(frontmatter) {
  const candidates = Object.entries(frontmatter)
    .filter(([key, value]) => key.endsWith('_id')
      && (typeof value === 'string' || typeof value === 'number')
      && String(value).trim())
    .map(([key, value]) => [key, String(value).trim()]);
  const source = typeof frontmatter.source === 'string'
    ? frontmatter.source.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_')
    : '';
  if (source) {
    const matched = candidates.find(([key]) => key.toLowerCase() === `${source}_id`);
    if (matched) return matched[1];
    return '';
  }
  return candidates.length === 1 ? candidates[0][1] : '';
}

// Capture ids are globally stable when unambiguous. The fallback must be the
// normalized vault-relative Markdown path (POSIX separators, `.md` retained):
// basenames collide as soon as configured and default folders share a title.
const sourceId = captureSourceId(metadata) || relativeMeetingPath;
const interaction = `- [${meetingTitle(metadata)}](${relativeMeetingPath}) — ${date}`;
const seen = new Set();
const ops = [];

try {
  for (const name of fallbackNames) {
    const stem = personStem(name);
    if (!stem || stem.toLowerCase() === 'readme') continue;
    const key = stem.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);

    const personPath = ['Internal', 'External', 'CPO_Network']
      .map((subdir) => path.join(peopleDir, subdir, `${stem}.md`))
      .find((candidate) => fs.existsSync(candidate) && path.basename(candidate).toLowerCase() !== 'readme.md');
    if (!personPath) continue;

    const original = fs.readFileSync(personPath, 'utf8');
    if (original.includes(relativeMeetingPath)) continue;
    const entity = parseEntityPage(personPath);
    if (entity.quarantined) continue;
    ops.push({
      op: 'mutate',
      path: personPath,
      entity_identity: identityForEntity(entity),
      intent: {
        kind: 'hook-interaction',
        interaction: {
          path: relativeMeetingPath,
          line: interaction,
          date,
          source_id: sourceId,
        },
      },
    });
  }
  const write = flushEntityOps({
    vaultRoot,
    ops,
    scope: 'hook',
  });
  if (!write.ok) skip(`entity-write-pending:${write.error || 'retry queued'}`);
} catch (error) {
  skip(`unexpected-error:${error.message}`);
}
