#!/usr/bin/env node
/**
 * auto-link-people.cjs
 *
 * Converts bare person-name references in a markdown file to Obsidian WikiLinks:
 *   Chris Barsanti  →  [[Chris_Barsanti|Chris Barsanti]]
 *   Aaron           →  [[Aaron_Fry|Aaron]]   (only when unambiguous)
 *
 * Safe zones — the following are never modified:
 *   - YAML frontmatter (between opening/closing ---)
 *   - Existing WikiLinks  [[...]]
 *   - Inline code  `...`  and fenced code blocks  ```...```
 *   - Markdown headings, URLs, and HTML tags
 *   - A first name that appears elsewhere as part of an unregistered full name
 *     (e.g. "Jessica Jolly" — avoids linking standalone "Jessica" if "Jessica Jolly"
 *     isn't in the registry but "Jessica" alone resolves to someone else)
 *
 * Registry: built live by scanning People/External/ and People/Internal/ for
 * frontmatter `name:` fields. Falls back to the filename stem if no frontmatter.
 *
 * Usage:
 *   node .scripts/auto-link-people.cjs <file.md> [<file2.md> ...]
 *   node .scripts/auto-link-people.cjs --today     # batch: today's daily plan + new files
 *   node .scripts/auto-link-people.cjs --dry-run <file.md>   # print diff, don't write
 *
 * Exit 0 always (best-effort; never breaks a build).
 */

'use strict';

const fs   = require('fs');
const path = require('path');

const VAULT = path.resolve(__dirname, '..');

// ---------------------------------------------------------------------------
// Registry: scan People/ subdirs for person pages
// ---------------------------------------------------------------------------

function buildRegistry() {
  const dirs = [
    path.join(VAULT, 'People', 'External'),
    path.join(VAULT, 'People', 'Internal'),
  ];

  // Map: canonical name → { wikiTarget, fullName }
  //   wikiTarget  e.g. "Aaron_Fry"   (filename stem without .md)
  //   fullName    e.g. "Aaron Fry"   (from frontmatter `name:` or derived from stem)
  const people = []; // [{firstName, lastName, fullName, wikiTarget, aliases}]

  for (const dir of dirs) {
    if (!fs.existsSync(dir)) continue;
    for (const fname of fs.readdirSync(dir)) {
      if (!fname.endsWith('.md') || fname === 'README.md') continue;
      const stem = fname.replace(/\.md$/, '');          // e.g. "Aaron_Fry"
      const filePath = path.join(dir, fname);

      let fullName = stem.replace(/_/g, ' ');           // default: filename
      try {
        const raw = fs.readFileSync(filePath, 'utf8');
        const fmMatch = raw.match(/^---\r?\n([\s\S]*?)\r?\n---/);
        if (fmMatch) {
          const nameMatch = fmMatch[1].match(/^name:\s*(.+)$/m);
          if (nameMatch) fullName = nameMatch[1].trim();
        }
      } catch (_) { /* skip unreadable files */ }

      const parts = fullName.split(/\s+/).filter(Boolean);
      const firstName = parts[0] || '';
      const lastName  = parts[parts.length - 1] || '';

      people.push({ firstName, lastName, fullName, wikiTarget: stem });
    }
  }

  return people;
}

// ---------------------------------------------------------------------------
// Determine which first names are unambiguous (map to exactly one person)
// ---------------------------------------------------------------------------

function buildLinkMaps(people) {
  // fullNameMap:  "Aaron Fry"  → "Aaron_Fry"
  const fullNameMap = new Map();
  // firstNameMap: "Aaron"      → "Aaron_Fry"  (only if unique)
  const firstNameCounts = new Map();

  for (const p of people) {
    fullNameMap.set(p.fullName.toLowerCase(), p);
    const fn = p.firstName.toLowerCase();
    firstNameCounts.set(fn, (firstNameCounts.get(fn) || 0) + 1);
  }

  // firstNameMap: only include first names that map to exactly one person
  const firstNameMap = new Map();
  for (const p of people) {
    const fn = p.firstName.toLowerCase();
    if (firstNameCounts.get(fn) === 1) {
      firstNameMap.set(fn, p);
    }
  }

  return { fullNameMap, firstNameMap };
}

// ---------------------------------------------------------------------------
// Splitting: separate safe zones from linkable text
// ---------------------------------------------------------------------------

