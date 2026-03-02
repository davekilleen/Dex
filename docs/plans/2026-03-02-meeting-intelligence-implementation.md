# Meeting Intelligence (Granola Sync) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the meeting intelligence automation that syncs meetings from Granola, processes them with AI, and integrates with Notion every 30 minutes.

**Architecture:** Single autonomous Node.js script that reads Granola's local cache, processes meetings with multi-provider LLM, creates structured notes, updates person pages, extracts tasks, and optionally syncs to Notion. Runs via macOS LaunchAgent every 30 minutes.

**Tech Stack:** Node.js, js-yaml, dotenv, @notionhq/client, Anthropic/OpenAI/Gemini APIs

**Design Document:** `docs/plans/2026-03-02-meeting-intelligence-design.md`

---

## Pre-Implementation Check

Before starting, verify:
- [ ] Design document reviewed and approved
- [ ] `.env` file has at least one LLM API key
- [ ] Granola is installed and has meetings in cache
- [ ] `System/user-profile.yaml` and `System/pillars.yaml` exist

---

## Task 1: Create LLM Client Library

**Files:**
- Create: `.scripts/lib/llm-client.cjs`

**Step 1: Create lib directory**

```bash
mkdir -p .scripts/lib
```

**Step 2: Create LLM client with multi-provider support**

Create `.scripts/lib/llm-client.cjs`:

```javascript
#!/usr/bin/env node

/**
 * Multi-provider LLM client
 * Supports Anthropic, OpenAI, and Google Gemini
 */

const https = require('https');
const http = require('http');

// API endpoints
const ANTHROPIC_API = 'https://api.anthropic.com/v1/messages';
const OPENAI_API = 'https://api.openai.com/v1/chat/completions';
const GEMINI_API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models';

// Load API keys from environment
const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
const OPENAI_KEY = process.env.OPENAI_API_KEY;
const GEMINI_KEY = process.env.GEMINI_API_KEY;

// Model configuration
const ANTHROPIC_MODEL = process.env.ANTHROPIC_MODEL || 'claude-sonnet-4-5-20250929';
const OPENAI_MODEL = process.env.OPENAI_MODEL || 'gpt-4o';
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemini-2.0-flash-exp';

/**
 * Determine which provider is configured
 */
function getActiveProvider() {
  if (ANTHROPIC_KEY) return 'anthropic';
  if (GEMINI_KEY) return 'gemini';
  if (OPENAI_KEY) return 'openai';
  return null;
}

/**
 * Check if any LLM provider is configured
 */
function isConfigured() {
  return getActiveProvider() !== null;
}

/**
 * Make HTTPS request
 */
function httpsRequest(url, options, body) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const reqOptions = {
      ...options,
      hostname: urlObj.hostname,
      path: urlObj.pathname + urlObj.search,
      port: 443,
      method: options.method || 'POST'
    };

    const req = https.request(reqOptions, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            resolve(data);
          }
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${data}`));
        }
      });
    });

    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

/**
 * Call Anthropic API
 */
async function callAnthropic(prompt, options = {}) {
  const { maxOutputTokens = 4096 } = options;

  const body = {
    model: ANTHROPIC_MODEL,
    max_tokens: maxOutputTokens,
    messages: [{ role: 'user', content: prompt }]
  };

  const response = await httpsRequest(ANTHROPIC_API, {
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': ANTHROPIC_KEY,
      'anthropic-version': '2023-06-01'
    }
  }, body);

  return response.content[0].text;
}

/**
 * Call OpenAI API
 */
