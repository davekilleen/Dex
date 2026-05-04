#!/usr/bin/env node

/**
 * Sync from Granola - Background meeting intelligence processor
 *
 * Uses Granola's Supabase API as PRIMARY data source (structured JSON,
 * includes mobile recordings), with local cache as FALLBACK.
 * Processes new meetings with LLM and generates structured meeting notes.
 *
 * Designed to run automatically via macOS Launch Agent every 30 minutes.
 * No Cursor or Claude required - fully autonomous.
 *
 * Data source priority:
 *   1. Granola API (api.granola.ai) — structured JSON, includes mobile recordings
 *   2. Local Granola cache (cache-v*.json, latest version) — desktop-only fallback
 *
 * Usage:
 *   node .scripts/meeting-intel/sync-from-granola.cjs           # Process new meetings
 *   node .scripts/meeting-intel/sync-from-granola.cjs --force   # Reprocess all meetings from today
 *   node .scripts/meeting-intel/sync-from-granola.cjs --dry-run # Show what would be processed
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');
const yaml = require('js-yaml');

// ============================================================================
// CONFIGURATION
// ============================================================================

const VAULT_ROOT = path.resolve(__dirname, '../..');

// Find the highest-versioned cache-v*.json in a directory
function findLatestGranolaCache(granolaDir) {
  if (!fs.existsSync(granolaDir)) return null;
  const files = fs.readdirSync(granolaDir)
    .filter(f => /^cache-v\d+\.json$/.test(f))
    .sort((a, b) => {
      const vA = parseInt(a.match(/v(\d+)/)[1]);
      const vB = parseInt(b.match(/v(\d+)/)[1]);
      return vB - vA; // descending
    });
  return files.length > 0 ? path.join(granolaDir, files[0]) : null;
}

// Get Granola cache path for current OS (auto-detects latest cache version)
function getGranolaCachePath() {
  const homedir = os.homedir();
  const platform = os.platform();

  if (platform === 'darwin') {
    const granolaDir = path.join(homedir, 'Library/Application Support/Granola');
    return findLatestGranolaCache(granolaDir) || path.join(granolaDir, 'cache-v3.json');
  } else if (platform === 'win32') {
    const roaming = process.env.APPDATA || path.join(homedir, 'AppData/Roaming');
    const local = process.env.LOCALAPPDATA || path.join(homedir, 'AppData/Local');

    for (const basePath of [roaming, local]) {
      const result = findLatestGranolaCache(path.join(basePath, 'Granola'));
      if (result) return result;
    }

    return path.join(roaming, 'Granola/cache-v3.json');
  } else {
    const granolaDir = path.join(homedir, '.config/Granola');
    return findLatestGranolaCache(granolaDir) || path.join(granolaDir, 'cache-v3.json');
  }
}

// Get Granola credentials path (for API access)
function getGranolaCredsPath() {
  const homedir = os.homedir();
  const platform = os.platform();

  if (platform === 'darwin') {
    return path.join(homedir, 'Library/Application Support/Granola/supabase.json');
  } else if (platform === 'win32') {
    const roaming = process.env.APPDATA || path.join(homedir, 'AppData/Roaming');
    return path.join(roaming, 'Granola/supabase.json');
  } else {
    return path.join(homedir, '.config/Granola/supabase.json');
  }
}

const GRANOLA_CACHE = getGranolaCachePath();
const GRANOLA_CREDS = getGranolaCredsPath();
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
// PROSEMIRROR TO MARKDOWN CONVERTER
// ============================================================================

/**
 * Convert ProseMirror JSON content to Markdown.
 * Ported from granola_server.py convert_prosemirror_to_markdown()
 */
