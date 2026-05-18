#!/usr/bin/env node
/**
 * Post-meeting project page updater — dual mode
 *
 * MODE 1: Hook (default)
 *   Fires after Write during /process-meetings (PostToolUse matcher=Write)
 *   Reads CLAUDE_HOOK_CONTEXT for the written meeting file path, scans its content.
 *
 * MODE 2: Inline CLI
 *   For skills that fetch Otter transcripts inline (without writing a file).
 *   Pipe transcript content via stdin; pass meeting name via --name.
 *
 *   Usage:
 *     echo "$transcript" | node post-meeting-project-update.cjs \
 *         --inline --name "YYYY-MM-DD - Meeting Title"
 *
 *   Integration recipe for meeting-fetching skills:
 *     After fetching a transcript inline (e.g., via Granola/Otter MCP without
 *     writing a file), pipe its content here. The hook will update any matching
 *     project's Meeting History section with a link to [[<meeting-name>]].
 *     If the meeting file IS later saved to 00-Inbox/Meetings/, the file-mode
 *     hook fires automatically — idempotency prevents double-linking.
 *
 * SHARED LOGIC (both modes):
 *   Keyword strategy: explicit `keywords:` frontmatter > full-name-only derived from filename
 *   Skips: status: closed or archived
 *   Idempotent: won't add duplicates
 */

const fs = require('fs');
const path = require('path');

// ============================================================================
// 1. Parse mode + inputs
// ============================================================================

const args = process.argv.slice(2);
const inlineMode = args.includes('--inline');
const nameFlagIdx = args.indexOf('--name');
const meetingNameArg = nameFlagIdx >= 0 ? args[nameFlagIdx + 1] : null;

let meetingContent;
let meetingName;

if (inlineMode) {
  if (!meetingNameArg) {
    console.error('Error: --inline requires --name "<meeting-name>"');
    console.error('Usage: cat transcript.txt | post-meeting-project-update.cjs --inline --name "YYYY-MM-DD - Title"');
    process.exit(2);
  }
  // Read stdin
  let stdinContent;
  try {
    stdinContent = fs.readFileSync(0, 'utf-8');
  } catch (e) {
    console.error('Error: no content on stdin');
    process.exit(2);
  }
  if (!stdinContent.trim()) {
    console.error('Error: stdin content is empty');
    process.exit(2);
  }
  meetingContent = stdinContent.toLowerCase();
  meetingName = meetingNameArg;
} else {
  // Hook mode — read CLAUDE_HOOK_CONTEXT
  const input = JSON.parse(process.env.CLAUDE_HOOK_CONTEXT || '{}');
  const filePath = input?.tool_input?.file_path || input?.toolInput?.file_path || '';

  if (!filePath.includes('Meeting_Intel') && !filePath.includes('Meetings/') && !filePath.includes('Meeting_Notes')) {
    process.exit(0);
  }
  if (path.basename(filePath).toLowerCase() === 'readme.md') {
    process.exit(0);
  }
  if (!fs.existsSync(filePath)) {
    process.exit(0);
  }
  meetingContent = fs.readFileSync(filePath, 'utf-8').toLowerCase();
  meetingName = path.basename(filePath, '.md');
}

const today = new Date().toISOString().split('T')[0];

// ============================================================================
// 2. Resolve projects directory
// ============================================================================

// In hook mode, CLAUDE_PROJECT_DIR is set by Claude Code.
// In inline mode, the skill should set it (or we resolve from cwd).
const vaultRoot = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const projectsDir = path.join(vaultRoot, '04-Projects');

if (!fs.existsSync(projectsDir)) {
  if (inlineMode) {
    console.error(`Error: 04-Projects/ not found at ${vaultRoot}. Set CLAUDE_PROJECT_DIR or run from vault root.`);
    process.exit(2);
  }
  process.exit(0);
}

// ============================================================================
// 3. Helpers (shared)
// ============================================================================

function parseFrontmatter(content) {
  const match = content.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return {};
  const fm = {};
  for (const line of match[1].split('\n')) {
    const m = line.match(/^([a-z_]+):\s*(.+)$/i);
    if (m) fm[m[1].toLowerCase()] = m[2].trim();
  }
  return fm;
}

function derivedKeywords(projectFilename) {
  const base = projectFilename.replace(/\.md$/, '');
  const words = base.toLowerCase().split('_').filter(w => w && w !== 'the');
  if (words.length === 0) return [];
  if (words.length === 1) {
    return words[0].length >= 5 ? [words[0]] : [];
  }
  return [words.join(' ')];
}

function meetingMatches(keywords) {
  for (const kw of keywords) {
    const safe = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp(`\\b${safe}\\b`, 'i');
    if (pattern.test(meetingContent)) return kw;
  }
  return null;
}

function appendMeetingRef(projectPath, matchedKeyword) {
  let content = fs.readFileSync(projectPath, 'utf-8');

  if (content.includes(meetingName)) return false;

  const sourceTag = inlineMode ? 'inline' : 'file';
  const refLine = `- [[${meetingName}]] — auto-linked ${today} (matched: \`${matchedKeyword}\`, source: ${sourceTag})`;
  const sectionRegex = /(## Meeting History\n+(?:\*[^\n]*\*\n+)?)/;

  if (sectionRegex.test(content)) {
    content = content.replace(sectionRegex, (match) => `${match}${refLine}\n\n`);
    content = content.replace(/\n{3,}/g, '\n\n');
  } else {
    if (!content.endsWith('\n')) content += '\n';
    content += `\n---\n\n## Meeting History\n\n*Auto-maintained by \`post-meeting-project-update.cjs\` — newest at top.*\n\n${refLine}\n`;
  }

  fs.writeFileSync(projectPath, content);
  return true;
}

// ============================================================================
// 4. Scan active projects
// ============================================================================

const projectFiles = fs.readdirSync(projectsDir).filter(f =>
  f.endsWith('.md') && f.toLowerCase() !== 'readme.md'
);

const updated = [];

for (const pf of projectFiles) {
  const projectPath = path.join(projectsDir, pf);
  const projectContent = fs.readFileSync(projectPath, 'utf-8');
  const fm = parseFrontmatter(projectContent);

  if (fm.status && ['closed', 'archived'].includes(fm.status.toLowerCase())) continue;

  let keywords;
  if (fm.keywords) {
    keywords = fm.keywords.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
  } else {
    keywords = derivedKeywords(pf);
  }
  if (keywords.length === 0) continue;

  const matched = meetingMatches(keywords);
  if (matched) {
    const did = appendMeetingRef(projectPath, matched);
    if (did) updated.push({ project: pf.replace(/\.md$/, ''), keyword: matched });
  }
}

// ============================================================================
// 5. Report
// ============================================================================

if (updated.length > 0) {
  const summary = updated.map(u => `${u.project} (matched "${u.keyword}")`).join(', ');
  const modeTag = inlineMode ? '[inline]' : '[file]';
  console.log(`${modeTag} Linked meeting "${meetingName}" to ${updated.length} project(s): ${summary}`);
} else if (inlineMode) {
  // In inline mode, signal "nothing matched" so skill can react if needed
  console.log(`[inline] Meeting "${meetingName}" — no project keywords matched`);
}