async function callOpenAI(prompt, options = {}) {
  const { maxOutputTokens = 4096 } = options;

  const body = {
    model: OPENAI_MODEL,
    max_tokens: maxOutputTokens,
    messages: [{ role: 'user', content: prompt }]
  };

  const response = await httpsRequest(OPENAI_API, {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${OPENAI_KEY}`
    }
  }, body);

  return response.choices[0].message.content;
}

/**
 * Call Google Gemini API
 */
async function callGemini(prompt, options = {}) {
  const { maxOutputTokens = 4096 } = options;

  const url = `${GEMINI_API_BASE}/${GEMINI_MODEL}:generateContent?key=${GEMINI_KEY}`;
  const body = {
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: { maxOutputTokens }
  };

  const response = await httpsRequest(url, {
    headers: { 'Content-Type': 'application/json' }
  }, body);

  return response.candidates[0].content.parts[0].text;
}

/**
 * Generate content using configured provider
 */
async function generateContent(prompt, options = {}) {
  const provider = getActiveProvider();

  if (!provider) {
    throw new Error('No LLM API key configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY');
  }

  switch (provider) {
    case 'anthropic':
      return callAnthropic(prompt, options);
    case 'openai':
      return callOpenAI(prompt, options);
    case 'gemini':
      return callGemini(prompt, options);
    default:
      throw new Error(`Unknown provider: ${provider}`);
  }
}

module.exports = {
  generateContent,
  isConfigured,
  getActiveProvider
};
```

**Step 3: Test LLM client**

Create test file `.scripts/lib/test-llm-client.cjs`:

```javascript
#!/usr/bin/env node

const { generateContent, isConfigured, getActiveProvider } = require('./llm-client.cjs');

async function test() {
  console.log('Testing LLM client...');
  console.log('Provider:', getActiveProvider());
  console.log('Configured:', isConfigured());

  if (!isConfigured()) {
    console.error('No API key configured');
    process.exit(1);
  }

  const response = await generateContent('Say "Hello, World!" and nothing else.');
  console.log('Response:', response);
  console.log('✅ LLM client working');
}

test().catch(console.error);
```

Run: `node .scripts/lib/test-llm-client.cjs`
Expected: Should print "Hello, World!" response from configured LLM

**Step 4: Commit LLM client**

```bash
git add .scripts/lib/llm-client.cjs .scripts/lib/test-llm-client.cjs
git commit -m "feat: add multi-provider LLM client library

Supports Anthropic, OpenAI, and Gemini APIs with automatic provider detection.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Create Meeting Intelligence Directory Structure

**Files:**
- Create: `.scripts/meeting-intel/` directory
- Create: `.scripts/logs/` directory

**Step 1: Create directories**

```bash
mkdir -p .scripts/meeting-intel
mkdir -p .scripts/logs
touch .scripts/logs/meeting-intel.log
```

**Step 2: Initialize state files**

Create `.scripts/meeting-intel/processed-meetings.json`:

```json
{
  "processedMeetings": {},
  "lastSync": null
}
```

Create `.scripts/meeting-intel/notion-mapping.json`:

```json
{}
```

**Step 3: Commit directory structure**

```bash
git add .scripts/meeting-intel/ .scripts/logs/
git commit -m "feat: create meeting intelligence directory structure

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Create Granola Cache Reader

**Files:**
- Create: `.scripts/meeting-intel/sync-from-granola.cjs` (partial - cache reader section)

**Step 1: Create script with shebang and imports**

Create `.scripts/meeting-intel/sync-from-granola.cjs`:

```javascript
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

  const rawData = fs.readFileSync(GRANOLA_CACHE, 'utf-8');
  const cacheWrapper = JSON.parse(rawData);

  // Granola cache is double-JSON-encoded
  const cacheData = JSON.parse(cacheWrapper.cache);

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
    if (!forceToday && !reprocess && state.processedMeetings[id]) {
      const processedDate = new Date(state.processedMeetings[id].processedAt);
      if (processedDate >= todayStart) continue;
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

// Placeholder for rest of the script
console.log('Cache reader functions loaded');

module.exports = { readGranolaCache, getNewMeetings };
```

**Step 2: Test cache reader**

Run: `node .scripts/meeting-intel/sync-from-granola.cjs`
Expected: Should print "Cache reader functions loaded" without errors

**Step 3: Commit cache reader**

```bash
git add .scripts/meeting-intel/sync-from-granola.cjs
git commit -m "feat: add Granola cache reader

Reads Granola's local cache-v3.json file, parses meetings, transcripts, and participants.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Add Meeting Processor (LLM Analysis)

**Files:**
- Modify: `.scripts/meeting-intel/sync-from-granola.cjs` (add LLM processing)

**Step 1: Add LLM prompt builder and meeting processor**

Add to `.scripts/meeting-intel/sync-from-granola.cjs` before the module.exports:

```javascript
/**
 * Build LLM prompt for meeting analysis
 */
function buildMeetingPrompt(meeting, profile, pillars) {
  const pillarList = pillars.map(p => `- ${p.name}: ${p.description} (Keywords: ${p.keywords.join(', ')})`).join('\n');

  return `You are analyzing a meeting for ${profile.name}, who is a ${profile.role} at a ${profile.company_size}-person company.

## Meeting Context

**Title:** ${meeting.title}
**Date:** ${meeting.createdAt}
**Participants:** ${meeting.participants.join(', ')}
${meeting.company ? `**Company:** ${meeting.company}` : ''}
${meeting.duration ? `**Duration:** ${meeting.duration} minutes` : ''}

## User's Strategic Pillars

${pillarList}

## Raw Content

**Notes:**
${meeting.notes}

${meeting.transcript ? `**Transcript:**\n${meeting.transcript.slice(0, 50000)}` : ''}

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
    const analysis = await generateContent(prompt, { maxOutputTokens: 4096 });
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
  const match = analysis.match(/## Pillar Assignment\s*\n([^\n]+)/);
  if (!match) return null;

  const assignedPillar = match[1].trim();

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
```

**Step 2: Test meeting processor (dry run)**

Add test code at end of file (temporary):

```javascript
// Test code (remove after testing)
async function testProcessor() {
  const profile = yaml.load(fs.readFileSync(PROFILE_FILE, 'utf-8'));
  const pillarsData = yaml.load(fs.readFileSync(PILLARS_FILE, 'utf-8'));
  const pillars = pillarsData.pillars || [];

  const testMeeting = {
    id: 'test-123',
    title: 'Test Meeting',
    createdAt: new Date().toISOString(),
    participants: ['Alice', 'Bob'],
    company: 'Test Co',
    notes: 'Discussed project timeline and budget concerns.',
    transcript: 'Hello everyone. We need to finalize the timeline. The budget is tight.',
    duration: 30
  };

  console.log('Testing LLM processor...');
  const analysis = await processMeetingWithLLM(testMeeting, profile, pillars);
  console.log('Analysis:', analysis.slice(0, 500));
  console.log('✅ LLM processor working');
}

if (require.main === module && process.argv.includes('--test-processor')) {
  testProcessor().catch(console.error);
}
```

Run: `node .scripts/meeting-intel/sync-from-granola.cjs --test-processor`
Expected: Should generate LLM analysis and print first 500 chars

**Step 3: Remove test code and commit**

Remove the test code block, then:

```bash
git add .scripts/meeting-intel/sync-from-granola.cjs
git commit -m "feat: add meeting processor with LLM analysis

Builds structured prompts and processes meetings with AI to extract summaries, action items, and insights.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Add Meeting Note File Writer

**Files:**
- Modify: `.scripts/meeting-intel/sync-from-granola.cjs` (add file writer)

**Step 1: Add utility functions**

Add to script before module.exports:

```javascript
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
  const date = meeting.createdAt.split('T')[0];
  const time = meeting.createdAt.split('T')[1].substring(0, 5);
  const slug = slugify(meeting.title);

  const meetingDir = path.join(MEETINGS_DIR, date);
  fs.mkdirSync(meetingDir, { recursive: true });

  const filename = path.join(meetingDir, `${slug}.md`);

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

  // Build wiki-links to person pages
  const participantLinks = meeting.participants
    .filter(p => !p.toLowerCase().includes(profile.name.toLowerCase()))
    .map(p => `[[05-Areas/People/External/${p.replace(/\s+/g, '_').replace(/[^\\w\\-]/g, '')}.md|${p}]]`)
    .join(', ');

  // Build content
  const content = `---
${Object.entries(frontmatter).map(([k, v]) => {
  if (Array.isArray(v)) return `${k}: [${v.map(x => `"${x}"`).join(', ')}]`;
  if (typeof v === 'string') return `${k}: "${v}"`;
  return `${k}: ${v}`;
}).join('\n')}
---

# ${meeting.title}

**Date:** ${date} ${time}
**Participants:** ${participantLinks || 'None'}
${meeting.company ? `**Company:** [[05-Areas/Companies/${meeting.company.replace(/\\s+/g, '_')}.md|${meeting.company}]]` : ''}

---

${analysis}

---

## Raw Content

<details>
<summary>Original Notes</summary>

${meeting.notes}

</details>

${meeting.transcript ? `<details>
<summary>Transcript (${meeting.transcript.split(/\\s+/).length} words)</summary>

${meeting.transcript.slice(0, 5000)}${meeting.transcript.length > 5000 ? '\\n\\n[...truncated]' : ''}

</details>` : ''}

---

*Processed by Dex Meeting Intel (${getActiveProvider().toUpperCase()})*
`;

  fs.writeFileSync(filename, content);

  return filename;
}
```

**Step 2: Test note creation**

Add temporary test at end:

```javascript
// Test note creation (remove after testing)
if (require.main === module && process.argv.includes('--test-notes')) {
  const testMeeting = {
    id: 'test-456',
    title: 'Test Meeting Note',
    createdAt: '2026-03-02T14:00:00Z',
    participants: ['Alice', 'Bob'],
    company: 'Test Corp',
    notes: 'Test notes content',
    transcript: 'Test transcript content',
    duration: 45
  };

  const testAnalysis = `## Summary
Test meeting about project planning.

## Key Discussion Points
### Timeline
Discussed Q1 deadlines.

## Decisions Made
- Move launch to April

## Action Items
### For Me
- [ ] Review timeline - by next week

## Meeting Intelligence
**Pain Points:** Budget constraints
**Requests/Needs:** More resources
**Competitive Mentions:** None identified

## Pillar Assignment
Test Pillar
Rationale: Aligns with project goals`;

  const profile = yaml.load(fs.readFileSync(PROFILE_FILE, 'utf-8'));
  const testPillar = { name: 'Test Pillar', id: 'test-pillar' };

  const filename = createMeetingNote(testMeeting, testAnalysis, profile, testPillar);
  console.log('Created test note:', filename);
  console.log('✅ Note creation working');
}
```

Run: `node .scripts/meeting-intel/sync-from-granola.cjs --test-notes`
Expected: Creates meeting note file in 00-Inbox/Meetings/2026-03-02/

Verify file was created and check content.

**Step 3: Remove test and commit**

```bash
git add .scripts/meeting-intel/sync-from-granola.cjs
git commit -m "feat: add meeting note file writer

Creates structured markdown meeting notes with YAML frontmatter and wiki-links.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Add Person Page Manager

**Files:**
- Modify: `.scripts/meeting-intel/sync-from-granola.cjs` (add person page updates)

**Step 1: Add person page functions**

Add before module.exports:

```javascript
/**
 * Ensure person page exists and add meeting reference
 */
function ensurePersonPage(name, meetingRef, profile) {
  if (!name) return null;

  // Skip if person is the owner
  if (name.toLowerCase().includes(profile.name.toLowerCase())) {
    return null;
  }

  const filename = name.replace(/\s+/g, '_').replace(/[^\w\-]/g, '');
  if (!filename) return null;

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
```

**Step 2: Commit person page manager**

```bash
git add .scripts/meeting-intel/sync-from-granola.cjs
git commit -m "feat: add person page manager

Creates and updates person pages with meeting references.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Add Task Extractor

**Files:**
- Modify: `.scripts/meeting-intel/sync-from-granola.cjs` (add task extraction)

**Step 1: Add task extraction functions**

Add before module.exports:

```javascript
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
```

**Step 2: Commit task extractor**

```bash
git add .scripts/meeting-intel/sync-from-granola.cjs
git commit -m "feat: add task extractor

Extracts action items from meetings and adds them to Tasks.md with proper tags.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Add Notion Sync (Optional)

**Files:**
- Modify: `.scripts/meeting-intel/sync-from-granola.cjs` (add Notion integration)

**Step 1: Add Notion client initialization**

Add at top after other requires:

```javascript
// Notion client (conditional)
let notion = null;
if (NOTION_API_TOKEN) {
  const { Client } = require('@notionhq/client');
  notion = new Client({ auth: NOTION_API_TOKEN });
}
```

**Step 2: Add Notion helper functions**

Add before module.exports:

```javascript
/**
 * Load Notion mapping file
 */
function loadNotionMapping() {
  if (!fs.existsSync(NOTION_MAP_FILE)) {
    return {};
  }
  try {
    return JSON.parse(fs.readFileSync(NOTION_MAP_FILE, 'utf-8'));
  } catch (e) {
    console.warn('⚠️  Failed to load Notion mapping, starting fresh');
    return {};
  }
}

/**
 * Save Notion mapping file
 */
function saveNotionMapping(mapping) {
  fs.writeFileSync(NOTION_MAP_FILE, JSON.stringify(mapping, null, 2));
}

/**
 * Convert markdown to Notion blocks
 */
function buildNotionBlocksFromMarkdown(markdown) {
  const lines = markdown.split('\n');
  const blocks = [];

  for (const line of lines) {
    if (line.startsWith('###')) {
      blocks.push({
        object: 'block',
        type: 'heading_3',
        heading_3: { rich_text: [{ type: 'text', text: { content: line.replace(/^###\s*/, '') } }] }
      });
    } else if (line.startsWith('##')) {
      blocks.push({
        object: 'block',
        type: 'heading_2',
        heading_2: { rich_text: [{ type: 'text', text: { content: line.replace(/^##\s*/, '') } }] }
      });
    } else if (line.trim()) {
      blocks.push({
        object: 'block',
        type: 'paragraph',
        paragraph: { rich_text: [{ type: 'text', text: { content: line } }] }
      });
    }

    if (blocks.length >= 100) break; // Notion limit
  }

  return blocks;
}

/**
 * Sync meeting to Notion
 */
async function syncMeetingToNotion(meeting, analysis, pillar, meetingFilePath) {
  if (!notion || !NOTION_MEETINGS_DB_ID) {
    return null;
  }

  try {
    const mapping = loadNotionMapping();
    let pageId = mapping[meeting.id]?.page_id;

    // Check if page exists
    if (pageId) {
      try {
        await notion.pages.retrieve({ page_id: pageId });
      } catch (e) {
        pageId = null; // Page doesn't exist anymore
      }
    }

    const properties = {
      title: { title: [{ text: { content: meeting.title } }] },
      Date: { date: { start: meeting.createdAt.split('T')[0] } },
      Participants: { multi_select: meeting.participants.map(p => ({ name: p })) },
      Source: { select: { name: 'Granola' } },
      'Granola ID': { rich_text: [{ text: { content: meeting.id } }] }
    };

    if (pillar) {
      properties.Pillar = { select: { name: pillar.name } };
    }

    if (meeting.company) {
      properties.Company = { rich_text: [{ text: { content: meeting.company } }] };
    }

    if (pageId) {
      // Update existing page
      await notion.pages.update({ page_id: pageId, properties });
      console.log(`✅ Updated Notion page for "${meeting.title}"`);
    } else {
      // Create new page
      const blocks = buildNotionBlocksFromMarkdown(analysis);
      const response = await notion.pages.create({
        parent: { database_id: NOTION_MEETINGS_DB_ID },
        properties,
        children: blocks
      });
      pageId = response.id;
      console.log(`✅ Created Notion page for "${meeting.title}"`);
    }

    // Save mapping
    mapping[meeting.id] = {
      page_id: pageId,
      url: `https://notion.so/${pageId.replace(/-/g, '')}`
    };
    saveNotionMapping(mapping);

    return mapping[meeting.id].url;
  } catch (error) {
    console.error(`❌ Notion sync failed for "${meeting.title}":`, error.message);
    return null;
  }
}
```

**Step 3: Commit Notion sync**

```bash
git add .scripts/meeting-intel/sync-from-granola.cjs
git commit -m "feat: add Notion sync integration