function convertProseMirrorToMarkdown(content) {
  if (!content || typeof content !== 'object' || !content.content) {
    return '';
  }

  function processNode(node) {
    if (!node || typeof node !== 'object') return '';

    const nodeType = node.type || '';
    const children = node.content || [];
    let text = node.text || '';
    const marks = node.marks || [];

    // Apply text marks
    if (text && marks.length > 0) {
      for (const mark of marks) {
        const markType = mark.type || '';
        if (markType === 'bold') {
          text = `**${text}**`;
        } else if (markType === 'italic') {
          text = `*${text}*`;
        } else if (markType === 'code') {
          text = `\`${text}\``;
        }
      }
    }

    if (nodeType === 'heading') {
      const level = (node.attrs && node.attrs.level) || 1;
      const headingText = children.map(processNode).join('');
      return '#'.repeat(level) + ' ' + headingText + '\n\n';
    } else if (nodeType === 'paragraph') {
      const paraText = children.map(processNode).join('');
      return paraText + '\n\n';
    } else if (nodeType === 'bulletList') {
      const items = [];
      for (const item of children) {
        if (item.type === 'listItem') {
          const itemContent = (item.content || []).map(processNode).join('').trim();
          items.push(`- ${itemContent}`);
        }
      }
      return items.join('\n') + '\n\n';
    } else if (nodeType === 'orderedList') {
      const items = [];
      let idx = 1;
      for (const item of children) {
        if (item.type === 'listItem') {
          const itemContent = (item.content || []).map(processNode).join('').trim();
          items.push(`${idx}. ${itemContent}`);
          idx++;
        }
      }
      return items.join('\n') + '\n\n';
    } else if (nodeType === 'codeBlock') {
      const codeText = children.map(processNode).join('');
      return '```\n' + codeText + '```\n\n';
    } else if (nodeType === 'blockquote') {
      const quoteText = children.map(processNode).join('');
      return '> ' + quoteText + '\n\n';
    } else if (nodeType === 'text') {
      return text;
    } else if (nodeType === 'hardBreak') {
      return '\n';
    }

    // Recursively process children for unknown types
    return children.map(processNode).join('');
  }

  return processNode(content).trim();
}

/**
 * Extract notes from a Granola document, checking notes_markdown first,
 * then falling back to last_viewed_panel (ProseMirror JSON).
 */
function extractNotesFromDoc(doc) {
  // Try notes_markdown first
  let notes = doc.notes_markdown || '';
  if (notes.length >= MIN_NOTES_LENGTH) return notes;

  // Fallback: check last_viewed_panel (ProseMirror format)
  if (doc.last_viewed_panel) {
    try {
      let panel = doc.last_viewed_panel;
      if (typeof panel === 'string') {
        panel = JSON.parse(panel);
      }
      if (panel && panel.content) {
        const converted = convertProseMirrorToMarkdown(panel.content || panel);
        if (converted.length > notes.length) {
          return converted;
        }
      }
    } catch (e) {
      // If parsing fails, stick with notes_markdown
    }
  }

  return notes;
}

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
// GRANOLA API CLIENT — PRIMARY DATA SOURCE
// ============================================================================

/**
 * Get Granola API access token from local credentials file.
 * Granola's desktop app stores these automatically — no separate OAuth needed.
 * Returns null if credentials not found or token missing.
 */
function getGranolaApiToken() {
  if (!fs.existsSync(GRANOLA_CREDS)) {
    return null;
  }

  try {
    const data = JSON.parse(fs.readFileSync(GRANOLA_CREDS, 'utf-8'));
    const workosTokens = JSON.parse(data.workos_tokens || '{}');
    return workosTokens.access_token || null;
  } catch (e) {
    return null;
  }
}

/**
 * Fetch data from Granola API.
 * Returns parsed JSON response or null on failure.
 * Handles gzip-compressed responses automatically.
 */
async function fetchFromGranolaApi(endpoint, data) {
  const token = getGranolaApiToken();
  if (!token) return null;

  const https = require('https');
  const zlib = require('zlib');
  const url = `https://api.granola.ai${endpoint}`;
  const payload = JSON.stringify(data);

  return new Promise((resolve) => {
    const req = https.request(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate',
        'User-Agent': 'Granola/5.354.0',
        'X-Client-Version': '5.354.0'
      },
      timeout: 15000
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
        if (res.statusCode === 200) {
          try {
            resolve(JSON.parse(body));
          } catch (e) {
            log(`  API response parse error: ${e.message}`);
            resolve(null);
          }
        } else {
          log(`  API returned ${res.statusCode}`);
          resolve(null);
        }
      });
      stream.on('error', () => resolve(null));
    });

    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
    req.write(payload);
    req.end();
  });
}

/**
 * Convert an API document (from /v2/get-documents) to the standard meeting format.
 */
