#!/usr/bin/env node

/**
 * Sync from Granola - Background meeting intelligence processor
 *
 * Reads meetings directly from Granola's local cache, processes new meetings
 * with LLM, and generates structured meeting notes.
 *
 * Usage:
 *   node .scripts/meeting-intel/sync-from-granola.cjs                  # Process new meetings
 *   node .scripts/meeting-intel/sync-from-granola.cjs --force          # Reprocess today's meetings
 *   node .scripts/meeting-intel/sync-from-granola.cjs --reprocess      # Reprocess all meetings in range
 *   node .scripts/meeting-intel/sync-from-granola.cjs --days-back=14   # Override lookback window
 *   node .scripts/meeting-intel/sync-from-granola.cjs --dry-run        # Show what would be processed
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');
const yaml = require('js-yaml');

// Configuration
const VAULT_ROOT = path.resolve(__dirname, '../..');
require('dotenv').config({ path: path.join(VAULT_ROOT, '.env') });

const { generateContent, isConfigured, getActiveProvider } = require('../lib/llm-client.cjs');

// Paths
const STATE_FILE = path.join(__dirname, 'processed-meetings.json');
const MEETINGS_DIR = path.join(VAULT_ROOT, '00-Inbox', 'Meetings');
const QUEUE_FILE = path.join(MEETINGS_DIR, 'queue.md');
const LOG_DIR = path.join(VAULT_ROOT, '.scripts', 'logs');
const NOTION_MAP_FILE = path.join(__dirname, 'notion-mapping.json');
const PILLARS_FILE = path.join(VAULT_ROOT, 'System', 'pillars.yaml');
const PROFILE_FILE = path.join(VAULT_ROOT, 'System', 'user-profile.yaml');
const TASKS_FILE = path.join(VAULT_ROOT, '03-Tasks', 'Tasks.md');
const PEOPLE_DIR_EXTERNAL = path.join(VAULT_ROOT, '05-Areas', 'People', 'External');

// Constants
const MIN_NOTES_LENGTH = 50;
const LOOKBACK_DAYS = 7;
const MAX_CACHE_SIZE_MB = 100;

// Notion configuration
const NOTION_API_TOKEN = process.env.NOTION_API_TOKEN;
const NOTION_MEETINGS_DB_ID = process.env.NOTION_MEETINGS_DB_ID;
const NOTION_TRIAGE_DB_ID = process.env.NOTION_TRIAGE_DB_ID;
const NOTION_SOURCE_OF_TRUTH = (process.env.NOTION_SOURCE_OF_TRUTH || '').toLowerCase() === 'true';

/**
 * Get Granola cache path for current OS
 */
function getGranolaCachePath() {
  const homedir = os.homedir();
  const platform = os.platform();

  if (platform === 'darwin') {
    return path.join(homedir, 'Library/Application Support/Granola/cache-v3.json');
  } else if (platform === 'win32') {
    const roaming = process.env.APPDATA || path.join(homedir, 'AppData/Roaming');
    const local = process.env.LOCALAPPDATA || path.join(homedir, 'AppData/Local');
    for (const basePath of [roaming, local]) {
      const cachePath = path.join(basePath, 'Granola/cache-v3.json');
      if (fs.existsSync(cachePath)) return cachePath;
    }
    return path.join(roaming, 'Granola/cache-v3.json');
  } else {
    return path.join(homedir, '.config/Granola/cache-v3.json');
  }
}

const GRANOLA_CACHE = getGranolaCachePath();

/**
 * Read and parse Granola cache
 */