Syncs meetings to Notion database with auto-property creation and markdown conversion.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Add Main Orchestration Loop

**Files:**
- Modify: `.scripts/meeting-intel/sync-from-granola.cjs` (add main function)

**Step 1: Add state management and main loop**

Add before module.exports:

```javascript
/**
 * Load processing state
 */
function loadState() {
  if (!fs.existsSync(STATE_FILE)) {
    return { processedMeetings: {}, lastSync: null };
  }
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));
  } catch (e) {
    console.warn('⚠️  Failed to load state file, starting fresh');
    return { processedMeetings: {}, lastSync: null };
  }
}

/**
 * Save processing state
 */
function saveState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

/**
 * Main processing function
 */
async function main() {
  console.log('🚀 Starting Granola sync...');
  console.log(`📊 LLM Provider: ${getActiveProvider().toUpperCase()}`);

  // Validate LLM configuration
  if (!isConfigured()) {
    console.error('❌ No LLM API key configured');
    console.error('Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY in .env');
    process.exit(1);
  }

  // Parse command-line options
  const args = process.argv.slice(2);
  const options = {
    forceToday: args.includes('--force'),
    reprocess: args.includes('--reprocess'),
    dryRun: args.includes('--dry-run'),
    lookbackDays: LOOKBACK_DAYS
  };

  const daysBackArg = args.find(a => a.startsWith('--days-back='));
  if (daysBackArg) {
    options.lookbackDays = parseInt(daysBackArg.split('=')[1], 10);
  }

  // Load configuration
  const profile = yaml.load(fs.readFileSync(PROFILE_FILE, 'utf-8'));
  const pillarsData = yaml.load(fs.readFileSync(PILLARS_FILE, 'utf-8'));
  const pillars = pillarsData.pillars || [];

  // Read cache and filter meetings
  const cache = readGranolaCache();
  const state = loadState();
  const meetings = getNewMeetings(cache, state, options);

  console.log(`📋 Found ${meetings.length} meeting(s) to process`);

  if (options.dryRun) {
    for (const meeting of meetings) {
      console.log(`  - ${meeting.title} (${meeting.createdAt.split('T')[0]})`);
    }
    console.log('ℹ️  Dry run complete (no processing done)');
    return;
  }

  if (meetings.length === 0) {
    console.log('ℹ️  No new meetings to process');
    return;
  }

  // Process each meeting
  let successCount = 0;
  let errorCount = 0;

  for (const meeting of meetings) {
    try {
      console.log(`\n📝 Processing: ${meeting.title}`);

      // Generate LLM analysis
      const analysis = await processMeetingWithLLM(meeting, profile, pillars);

      // Parse pillar
      const pillar = parsePillarFromAnalysis(analysis, pillars);
      if (!pillar) {
        console.warn(`⚠️  Could not assign pillar for "${meeting.title}"`);
      }

      // Create meeting note
      const noteFilePath = createMeetingNote(meeting, analysis, profile, pillar);
      console.log(`  ✅ Created note: ${path.relative(VAULT_ROOT, noteFilePath)}`);

      // Update person pages
      const personPages = updatePersonPages(meeting, noteFilePath, profile);
      if (personPages.length > 0) {
        console.log(`  ✅ Updated ${personPages.length} person page(s)`);
      }

      // Extract tasks
      const taskCount = addTasksForMeeting(meeting, analysis, pillar);
      if (taskCount > 0) {
        console.log(`  ✅ Added ${taskCount} task(s) to Tasks.md`);
      }

      // Sync to Notion
      const notionUrl = await syncMeetingToNotion(meeting, analysis, pillar, noteFilePath);

      // Update state
      state.processedMeetings[meeting.id] = {
        title: meeting.title,
        processedAt: new Date().toISOString(),
        filepath: noteFilePath,
        notionUrl
      };

      successCount++;
    } catch (error) {
      console.error(`❌ Failed to process "${meeting.title}":`, error.message);
      errorCount++;
    }
  }

  // Save state
  state.lastSync = new Date().toISOString();
  saveState(state);

  console.log(`\n✅ Sync complete: ${successCount} processed, ${errorCount} errors`);
}

// Run if called directly
if (require.main === module) {
  main().catch(error => {
    console.error('❌ Fatal error:', error);
    process.exit(1);
  });
}
```