function convertApiDocToMeeting(doc) {
  const id = doc.id || '';
  const title = doc.title || 'Untitled Meeting';
  const createdAt = doc.created_at || '';

  // Extract notes — try last_viewed_panel (ProseMirror) first, then notes_markdown
  let notes = '';
  const panel = doc.last_viewed_panel;
  if (panel && typeof panel === 'object') {
    const content = panel.content;
    if (content && typeof content === 'object') {
      notes = convertProseMirrorToMarkdown(content);
    }
  }
  if (!notes && doc.notes_markdown) {
    notes = doc.notes_markdown;
  }

  // Extract participants
  const participants = [];
  if (doc.people?.attendees) {
    for (const attendee of doc.people.attendees) {
      const name = attendee.details?.person?.name?.fullName || attendee.name || attendee.email;
      if (name) participants.push(name);
    }
  }
  if (doc.people?.creator?.name) {
    participants.push(doc.people.creator.name);
  }

  // Get transcript if available in the document
  let transcript = '';
  if (doc.transcripts && Array.isArray(doc.transcripts)) {
    transcript = doc.transcripts
      .sort((a, b) => new Date(a.start_timestamp) - new Date(b.start_timestamp))
      .map(t => t.text)
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  return {
    id,
    title,
    createdAt,
    updatedAt: doc.updated_at || '',
    notes,
    transcript,
    participants: [...new Set(participants)],
    company: extractCompanyFromTitle(title),
    duration: doc.meeting_end_count ? doc.meeting_end_count * 5 : null,
    source: 'api'
  };
}

/**
 * Fetch new meetings via Granola's API (includes mobile recordings).
 *
 * Uses the same API that Granola's desktop app uses, authenticated via
 * the token Granola stores locally in supabase.json. No separate OAuth
 * flow needed — if Granola is installed and you're signed in, it works.
 *
 * Returns an array of meeting objects, or null if API is unavailable.
 */
async function getNewMeetingsFromApi(state, forceToday = false) {
  const token = getGranolaApiToken();
  if (!token) {
    log('  Granola API token not found (is Granola installed and signed in?)');
    return null;
  }

  try {
    const response = await fetchFromGranolaApi('/v2/get-documents', {
      limit: 100,
      offset: 0,
      include_last_viewed_panel: true
    });

    if (!response || !response.docs) {
      log('  API unavailable or returned no data');
      return null;
    }

    log(`  API returned ${response.docs.length} documents`);

    // Load local cache to augment API meetings with transcripts
    // (API /v2/get-documents does not embed transcripts — they live in the local cache)
    let localTranscripts = {};
    try {
      const cache = readGranolaCache();
      localTranscripts = cache.transcripts || {};
      log(`  Loaded ${Object.keys(localTranscripts).length} transcripts from local cache`);
    } catch (e) {
      log(`  Warning: Could not load local cache for transcripts: ${e.message}`);
    }

    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - LOOKBACK_DAYS);
    const today = new Date().toISOString().split('T')[0];

    const newMeetings = [];
    for (const doc of response.docs) {
      // Skip deleted
      if (doc.deleted_at) continue;

      // Check if already processed (unless forcing today's meetings)
      const docDate = doc.created_at?.split('T')[0];
      if (forceToday && docDate === today) {
        // Allow reprocessing today's meetings
      } else if (state.processedMeetings[doc.id]) {
        continue;
      }

      // Check date cutoff
      const createdAt = new Date(doc.created_at);
      if (isNaN(createdAt.getTime()) || createdAt < cutoffDate) continue;

      const meeting = convertApiDocToMeeting(doc);

      // Augment with transcript from local cache if API doc has none
      if (!meeting.transcript && localTranscripts[doc.id]?.length > 0) {
        meeting.transcript = localTranscripts[doc.id]
          .sort((a, b) => new Date(a.start_timestamp) - new Date(b.start_timestamp))
          .map(t => t.text)
          .join(' ')
          .replace(/\s+/g, ' ')
          .trim();
      }

      // Check minimum content — allow through if transcript exists even when notes are short
      if (meeting.notes.length < MIN_NOTES_LENGTH && meeting.transcript.length < MIN_NOTES_LENGTH) continue;

      newMeetings.push(meeting);
    }

    newMeetings.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    return newMeetings;

  } catch (err) {
    log(`  API error: ${err.message}`);
    return null;
  }
}

// ============================================================================
// GRANOLA CACHE READING — FALLBACK DATA SOURCE
// ============================================================================