function readGranolaCache() {
  if (!fs.existsSync(GRANOLA_CACHE)) {
    throw new Error(`Granola cache not found at ${GRANOLA_CACHE}. Is Granola installed?`);
  }

  // Check file size before reading to avoid memory issues
  const stat = fs.statSync(GRANOLA_CACHE);
  const sizeMB = stat.size / (1024 * 1024);
  if (sizeMB > MAX_CACHE_SIZE_MB) {
    console.warn(`Warning: Granola cache is ${sizeMB.toFixed(1)} MB (threshold: ${MAX_CACHE_SIZE_MB} MB). Reading may be slow.`);
  }

  const rawData = fs.readFileSync(GRANOLA_CACHE, 'utf-8');

  let cacheWrapper;
  try {
    cacheWrapper = JSON.parse(rawData);
  } catch (err) {
    throw new Error(`Granola cache is corrupted (outer JSON parse failed): ${err.message}`);
  }

  if (!cacheWrapper.cache || typeof cacheWrapper.cache !== 'string') {
    throw new Error('Granola cache has unexpected structure: missing or non-string "cache" field');
  }

  let cacheData;
  try {
    // Granola cache is double-JSON-encoded
    cacheData = JSON.parse(cacheWrapper.cache);
  } catch (err) {
    throw new Error(`Granola cache is corrupted (inner JSON parse failed): ${err.message}`);
  }

  return {
    documents: cacheData.state?.documents || {},
    transcripts: cacheData.state?.transcripts || {},
    people: cacheData.state?.people || {}
  };
}

/**
 * Extract company name from meeting title
 */
function extractCompanyFromTitle(title) {
  if (!title) return null;

  const lower = title.toLowerCase();

  // Hardcoded patterns
  if (lower.includes('premier league')) return 'Premier League';
  if (lower.includes('c2/google') || lower.includes('google')) return 'Google';
  if (lower.includes('chapter 2') || lower.includes('chapter2')) return 'Chapter 2';
  if (lower.includes('aris') || lower.includes('a&n')) return 'Aris / A&N';

  // Regex patterns
  const patterns = [
    /^([A-Z][a-zA-Z0-9\s&]+?)\s+(call|meeting|sync|1:1|check-in)/i,
    /meeting with ([A-Z][a-zA-Z0-9\s&]+?)$/i,
    /^([A-Z][a-zA-Z0-9\s&]+?)\s+-\s+/i,
    /C2\/([A-Z][a-zA-Z0-9\s&]+)/i
  ];

  for (const pattern of patterns) {
    const match = title.match(pattern);
    if (match && match[1]) {
      return match[1].trim();
    }
  }

  return null;
}

/**
 * Get new meetings from cache that haven't been processed
 */