**Step 2: Update module exports**

Replace the module.exports line with:

```javascript
module.exports = { main, readGranolaCache, getNewMeetings };
```

**Step 3: Test full script**

Run: `node .scripts/meeting-intel/sync-from-granola.cjs --dry-run`
Expected: Should list meetings that would be processed

Run: `node .scripts/meeting-intel/sync-from-granola.cjs`
Expected: Should process one or more meetings and create files

**Step 4: Commit main orchestration**

```bash
git add .scripts/meeting-intel/sync-from-granola.cjs
git commit -m "feat: add main orchestration loop

Complete meeting processing pipeline with state management and error handling.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 10: Create LaunchAgent and Install Script

**Files:**
- Create: `.scripts/meeting-intel/com.dex.meeting-intel.plist`
- Create: `.scripts/meeting-intel/install-automation.sh`

**Step 1: Create LaunchAgent plist**

Create `.scripts/meeting-intel/com.dex.meeting-intel.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.dex.meeting-intel</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/node</string>
    <string>/Users/tomgreen/Dex/.scripts/meeting-intel/sync-from-granola.cjs</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/tomgreen/Dex</string>
  <key>StandardOutPath</key>
  <string>/Users/tomgreen/Library/Logs/dex-meeting-intel.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/tomgreen/Library/Logs/dex-meeting-intel.log</string>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
