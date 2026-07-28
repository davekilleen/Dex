#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { loadPaths } = require('./paths.cjs');

let yaml = null;
try {
  yaml = require('js-yaml');
} catch (error) {
  // Filename, day-directory, and text signals remain available without YAML.
}

let CONTRACT = null;
try {
  CONTRACT = loadPaths();
} catch (error) {
  // A missing path contract makes the check inapplicable.
}

const DAY_MS = 24 * 60 * 60 * 1000;
const THROTTLE_SECONDS = 30 * 60;

function emptyResult() {
  return { count: 0, lines: [] };
}

function anchoredPaths(vaultRoot) {
  if (!CONTRACT?.VAULT_ROOT || !CONTRACT?.MEETINGS_DIR || !CONTRACT?.SYSTEM_DIR) {
    return null;
  }

  const rel = (contractPath) => path.relative(CONTRACT.VAULT_ROOT, contractPath);
  const meetingsDir = path.join(vaultRoot, rel(CONTRACT.MEETINGS_DIR));
  const systemDir = path.join(vaultRoot, rel(CONTRACT.SYSTEM_DIR));
  return { meetingsDir, systemDir };
}

function isThrottled(markerPath, nowSeconds) {
  try {
    if (!fs.existsSync(markerPath)) return false;
    const value = fs.readFileSync(markerPath, 'utf8').trim();
    if (!/^\d+$/.test(value)) return false;
    return nowSeconds - Number(value) < THROTTLE_SECONDS;
  } catch (error) {
    return true;
  }
}

function parseFrontmatter(source) {
  const match = source.match(/^---[ \t]*\r?\n([\s\S]*?)\r?\n---(?:[ \t]*\r?\n|$)/);
  if (!match || !yaml) return null;

  let document;
  try {
    document = yaml.load(match[1]);
  } catch (error) {
    return null;
  }
  if (!document || typeof document !== 'object' || Array.isArray(document)) return null;

  const fields = {};
  for (const key of ['date', 'ai_analyzed']) {
    if (!Object.hasOwn(document, key) || document[key] === null) continue;
    fields[key] = document[key] instanceof Date
      ? document[key].toISOString()
      : String(document[key]).trim();
  }

  return {
    fields,
    body: source.slice(match[0].length),
  };
}

function dayFromValue(value) {
  if (!value) return null;
  const match = value.match(/^(\d{4}-\d{2}-\d{2})(?:[T\s].*)?$/);
  if (!match) return null;
  const timestamp = Date.parse(`${match[1]}T00:00:00Z`);
  if (!Number.isFinite(timestamp)) return null;
  if (new Date(timestamp).toISOString().slice(0, 10) !== match[1]) return null;
  return { day: match[1], timestamp };
}

function isRecentDay(value, nowMilliseconds) {
  const parsed = dayFromValue(value);
  if (!parsed) return false;
  const today = new Date(nowMilliseconds).toISOString().slice(0, 10);
  const todayStart = Date.parse(`${today}T00:00:00Z`);
  return parsed.day <= today && parsed.timestamp >= todayStart - (7 * DAY_MS);
}

function datePrefixFromFilename(filePath) {
  const match = path.basename(filePath).match(/^(\d{4}-\d{2}-\d{2})(?:\b|_)/);
  return match?.[1] || null;
}

function resolveNoteDay(filePath, frontmatterDate, fallbackDay) {
  for (const candidate of [
    frontmatterDate,
    datePrefixFromFilename(filePath),
    fallbackDay,
  ]) {
    const parsed = dayFromValue(candidate);
    if (parsed) return parsed.day;
  }
  return null;
}

function hasUncheckedForMeItem(source) {
  let underForMe = false;
  for (const line of source.split(/\r?\n/)) {
    if (/^###\s+For Me\s*$/i.test(line)) {
      underForMe = true;
      continue;
    }
    if (underForMe && /^#{1,3}\s+/.test(line)) {
      underForMe = false;
      continue;
    }
    if (underForMe && /^\s*-\s+\[ \](?:\s+|$)/.test(line)) return true;
  }
  return false;
}

