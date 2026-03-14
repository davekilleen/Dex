#!/usr/bin/env node
/**
 * Meeting Cache Builder
 *
 * Extracts structured summaries from meeting notes and caches them
 * for fast lookup by /meeting-prep, /daily-plan, and entity context.
 *
 * Usage: node meeting-cache-builder.cjs [--rebuild]
 *   --rebuild: Reprocess all meetings (not just recent ones)
 *
 * Reads: 00-Inbox/Meetings/*.md
 * Writes: System/Memory/meeting-cache.json
 */

const fs = require("fs");
const path = require("path");

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VAULT_ROOT =
  process.env.CLAUDE_PROJECT_DIR || path.resolve(__dirname, "../..");
const MEETINGS_DIR = path.join(VAULT_ROOT, "00-Inbox", "Meetings");
const CACHE_FILE = path.join(VAULT_ROOT, "System", "Memory", "meeting-cache.json");
const PRUNE_DAYS = 90;
const REBUILD = process.argv.includes("--rebuild");

// ---------------------------------------------------------------------------
// YAML frontmatter parser (simple regex — no dependencies)
// ---------------------------------------------------------------------------

/**
 * Parse YAML frontmatter from markdown content.
 * @param {string} content - Raw markdown file content
 * @returns {Record<string, string | string[]>} Parsed key-value pairs
 */
function parseFrontmatter(content) {
  const match = content.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return {};
  const fm = {};
  match[1].split("\n").forEach((line) => {
    const kv = line.match(/^(\w+):\s*(.+)/);
    if (kv) {
      let val = kv[2].trim();
      // Handle YAML arrays: [item1, item2]
      if (val.startsWith("[") && val.endsWith("]")) {
        val = val
          .slice(1, -1)
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      }
      // Strip surrounding quotes
      if (typeof val === "string" && val.startsWith('"') && val.endsWith('"')) {
        val = val.slice(1, -1);
      }
      fm[kv[1]] = val;
    }
  });
  return fm;
}

// ---------------------------------------------------------------------------
// Section extraction helpers
// ---------------------------------------------------------------------------

/**
 * Extract bullet items from a markdown section.
 * Looks for ## heading, then collects lines starting with - until the next ## or EOF.
 */
function extractSection(content, heading) {
  // Find the heading line (case-insensitive)
  const lines = content.split("\n");
  const headingLower = heading.toLowerCase();
  let startIdx = -1;

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim().toLowerCase();
    if (trimmed.startsWith("## ") && trimmed.slice(3).trim().startsWith(headingLower)) {
      startIdx = i + 1;
      break;
    }
  }

  if (startIdx === -1) return [];

  // Collect lines until next ## heading or end of content
  const blockLines = [];
  for (let i = startIdx; i < lines.length; i++) {
    if (lines[i].trim().startsWith("## ")) break;
    blockLines.push(lines[i]);
  }

  const block = blockLines.join("\n");
  const items = [];
  for (const line of block.split("\n")) {
    const trimmed = line.trim();
    // Match lines starting with - or - [ ] / - [x] (action item checkboxes)
    if (trimmed.startsWith("- ")) {
      let item = trimmed.slice(2).trim();
      // Strip checkbox markers: [ ] or [x]
      item = item.replace(/^\[[ x]\]\s*/, "");
      // Strip task IDs: ^task-XXXXXXXX-XXX
      item = item.replace(/\s*\^task-\d{8}-\d{3}\s*$/, "");
      // Strip WikiLink wrappers: [[path|display]] -> display
      item = item.replace(/\[\[[^\]|]*\|([^\]]*)\]\]/g, "$1");
      item = item.replace(/\[\[([^\]]*)\]\]/g, "$1");
      // Strip bold markers: **text** -> text
      item = item.replace(/\*\*([^*]+)\*\*/g, "$1");
      if (item.length > 0) {
        items.push(item);
      }
    }
  }
  return items;
}

/**
 * Extract the meeting title from the first H1 heading.
 */
