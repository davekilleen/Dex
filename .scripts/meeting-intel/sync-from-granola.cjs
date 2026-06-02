#!/usr/bin/env node

/**
 * Sync from Granola - Background meeting intelligence processor
 *
 * Uses the OFFICIAL Granola public REST API as the ONLY data source.
 * No local files: there is no reading of supabase.json, cache-v*.json,
 * granola-crypto, or any spoofed desktop-app headers. Everything comes
 * from https://public-api.granola.ai authenticated with a Bearer key.
 *
 * Processes new meetings with the LLM and generates structured meeting notes.
 * Designed to run automatically via macOS Launch Agent every 30 minutes.
 * No Cursor or Claude required - fully autonomous.
 *
 * Auth:
 *   - Reads GRANOLA_API_KEY from process.env, then from a .env file at the
 *     vault root. Key format is grn_... and requires a Granola Business plan.
 *   - If no key is configured the script logs a friendly one-liner and exits
 *     cleanly (exit 0) — it never errors.
 *
 * Data flow:
 *   1. LIST:   GET /v1/notes (page_size=30, created_after=lookback cutoff),
 *              paging via the returned cursor until hasMore is false.
 *   2. DETAIL: GET /v1/notes/{id}?include=transcript for each NEW note —
 *              the list response contains no summary/attendees/transcript.
 *   3. Map title, created_at, attendees, notes (summary_markdown||summary_text),
 *      and a flattened transcript into the existing note-generation flow.
 *
 * Usage:
 *   node .scripts/meeting-intel/sync-from-granola.cjs           # Process new meetings
 *   node .scripts/meeting-intel/sync-from-granola.cjs --force   # Reprocess all meetings from today
 *   node .scripts/meeting-intel/sync-from-granola.cjs --dry-run # Show what would be processed
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const yaml = require('js-yaml');

// ============================================================================
// CONFIGURATION
// ============================================================================

const VAULT_ROOT = path.resolve(__dirname, '../..');

// Official Granola public REST API
const GRANOLA_API_BASE = 'https://public-api.granola.ai';

/**
 * Read the Granola API key.
 * Priority: process.env.GRANOLA_API_KEY, then a GRANOLA_API_KEY=... line in
 * the .env file at the vault root. Returns the key string, or null if absent.
 * Never throws.
 */
function getGranolaApiKey() {
  if (process.env.GRANOLA_API_KEY && process.env.GRANOLA_API_KEY.trim()) {
    return process.env.GRANOLA_API_KEY.trim();
  }

  try {
    const envPath = path.join(VAULT_ROOT, '.env');
    if (!fs.existsSync(envPath)) return null;
    const raw = fs.readFileSync(envPath, 'utf-8');
    for (const line of raw.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const match = trimmed.match(/^GRANOLA_API_KEY\s*=\s*(.*)$/);
      if (match) {
        // Strip optional surrounding quotes and inline whitespace
        let value = match[1].trim();
        if ((value.startsWith('"') && value.endsWith('"')) ||
            (value.startsWith("'") && value.endsWith("'"))) {
          value = value.slice(1, -1);
        }
        return value.trim() || null;
      }
    }
  } catch (e) {
    // Unreadable .env — treat as not configured rather than failing.
  }
  return null;
}

const STATE_FILE = path.join(__dirname, 'processed-meetings.json');
const MEETINGS_DIR = path.join(VAULT_ROOT, '00-Inbox', 'Meetings');
const QUEUE_FILE = path.join(MEETINGS_DIR, 'queue.md');
const LOG_DIR = path.join(VAULT_ROOT, '.scripts', 'logs');
const PILLARS_FILE = path.join(VAULT_ROOT, 'System', 'pillars.yaml');
const PROFILE_FILE = path.join(VAULT_ROOT, 'System', 'user-profile.yaml');

// Minimum content length to consider a meeting worth processing
const MIN_NOTES_LENGTH = 50;
// How many days back to look for new meetings
const LOOKBACK_DAYS = 7;

// ============================================================================
// LOGGING
// ============================================================================

