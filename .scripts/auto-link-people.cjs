#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const { loadPaths } = require('../.claude/hooks/paths.cjs');

const STOPLIST = new Set([
  'Will',
  'May',
  'Mark',
  'Grace',
  'Art',
  'Rose',
  'Dawn',
  'Bill',
  'Penny',
  'Summer',
  'June',
  'April',
  'Jay',
  'Ray',
  'Miles',
  'Drew',
  'Chase',
  'Hope',
  'Faith',
  'Joy',
]);

const WORD_CONTINUATION = /[\p{L}\p{M}\p{N}\p{Pc}\p{Pd}'’\\/|[\]]/u;

function addTarget(targetsByLabel, label, target) {
  if (!label) return;
  if (!targetsByLabel.has(label)) targetsByLabel.set(label, new Set());
  targetsByLabel.get(label).add(target);
}

function collectTargets(label, fullNames, firstTargets, aliasTargets) {
  const targets = new Set();
  if (fullNames.has(label)) targets.add(label);
  for (const target of firstTargets.get(label) || []) targets.add(target);
  for (const target of aliasTargets.get(label) || []) targets.add(target);
  return targets;
}

function onlyValue(values) {
  return values.size === 1 ? values.values().next().value : null;
}

function listMarkdownFiles(rootDirectory) {
  const files = [];

  function visit(directory) {
    let entries;
    try {
      entries = fs.readdirSync(directory, { withFileTypes: true });
    } catch (error) {
      return;
    }

    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const entryPath = path.join(directory, entry.name);
      if (entry.isDirectory()) {
        visit(entryPath);
      } else if (
        entry.isFile()
        && path.extname(entry.name).toLowerCase() === '.md'
        && entry.name.toLowerCase() !== 'readme.md'
      ) {
        files.push(entryPath);
      }
    }
  }

  if (rootDirectory && fs.existsSync(rootDirectory)) visit(rootDirectory);
  return files;
}

function displayNameFromFile(filePath) {
  return path.basename(filePath, path.extname(filePath)).replace(/_/g, ' ').trim();
}