```

**Step 2: Create install script**

Create `.scripts/meeting-intel/install-automation.sh`:

```bash
#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SOURCE="$SCRIPT_DIR/com.dex.meeting-intel.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.dex.meeting-intel.plist"

echo "🚀 Installing Meeting Intel LaunchAgent..."

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$HOME/Library/LaunchAgents"

# Copy plist
cp "$PLIST_SOURCE" "$PLIST_DEST"
echo "  ✅ Copied plist to $PLIST_DEST"

# Unload if already loaded
launchctl unload "$PLIST_DEST" 2>/dev/null || true

# Load the agent
launchctl load "$PLIST_DEST"
echo "  ✅ LaunchAgent loaded"

echo ""
echo "✅ Installation complete!"
echo ""
echo "The script will run every 30 minutes automatically."
echo ""
echo "Commands:"
echo "  Check status:  launchctl list | grep dex.meeting-intel"
echo "  View logs:     tail -f ~/Library/Logs/dex-meeting-intel.log"
echo "  Unload:        launchctl unload ~/Library/LaunchAgents/com.dex.meeting-intel.plist"
echo "  Reload:        launchctl unload ~/Library/LaunchAgents/com.dex.meeting-intel.plist && launchctl load ~/Library/LaunchAgents/com.dex.meeting-intel.plist"
echo "  Run manually:  node .scripts/meeting-intel/sync-from-granola.cjs"
```

**Step 3: Make install script executable**

```bash
chmod +x .scripts/meeting-intel/install-automation.sh
```

**Step 4: Test installation**

Run: `.scripts/meeting-intel/install-automation.sh`
Expected: Should install and load LaunchAgent

Verify: `launchctl list | grep dex.meeting-intel`
Expected: Should show agent in list

**Step 5: Commit LaunchAgent**

```bash
git add .scripts/meeting-intel/com.dex.meeting-intel.plist .scripts/meeting-intel/install-automation.sh
git commit -m "feat: add LaunchAgent for 30-minute auto-sync