function log(message) {
  const timestamp = new Date().toISOString();
  const logMessage = `[${timestamp}] ${message}`;
  console.log(logMessage);

  // Also write to log file
  if (!fs.existsSync(LOG_DIR)) {
    fs.mkdirSync(LOG_DIR, { recursive: true });
  }
  const logFile = path.join(LOG_DIR, 'meeting-intel.log');
  fs.appendFileSync(logFile, logMessage + '\n');
}

// ============================================================================
// CONFIGURATION LOADING
// ============================================================================

function loadPillars() {
  if (!fs.existsSync(PILLARS_FILE)) {
    log('Warning: pillars.yaml not found, using default pillars');
    return ['General'];
  }
  try {
    const pillarsData = yaml.load(fs.readFileSync(PILLARS_FILE, 'utf-8'));
    return pillarsData.pillars.map(p => p.name || p.id);
  } catch (e) {
    log(`Warning: Could not parse pillars.yaml: ${e.message}`);
    return ['General'];
  }
}

function loadUserProfile() {
  const defaults = {
    name: 'User',
    role: 'Professional',
    company: '',
    meeting_processing: {
      mode: 'automatic',
      api_provider: 'gemini'
    },
    meeting_intelligence: {
      extract_customer_intel: true,
      extract_competitive_intel: true,
      extract_action_items: true,
      extract_decisions: true
    }
  };

  if (!fs.existsSync(PROFILE_FILE)) {
    log('Warning: user-profile.yaml not found, using defaults');
    return defaults;
  }

  try {
    const profile = yaml.load(fs.readFileSync(PROFILE_FILE, 'utf-8'));
    return { ...defaults, ...profile };
  } catch (e) {
    log(`Warning: Could not parse user-profile.yaml: ${e.message}`);
    return defaults;
  }
}

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

function loadState() {
  if (!fs.existsSync(STATE_FILE)) {
    return { processedMeetings: {}, lastSync: null };
  }
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));
  } catch (e) {
    log(`Warning: Could not read state file: ${e.message}`);
    return { processedMeetings: {}, lastSync: null };
  }
}

