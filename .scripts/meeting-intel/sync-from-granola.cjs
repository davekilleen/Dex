#!/usr/bin/env node

/**
 * Sync from Granola - Background meeting intelligence processor
 *
 * Uses Granola's official MCP server as PRIMARY data source, with local
 * cache as FALLBACK. Processes new meetings with LLM and generates
 * structured meeting notes.
 *
 * Designed to run automatically via macOS Launch Agent every 30 minutes.
 * No Cursor or Claude required - fully autonomous.
 *
 * Data source priority:
 *   1. Granola MCP server (https://mcp.granola.ai/mcp) — includes mobile recordings
 *   2. Local Granola cache (cache-v3.json) — desktop-only fallback
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

const GRANOLA_MCP_ENDPOINT = 'https://mcp.granola.ai/mcp';
const TOKEN_FILE = path.join(os.homedir(), '.config', 'dex', 'granola-tokens.json');

// Get Granola cache path for current OS
function getGranolaCachePath() {
  const homedir = os.homedir();
  const platform = os.platform();

  if (platform === 'darwin') {
    // macOS
    return path.join(homedir, 'Library/Application Support/Granola/cache-v3.json');
  } else if (platform === 'win32') {
    // Windows - try AppData\Roaming first, then Local
    const roaming = process.env.APPDATA || path.join(homedir, 'AppData/Roaming');
    const local = process.env.LOCALAPPDATA || path.join(homedir, 'AppData/Local');

    for (const basePath of [roaming, local]) {
      const cachePath = path.join(basePath, 'Granola/cache-v3.json');
      if (fs.existsSync(cachePath)) {
        return cachePath;
      }
    }

    // Default to Roaming if neither exists
    return path.join(roaming, 'Granola/cache-v3.json');
  } else {
    // Linux or other
    return path.join(homedir, '.config/Granola/cache-v3.json');
  }
}

const GRANOLA_CACHE = getGranolaCachePath();
const STATE_FILE = path.join(__dirname, 'processed-meetings.json');
const MEETINGS_DIR = path.join(VAULT_ROOT, 'Inbox', 'Meetings');
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
// GRANOLA MCP CLIENT — PRIMARY DATA SOURCE
// ============================================================================

const { createMcpClient } = require('./granola-mcp-client.cjs');

/**
 * Convert MCP meeting data to the standard meeting format expected by the
 * rest of the pipeline.
 *
 * The MCP get_meetings response may return data in various shapes depending
 * on the server version. This function normalises all known variants into:
 *   { id, title, createdAt, updatedAt, notes, transcript, participants,
 *     company, duration, source }
 */
function convertMcpMeetingToStandard(meeting) {
  const id = meeting.id || meeting.meeting_id || '';
  const title = meeting.title || meeting.name || 'Untitled Meeting';
  const createdAt = meeting.date || meeting.created_at || meeting.start_time || '';
  const updatedAt = meeting.updated_at || meeting.end_time || '';

  // Build notes from enhanced_notes + private_notes
  const noteParts = [];
  if (meeting.enhanced_notes) {
    noteParts.push(meeting.enhanced_notes);
  }
  if (meeting.private_notes) {
    noteParts.push(meeting.private_notes);
  }
  if (meeting.notes) {
    // Plain notes field — only add if we don't already have enhanced/private
    if (noteParts.length === 0) {
      noteParts.push(typeof meeting.notes === 'string' ? meeting.notes : '');
    }
  }
  // If notes came as ProseMirror JSON (from notes_content or similar)
  if (meeting.notes_content && typeof meeting.notes_content === 'object') {
    const converted = convertProseMirrorToMarkdown(meeting.notes_content);
    if (converted.length > noteParts.join('\n\n').length) {
      noteParts.length = 0;
      noteParts.push(converted);
    }
  }

  const notes = noteParts.join('\n\n---\n\n').trim();

  // Extract participant names from attendees
  const participants = [];
  const attendees = meeting.attendees || meeting.participants || [];
  if (Array.isArray(attendees)) {
    for (const att of attendees) {
      if (typeof att === 'string') {
        participants.push(att);
      } else if (att && typeof att === 'object') {
        const name = att.name || att.fullName || att.display_name || att.email || '';
        if (name) participants.push(name);
      }
    }
  }

  // Duration
  let duration = meeting.duration || null;
  if (!duration && createdAt && updatedAt) {
    const start = new Date(createdAt);
    const end = new Date(updatedAt);
    if (!isNaN(start) && !isNaN(end) && end > start) {
      duration = Math.round((end - start) / 60000); // minutes
    }
  }

  return {
    id,
    title,
    createdAt,
    updatedAt,
    notes,
    transcript: '', // transcript fetched separately
    participants: [...new Set(participants)],
    company: extractCompanyFromTitle(title),
    duration,
    source: 'mcp'
  };
}