// Returns array of {text, safe} segments.
// safe=true  → do not modify (frontmatter, code, existing wikilinks, URLs, etc.)
function splitSafeZones(content) {
  const segments = [];
  // Patterns matched as SAFE (order matters):
  //   1. YAML frontmatter at file start
  //   2. Fenced code blocks
  //   3. Inline code
  //   4. Existing WikiLinks
  //   5. Markdown images/links with URLs
  //   6. Bare URLs
  const SAFE_RE = new RegExp(
    '(' +
      // 1. frontmatter (only at very start of file)
      '(?:^---\\r?\\n[\\s\\S]*?\\r?\\n---(?:\\r?\\n|$))' +
      // 2. fenced code blocks
      '|(?:```[\\s\\S]*?```|~~~[\\s\\S]*?~~~)' +
      // 3. inline code
      '|(?:`[^`\r\n]+`)' +
      // 4. existing WikiLinks
      '|(?:\\[\\[[^\\]]*\\]\\])' +
      // 5. markdown link/image syntax including URL
      '|(?:!?\\[[^\\]]*\\]\\([^)]*\\))' +
      // 6. bare URLs (http/https)
      '|(?:https?://\\S+)' +
    ')',
    'g'
  );

  let lastIndex = 0;
  let match;
  while ((match = SAFE_RE.exec(content)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: content.slice(lastIndex, match.index), safe: false });
    }
    segments.push({ text: match[0], safe: true });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < content.length) {
    segments.push({ text: content.slice(lastIndex), safe: false });
  }
  return segments;
}

// ---------------------------------------------------------------------------
// Detect unregistered full names that contain a registered first name
// (to prevent false first-name links like "Jessica" when "Jessica Jolly" appears
//  but isn't in the registry)
// ---------------------------------------------------------------------------

function findUnknownFullNames(content, firstNameMap) {
  // "FirstName LastName" patterns where FirstName is in firstNameMap
  // but the full name is NOT in fullNameMap
  const suspicious = new Set();
  // Match Title Case word pairs
  const pairRe = /\b([A-Z][a-z]+)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b/g;
  let m;
  while ((m = pairRe.exec(content)) !== null) {
    const first = m[1].toLowerCase();
    if (firstNameMap.has(first)) {
      // If this full span (first + rest) is NOT itself a registered person, suppress
      // first-name-only linking for that first name in this document.
      suspicious.add(first);
    }
  }
  return suspicious;
}

// ---------------------------------------------------------------------------
// Core replacement logic for a single non-safe text segment
// ---------------------------------------------------------------------------

function linkSegment(text, fullNameMap, firstNameMap, suppress) {
  // Build a combined regex: try full names first (longer matches win), then first names.
  // Sort by descending length so "Brian A. Clark" matches before "Brian".
  const fullNames = [...fullNameMap.keys()].sort((a, b) => b.length - a.length);
  const firstNames = [...firstNameMap.keys()]
    .filter(fn => !suppress.has(fn))
    .sort((a, b) => b.length - a.length);

  // Build alternation: full names (case-insensitive word-boundary) then first names
  // We process the text character-by-character with a single pass regex.
  if (fullNames.length === 0 && firstNames.length === 0) return text;

  const escapeName = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  // Full-name patterns — match the exact capitalisation that exists in the registry
  // by using case-insensitive flag
  const allPatterns = [
    ...fullNames.map(n => escapeName(n)),
    ...firstNames.map(n => escapeName(n)),
  ];

  // (?!['’]\w) — don't treat the "Don" in "Don't" / "don't" as a name; the
  // apostrophe is a non-word char, so \b alone fires mid-contraction.
  const re = new RegExp(`\\b(${allPatterns.join('|')})\\b(?!['’]\\w)`, 'gi');

  return text.replace(re, (match) => {
    const lower = match.toLowerCase();
    const isFullName = fullNameMap.has(lower);
    const person = fullNameMap.get(lower) || firstNameMap.get(lower);
    if (!person) return match; // shouldn't happen but guard
    // Bare first names must be capitalised in the text ("Don", not "don") —
    // lowercase hits are almost always ordinary words, not people.
    if (!isFullName && !/^[A-Z]/.test(match)) return match;
    return `[[${person.wikiTarget}|${match}]]`;
  });
}

// ---------------------------------------------------------------------------
// Process a single file
// ---------------------------------------------------------------------------