function readGranolaCache() {
  if (!fs.existsSync(GRANOLA_CACHE)) {
    throw new Error(`Granola cache not found at ${GRANOLA_CACHE}`);
  }

  const rawData = fs.readFileSync(GRANOLA_CACHE, 'utf-8');
  const cacheWrapper = JSON.parse(rawData);

  // The cache has a nested structure: { cache: JSON_STRING } or { cache: OBJECT }
  // Newer Granola versions store cache as a pre-parsed object, not a JSON string
  const cacheData = typeof cacheWrapper.cache === 'string'
    ? JSON.parse(cacheWrapper.cache)
    : cacheWrapper.cache;

  return {
    documents: cacheData.state?.documents || {},
    transcripts: cacheData.state?.transcripts || {},
    people: cacheData.state?.people || {}
  };
}

function getNewMeetings(cache, state, forceToday = false) {
  const cutoffDate = new Date();
  cutoffDate.setDate(cutoffDate.getDate() - LOOKBACK_DAYS);

  const today = new Date().toISOString().split('T')[0];
  const newMeetings = [];

  for (const [id, doc] of Object.entries(cache.documents)) {
    // Skip non-meeting documents
    if (doc.type !== 'meeting') continue;

    // Skip deleted documents
    if (doc.deleted_at) continue;

    // Check if already processed (unless forcing today's meetings)
    const docDate = doc.created_at?.split('T')[0];
    if (forceToday && docDate === today) {
      // Allow reprocessing today's meetings
    } else if (state.processedMeetings[id]) {
      continue;
    }

    // Check date cutoff
    const createdAt = new Date(doc.created_at);
    if (createdAt < cutoffDate) continue;

    // Check if meeting has meaningful content (checks notes_markdown + last_viewed_panel)
    const notes = extractNotesFromDoc(doc);
    const hasTranscript = cache.transcripts[id] && cache.transcripts[id].length > 0;

    if (notes.length < MIN_NOTES_LENGTH && !hasTranscript) {
      continue;
    }

    // Get transcript if available
    const transcriptEntries = cache.transcripts[id] || [];
    const transcript = transcriptEntries
      .sort((a, b) => new Date(a.start_timestamp) - new Date(b.start_timestamp))
      .map(t => t.text)
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim();

    // Extract participants from people data
    const participants = [];
    if (doc.people?.attendees) {
      for (const attendee of doc.people.attendees) {
        const name = attendee.details?.person?.name?.fullName || attendee.name || attendee.email;
        if (name) participants.push(name);
      }
    }
    if (doc.people?.creator?.name) {
      participants.push(doc.people.creator.name);
    }

    newMeetings.push({
      id,
      title: doc.title || 'Untitled Meeting',
      createdAt: doc.created_at,
      updatedAt: doc.updated_at,
      notes,
      transcript,
      participants: [...new Set(participants)],
      company: extractCompanyFromTitle(doc.title),
      duration: doc.meeting_end_count ? doc.meeting_end_count * 5 : null, // rough estimate
      source: 'cache'
    });
  }

  // Sort by date (newest first)
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
    throw new Error('No LLM API key found. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY in .env');
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
  log('Dex Meeting Intel - Granola Sync (API-first)');
  log('='.repeat(60));

  // Load configuration
  const profile = loadUserProfile();
  const pillars = loadPillars();
  log(`User: ${profile.name} (${profile.role})`);
  log(`Pillars: ${pillars.join(', ')}`);

  // Load state
  const state = loadState();
  log(`Last sync: ${state.lastSync || 'Never'}`);
  log(`Previously processed: ${Object.keys(state.processedMeetings).length} meetings`);

  // ---- Data source: API-first with cache fallback ----
  let newMeetings = null;
  let dataSource = 'none';

  log('\nFetching meetings (API-first with cache fallback)...');

  // Try Granola API first (structured JSON, includes mobile recordings)
  newMeetings = await getNewMeetingsFromApi(state, force);

  if (newMeetings !== null) {
    dataSource = 'api';
    log(`  Using API data (${newMeetings.length} meetings)`);
  } else {
    // Fallback to local cache (desktop meetings only)
    log('  API unavailable, falling back to local cache...');
    let cache;
    try {
      cache = readGranolaCache();
      log(`  Granola cache loaded: ${Object.keys(cache.documents).length} documents`);
      dataSource = 'cache';
    } catch (err) {
      log(`ERROR: Could not read cache either: ${err.message}`);
      log('Neither API nor local cache available. Exiting.');
      process.exit(1);
    }
    newMeetings = getNewMeetings(cache, state, force);
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

module.exports = { main, readGranolaCache, getNewMeetings };
