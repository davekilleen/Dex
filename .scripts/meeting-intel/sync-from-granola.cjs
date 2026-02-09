#!/usr/bin/env node

/**
 * Sync from Granola - Background meeting intelligence processor
 * 
 * Reads meetings directly from Granola's local cache, processes new meetings
 * with Gemini 3 Pro, and generates structured meeting notes.
 * 
 * Designed to run automatically via macOS Launch Agent every 30 minutes.
 * No Cursor or Claude required - fully autonomous.
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
// GRANOLA CACHE READING
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
    
    // Check if meeting has meaningful content
    const notesLength = (doc.notes_markdown || '').length;
    const hasTranscript = cache.transcripts[id] && cache.transcripts[id].length > 0;
    
    if (notesLength < MIN_NOTES_LENGTH && !hasTranscript) {
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
      notes: doc.notes_markdown || '',
      transcript,
      participants: [...new Set(participants)],
      company: extractCompanyFromTitle(doc.title),
      duration: doc.meeting_end_count ? doc.meeting_end_count * 5 : null // rough estimate
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
    /^([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\s*[-–—]/,
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
*Processed by Dex Meeting Intel (Gemini 3 Pro)*
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
  log('Dex Meeting Intel - Granola Sync');
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
  
  // Read Granola cache
  let cache;
  try {
    cache = readGranolaCache();
    log(`Granola cache loaded: ${Object.keys(cache.documents).length} documents`);
  } catch (err) {
    log(`ERROR: ${err.message}`);
    process.exit(1);
  }
  
  // Find new meetings
  const newMeetings = getNewMeetings(cache, state, force);
  log(`Found ${newMeetings.length} new meetings to process`);
  
  if (newMeetings.length === 0) {
    log('Nothing to process. Exiting.');
    saveState(state);
    return;
  }
  
  if (dryRun) {
    log('\n--- DRY RUN ---');
    for (const meeting of newMeetings) {
      log(`Would process: ${meeting.title} (${meeting.createdAt.split('T')[0]})`);
      log(`  Notes: ${meeting.notes.length} chars`);
      log(`  Transcript: ${meeting.transcript.length} chars`);
      log(`  Participants: ${meeting.participants.join(', ') || 'Unknown'}`);
    }
    return;
  }
  
  // Process each meeting
  const processedResults = [];
  
  for (const meeting of newMeetings) {
    log(`\nProcessing: ${meeting.title}`);
    log(`  Date: ${meeting.createdAt.split('T')[0]}`);
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
        filepath: result.filepath
      };
      
      processedResults.push({
        meeting,
        ...result
      });
      
      log(`  ✓ Done: ${result.wikilink}`);
      
      // Small delay between API calls
      await new Promise(r => setTimeout(r, 1000));
      
    } catch (err) {
      log(`  ✗ Failed: ${err.message}`);
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
  log(`SYNC COMPLETE`);
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