function noteIsWaiting(filePath, fallbackDay, nowMilliseconds) {
  try {
    const source = fs.readFileSync(filePath, 'utf8');
    const parsed = parseFrontmatter(source);

    const day = resolveNoteDay(filePath, parsed?.fields.date, fallbackDay);
    if (!isRecentDay(day, nowMilliseconds)) return false;

    if (
      /<!--\s*tasks-extracted:/.test(source)
      || source.includes('<!-- dex:skip-processing -->')
    ) {
      return false;
    }
    if (parsed?.fields.ai_analyzed?.toLowerCase() === 'false') return true;
    return hasUncheckedForMeItem(parsed ? parsed.body : source);
  } catch (error) {
    return false;
  }
}

function countWaitingNotes(meetingsDir, nowMilliseconds) {
  let entries;
  try {
    entries = fs.readdirSync(meetingsDir, { withFileTypes: true });
  } catch (error) {
    return 0;
  }

  let count = 0;
  for (const file of entries) {
    if (!file.isFile() || !file.name.endsWith('.md')) continue;
    if (noteIsWaiting(
      path.join(meetingsDir, file.name),
      null,
      nowMilliseconds,
    )) {
      count += 1;
    }
  }

  for (const dayDirectory of entries) {
    if (!dayDirectory.isDirectory()) continue;
    const directoryPath = path.join(meetingsDir, dayDirectory.name);
    let files;
    try {
      files = fs.readdirSync(directoryPath, { withFileTypes: true });
    } catch (error) {
      continue;
    }

    for (const file of files) {
      if (!file.isFile() || !file.name.endsWith('.md')) continue;
      if (noteIsWaiting(
        path.join(directoryPath, file.name),
        dayDirectory.name,
        nowMilliseconds,
      )) {
        count += 1;
      }
    }
  }
  return count;
}

function countQueueFiles(meetingsDir) {
  try {
    return fs.readdirSync(path.join(meetingsDir, 'queue'), { withFileTypes: true })
      .filter((entry) => entry.isFile() && entry.name.endsWith('.json'))
      .length;
  } catch (error) {
    return 0;
  }
}

function noticeLines(count) {
  const noun = count === 1 ? 'meeting' : 'meetings';
  const verb = count === 1 ? 'has' : 'have';
  return [
    `--- 📋 Meetings waiting to be processed (${count}) ---`,
    `${count} ${noun} ${verb} not been processed yet (person pages, tasks, notes).`,
    "After you finish responding to the user's first message, invoke the",
    '/process-meetings skill to handle them in the background — it runs forked and',
    'is idempotent, so do this without being asked. Tell the user in one short line',
    'that meetings are being processed in the background.',
    "If the user's first message IS about meetings, just process them as part of it.",
    '---',
  ];
}

function checkMeetingQueue(options = {}) {
  try {
    const {
      vaultRoot = process.cwd(),
      now = Date.now(),
    } = options || {};
    const nowMilliseconds = Number(now);
    if (typeof vaultRoot !== 'string' || !Number.isFinite(nowMilliseconds)) {
      return emptyResult();
    }

    const paths = anchoredPaths(path.resolve(vaultRoot));
    if (!paths) return emptyResult();

    const markerPath = path.join(paths.systemDir, '.last-meeting-queue-notice');
    const nowSeconds = Math.floor(nowMilliseconds / 1000);
    if (isThrottled(markerPath, nowSeconds)) return emptyResult();

    let meetingsDirectory;
    try {
      meetingsDirectory = fs.statSync(paths.meetingsDir);
    } catch (error) {
      return emptyResult();
    }
    if (!meetingsDirectory.isDirectory()) return emptyResult();

    const count = countWaitingNotes(paths.meetingsDir, nowMilliseconds)
      + countQueueFiles(paths.meetingsDir);
    if (count === 0) return emptyResult();

    try {
      fs.mkdirSync(paths.systemDir, { recursive: true });
      fs.writeFileSync(markerPath, `${nowSeconds}\n`);
    } catch (error) {
      // A notice still helps even when its throttle marker cannot be persisted.
    }

    return { count, lines: noticeLines(count) };
  } catch (error) {
    return emptyResult();
  }
}

module.exports = { checkMeetingQueue };

if (require.main === module) {
  try {
    const result = checkMeetingQueue({ vaultRoot: process.argv[2] || process.cwd() });
    if (result.count > 0) process.stdout.write(`${result.lines.join('\n')}\n`);
  } catch (error) {
    // Silent by design.
  }
  process.exitCode = 0;
}