Installs macOS LaunchAgent that runs meeting sync every 30 minutes.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 11: Final Testing and Documentation

**Files:**
- Modify: `RESTORATION_SUMMARY.md` (update with completion status)

**Step 1: Run full integration test**

Wait 30 minutes and check logs:

```bash
tail -f ~/Library/Logs/dex-meeting-intel.log
```

Expected: Should show sync running automatically

**Step 2: Verify all components**

Check:
- [ ] Meeting notes created in `00-Inbox/Meetings/`
- [ ] Person pages created/updated in `05-Areas/People/External/`
- [ ] Tasks added to `03-Tasks/Tasks.md`
- [ ] Notion pages created (if enabled)
- [ ] State file updated
- [ ] LaunchAgent running

**Step 3: Update restoration summary**

Edit `RESTORATION_SUMMARY.md` and update the "Custom Scripts NOT Restored" section:

Replace the "Meeting Intelligence" section with:

```markdown
### Meeting Intelligence ✅ COMPLETE
- `.scripts/meeting-intel/sync-from-granola.cjs` - Auto-sync meetings from Granola
- `.scripts/meeting-intel/com.dex.meeting-intel.plist` - LaunchAgent (30-min interval)
- `.scripts/meeting-intel/install-automation.sh` - Installation script
- `.scripts/meeting-intel/notion-mapping.json` - Meeting-to-Notion page mapping
- **Status:** Fully operational, running every 30 minutes
```

