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
  replaceMachineRegionInFile,
  upsertFrontmatter,
} = require('../../.scripts/lib/entity-pages.cjs');
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

if (!isWithin(filePath, meetingsDir)
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

function appendLegacyInteraction(personPath, line) {
  const original = fs.readFileSync(personPath, 'utf8');
  const headings = [/^## Recent Interactions\s*$/m, /^## Recent Meetings\s*$/m, /^## Meetings\s*$/m];
  for (const heading of headings) {
    const match = heading.exec(original);
    if (!match) continue;
    const insertion = match.index + match[0].length;
    const suffix = original.slice(insertion);
    fs.writeFileSync(personPath, `${original.slice(0, insertion)}\n${line}${suffix.startsWith('\n') ? '' : '\n'}${suffix}`);
    return;
  }
  fs.writeFileSync(personPath, `${original.replace(/\s*$/, '')}\n\n${line}\n`);
}

const metadata = frontmatter(content);
const extracted = attendeeNames(metadata);
const names = extracted.length > 0 ? extracted : wikilinkNames(content);
const fallbackNames = names.length > 0 ? names : plainNames(content);
if (fallbackNames.length === 0) skip('no-person-references-found');

const relativeMeetingPath = path.relative(vaultRoot, filePath).split(path.sep).join('/');
const date = meetingDate(metadata);
const interaction = `- [${meetingTitle(metadata)}](${relativeMeetingPath}) — ${date}`;
const seen = new Set();

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

    if (original.includes('<!-- dex:auto:recent-interactions -->')) {
      const region = /<!-- dex:auto:recent-interactions -->\r?\n?([\s\S]*?)<!-- \/dex:auto -->/.exec(original);
      const existing = region
        ? region[1].split(/\r?\n/).map((line) => line.trim()).filter((line) => line.startsWith('- '))
        : [];
      const newestFirst = [interaction, ...existing].sort((left, right) => {
        const leftDate = left.match(/\d{4}-\d{2}-\d{2}\s*$/)?.[0] || '';
        const rightDate = right.match(/\d{4}-\d{2}-\d{2}\s*$/)?.[0] || '';
        return rightDate.localeCompare(leftDate);
      });
      replaceMachineRegionInFile(personPath, 'recent-interactions', newestFirst.slice(0, 20).join('\n'));
    } else {
      appendLegacyInteraction(personPath, interaction);
    }

    if (!entity.last_interaction || date > entity.last_interaction) {
      upsertFrontmatter(personPath, { last_interaction: date });
    }
  }
} catch (error) {
  skip(`unexpected-error:${error.message}`);
}