function saveState(state) {
  state.lastSync = new Date().toISOString();
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

// ============================================================================
// GRANOLA OFFICIAL PUBLIC API CLIENT — THE ONLY DATA SOURCE
// ============================================================================

/**
 * Perform a GET request against the official Granola public API.
 *
 * Authenticated with the Bearer GRANOLA_API_KEY. Handles gzip/deflate.
 * Returns { status, data } where data is the parsed JSON (or null if the
 * body could not be parsed). Never throws — network/parse failures resolve
 * to { status: 0, data: null } so callers can decide how to react.
 */
function granolaApiGet(apiKey, pathWithQuery) {
  const https = require('https');
  const zlib = require('zlib');
  const url = `${GRANOLA_API_BASE}${pathWithQuery}`;

  return new Promise((resolve) => {
    let settled = false;
    const done = (result) => { if (!settled) { settled = true; resolve(result); } };

    let req;
    try {
      req = https.request(url, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${apiKey}`,
          'Accept': 'application/json',
          'Accept-Encoding': 'gzip, deflate'
        },
        timeout: 20000
      }, (res) => {
        // Handle gzip/deflate compressed responses
        let stream = res;
        const encoding = res.headers['content-encoding'];
        if (encoding === 'gzip') {
          stream = res.pipe(zlib.createGunzip());
        } else if (encoding === 'deflate') {
          stream = res.pipe(zlib.createInflate());
        }

        const chunks = [];
        stream.on('data', chunk => chunks.push(chunk));
        stream.on('end', () => {
          const body = Buffer.concat(chunks).toString('utf-8');
          let data = null;
          if (body) {
            try { data = JSON.parse(body); } catch (e) { data = null; }
          }
          done({ status: res.statusCode, data });
        });
        stream.on('error', () => done({ status: res.statusCode || 0, data: null }));
      });
    } catch (e) {
      done({ status: 0, data: null });
      return;
    }

    req.on('error', () => done({ status: 0, data: null }));
    req.on('timeout', () => { req.destroy(); done({ status: 0, data: null }); });
    req.end();
  });
}

/**
 * granolaApiGet with a single retry on HTTP 429 (rate limit), backing off
 * briefly before the retry. All other statuses are returned as-is.
 */
async function fetchFromGranolaApi(apiKey, pathWithQuery) {
  let result = await granolaApiGet(apiKey, pathWithQuery);
  if (result.status === 429) {
    log('  Granola API rate limited (429) — backing off and retrying once...');
    await new Promise(r => setTimeout(r, 2000));
    result = await granolaApiGet(apiKey, pathWithQuery);
  }
  return result;
}

/**
 * Encode query params into a URL query string.
 */
function buildQuery(params) {
  const parts = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  }
  return parts.length ? `?${parts.join('&')}` : '';
}

/**
 * Flatten a detail-endpoint transcript array into a single readable string.
 * Prefixes each line with its diarization label when present.
 */
function flattenTranscript(transcript) {
  if (!Array.isArray(transcript) || transcript.length === 0) return '';
  return transcript
    .map(entry => {
      if (!entry || typeof entry !== 'object') return '';
      const text = (entry.text || '').trim();
      if (!text) return '';
      const label = entry.speaker && entry.speaker.diarization_label;
      return label ? `${label}: ${text}` : text;
    })
    .filter(Boolean)
    .join('\n')
    .trim();
}

/**
 * Page through GET /v1/notes (page_size=30) using created_after = lookback
 * cutoff, following the returned cursor until hasMore is false.
 *
 * Returns an array of list-item note objects ({ id, title, created_at, ... }),
 * or null if the API rejected auth / was unreachable so the caller can exit
 * cleanly. List items contain NO summary/attendees/transcript.
 */
async function listGranolaNotes(apiKey) {
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - LOOKBACK_DAYS);
  const createdAfter = cutoffDate.toISOString();

  const notes = [];
  let cursor = null;
  let page = 0;
  const MAX_PAGES = 200; // safety bound against a runaway cursor loop

  while (page < MAX_PAGES) {
    page++;
    const query = buildQuery({
      page_size: 30,
      created_after: createdAfter,
      cursor: cursor || undefined
    });

    const { status, data } = await fetchFromGranolaApi(apiKey, `/v1/notes${query}`);

    if (status === 401) {
      log('Granola API key rejected — re-run /granola-setup');
      return null;
    }
    if (status !== 200 || !data) {
      log(`  Granola API list request failed (HTTP ${status || 'no response'})`);
      return null;
    }

    const pageNotes = Array.isArray(data.notes) ? data.notes : [];
    notes.push(...pageNotes);
    log(`  Listed page ${page}: ${pageNotes.length} notes (total ${notes.length})`);

    if (!data.hasMore || !data.cursor) break;
    cursor = data.cursor;

    // Be gentle between sequential list pages.
    await new Promise(r => setTimeout(r, 200));
  }

  return notes;
}

/**
 * Fetch full detail for a single note (GET /v1/notes/{id}?include=transcript)
 * and map it to the standard meeting object the downstream flow consumes.
 *
 * Returns a meeting object, or null on 401 (so the caller can abort) or
 * undefined-equivalent null when the note could not be fetched/mapped.
 */
async function fetchMeetingDetail(apiKey, noteId) {
  const { status, data } = await fetchFromGranolaApi(
    apiKey,
    `/v1/notes/${encodeURIComponent(noteId)}${buildQuery({ include: 'transcript' })}`
  );

  if (status === 401) {
    log('Granola API key rejected — re-run /granola-setup');
    return { authFailed: true };
  }
  if (status !== 200 || !data) {
    log(`  Could not fetch note ${noteId} (HTTP ${status || 'no response'})`);
    return null;
  }

  const id = data.id || noteId;
  const title = data.title || 'Untitled Meeting';
  const createdAt = data.created_at || '';

  // Notes: prefer the richer markdown summary, fall back to plain summary text.
  const notes = (data.summary_markdown && data.summary_markdown.trim())
    ? data.summary_markdown
    : (data.summary_text || '');

  // Attendees: name (fallback to email) for each attendee.
  const participants = [];
  if (Array.isArray(data.attendees)) {
    for (const attendee of data.attendees) {
      if (!attendee) continue;
      const name = (attendee.name && attendee.name.trim()) ? attendee.name.trim() : attendee.email;
      if (name) participants.push(name);
    }
  }
  // Include the owner if present so creator filtering still works downstream.
  if (data.owner && (data.owner.name || data.owner.email)) {
    participants.push(data.owner.name || data.owner.email);
  }

  const transcript = flattenTranscript(data.transcript);

  return {
    id,
    title,
    createdAt,
    updatedAt: data.updated_at || '',
    notes,
    transcript,
    participants: [...new Set(participants)],
    company: extractCompanyFromTitle(title),
    duration: null, // not provided by the public API
    source: 'api'
  };
}

/**
 * Build the list of NEW meetings (full detail) from the official API.
 *
 * 1. List notes within the lookback window (cursor-paged).
 * 2. Filter to notes not already processed (unless forcing today's meetings)
 *    and within the lookback cutoff.
 * 3. Fetch per-note detail (summary + attendees + transcript) sequentially.
 * 4. Keep notes that have meaningful content (notes OR transcript).
 *
 * Returns an array of meeting objects (possibly empty), or null if the API
 * was unavailable / auth was rejected so the caller can exit cleanly.
 */
async function getNewMeetingsFromApi(apiKey, state, forceToday = false) {
  const listed = await listGranolaNotes(apiKey);
  if (listed === null) return null; // auth/network failure already logged

  log(`  API returned ${listed.length} notes within the last ${LOOKBACK_DAYS} days`);

  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - LOOKBACK_DAYS);
  const today = new Date().toISOString().split('T')[0];

  // Decide which listed notes are new and in-window before paying for detail fetches.
  const toFetch = [];
  for (const note of listed) {
    if (!note || !note.id) continue;

    const noteDate = note.created_at ? note.created_at.split('T')[0] : '';
    if (forceToday && noteDate === today) {
      // Allow reprocessing today's meetings.
    } else if (state.processedMeetings[note.id]) {
      continue;
    }

    const createdAt = new Date(note.created_at);
    if (isNaN(createdAt.getTime()) || createdAt < cutoffDate) continue;

    toFetch.push(note);
  }

  log(`  ${toFetch.length} new note(s) need detail fetches`);

  const newMeetings = [];
  for (const note of toFetch) {
    const meeting = await fetchMeetingDetail(apiKey, note.id);
    if (meeting && meeting.authFailed) return null; // 401 mid-run — abort cleanly
    if (!meeting) continue;

    // Keep if either notes or transcript carry meaningful content.
    if (meeting.notes.length < MIN_NOTES_LENGTH && meeting.transcript.length < MIN_NOTES_LENGTH) {
      continue;
    }

    newMeetings.push(meeting);

    // Gentle, sequential detail fetches (rate limits undocumented).
    await new Promise(r => setTimeout(r, 250));
  }

  newMeetings.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
  return newMeetings;
}

function extractCompanyFromTitle(title) {
  if (!title) return '';

  // Common patterns: "Company Name - Meeting", "Meeting with Company", "Company call"
  const companyPatterns = [
    /^([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s*(?:call|meeting|sync|1:1|check-?in)/i,
    /meeting with ([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)/i,
    /^([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s*[-\u2013\u2014]/,
  ];

  for (const pattern of companyPatterns) {
    const match = title.match(pattern);
    if (match) return match[1];
  }

  return '';
}

// ============================================================================
// PROMPT BUILDING
// ============================================================================

function buildIntelligenceSection(profile) {
  const intel = profile.meeting_intelligence || {};
  let sections = [];

  if (intel.extract_customer_intel) {
    sections.push(`## Meeting Intelligence

**Pain Points:**
- [Any pain points or challenges mentioned, or "None identified"]

**Requests/Needs:**
- [Any requests or feature needs mentioned, or "None identified"]`);
  }

  if (intel.extract_competitive_intel) {
    sections.push(`**Competitive Mentions:**
- [Any competitors or alternatives mentioned, or "None identified"]`);
  }

  return sections.join('\n\n');
}

function buildAnalysisPrompt(meeting, profile, pillars) {
  const content = buildMeetingContent(meeting);
  const intelSection = buildIntelligenceSection(profile);
  const pillarList = pillars.join(', ');

  return `You are analyzing a meeting for a ${profile.role}${profile.company ? ` at ${profile.company}` : ''}. Extract structured intelligence from this meeting.

**Meeting:** ${meeting.title}
**Date:** ${meeting.createdAt}
**Participants:** ${meeting.participants.join(', ') || 'Unknown'}
${meeting.company ? `**Company:** ${meeting.company}` : ''}

**Content:**
${content}

---

Generate a structured analysis in this exact markdown format:

## Summary

[2-3 sentence overview of what the meeting was about and key outcomes]

## Key Discussion Points

### [Topic 1]
[Key details and context]

### [Topic 2]
[Key details and context]

## Decisions Made

- [Decision 1]
- [Decision 2]

## Action Items

### For Me
- [ ] [Specific task] - by [timeframe if mentioned] ^task-${new Date().toISOString().split('T')[0].replace(/-/g, '')}-${generateTaskId()}

### For Others
- [ ] @[Person]: [Specific task]

${intelSection}

## Pillar Assignment

[Choose ONE primary pillar from: ${pillarList}]

Rationale: [One sentence explaining why this pillar fits]

---

Be concise but thorough. Extract real insights, not generic summaries. If something isn't clear from the content, say so rather than making things up.`;
}

// ============================================================================
// LLM ANALYSIS
// ============================================================================

async function analyzeWithLLM(meeting, profile, pillars) {
  const { generateContent, isConfigured, getActiveProvider } = require('../lib/llm-client.cjs');

  if (!isConfigured()) {
    throw new Error('No LLM API key found. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY in .env');
  }

  const prompt = buildAnalysisPrompt(meeting, profile, pillars);
  const provider = getActiveProvider();

  try {
    log(`Analyzing ${meeting.title} with ${provider}...`);
    const response = await generateContent(prompt, {
      maxOutputTokens: 3000
    });
    return response;
  } catch (err) {
    log(`LLM analysis failed for ${meeting.title}: ${err.message}`);
    throw err;
  }
}

function buildMeetingContent(meeting) {
  let content = '';

  if (meeting.notes && meeting.notes.length > 0) {
    content += `## Notes\n\n${meeting.notes}\n\n`;
  }

  if (meeting.transcript && meeting.transcript.length > 0) {
    // Truncate long transcripts
    const maxTranscript = 30000;
    const transcript = meeting.transcript.length > maxTranscript
      ? meeting.transcript.slice(0, maxTranscript) + '\n\n[Transcript truncated...]'
      : meeting.transcript;
    content += `## Transcript\n\n${transcript}\n\n`;
  }

  if (!content.trim()) {
    content = '[No detailed content available - meeting may have been brief or not transcribed]';
  }

  return content;
}

function generateTaskId() {
  const now = new Date();
  const ms = now.getMilliseconds();
  const seconds = now.getSeconds();
  const num = ((seconds * 1000 + ms) % 999) + 1;
  return num.toString().padStart(3, '0');
}

// ============================================================================
// NOTE GENERATION
// ============================================================================

function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 60);
}

function createMeetingNote(meeting, analysis, profile, pillars) {
  const date = meeting.createdAt.split('T')[0];
  const time = meeting.createdAt.split('T')[1]?.slice(0, 5) || '00:00';

  const outputDir = path.join(MEETINGS_DIR, date);
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const slug = slugify(meeting.title);
  const filename = `${slug}.md`;
  const filepath = path.join(outputDir, filename);

  // Extract pillar from analysis
  const pillarMatch = analysis.match(/## Pillar Assignment\n\n([^\n]+)/i);
  let pillar = pillarMatch ? pillarMatch[1].trim() : pillars[0];
  pillar = pillar.replace(/[\[\]"']/g, '').trim();

  // Filter participants to exclude the owner
  const ownerName = profile.name || '';
  const filteredParticipants = meeting.participants.filter(p =>
    p.toLowerCase() !== ownerName.toLowerCase() &&
    !p.toLowerCase().includes(ownerName.toLowerCase().split(' ')[0])
  );

  const sourceLabel = meeting.source === 'api' ? 'API' : 'Cache';

  const content = `---
date: ${date}
time: ${time}
type: meeting-note
source: granola
title: "${meeting.title.replace(/"/g, '\\"')}"
participants: [${filteredParticipants.map(p => `"${p}"`).join(', ')}]
company: "${meeting.company}"
pillar: "${pillar}"
duration: ${meeting.duration || 'unknown'}
granola_id: ${meeting.id}
processed: ${new Date().toISOString()}
---

# ${meeting.title}

**Date:** ${date} ${time}
**Participants:** ${filteredParticipants.map(p => `05-Areas/People/External/${p.replace(/\s+/g, '_')}.md`).join(', ') || 'Unknown'}
${meeting.company ? `**Company:** 05-Areas/Companies/${meeting.company}.md` : ''}

---

${analysis}

---

## Raw Content

<details>
<summary>Original Notes</summary>

${meeting.notes || 'No notes captured'}

</details>

${meeting.transcript ? `
<details>
<summary>Transcript (${meeting.transcript.split(' ').length} words)</summary>

${meeting.transcript.slice(0, 5000)}${meeting.transcript.length > 5000 ? '\n\n[Truncated...]' : ''}

</details>
` : ''}

---
*Processed by Dex Meeting Intel (${sourceLabel} source)*
`;

  fs.writeFileSync(filepath, content);
  log(`Created meeting note: ${filepath}`);

  return {
    filepath,
    wikilink: `00-Inbox/Meetings/${date}/${slug}.md`
  };
}

// ============================================================================
// BASIC NOTE (no LLM — fallback for automatic mode when API key not configured)
// ============================================================================

function createBasicMeetingNote(meeting, profile) {
  const date = meeting.createdAt.split('T')[0];
  const time = meeting.createdAt.split('T')[1]?.slice(0, 5) || '00:00';

  const outputDir = path.join(MEETINGS_DIR, date);
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }

  const slug = slugify(meeting.title);
  const filename = `${slug}.md`;
  const filepath = path.join(outputDir, filename);

  const ownerName = profile.name || '';
  const filteredParticipants = meeting.participants.filter(p =>
    p.toLowerCase() !== ownerName.toLowerCase() &&
    !p.toLowerCase().includes(ownerName.toLowerCase().split(' ')[0])
  );

  const notesSection = meeting.notes
    ? `## Notes\n\n${meeting.notes}\n`
    : '';

  const transcriptSection = meeting.transcript
    ? `## Transcript\n\n${meeting.transcript.slice(0, 5000)}${meeting.transcript.length > 5000 ? '\n\n[Truncated...]' : ''}\n`
    : '';

  const content = `---
date: ${date}
time: ${time}
type: meeting-note
source: granola
title: "${meeting.title.replace(/"/g, '\\"')}"
participants: [${filteredParticipants.map(p => `"${p}"`).join(', ')}]
company: "${meeting.company || ''}"
granola_id: ${meeting.id}
processed: ${new Date().toISOString()}
ai_analyzed: false
---

# ${meeting.title}

**Date:** ${date} ${time}
**Participants:** ${filteredParticipants.join(', ') || 'Unknown'}
${meeting.company ? `**Company:** ${meeting.company}` : ''}

---

${notesSection}
${transcriptSection}

---
*Auto-synced by Dex. Run \`/process-meetings\` to add AI analysis, or set up an LLM key via \`/ai-setup\`.*
`;

  fs.writeFileSync(filepath, content);
  log(`  Created basic note (no LLM): ${filepath}`);

  return {
    filepath,
    wikilink: `00-Inbox/Meetings/${date}/${slug}.md`
  };
}

// ============================================================================
// MANUAL MODE — queue meeting as JSON for later /process-meetings
// ============================================================================

function queueMeetingAsJson(meeting, state) {
  const QUEUE_DIR = path.join(MEETINGS_DIR, 'queue');
  if (!fs.existsSync(QUEUE_DIR)) {
    fs.mkdirSync(QUEUE_DIR, { recursive: true });
  }

  const date = meeting.createdAt.split('T')[0];
  const slug = slugify(meeting.title);
  const shortId = meeting.id.slice(0, 8);
  const filename = `${date}-${slug}-${shortId}.json`;
  const filepath = path.join(QUEUE_DIR, filename);

  fs.writeFileSync(filepath, JSON.stringify(meeting, null, 2));
  log(`  Queued for manual processing: ${filename}`);

  // Track in state
  if (!state.queuedMeetings) state.queuedMeetings = {};
  state.queuedMeetings[meeting.id] = {
    queuedAt: new Date().toISOString(),
    queueFile: filename
  };
  if (!state.lastQueuedAt) {
    state.lastQueuedAt = new Date().toISOString();
  }
  state.lastQueuedAt = new Date().toISOString();
}

// ============================================================================
// QUEUE MANAGEMENT
// ============================================================================

function updateQueue(processedMeetings) {
  const today = new Date().toISOString().split('T')[0];

  if (!fs.existsSync(MEETINGS_DIR)) {
    fs.mkdirSync(MEETINGS_DIR, { recursive: true });
  }

  let queueContent = '';
  if (fs.existsSync(QUEUE_FILE)) {
    queueContent = fs.readFileSync(QUEUE_FILE, 'utf-8');
  } else {
    queueContent = `# Meeting Intel Queue

Meetings pending processing and recently processed.

## Pending

<!-- Meetings from Granola will appear here -->

## Processing

<!-- Meetings currently being processed -->

## Processed (Last 7 Days)

<!-- Processed meetings will appear here -->
`;
  }

  const processedSection = /## Processed \(Last 7 Days\)\n\n/;
  const newLines = processedMeetings.map(m =>
    `- [x] ${m.meeting.title} | ${m.meeting.company || 'N/A'} | ${today} | ${m.wikilink}`
  ).join('\n');

  if (processedSection.test(queueContent) && newLines) {
    queueContent = queueContent.replace(
      processedSection,
      `## Processed (Last 7 Days)\n\n${newLines}\n`
    );
  }

  // Clean up old entries (older than 7 days)
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 7);
  const cutoffStr = cutoff.toISOString().split('T')[0];

  const lines = queueContent.split('\n');
  const filteredLines = lines.filter(line => {
    const dateMatch = line.match(/\| (\d{4}-\d{2}-\d{2}) \|/);
    if (dateMatch && dateMatch[1] < cutoffStr) {
      return false;
    }
    return true;
  });

  fs.writeFileSync(QUEUE_FILE, filteredLines.join('\n'));
}

// ============================================================================
// POST-PROCESSING
// ============================================================================

function runPostProcessing() {
  // Post-processing has been removed - person page updates and synthesis
  // are now handled via MCP tools during /process-meetings command
  log('Post-processing skipped (handled by MCP tools)');
}

// ============================================================================
// MAIN
// ============================================================================

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const force = args.includes('--force');

  log('='.repeat(60));
  log('Dex Meeting Intel - Granola Sync (official public API)');
  log('='.repeat(60));

  // ---- Auth: official Granola public API key (no local files) ----
  const apiKey = getGranolaApiKey();
  if (!apiKey) {
    log('Granola not connected — run /granola-setup to add your Granola API key (requires a Granola Business plan).');
    return; // clean exit (exit 0 via the runner)
  }

  // Load configuration
  const profile = loadUserProfile();
  const pillars = loadPillars();
  log(`User: ${profile.name} (${profile.role})`);
  log(`Pillars: ${pillars.join(', ')}`);

  // Load state
  const state = loadState();
  log(`Last sync: ${state.lastSync || 'Never'}`);
  log(`Previously processed: ${Object.keys(state.processedMeetings).length} meetings`);

  // ---- Data source: official Granola public API (the only source) ----
  const dataSource = 'api';

  log('\nFetching meetings from the Granola public API...');

  const newMeetings = await getNewMeetingsFromApi(apiKey, state, force);

  if (newMeetings === null) {
    // Auth rejected or network failure — already logged a friendly reason.
    log('Could not reach the Granola API this run. Exiting cleanly.');
    return;
  }

  log(`Found ${newMeetings.length} new meetings to process (source: ${dataSource})`);

  if (newMeetings.length === 0) {
    log('Nothing to process. Exiting.');
    saveState(state);
    return;
  }

  if (dryRun) {
    log('\n--- DRY RUN ---');
    for (const meeting of newMeetings) {
      log(`Would process: ${meeting.title} (${meeting.createdAt.split('T')[0]})`);
      log(`  Source: ${meeting.source || dataSource}`);
      log(`  Notes: ${meeting.notes.length} chars`);
      log(`  Transcript: ${(meeting.transcript || '').length} chars`);
      log(`  Participants: ${meeting.participants.join(', ') || 'Unknown'}`);
    }
    return;
  }

  // Determine processing mode
  // "automatic" = write meeting notes now (default for new users)
  // "manual"    = queue JSON files for /process-meetings command
  const processingMode = profile.meeting_processing?.mode || 'automatic';
  log(`\nProcessing mode: ${processingMode}`);

  if (processingMode === 'manual') {
    // Queue mode — write JSON files, user runs /process-meetings to analyse
    log(`Queuing ${newMeetings.length} meeting(s) for manual processing...`);
    for (const meeting of newMeetings) {
      log(`\nQueuing: ${meeting.title}`);
      queueMeetingAsJson(meeting, state);
    }
    saveState(state);
    log('\n' + '='.repeat(60));
    log(`SYNC COMPLETE (source: ${dataSource})`);
    log(`Queued: ${newMeetings.length} meetings`);
    log('Run /process-meetings in your Dex session to analyse them.');
    log('='.repeat(60));
    return;
  }

  // Automatic mode — process and write notes immediately
  const processedResults = [];

  for (const meeting of newMeetings) {
    log(`\nProcessing: ${meeting.title}`);
    log(`  Date: ${meeting.createdAt.split('T')[0]}`);
    log(`  Source: ${meeting.source || dataSource}`);
    log(`  Participants: ${meeting.participants.join(', ') || 'Unknown'}`);

    let result;

    try {
      // Try LLM analysis first
      log('  Calling LLM for analysis...');
      const analysis = await analyzeWithLLM(meeting, profile, pillars);
      log('  Creating meeting note with AI analysis...');
      result = createMeetingNote(meeting, analysis, profile, pillars);
    } catch (err) {
      if (err.message.includes('No LLM API key') || err.message.includes('not configured')) {
        // No LLM configured — create a basic structured note instead
        log(`  No LLM available — creating basic note (run /ai-setup to enable AI analysis)`);
        result = createBasicMeetingNote(meeting, profile);
      } else {
        log(`  Failed: ${err.message}`);
        continue;
      }
    }

    // Mark as processed
    state.processedMeetings[meeting.id] = {
      title: meeting.title,
      processedAt: new Date().toISOString(),
      filepath: result.filepath,
      source: meeting.source || dataSource
    };

    processedResults.push({ meeting, ...result });
    log(`  Done: ${result.wikilink}`);

    // Small delay between LLM calls
    await new Promise(r => setTimeout(r, 500));
  }

  // Save state
  saveState(state);

  // Update queue log
  if (processedResults.length > 0) {
    log('\nUpdating queue log...');
    updateQueue(processedResults);
    log('\nRunning post-processing...');
    runPostProcessing();
  }

  // Summary
  log('\n' + '='.repeat(60));
  log(`SYNC COMPLETE (source: ${dataSource})`);
  log(`Processed: ${processedResults.length} meetings`);
  log(`Failed: ${newMeetings.length - processedResults.length}`);
  log('='.repeat(60));
}

// Run if called directly
if (require.main === module) {
  main()
    .then(() => process.exit(0))
    .catch(err => {
      log(`FATAL: ${err.message}`);
      console.error(err);
      process.exit(1);
    });
}

module.exports = { main, getGranolaApiKey, getNewMeetingsFromApi, fetchMeetingDetail };