function processFile(filePath, { dryRun = false } = {}) {
  const people = buildRegistry();
  if (people.length === 0) {
    console.error('[auto-link] No person pages found in People/. Skipping.');
    return;
  }

  const { fullNameMap, firstNameMap } = buildLinkMaps(people);

  let content;
  try {
    content = fs.readFileSync(filePath, 'utf8');
  } catch (err) {
    console.error(`[auto-link] Cannot read ${filePath}: ${err.message}`);
    return;
  }

  // Detect first-name suppressions for this specific document
  const suppress = findUnknownFullNames(content, firstNameMap);

  const segments = splitSafeZones(content);
  const linked = segments.map(seg =>
    seg.safe ? seg.text : linkSegment(seg.text, fullNameMap, firstNameMap, suppress)
  ).join('');

  if (linked === content) {
    if (dryRun) console.log(`[auto-link] No changes: ${filePath}`);
    return;
  }

  if (dryRun) {
    // Simple line-level diff
    const before = content.split('\n');
    const after  = linked.split('\n');
    const maxLen = Math.max(before.length, after.length);
    for (let i = 0; i < maxLen; i++) {
      if (before[i] !== after[i]) {
        console.log(`L${i+1} - ${before[i] ?? ''}`);
        console.log(`L${i+1} + ${after[i]  ?? ''}`);
      }
    }
    return;
  }

  try {
    fs.writeFileSync(filePath, linked, 'utf8');
    const count = (linked.match(/\[\[/g) || []).length - (content.match(/\[\[/g) || []).length;
    if (count > 0) console.log(`[auto-link] +${count} link(s): ${path.relative(VAULT, filePath)}`);
  } catch (err) {
    console.error(`[auto-link] Cannot write ${filePath}: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// --today: process files created/modified today
// ---------------------------------------------------------------------------

function processToday(opts) {
  const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
  const targets = [];

  // Today's daily plan
  const dailyPlanDir = path.join(VAULT, 'Inbox', 'Daily_Plans');
  if (fs.existsSync(dailyPlanDir)) {
    for (const f of fs.readdirSync(dailyPlanDir)) {
      if (f.startsWith(today) && f.endsWith('.md')) {
        targets.push(path.join(dailyPlanDir, f));
      }
    }
  }

  // Recently modified vault markdown files (Planning, Projects, People)
  const scanDirs = ['Planning', 'Projects', 'Inbox/Meetings'];
  for (const dir of scanDirs) {
    const abs = path.join(VAULT, dir);
    if (!fs.existsSync(abs)) continue;
    scanRecent(abs, today, targets);
  }

  if (targets.length === 0) {
    console.log('[auto-link] --today: no files modified today found.');
    return;
  }

  for (const f of targets) processFile(f, opts);
}

function scanRecent(dir, today, out) {
  try {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) { scanRecent(full, today, out); continue; }
      if (!entry.name.endsWith('.md')) continue;
      const mtime = fs.statSync(full).mtime.toISOString().slice(0, 10);
      if (mtime === today) out.push(full);
    }
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// Expose as module (for require() usage in other scripts)
// ---------------------------------------------------------------------------

function autoLinkContent(content, opts = {}) {
  const people = buildRegistry();
  if (people.length === 0) return content;
  const { fullNameMap, firstNameMap } = buildLinkMaps(people);
  const suppress = findUnknownFullNames(content, firstNameMap);
  const segments = splitSafeZones(content);
  return segments.map(seg =>
    seg.safe ? seg.text : linkSegment(seg.text, fullNameMap, firstNameMap, suppress)
  ).join('');
}

module.exports = { autoLinkContent, buildRegistry, buildLinkMaps };

// ---------------------------------------------------------------------------
// CLI entry point
// ---------------------------------------------------------------------------

if (require.main === module) {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const filtered = args.filter(a => a !== '--dry-run');

  if (filtered[0] === '--today') {
    processToday({ dryRun });
    process.exit(0);
  }

  if (filtered.length === 0) {
    console.error('Usage: node auto-link-people.cjs [--dry-run] <file.md> [...] | --today');
    process.exit(1);
  }

  for (const arg of filtered) {
    const resolved = path.resolve(arg);
    if (!fs.existsSync(resolved)) {
      console.error(`[auto-link] File not found: ${resolved}`);
      continue;
    }
    processFile(resolved, { dryRun });
  }
}