**Step 4: Commit documentation**

```bash
git add RESTORATION_SUMMARY.md
git commit -m "docs: mark meeting intelligence as complete

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Verification Checklist

After implementation, verify:

### Core Functionality
- [ ] Script reads Granola cache without errors
- [ ] LLM analysis generates structured output
- [ ] Meeting notes created with valid YAML frontmatter
- [ ] Person pages created/updated correctly
- [ ] Tasks extracted and added to Tasks.md
- [ ] Task IDs are sequential and unique
- [ ] State file tracks processed meetings

### Notion Integration (if enabled)
- [ ] Notion pages created in meetings DB
- [ ] Properties populated correctly
- [ ] Markdown converted to blocks
- [ ] Mapping file maintained
- [ ] Tasks synced to triage DB

### Automation
- [ ] LaunchAgent installed
- [ ] Agent runs every 30 minutes
- [ ] Logs written correctly
- [ ] No errors in logs

### Error Handling
- [ ] Gracefully handles missing Granola cache
- [ ] Continues processing after single meeting failure
- [ ] Logs errors appropriately
- [ ] State preserved across runs

---

## Success Criteria

**Functional Requirements:**
- ✅ Automatically syncs meetings from Granola every 30 minutes
- ✅ Creates structured meeting notes with AI analysis
- ✅ Extracts action items into task list
- ✅ Updates person pages for all participants
- ✅ Syncs to Notion (meetings + triage) - optional
- ✅ Handles errors gracefully without stopping
- ✅ Prevents duplicate processing

**Performance:**
- ✅ Completes within 5 minutes per meeting
- ✅ Handles 10+ meetings per sync
- ✅ Minimal memory footprint

**User Experience:**
- ✅ Meetings appear in inbox within 30 minutes
- ✅ Action items automatically added to tasks
- ✅ Person pages stay up to date
- ✅ Can manually trigger sync when needed

---

## Next Steps

After completing this implementation:

1. **Monitor for first week** - Check logs daily, verify meetings are processing correctly
2. **Tune company extraction** - Add more hardcoded patterns as needed
3. **Build Notion sync scripts** (if needed):
   - `notion-sync-triage-priorities.cjs`
   - `notion-sync-week-priorities.cjs`
4. **Build Slack bot** (if needed) - EOD check-ins, meeting prep

---

*Implementation plan created: 2026-03-02*