function getNewMeetings(cache, state, options = {}) {
  const { forceToday = false, lookbackDays = LOOKBACK_DAYS, reprocess = false } = options;

  const now = new Date();
  const cutoffDate = new Date(now.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  const meetings = [];

  for (const [id, doc] of Object.entries(cache.documents)) {
    // Filter: must be a meeting
    if (doc.type !== 'meeting') continue;

    // Filter: not deleted
    if (doc.deleted_at) continue;

    // Filter: within lookback window
    const createdAt = new Date(doc.created_at);
    if (!reprocess && createdAt < cutoffDate) continue;

    // Filter: not already processed (unless force/reprocess)
    if (reprocess) {
      // --reprocess: reprocess everything in the lookback window
    } else if (forceToday) {
      // --force: only reprocess meetings created today
      if (state.processedMeetings[id] && createdAt < todayStart) continue;
    } else {
      // Default: skip all previously processed meetings
      if (state.processedMeetings[id]) continue;
    }

    // Filter: has sufficient content
    const notes = doc.notes_markdown || '';
    const hasTranscript = cache.transcripts[id] && cache.transcripts[id].length > 0;
    if (notes.length < MIN_NOTES_LENGTH && !hasTranscript) continue;

    // Extract transcript
    let transcript = '';
    if (cache.transcripts[id]) {
      transcript = cache.transcripts[id]
        .sort((a, b) => new Date(a.start_timestamp) - new Date(b.start_timestamp))
        .map(t => t.text)
        .join(' ');
    }

    // Extract participants
    const participants = [];
    if (doc.people?.attendees) {
      for (const attendee of doc.people.attendees) {
        const name = attendee.details?.person?.name?.fullName || attendee.name || attendee.email;
        if (name && !participants.includes(name)) {
          participants.push(name);
        }
      }
    }

    meetings.push({
      id,
      title: doc.title || 'Untitled Meeting',
      createdAt: doc.created_at,
      updatedAt: doc.updated_at,
      notes,
      transcript,
      participants,
      company: extractCompanyFromTitle(doc.title),
      duration: doc.meeting_end_count ? doc.meeting_end_count * 5 : null
    });
  }

  return meetings.sort((a, b) => new Date(a.createdAt) - new Date(b.createdAt));
}

/**
 * Build LLM prompt for meeting analysis
 */
function buildMeetingPrompt(meeting, profile, pillars) {
  const safeMeeting = {
    title: meeting?.title || 'Untitled Meeting',
    createdAt: meeting?.createdAt || new Date().toISOString(),
    participants: meeting?.participants || [],
    company: meeting?.company || null,
    duration: meeting?.duration || null,
    notes: meeting?.notes || '',
    transcript: meeting?.transcript || ''
  };
  const safeProfile = {
    name: profile?.name || 'Unknown',
    role: profile?.role || 'team member',
    company_size: profile?.company_size || 'mid-size'
  };
  const safePillars = Array.isArray(pillars) ? pillars : [];

  const pillarList = safePillars.map(p => `- ${p.name || 'Unnamed'}: ${p.description || ''} (Keywords: ${(p.keywords || []).join(', ')})`).join('\n');

  return `You are analyzing a meeting for ${safeProfile.name}, who is a ${safeProfile.role} at a ${safeProfile.company_size} company.

## Meeting Context

**Title:** ${safeMeeting.title}
**Date:** ${safeMeeting.createdAt}
**Participants:** ${safeMeeting.participants.join(', ')}
${safeMeeting.company ? `**Company:** ${safeMeeting.company}` : ''}
${safeMeeting.duration ? `**Duration:** ${safeMeeting.duration} minutes` : ''}

## User's Strategic Pillars

${pillarList}

## Raw Content

**Notes:**
${safeMeeting.notes}

${safeMeeting.transcript ? `**Transcript:**\n${safeMeeting.transcript.slice(0, 50000)}` : ''}

---

## Your Task

Analyze this meeting and provide structured output in **exactly** this format:

## Summary
[2-3 sentence overview of what this meeting was about and key outcomes]

## Key Discussion Points
### [Topic 1]
[What was discussed, decisions, context]
### [Topic 2]
[Continue as needed]

## Decisions Made
- [Decision 1]
- [Decision 2]
[Or "None identified" if no clear decisions]

## Action Items
### For Me
- [ ] [Specific action item] - by [timeframe or "no deadline"]
### For Others
- [ ] @[Person Name]: [What they need to do]
[Or "None identified" if no action items]

## Meeting Intelligence
**Pain Points:**
- [What challenges or frustrations were expressed]
[Or "None identified"]

**Requests/Needs:**
- [What they asked for or need from us]
[Or "None identified"]

**Competitive Mentions:**
- [Any competitors mentioned and context]
[Or "None identified"]

## Pillar Assignment
[Choose the MOST relevant pillar from the list above]
Rationale: [One sentence explaining why this pillar fits best]

---

**Important:**
- Be specific in action items (who, what, when)
- Extract pain points even if implicit
- Note any budget, timeline, or decision-making authority mentions
- Use EXACTLY the format above - this will be parsed programmatically`;
}

/**
 * Process meeting with LLM
 */
async function processMeetingWithLLM(meeting, profile, pillars) {
  const prompt = buildMeetingPrompt(meeting, profile, pillars);

  try {
    const analysis = await generateContent(prompt, { maxOutputTokens: 8192 });
    return analysis;
  } catch (error) {
    console.error(`❌ LLM analysis failed for meeting "${meeting.title}":`, error.message);
    throw error;
  }
}

/**
 * Parse pillar from analysis
 */
function parsePillarFromAnalysis(analysis, pillars) {
  const match = analysis.match(/## Pillar Assignment\s*\n+\s*(.+)/);
  if (!match) return null;

  // Strip markdown formatting (bold, headers) from captured value
  const assignedPillar = match[1].trim().replace(/\*\*/g, '').replace(/^#+\s*/, '');

  // Find matching pillar
  for (const pillar of pillars) {
    if (pillar.name.toLowerCase() === assignedPillar.toLowerCase()) {
      return pillar;
    }
  }

  // Fallback: find by keywords
  for (const pillar of pillars) {
    if (pillar.keywords.some(kw => assignedPillar.toLowerCase().includes(kw.toLowerCase()))) {
      return pillar;
    }
  }

  return null;
}

/**
 * Slugify title for filename
 */
function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .substring(0, 60);
}

/**
 * Create meeting note file
 */
function createMeetingNote(meeting, analysis, profile, pillar) {
  // Fix #1: Guard against malformed createdAt (no 'T' separator)
  const dateParts = meeting.createdAt.split('T');
  const date = dateParts[0];
  const time = dateParts[1] ? dateParts[1].substring(0, 5) : '00:00';
  const slug = slugify(meeting.title);

  const meetingDir = path.join(MEETINGS_DIR, date);
  fs.mkdirSync(meetingDir, { recursive: true });

  // Fix #5: Handle slug collisions by appending time
  let filename = path.join(meetingDir, `${slug}.md`);
  if (fs.existsSync(filename)) {
    const timeSuffix = time.replace(':', '');
    filename = path.join(meetingDir, `${slug}-${timeSuffix}.md`);
  }

  // Build frontmatter
  const frontmatter = {
    date,
    time,
    type: 'meeting-note',
    source: 'granola',
    title: meeting.title,
    participants: meeting.participants,
    company: meeting.company || '',
    pillar: pillar ? pillar.name : 'unassigned',
    duration: meeting.duration,
    granola_id: meeting.id,
    processed: new Date().toISOString()
  };

  // Fix #4: Use yaml.dump instead of hand-rolled serialization
  const frontmatterYaml = yaml.dump(frontmatter, { lineWidth: -1, quotingType: '"', forceQuotes: false });

  // Fix #3: Guard against empty/undefined profile name
  const profileName = (profile?.name || '').toLowerCase();

  // Build wiki-links to person pages
  const participantLinks = meeting.participants
    .filter(p => profileName && !p.toLowerCase().includes(profileName))
    .map(p => `[[05-Areas/People/External/${p.replace(/\s+/g, '_').replace(/[^\w\-]/g, '')}.md|${p}]]`)
    .join(', ');

  // Fix #6: Sanitize company name consistently with person links
  const sanitizeForLink = (name) => name.replace(/\s+/g, '_').replace(/[^\w\-]/g, '');

  // Build content
  // Fix #2: Guard against null getActiveProvider()
  const provider = (getActiveProvider() || 'unknown').toUpperCase();
  const content = `---
${frontmatterYaml.trimEnd()}
---

# ${meeting.title}

**Date:** ${date} ${time}
**Participants:** ${participantLinks || 'None'}
${meeting.company ? `**Company:** [[05-Areas/Companies/${sanitizeForLink(meeting.company)}.md|${meeting.company}]]` : ''}

---

${analysis}

---

## Raw Content

<details>
<summary>Original Notes</summary>

${meeting.notes}

</details>

${meeting.transcript ? `<details>
<summary>Transcript (${meeting.transcript.split(/\s+/).length} words)</summary>

${meeting.transcript.slice(0, 5000)}${meeting.transcript.length > 5000 ? '\n\n[...truncated]' : ''}

</details>` : ''}

---

*Processed by Dex Meeting Intel (${provider})*
`;

  fs.writeFileSync(filename, content);

  return filename;
}

/**
 * Ensure person page exists and add meeting reference
 */
function ensurePersonPage(name, meetingRef, profile) {
  if (!name || !profile || !profile.name) return null;

  // Skip if person is the owner
  if (name.toLowerCase().includes(profile.name.toLowerCase())) {
    return null;
  }

  const filename = name.replace(/\s+/g, '_').replace(/[^\w\-]/g, '');
  if (!filename) return null;

  try {
    const targetDir = PEOPLE_DIR_EXTERNAL;
    fs.mkdirSync(targetDir, { recursive: true });

    const filePath = path.join(targetDir, `${filename}.md`);

    // Create if doesn't exist
    if (!fs.existsSync(filePath)) {
      const content = `# ${name}

## Role / Company

Unknown

## Meetings

`;
      fs.writeFileSync(filePath, content);
    }

    // Add meeting reference
    const existing = fs.readFileSync(filePath, 'utf-8');
    const entry = `- ${meetingRef}`;

    if (existing.includes(entry)) {
      return filePath; // Already added
    }

    const marker = '## Meetings';
    if (existing.includes(marker)) {
      const updated = existing.replace(marker, `${marker}\n\n${entry}`);
      fs.writeFileSync(filePath, updated);
    } else {
      fs.appendFileSync(filePath, `\n\n## Meetings\n\n${entry}\n`);
    }

    return filePath;
  } catch (error) {
    console.error(`Failed to update person page for "${name}":`, error.message);
    return null;
  }
}

/**
 * Update person pages for all meeting participants
 */
function updatePersonPages(meeting, meetingFilePath, profile) {
  const date = meeting.createdAt.split('T')[0];
  const relativePath = path.relative(VAULT_ROOT, meetingFilePath);
  const meetingRef = `${date} — [[${relativePath}|${meeting.title}]]`;

  const updatedPages = [];

  for (const person of meeting.participants) {
    const filePath = ensurePersonPage(person, meetingRef, profile);
    if (filePath) {
      updatedPages.push(filePath);
    }
  }

  return updatedPages;
}

/**
 * Extract action items from analysis
 */
function extractActionItems(analysis) {
  const actionItemsSection = analysis.match(/## Action Items([\s\S]*?)(?=\n##|$)/);
  if (!actionItemsSection) return [];

  const groups = [];
  const lines = actionItemsSection[1].split('\n');
  let currentGroup = null;

  for (const line of lines) {
    if (line.startsWith('###')) {
      if (currentGroup) groups.push(currentGroup);
      currentGroup = { heading: line.replace(/^###\s*/, '').trim(), items: [] };
    } else if (currentGroup && line.trim().match(/^-\s*\[?\s*\]?\s*/)) {
      const item = line.replace(/^-\s*\[?\s*\]?\s*/, '').trim();
      if (item) currentGroup.items.push(item);
    }
  }

  if (currentGroup) groups.push(currentGroup);
  return groups;
}

/**
 * Get personal action items (For Me section)
 */
function getPersonalActionItems(groups) {
  const forMeGroup = groups.find(g => g.heading.toLowerCase().includes('for me'));
  return forMeGroup ? forMeGroup.items : [];
}

/**
 * Generate next task ID for today
 */
function getNextTaskId() {
  const today = new Date().toISOString().split('T')[0].replace(/-/g, '');
  const tasksContent = fs.existsSync(TASKS_FILE) ? fs.readFileSync(TASKS_FILE, 'utf-8') : '';

  // Find all task IDs for today
  const pattern = new RegExp(`\\^task-${today}-(\\d+)`, 'g');
  const matches = [...tasksContent.matchAll(pattern)];

  let maxNum = 0;
  for (const match of matches) {
    const num = parseInt(match[1], 10);
    if (num > maxNum) maxNum = num;
  }

  return `^task-${today}-${String(maxNum + 1).padStart(3, '0')}`;
}

/**
 * Add tasks for meeting
 */
function addTasksForMeeting(meeting, analysis, pillar) {
  if (!fs.existsSync(TASKS_FILE)) {
    console.warn(`⚠️  Tasks file not found: ${TASKS_FILE}`);
    return 0;
  }

  const tasksContent = fs.readFileSync(TASKS_FILE, 'utf-8');

  // Check if meeting already has tasks
  if (tasksContent.includes(`#granola:${meeting.id}`)) {
    console.log(`ℹ️  Meeting "${meeting.title}" already has tasks, skipping`);
    return 0;
  }

  const groups = extractActionItems(analysis);
  const items = getPersonalActionItems(groups);

  if (items.length === 0) {
    return 0;
  }

  const pillarSlug = pillar ? pillar.id : 'unassigned';
  const taskLines = items.map(item => {
    const taskId = getNextTaskId();
    return `- [ ] ${item} ${taskId} #pillar:${pillarSlug} #lno:N #granola:${meeting.id}`;
  });

  // Insert under ## P2 - Normal
  const marker = '## P2 - Normal';
  if (tasksContent.includes(marker)) {
    const updated = tasksContent.replace(marker, `${marker}\n\n${taskLines.join('\n')}`);
    fs.writeFileSync(TASKS_FILE, updated);
    return items.length;
  } else {
    console.warn(`⚠️  Could not find "${marker}" section in Tasks.md`);
    return 0;
  }
}

module.exports = { readGranolaCache, getNewMeetings, buildMeetingPrompt, processMeetingWithLLM, parsePillarFromAnalysis, slugify, createMeetingNote, ensurePersonPage, updatePersonPages };