function readOwnerName(profileFile) {
  if (!profileFile || !fs.existsSync(profileFile)) return '';

  try {
    const profile = fs.readFileSync(profileFile, 'utf-8');
    const match = profile.match(/^name\s*:\s*(.*?)\s*$/m);
    if (!match) return '';

    let value = match[1].trim();
    const quote = value[0];
    if ((quote === '"' || quote === "'") && value.endsWith(quote)) {
      value = value.slice(1, -1);
    } else {
      value = value.replace(/\s+#.*$/, '').trim();
    }
    return value.trim();
  } catch (error) {
    return '';
  }
}

// WikiLinks are an Obsidian convention; plain-markdown vaults keep plain
// names (mirrors core/utils/reference_formatter.py). Linking is a no-op
// unless the profile opts in with `obsidian_mode: true`.
function readObsidianMode(profileFile) {
  if (!profileFile || !fs.existsSync(profileFile)) return false;
  try {
    const profile = fs.readFileSync(profileFile, 'utf-8');
    return /^obsidian_mode\s*:\s*true\s*(#.*)?$/m.test(profile);
  } catch (error) {
    return false;
  }
}

function aliasesFromPage(content) {
  const aliases = [];
  const pattern = /\bGoes\s+by\s+["“]([^"”\r\n]+)["”]/giu;
  let match;
  while ((match = pattern.exec(content)) !== null) {
    const alias = match[1].trim();
    if (alias) aliases.push(alias);
  }
  return aliases;
}

function buildRegistry(pathConfig = loadPaths()) {
  const personFiles = listMarkdownFiles(pathConfig.PEOPLE_DIR);
  const fullNames = new Set();
  const firstTargets = new Map();
  const aliasTargets = new Map();
  const targetsByFullName = new Map();

  for (const filePath of personFiles) {
    const fullName = displayNameFromFile(filePath);
    if (!fullName) continue;

    fullNames.add(fullName);
    if (pathConfig.VAULT_ROOT) {
      const relativePath = path.relative(pathConfig.VAULT_ROOT, filePath)
        .split(path.sep)
        .join('/');
      targetsByFullName.set(fullName, relativePath.slice(0, -path.extname(relativePath).length));
    }
    const firstName = fullName.split(/\s+/u)[0];
    addTarget(firstTargets, firstName, fullName);

    try {
      const page = fs.readFileSync(filePath, 'utf-8');
      for (const alias of aliasesFromPage(page)) {
        addTarget(aliasTargets, alias, fullName);
      }
    } catch (error) {
      // An unreadable person page should not prevent other pages being indexed.
    }
  }

  const firstNameToFull = new Map();
  for (const firstName of firstTargets.keys()) {
    const targets = collectTargets(firstName, fullNames, firstTargets, aliasTargets);
    firstNameToFull.set(firstName, onlyValue(targets));
  }

  const aliases = new Map();
  for (const alias of aliasTargets.keys()) {
    const targets = collectTargets(alias, fullNames, firstTargets, aliasTargets);
    const target = onlyValue(targets);
    if (target) aliases.set(alias, target);
  }

  return {
    fullNames,
    firstNameToFull,
    ownerName: readOwnerName(pathConfig.USER_PROFILE_FILE),
    aliases,
    targetsByFullName,
  };
}

function linesWithOffsets(text) {
  const lines = [];
  let start = 0;

  while (start < text.length) {
    let contentEnd = start;
    while (contentEnd < text.length && text[contentEnd] !== '\n' && text[contentEnd] !== '\r') {
      contentEnd += 1;
    }

    let end = contentEnd;
    if (text[end] === '\r' && text[end + 1] === '\n') end += 2;
    else if (text[end] === '\r' || text[end] === '\n') end += 1;

    lines.push({ start, contentEnd, end, body: text.slice(start, contentEnd) });
    start = end;
  }

  return lines;
}

function findBlockRanges(text) {
  const lines = linesWithOffsets(text);
  const ranges = [];
  let frontmatterEnd = 0;

  if (lines.length > 0 && lines[0].body.replace(/^\uFEFF/u, '') === '---') {
    let closingLine = null;
    for (let index = 1; index < lines.length; index += 1) {
      if (lines[index].body === '---' || lines[index].body === '...') {
        closingLine = lines[index];
        break;
      }
    }
    frontmatterEnd = closingLine ? closingLine.end : text.length;
    ranges.push({ start: 0, end: frontmatterEnd, type: 'frontmatter' });
  }

  let openFence = null;
  for (const line of lines) {
    if (line.start < frontmatterEnd) continue;

    if (!openFence) {
      const opener = line.body.match(/^ {0,3}(`{3,}|~{3,})/u);
      if (opener) {
        openFence = {
          start: line.start,
          character: opener[1][0],
          length: opener[1].length,
        };
      }
      continue;
    }

    const closingPattern = new RegExp(
      `^ {0,3}${openFence.character}{${openFence.length},}\\s*$`,
      'u',
    );
    if (closingPattern.test(line.body)) {
      ranges.push({ start: openFence.start, end: line.end, type: 'fence' });
      openFence = null;
    }
  }

  if (openFence) ranges.push({ start: openFence.start, end: text.length, type: 'fence' });
  return ranges.sort((left, right) => left.start - right.start);
}

function containingRange(index, ranges) {
  for (const range of ranges) {
    if (range.start > index) return null;
    if (range.start <= index && index < range.end) return range;
  }
  return null;
}

function findClosingBracket(text, openIndex) {
  let depth = 1;
  for (let index = openIndex + 1; index < text.length; index += 1) {
    if (text[index] === '\\') {
      index += 1;
      continue;
    }
    if (text[index] === '[') depth += 1;
    if (text[index] === ']') {
      depth -= 1;
      if (depth === 0) return index;
    }
    if (text[index] === '\n' || text[index] === '\r') return -1;
  }
  return -1;
}

function findClosingDestination(text, openIndex) {
  let depth = 1;
  for (let index = openIndex + 1; index < text.length; index += 1) {
    if (text[index] === '\\') {
      index += 1;
      continue;
    }
    if (text[index] === '(') depth += 1;
    if (text[index] === ')') {
      depth -= 1;
      if (depth === 0) return index;
    }
    if (text[index] === '\n' || text[index] === '\r') return -1;
  }
  return -1;
}

function normalizeReferenceLabel(label) {
  return label.trim().replace(/\s+/gu, ' ').toLowerCase();
}

function findReferenceLabels(text, blockRanges) {
  const labels = new Set();
  const definitionPattern = /^ {0,3}\[([^\]\r\n]+)\]:/gmu;
  let match;
  while ((match = definitionPattern.exec(text)) !== null) {
    if (!rangesOverlap(match.index, match.index + match[0].length, blockRanges)) {
      labels.add(normalizeReferenceLabel(match[1]));
    }
  }
  return labels;
}

function findMarkdownLinkEnd(text, labelOpen, labelClose, referenceLabels) {
  const next = labelClose + 1;
  if (text[next] === '(') {
    const destinationClose = findClosingDestination(text, next);
    return destinationClose === -1 ? -1 : destinationClose + 1;
  }

  if (text[next] === '[') {
    const referenceClose = findClosingBracket(text, next);
    return referenceClose === -1 ? -1 : referenceClose + 1;
  }

  if (text[next] === ':') {
    let lineEnd = next + 1;
    while (lineEnd < text.length && text[lineEnd] !== '\n' && text[lineEnd] !== '\r') {
      lineEnd += 1;
    }
    return lineEnd;
  }

  const label = normalizeReferenceLabel(text.slice(labelOpen + 1, labelClose));
  if (referenceLabels.has(label)) return labelClose + 1;

  return -1;
}

function findInlineRanges(text, blockRanges) {
  const ranges = [];
  const wikiRanges = [];
  const referenceLabels = findReferenceLabels(text, blockRanges);
  let index = 0;

  while (index < text.length) {
    const blockRange = containingRange(index, blockRanges);
    if (blockRange) {
      index = blockRange.end;
      continue;
    }

    if (text.startsWith('[[', index)) {
      const close = text.indexOf(']]', index + 2);
      if (close !== -1) {
        const range = { start: index, end: close + 2, type: 'wiki' };
        ranges.push(range);
        wikiRanges.push(range);
        index = range.end;
        continue;
      }
    }

    if (text.startsWith('\\[\\[', index)) {
      const escapedClose = text.indexOf('\\]\\]', index + 4);
      const plainClose = text.indexOf(']]', index + 4);
      const closes = [
        escapedClose === -1 ? -1 : escapedClose + 4,
        plainClose === -1 ? -1 : plainClose + 2,
      ].filter((value) => value !== -1);
      if (closes.length > 0) {
        const end = Math.min(...closes);
        ranges.push({ start: index, end, type: 'escaped-wiki' });
        index = end;
        continue;
      }
    }

    if (text[index] === '`') {
      let runEnd = index + 1;
      while (text[runEnd] === '`') runEnd += 1;
      const marker = text.slice(index, runEnd);
      let close = text.indexOf(marker, runEnd);
      while (close !== -1 && (text[close - 1] === '`' || text[close + marker.length] === '`')) {
        close = text.indexOf(marker, close + marker.length);
      }
      if (close !== -1) {
        const end = close + marker.length;
        ranges.push({ start: index, end, type: 'inline-code' });
        index = end;
        continue;
      }
    }

    const isImage = text[index] === '!' && text[index + 1] === '[';
    const labelOpen = isImage ? index + 1 : index;
    if (text[labelOpen] === '[') {
      const labelClose = findClosingBracket(text, labelOpen);
      if (labelClose !== -1) {
        const linkEnd = findMarkdownLinkEnd(text, labelOpen, labelClose, referenceLabels);
        if (linkEnd !== -1) {
          ranges.push({ start: index, end: linkEnd, type: 'markdown-link' });
          index = linkEnd;
          continue;
        }
      }
    }

    const urlMatch = text.slice(index).match(
      /^[A-Za-z][A-Za-z0-9+.-]*:(?:\/\/)?[^\s<>\[\]]+/u,
    );
    if (urlMatch) {
      const end = index + urlMatch[0].length;
      ranges.push({ start: index, end, type: 'url' });
      index = end;
      continue;
    }

    index += 1;
  }

  return { ranges, wikiRanges };
}

function mergeRanges(ranges) {
  const sorted = [...ranges].sort((left, right) => left.start - right.start || left.end - right.end);
  const merged = [];
  for (const range of sorted) {
    const previous = merged[merged.length - 1];
    if (previous && range.start <= previous.end) {
      previous.end = Math.max(previous.end, range.end);
    } else {
      merged.push({ start: range.start, end: range.end });
    }
  }
  return merged;
}

function rangesOverlap(start, end, ranges) {
  for (const range of ranges) {
    if (range.start >= end) return false;
    if (range.end > start && range.start < end) return true;
  }
  return false;
}

function codePointBefore(text, index) {
  if (index <= 0) return '';
  const finalUnit = text.charCodeAt(index - 1);
  if (finalUnit >= 0xDC00 && finalUnit <= 0xDFFF && index >= 2) {
    const firstUnit = text.charCodeAt(index - 2);
    if (firstUnit >= 0xD800 && firstUnit <= 0xDBFF) return text.slice(index - 2, index);
  }
  return text[index - 1];
}

function codePointAt(text, index) {
  if (index >= text.length) return '';
  return String.fromCodePoint(text.codePointAt(index));
}

function boundaryIsSafe(text, start, length) {
  const previous = codePointBefore(text, start);
  const next = codePointAt(text, start + length);
  return (!previous || !WORD_CONTINUATION.test(previous))
    && (!next || !WORD_CONTINUATION.test(next));
}

function canonicalWikiTarget(text, range) {
  let target = text.slice(range.start + 2, range.end - 2).split('|', 1)[0].trim();
  target = target.split('#', 1)[0].trim();
  target = target.replace(/\\/g, '/');
  target = path.posix.basename(target);
  if (target.toLowerCase().endsWith('.md')) target = target.slice(0, -3);
  return target.replace(/_/g, ' ');
}

function wikiLinkLabel(text, range) {
  const body = text.slice(range.start + 2, range.end - 2);
  const separator = body.indexOf('|');
  return separator === -1 ? '' : body.slice(separator + 1).trim();
}

function normalizedPersonName(name) {
  return name.trim().replace(/\s+/gu, ' ').toLowerCase();
}

function findPoisonedFirstNames(text, registry, protectedRanges) {
  const poisoned = new Set();
  const pattern = /[\p{Lu}][\p{L}\p{M}'’\p{Pd}]*/gu;
  let match;

  while ((match = pattern.exec(text)) !== null) {
    const tail = text.slice(match.index + match[0].length).match(
      /^[ \t]+([\p{Lu}][\p{L}\p{M}'’\p{Pd}]*)/u,
    );
    if (!tail) continue;

    const start = match.index;
    const phraseLength = match[0].length + tail[0].length;
    const end = start + phraseLength;
    if (rangesOverlap(start, end, protectedRanges)) continue;
    if (!boundaryIsSafe(text, start, phraseLength)) continue;

    const startsKnownFullName = [...registry.fullNames].some((knownFullName) => (
      text.startsWith(knownFullName, start)
      && boundaryIsSafe(text, start, knownFullName.length)
      && !rangesOverlap(start, start + knownFullName.length, protectedRanges)
    ));
    if (startsKnownFullName) continue;

    const fullName = `${match[0]} ${tail[1]}`;
    if (!registry.fullNames.has(fullName) && registry.firstNameToFull.has(match[0])) {
      poisoned.add(match[0]);
    }
  }

  return poisoned;
}

function autoLinkContent(text, registry = buildRegistry()) {
  const blockRanges = findBlockRanges(text);
  const inline = findInlineRanges(text, blockRanges);
  const protectedRanges = mergeRanges([...blockRanges, ...inline.ranges]);
  const linkedPeople = new Set();
  const peopleByReferenceName = new Map();

  for (const fullName of registry.fullNames) {
    peopleByReferenceName.set(normalizedPersonName(fullName), fullName);
  }
  for (const [alias, fullName] of registry.aliases || []) {
    peopleByReferenceName.set(normalizedPersonName(alias), fullName);
  }

  for (const wikiRange of inline.wikiRanges) {
    const target = canonicalWikiTarget(text, wikiRange);
    const label = wikiLinkLabel(text, wikiRange);
    const linkedPerson = peopleByReferenceName.get(normalizedPersonName(target))
      || peopleByReferenceName.get(normalizedPersonName(label));
    if (linkedPerson) linkedPeople.add(linkedPerson);
  }

  const poisoned = findPoisonedFirstNames(text, registry, protectedRanges);
  const ownerName = registry.ownerName || '';
  const ownerFirstName = ownerName ? ownerName.split(/\s+/u)[0] : '';
  const candidates = [];

  for (const fullName of registry.fullNames) {
    if (fullName === ownerName) continue;
    candidates.push({ text: fullName, target: fullName, kind: 'full', priority: 0 });
  }

  for (const [alias, fullName] of registry.aliases || []) {
    if (!fullName || fullName === ownerName || alias === ownerName || alias === ownerFirstName) continue;
    candidates.push({ text: alias, target: fullName, kind: 'alias', priority: 1 });
  }

  for (const [firstName, fullName] of registry.firstNameToFull) {
    if (
      !fullName
      || fullName === ownerName
      || firstName === ownerName
      || firstName === ownerFirstName
      || STOPLIST.has(firstName)
      || poisoned.has(firstName)
    ) {
      continue;
    }
    candidates.push({ text: firstName, target: fullName, kind: 'first', priority: 2 });
  }

  const occurrences = [];
  for (const candidate of candidates) {
    if (!candidate.text) continue;
    let fromIndex = 0;
    while (fromIndex < text.length) {
      const start = text.indexOf(candidate.text, fromIndex);
      if (start === -1) break;
      const end = start + candidate.text.length;
      if (
        boundaryIsSafe(text, start, candidate.text.length)
        && !rangesOverlap(start, end, protectedRanges)
      ) {
        occurrences.push({ ...candidate, start, end });
      }
      fromIndex = start + Math.max(1, candidate.text.length);
    }
  }

  occurrences.sort((left, right) => (
    left.start - right.start
    || (right.end - right.start) - (left.end - left.start)
    || left.priority - right.priority
    || left.target.localeCompare(right.target)
  ));

  const replacements = [];
  for (const occurrence of occurrences) {
    if (linkedPeople.has(occurrence.target)) continue;
    if (rangesOverlap(occurrence.start, occurrence.end, replacements)) continue;

    const linkTarget = registry.targetsByFullName?.get(occurrence.target);
    const replacement = linkTarget
      ? `[[${linkTarget}|${occurrence.text}]]`
      : occurrence.kind === 'full'
        ? `[[${occurrence.target}]]`
        : `[[${occurrence.target}|${occurrence.text}]]`;
    replacements.push({
      start: occurrence.start,
      end: occurrence.end,
      replacement,
    });
    linkedPeople.add(occurrence.target);
  }

  let linkedText = text;
  replacements.sort((left, right) => right.start - left.start);
  for (const replacement of replacements) {
    linkedText = linkedText.slice(0, replacement.start)
      + replacement.replacement
      + linkedText.slice(replacement.end);
  }
  return linkedText;
}

function addedWikiLinks(original, linked) {
  const existingCounts = new Map();
  for (const match of original.matchAll(/\[\[[^\]\r\n]+\]\]/gu)) {
    existingCounts.set(match[0], (existingCounts.get(match[0]) || 0) + 1);
  }

  const added = [];
  for (const match of linked.matchAll(/\[\[[^\]\r\n]+\]\]/gu)) {
    const remaining = existingCounts.get(match[0]) || 0;
    if (remaining > 0) existingCounts.set(match[0], remaining - 1);
    else added.push(match[0]);
  }
  return added;
}

function displayPath(filePath, vaultRoot) {
  const relative = vaultRoot ? path.relative(vaultRoot, filePath) : '';
  return relative && !relative.startsWith('..') ? relative : filePath;
}

function processFile(filePath, options) {
  const absolutePath = path.resolve(filePath);
  if (!fs.existsSync(absolutePath) || !fs.statSync(absolutePath).isFile()) {
    throw new Error(`File not found: ${absolutePath}`);
  }

  const original = fs.readFileSync(absolutePath, 'utf-8');
  const linked = autoLinkContent(original, options.registry);
  const added = addedWikiLinks(original, linked);
  if (linked !== original && !options.dryRun) {
    fs.writeFileSync(absolutePath, linked, 'utf-8');
  }
  return { filePath: absolutePath, changed: linked !== original, added };
}

function reportResult(result, options) {
  const fileName = displayPath(result.filePath, options.vaultRoot);
  if (!result.changed) {
    console.log(`${fileName}: no changes`);
    return;
  }

  const noun = result.added.length === 1 ? 'link' : 'links';
  if (options.dryRun) {
    console.log(`[dry-run] ${fileName}: would add ${result.added.length} person ${noun}`);
  } else {
    console.log(`${fileName}: added ${result.added.length} person ${noun}`);
  }
  for (const wikiLink of result.added) console.log(`  ${wikiLink}`);
}

function localDateString(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function isTodaysMeeting(filePath, meetingsDirectory, today) {
  const relative = path.relative(meetingsDirectory, filePath);
  if (relative.split(path.sep).includes(today)) return true;

  const stem = path.basename(filePath, path.extname(filePath));
  return stem === today
    || stem.startsWith(`${today}-`)
    || stem.startsWith(`${today}_`)
    || stem.startsWith(`${today} `);
}

function printUsage() {
  console.error('Usage: node .scripts/auto-link-people.cjs <file>');
  console.error('       node .scripts/auto-link-people.cjs --dry-run <file>');
  console.error('       node .scripts/auto-link-people.cjs [--dry-run] --today');
}

function runCli() {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const remaining = args.filter((argument) => argument !== '--dry-run');
  const todayMode = remaining.includes('--today');
  const paths = loadPaths();
  if (!readObsidianMode(paths.USER_PROFILE_FILE)) {
    console.log('Auto-link skipped: obsidian_mode is false.');
    return;
  }
  const registry = buildRegistry(paths);
  const options = { dryRun, registry, vaultRoot: paths.VAULT_ROOT };

  if (todayMode) {
    if (remaining.length !== 1) {
      printUsage();
      process.exitCode = 1;
      return;
    }

    const today = localDateString();
    const meetingFiles = listMarkdownFiles(paths.MEETINGS_DIR)
      .filter((filePath) => isTodaysMeeting(filePath, paths.MEETINGS_DIR, today));
    if (meetingFiles.length === 0) {
      console.log(`No meeting notes found for ${today}.`);
      return;
    }

    for (const filePath of meetingFiles) {
      const result = processFile(filePath, options);
      reportResult(result, options);
    }
    return;
  }

  if (remaining.length !== 1 || remaining[0].startsWith('--')) {
    printUsage();
    process.exitCode = 1;
    return;
  }

  const result = processFile(remaining[0], options);
  reportResult(result, options);
}

if (require.main === module) {
  try {
    runCli();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

/**
 * Link person names across a batch of files (used by the background sync).
 * Gated on obsidian_mode; builds the registry once; never throws per-file —
 * a bad file is skipped and counted, the rest still link.
 * Returns { changed, skipped, results }.
 */
function autoLinkFiles(files, options = {}) {
  const paths = loadPaths();
  if (!readObsidianMode(paths.USER_PROFILE_FILE)) {
    return { changed: 0, skipped: 'obsidian_mode_off', results: [] };
  }
  const registry = buildRegistry(paths);
  const runOptions = { dryRun: Boolean(options.dryRun), registry, vaultRoot: paths.VAULT_ROOT };
  const results = [];
  let changed = 0;
  for (const filePath of Array.isArray(files) ? files : []) {
    if (!filePath) continue;
    try {
      const result = processFile(filePath, runOptions);
      results.push(result);
      if (result.changed) changed += 1;
    } catch (error) {
      results.push({ filePath, changed: false, error: error.message });
    }
  }
  return { changed, skipped: null, results };
}

module.exports = { autoLinkContent, buildRegistry, autoLinkFiles, readObsidianMode };
