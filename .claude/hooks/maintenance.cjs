#!/usr/bin/env node
/**
 * Dex Vault Maintenance
 *
 * Usage: node .claude/hooks/maintenance.cjs
 * Future: Will be triggered by Claude Code "Setup" hook event
 *
 * Performs vault health checks:
 * - Stale inbox files (>30 days)
 * - Broken WikiLinks
 * - Orphaned person pages
 * - Agent memory cleanup (>90 days)
 */
const fs = require('fs');
const path = require('path');

const { loadPaths } = require('./paths.cjs');
const _paths = loadPaths();
const vaultRoot = _paths.VAULT_ROOT || process.env.CLAUDE_PROJECT_DIR || path.resolve(__dirname, '../..');
const now = Date.now();
const DAY_MS = 86400000;
const report = { staleFiles: [], brokenLinks: [], orphanedPages: [], staleMemory: [] };

/**
 * Find markdown files in 00-Inbox/ that haven't been modified in over 30 days.
 * Populates report.staleFiles.
 */
function checkStaleInbox() {
  const inboxDir = path.join(vaultRoot, '00-Inbox');
  if (!fs.existsSync(inboxDir)) return;

  const walkDir = (dir) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (e) { return; }

    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        walkDir(fullPath);
      } else if (entry.name.endsWith('.md')) {
        try {
          const stat = fs.statSync(fullPath);
          const ageDays = Math.floor((now - stat.mtimeMs) / DAY_MS);
          if (ageDays > 30) {
            report.staleFiles.push({ file: path.relative(vaultRoot, fullPath), ageDays });
          }
        } catch (e) { /* stat error */ }
      }
    }
  };
  walkDir(inboxDir);
}

/**
 * Scan PARA directories for [[WikiLinks]] whose targets don't exist.
 * Samples up to 100 files for performance. Populates report.brokenLinks.
 */
function checkBrokenLinks() {
  const mdFiles = [];
  const collectMd = (dir, depth = 0) => {
    if (depth > 5) return;
    if (!fs.existsSync(dir)) return;
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (e) { return; }

    for (const entry of entries) {
      if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) collectMd(fullPath, depth + 1);
      else if (entry.name.endsWith('.md')) mdFiles.push(fullPath);
    }
  };

  // Only scan key PARA directories
  ['00-Inbox', '01-Quarter_Goals', '02-Week_Priorities', '03-Tasks', '04-Projects', '05-Areas'].forEach(d => {
    collectMd(path.join(vaultRoot, d));
  });

  const allMdNames = new Set(mdFiles.map(f => path.basename(f, '.md')));
  const linkPattern = /\[\[([^\]|#]+?)(?:[|#][^\]]+)?\]\]/g;

  // Sample max 100 files for speed
  const sample = mdFiles.slice(0, 100);
  const seen = new Set();

  for (const file of sample) {
    let content;
    try {
      content = fs.readFileSync(file, 'utf-8');
    } catch (e) { continue; }

    let match;
    while ((match = linkPattern.exec(content)) !== null) {
      const target = match[1].trim();
      if (!target) continue;
      const key = `${path.relative(vaultRoot, file)}:${target}`;
      if (seen.has(key)) continue;
      seen.add(key);

      if (!allMdNames.has(target)) {
        report.brokenLinks.push({
          source: path.relative(vaultRoot, file),
          target
        });
      }
    }
  }
}

/**
 * Find person pages not referenced in Tasks.md or recent meeting notes.
 * Populates report.orphanedPages.
 */
function checkOrphanedPages() {
  const peopleDir = path.join(vaultRoot, '05-Areas/People');
  if (!fs.existsSync(peopleDir)) return;

  const personFiles = [];
  const walkPeople = (dir) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (e) { return; }

    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) walkPeople(fullPath);
      else if (entry.name.endsWith('.md')) personFiles.push(fullPath);
    }
  };
  walkPeople(peopleDir);

  for (const pf of personFiles) {
    const name = path.basename(pf, '.md');
    let referenced = false;

    // Check Tasks.md
    const tasksPath = path.join(vaultRoot, '03-Tasks/Tasks.md');
    if (fs.existsSync(tasksPath)) {
      try {
        const tasksContent = fs.readFileSync(tasksPath, 'utf-8');
        if (tasksContent.includes(name)) referenced = true;
      } catch (e) { /* read error */ }
    }

    // Check meeting files (sample recent 20)
    if (!referenced) {
      const meetingDir = path.join(vaultRoot, '06-Resources/Intel/Meeting_Intel');
      if (fs.existsSync(meetingDir)) {
        try {
          const meetings = fs.readdirSync(meetingDir)
            .filter(f => f.endsWith('.md'))
            .sort()
            .reverse()
            .slice(0, 20);
          for (const m of meetings) {
            const mc = fs.readFileSync(path.join(meetingDir, m), 'utf-8');
            if (mc.includes(name)) { referenced = true; break; }
          }
        } catch (e) { /* read error */ }
      }
    }

    if (!referenced) {
      report.orphanedPages.push(path.relative(vaultRoot, pf));
    }
  }
}

/**
 * Find agent memory files older than 90 days that can be cleaned up.
 * Populates report.staleMemory.
 */
function checkStaleMemory() {
  const memoryDir = path.join(vaultRoot, '.claude/memory');
  if (!fs.existsSync(memoryDir)) return;

  let entries;
  try {
    entries = fs.readdirSync(memoryDir, { withFileTypes: true });
  } catch (e) { return; }

  for (const entry of entries) {
    if (entry.name.startsWith('.')) continue;
    const fullPath = path.join(memoryDir, entry.name);
    try {
      const stat = fs.statSync(fullPath);
      const ageDays = Math.floor((now - stat.mtimeMs) / DAY_MS);
      if (ageDays > 90) {
        report.staleMemory.push({ file: entry.name, ageDays });
      }
    } catch (e) { /* stat error */ }
  }
}

// === Run All Checks ===
console.log('Dex Vault Maintenance\n');

checkStaleInbox();
checkBrokenLinks();
checkOrphanedPages();
checkStaleMemory();

// === Output Report ===
console.log(`## Stale Inbox Files (>30 days): ${report.staleFiles.length}`);
for (const f of report.staleFiles.slice(0, 10)) {
  console.log(`  - ${f.file} (${f.ageDays} days)`);
}
if (report.staleFiles.length > 10) console.log(`  ... and ${report.staleFiles.length - 10} more`);

console.log(`\n## Broken WikiLinks: ${report.brokenLinks.length}`);
for (const l of report.brokenLinks.slice(0, 10)) {
  console.log(`  - [[${l.target}]] in ${l.source}`);
}
if (report.brokenLinks.length > 10) console.log(`  ... and ${report.brokenLinks.length - 10} more`);

console.log(`\n## Orphaned Person Pages: ${report.orphanedPages.length}`);
for (const p of report.orphanedPages.slice(0, 10)) {
  console.log(`  - ${p}`);
}
if (report.orphanedPages.length > 10) console.log(`  ... and ${report.orphanedPages.length - 10} more`);

console.log(`\n## Stale Agent Memory (>90 days): ${report.staleMemory.length}`);
for (const m of report.staleMemory) {
  console.log(`  - ${m.file} (${m.ageDays} days)`);
}

const total = report.staleFiles.length + report.brokenLinks.length + report.orphanedPages.length + report.staleMemory.length;
console.log(`\n---\nTotal issues: ${total}`);
if (total === 0) console.log('Vault is healthy!');