/**
 * Fetch new meetings via the Granola MCP server.
 *
 * Flow:
 *   1. list_meetings → get IDs and metadata
 *   2. Filter to unprocessed meetings within lookback window
 *   3. get_meetings for the unprocessed IDs → full content
 *   4. get_meeting_transcript for each → raw transcript (best-effort)
 *   5. Convert to standard meeting format
 *
 * Returns an array of meeting objects, or null if MCP is unavailable.
 */
async function getNewMeetingsFromMcp(state, forceToday = false) {
  const mcpClient = createMcpClient();

  if (!mcpClient.isAvailable()) {
    log('  MCP tokens not found, skipping MCP source');
    return null;
  }

  try {
    // Step 1: Initialize session
    await mcpClient.initialize();

    // Step 2: List meetings
    const listResult = await mcpClient.listMeetings();
    if (!listResult) {
      log('  MCP list_meetings returned no data');
      mcpClient.close();
      return null;
    }

    // Normalise list result to an array of meeting stubs
    let meetingList = [];
    if (Array.isArray(listResult)) {
      meetingList = listResult;
    } else if (listResult.meetings && Array.isArray(listResult.meetings)) {
      meetingList = listResult.meetings;
    } else if (typeof listResult === 'string') {
      // Sometimes MCP tools return markdown text — try to parse structured data from it
      log('  MCP list_meetings returned text, attempting parse...');
      try {
        meetingList = JSON.parse(listResult);
        if (!Array.isArray(meetingList)) {
          meetingList = meetingList.meetings || [];
        }
      } catch (e) {
        // Text response that is not JSON — cannot extract meeting IDs
        log('  Could not parse meeting list from text response');
        mcpClient.close();
        return null;
      }
    }

    log(`  MCP returned ${meetingList.length} meetings`);

    // Step 3: Filter to unprocessed, within lookback window
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - LOOKBACK_DAYS);
    const today = new Date().toISOString().split('T')[0];

    const unprocessedIds = [];
    const meetingMeta = {};

    for (const m of meetingList) {
      const id = m.id || m.meeting_id || '';
      if (!id) continue;

      const dateStr = m.date || m.created_at || m.start_time || '';
      const docDate = dateStr.split('T')[0];

      // Check processed state
      if (forceToday && docDate === today) {
        // Allow reprocessing today's meetings
      } else if (state.processedMeetings[id]) {
        continue;
      }

      // Check date cutoff
      const createdAt = new Date(dateStr);
      if (isNaN(createdAt.getTime()) || createdAt < cutoffDate) continue;

      unprocessedIds.push(id);
      meetingMeta[id] = m;
    }

    if (unprocessedIds.length === 0) {
      log('  No unprocessed meetings found via MCP');
      mcpClient.close();
      return [];
    }

    log(`  ${unprocessedIds.length} unprocessed meeting(s) to fetch`);

    // Step 4: Get full meeting content (batch)
    const fullMeetings = await mcpClient.getMeetings(unprocessedIds);

    // Normalise to array
    let meetingDetails = [];
    if (Array.isArray(fullMeetings)) {
      meetingDetails = fullMeetings;
    } else if (fullMeetings && fullMeetings.meetings && Array.isArray(fullMeetings.meetings)) {
      meetingDetails = fullMeetings.meetings;
    } else if (fullMeetings && typeof fullMeetings === 'object' && !Array.isArray(fullMeetings)) {
      // Single meeting object or keyed by ID
      if (fullMeetings.id || fullMeetings.meeting_id) {
        meetingDetails = [fullMeetings];
      } else {
        // Might be keyed object { id1: {...}, id2: {...} }
        meetingDetails = Object.values(fullMeetings);
      }
    }

    // Step 5: Convert to standard format and enrich with transcripts
    const newMeetings = [];

    for (const detail of meetingDetails) {
      const meeting = convertMcpMeetingToStandard(detail);

      // Merge any metadata from the list response
      const meta = meetingMeta[meeting.id];
      if (meta) {
        if (!meeting.title || meeting.title === 'Untitled Meeting') {
          meeting.title = meta.title || meta.name || meeting.title;
        }
        if (meeting.participants.length === 0 && meta.attendees) {
          const attendees = Array.isArray(meta.attendees) ? meta.attendees : [];
          for (const att of attendees) {
            const name = typeof att === 'string' ? att : (att.name || att.email || '');
            if (name) meeting.participants.push(name);
          }
          meeting.participants = [...new Set(meeting.participants)];
        }
        if (!meeting.company) {
          meeting.company = extractCompanyFromTitle(meeting.title);
        }
      }

      // Skip meetings with insufficient content
      if (meeting.notes.length < MIN_NOTES_LENGTH) {
        log(`  Skipping "${meeting.title}" — notes too short (${meeting.notes.length} chars)`);
        continue;
      }

      // Step 5b: Try to get transcript (best-effort, may fail on free tiers)
      try {
        const transcript = await mcpClient.getTranscript(meeting.id);
        if (transcript) {
          if (typeof transcript === 'string') {
            meeting.transcript = transcript;
          } else if (transcript.text) {
            meeting.transcript = transcript.text;
          } else if (transcript.transcript) {
            meeting.transcript = transcript.transcript;
          }
        }
      } catch (e) {
        // Transcript not available — not fatal
      }

      newMeetings.push(meeting);
    }

    // Sort newest first
    newMeetings.sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));

    mcpClient.close();
    return newMeetings;

  } catch (err) {
    log(`  MCP error: ${err.message}`);
    try { mcpClient.close(); } catch (e) { /* ignore */ }
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

  // The cache has a nested structure: { cache: JSON_STRING }
  const cacheData = JSON.parse(cacheWrapper.cache);

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
  // Generate sequential 3-digit ID for the day
  // In the automated script, we'll use a simple counter
  const now = new Date();
  const ms = now.getMilliseconds();
  const seconds = now.getSeconds();
  const num = ((seconds * 1000 + ms) % 999) + 1; // Ensures 1-999
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
  // Clean up pillar - remove brackets, quotes, etc.
  pillar = pillar.replace(/[\[\]"']/g, '').trim();

  // Filter participants to exclude the owner
  const ownerName = profile.name || '';
  const filteredParticipants = meeting.participants.filter(p =>
    p.toLowerCase() !== ownerName.toLowerCase() &&
    !p.toLowerCase().includes(ownerName.toLowerCase().split(' ')[0])
  );

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
*Processed by Dex Meeting Intel (${meeting.source === 'mcp' ? 'MCP' : 'Cache'} source)*
`;

  fs.writeFileSync(filepath, content);
  log(`Created meeting note: ${filepath}`);

  return {
    filepath,
    wikilink: `00-Inbox/Meetings/${date}/${slug}.md`
  };
}

// ============================================================================
// QUEUE MANAGEMENT
// ============================================================================

function updateQueue(processedMeetings) {
  const today = new Date().toISOString().split('T')[0];

  // Ensure meetings dir exists
  if (!fs.existsSync(MEETINGS_DIR)) {
    fs.mkdirSync(MEETINGS_DIR, { recursive: true });
  }

  // Read existing queue
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

  // Add processed meetings to the Processed section
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
  log('Dex Meeting Intel - Granola Sync (MCP-first)');
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

  // ---- Data source: MCP-first with cache fallback ----
  let newMeetings = null;
  let dataSource = 'none';

  log('\nFetching meetings (MCP-first with cache fallback)...');

  // Try MCP first
  newMeetings = await getNewMeetingsFromMcp(state, force);

  if (newMeetings !== null) {
    dataSource = 'mcp';
    log(`  Using MCP data (${newMeetings.length} meetings)`);
  } else {
    // Fallback to local cache
    log('  MCP unavailable, falling back to local cache...');
    let cache;
    try {
      cache = readGranolaCache();
      log(`  Granola cache loaded: ${Object.keys(cache.documents).length} documents`);
      dataSource = 'cache';
    } catch (err) {
      log(`ERROR: Could not read cache either: ${err.message}`);
      log('Neither MCP nor local cache available. Exiting.');
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

  // Process each meeting
  const processedResults = [];

  for (const meeting of newMeetings) {
    log(`\nProcessing: ${meeting.title}`);
    log(`  Date: ${meeting.createdAt.split('T')[0]}`);
    log(`  Source: ${meeting.source || dataSource}`);
    log(`  Participants: ${meeting.participants.join(', ') || 'Unknown'}`);

    try {
      // Analyze with LLM
      log('  Calling LLM for analysis...');
      const analysis = await analyzeWithLLM(meeting, profile, pillars);

      // Create meeting note
      log('  Creating meeting note...');
      const result = createMeetingNote(meeting, analysis, profile, pillars);

      // Mark as processed
      state.processedMeetings[meeting.id] = {
        title: meeting.title,
        processedAt: new Date().toISOString(),
        filepath: result.filepath,
        source: meeting.source || dataSource
      };

      processedResults.push({
        meeting,
        ...result
      });

      log(`  Done: ${result.wikilink}`);

      // Small delay between LLM calls
      await new Promise(r => setTimeout(r, 1000));

    } catch (err) {
      log(`  Failed: ${err.message}`);
    }
  }

  // Save state
  saveState(state);

  // Update queue
  if (processedResults.length > 0) {
    log('\nUpdating queue...');
    updateQueue(processedResults);

    // Run post-processing
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