function extractTitle(content) {
  const match = content.match(/^# (.+)$/m);
  if (match) return match[1].trim();
  return null;
}

// ---------------------------------------------------------------------------
// Sentiment detection (simple keyword-based)
// ---------------------------------------------------------------------------

const POSITIVE_SIGNALS = [
  "approved",
  "agreed",
  "on track",
  "aligned",
  "excited",
  "committed",
  "confirmed",
  "strong",
  "momentum",
  "enthusiastic",
  "successful",
  "expansion",
];

const NEGATIVE_SIGNALS = [
  "blocked",
  "delayed",
  "concerned",
  "at risk",
  "cancelled",
  "frustrated",
  "declined",
  "threatened",
  "breakdown",
  "forbade",
  "forbidden",
  "crisis",
  "failed",
];

function detectSentiment(content) {
  const lower = content.toLowerCase();
  let positiveCount = 0;
  let negativeCount = 0;

  for (const signal of POSITIVE_SIGNALS) {
    if (lower.includes(signal)) positiveCount++;
  }
  for (const signal of NEGATIVE_SIGNALS) {
    if (lower.includes(signal)) negativeCount++;
  }

  if (positiveCount > negativeCount && positiveCount >= 2) return "positive";
  if (negativeCount > positiveCount && negativeCount >= 2) return "negative";
  if (positiveCount > 0 && negativeCount > 0) return "mixed";
  if (positiveCount > 0) return "positive";
  if (negativeCount > 0) return "negative";
  return "neutral";
}

// ---------------------------------------------------------------------------
// Follow-up date extraction
// ---------------------------------------------------------------------------

const MONTH_NAMES = {
  january: "01", february: "02", march: "03", april: "04",
  may: "05", june: "06", july: "07", august: "08",
  september: "09", october: "10", november: "11", december: "12",
};

function detectFollowUpDate(content, meetingDate) {
  const lower = content.toLowerCase();

  // Pattern: "by [Month]" or "by [Month] [year]"
  const byMonthMatch = lower.match(
    /by\s+(january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+(\d{4}))?/
  );
  if (byMonthMatch) {
    const month = MONTH_NAMES[byMonthMatch[1]];
    const year = byMonthMatch[2] || (meetingDate ? meetingDate.slice(0, 4) : new Date().getFullYear().toString());
    return `${year}-${month}-01`;
  }

  // Pattern: "by YYYY-MM-DD"
  const byDateMatch = lower.match(/by\s+(\d{4}-\d{2}-\d{2})/);
  if (byDateMatch) return byDateMatch[1];

  // Pattern: "next week"
  if (lower.includes("next week") && meetingDate) {
    const d = new Date(meetingDate);
    d.setDate(d.getDate() + 7);
    return d.toISOString().slice(0, 10);
  }

  // Pattern: "end of week"
  if (lower.includes("end of week") && meetingDate) {
    const d = new Date(meetingDate);
    const dayOfWeek = d.getDay();
    const daysUntilFriday = dayOfWeek <= 5 ? 5 - dayOfWeek : 0;
    d.setDate(d.getDate() + daysUntilFriday);
    return d.toISOString().slice(0, 10);
  }

  return null;
}

// ---------------------------------------------------------------------------
// Parse a single meeting file into a cache entry
// ---------------------------------------------------------------------------

/**
 * Parse a single meeting markdown file into a structured cache entry.
 * @param {string} filePath - Absolute path to the meeting file
 * @param {string} fileName - Just the filename (e.g. "2026-03-01 - Sync.md")
 * @returns {{ date: string|null, title: string, source_file: string, attendees: string[], company: string|null, decisions: string[], action_items: string[], key_points: string[], sentiment: string, follow_up_date: string|null, cached_at: string }}
 */
function parseMeetingFile(filePath, fileName) {
  const content = fs.readFileSync(filePath, "utf-8");
  const fm = parseFrontmatter(content);

  // Extract date — frontmatter first, then filename pattern
  let date = fm.date || fm.created || null;
  if (!date) {
    const dateMatch = fileName.match(/(\d{4}-\d{2}-\d{2})/);
    if (dateMatch) date = dateMatch[1];
  }
  // Normalize date to string
  if (date && typeof date !== "string") date = String(date);

  // Extract title — H1 heading first, then derive from filename
  let title = extractTitle(content);
  if (!title) {
    title = fileName
      .replace(/\.md$/, "")
      .replace(/^\d{4}-\d{2}-\d{2}\s*-?\s*/, "")
      .replace(/^Meeting\s*-?\s*/i, "")
      .trim();
  }

  // Attendees — frontmatter uses both "participants" and "attendees"
  let attendees = fm.participants || fm.attendees || [];
  if (typeof attendees === "string") {
    attendees = attendees.split(",").map((s) => s.trim());
  }

  // Company
  const company = fm.company || null;

  // Structured sections
  // Try common heading variants
  let decisions = extractSection(content, "Decisions");
  if (decisions.length === 0) decisions = extractSection(content, "Key Decisions");
  const actionItems = extractSection(content, "Action Items");
  let keyPoints = extractSection(content, "Key Points");
  if (keyPoints.length === 0) keyPoints = extractSection(content, "Summary");

  // Sentiment
  const sentiment = detectSentiment(content);

  // Follow-up date
  const followUpDate = detectFollowUpDate(content, date);

  // Relative source path (from vault root)
  const sourcePath = path.relative(VAULT_ROOT, filePath);

  return {
    date: date,
    title: title,
    source_file: sourcePath,
    attendees: attendees,
    company: company,
    decisions: decisions,
    action_items: actionItems,
    key_points: keyPoints,
    sentiment: sentiment,
    follow_up_date: followUpDate,
    cached_at: new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// Cache management
// ---------------------------------------------------------------------------

function loadCache() {
  try {
    const raw = fs.readFileSync(CACHE_FILE, "utf-8");
    return JSON.parse(raw);
  } catch {
    return {
      version: 1,
      last_updated: null,
      meetings: [],
      _file_mtimes: {},
    };
  }
}

function saveCache(cache) {
  cache.last_updated = new Date().toISOString();
  fs.mkdirSync(path.dirname(CACHE_FILE), { recursive: true });
  fs.writeFileSync(CACHE_FILE, JSON.stringify(cache, null, 2) + "\n");
}

/**
 * Prune entries older than PRUNE_DAYS from cache.
 */
function pruneOldEntries(cache) {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - PRUNE_DAYS);
  const cutoffStr = cutoff.toISOString().slice(0, 10);

  const before = cache.meetings.length;
  cache.meetings = cache.meetings.filter((m) => {
    if (!m.date) return true; // Keep entries without dates (edge case)
    return m.date >= cutoffStr;
  });

  // Also prune stale mtime entries
  const activeSourceFiles = new Set(cache.meetings.map((m) => m.source_file));
  for (const key of Object.keys(cache._file_mtimes)) {
    if (!activeSourceFiles.has(key)) {
      delete cache._file_mtimes[key];
    }
  }

  const pruned = before - cache.meetings.length;
  if (pruned > 0) {
    process.stderr.write(`[meeting-cache] Pruned ${pruned} entries older than ${PRUNE_DAYS} days\n`);
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main() {
  // Guard: meetings directory must exist
  if (!fs.existsSync(MEETINGS_DIR)) {
    process.stderr.write("[meeting-cache] No meetings directory found, skipping\n");
    process.exit(0);
  }

  // List meeting markdown files (skip README)
  const files = fs.readdirSync(MEETINGS_DIR).filter((f) => {
    return f.endsWith(".md") && f !== "README.md";
  });

  if (files.length === 0) {
    process.stderr.write("[meeting-cache] No meeting files found\n");
    process.exit(0);
  }

  // Load existing cache
  const cache = loadCache();

  // Prune old entries first
  pruneOldEntries(cache);

  // Build set of existing source_file paths for quick lookup
  const existingBySource = new Map();
  for (let i = 0; i < cache.meetings.length; i++) {
    existingBySource.set(cache.meetings[i].source_file, i);
  }

  let processed = 0;
  let skipped = 0;

  for (const fileName of files) {
    const filePath = path.join(MEETINGS_DIR, fileName);
    const relativePath = path.relative(VAULT_ROOT, filePath);

    // Get file modification time
    let mtimeMs;
    try {
      const stat = fs.statSync(filePath);
      mtimeMs = stat.mtimeMs;
    } catch {
      skipped++;
      continue;
    }

    // Quick-skip files with dates in the filename that are beyond the prune threshold
    const filenameDateMatch = fileName.match(/(\d{4}-\d{2}-\d{2})/);
    if (filenameDateMatch) {
      const cutoff = new Date();
      cutoff.setDate(cutoff.getDate() - PRUNE_DAYS);
      if (filenameDateMatch[1] < cutoff.toISOString().slice(0, 10)) {
        skipped++;
        continue;
      }
    }

    // Check if we already cached this file at this mtime (skip unless --rebuild)
    if (!REBUILD) {
      const cachedMtime = cache._file_mtimes[relativePath];
      if (cachedMtime && cachedMtime === mtimeMs) {
        skipped++;
        continue;
      }
    }

    // Parse the meeting file
    try {
      const entry = parseMeetingFile(filePath, fileName);

      // Update or insert
      const existingIdx = existingBySource.get(relativePath);
      if (existingIdx !== undefined) {
        cache.meetings[existingIdx] = entry;
      } else {
        cache.meetings.push(entry);
        existingBySource.set(relativePath, cache.meetings.length - 1);
      }

      // Track mtime
      cache._file_mtimes[relativePath] = mtimeMs;
      processed++;
    } catch (err) {
      process.stderr.write(
        `[meeting-cache] Error parsing ${fileName}: ${err.message}\n`
      );
      skipped++;
    }
  }

  // Sort meetings by date (newest first)
  cache.meetings.sort((a, b) => {
    if (!a.date) return 1;
    if (!b.date) return -1;
    return b.date.localeCompare(a.date);
  });

  // Prune again after processing (rebuild may have added old entries)
  pruneOldEntries(cache);

  // Save cache
  saveCache(cache);

  if (processed > 0 || REBUILD) {
    process.stderr.write(
      `[meeting-cache] Processed ${processed}, skipped ${skipped}, total cached: ${cache.meetings.length}\n`
    );
  }

  process.exit(0);
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------

try {
  main();
} catch (err) {
  // Never crash — hooks must always exit cleanly
  process.stderr.write(`[meeting-cache] Fatal: ${err.message}\n`);
  process.exit(0);
}
