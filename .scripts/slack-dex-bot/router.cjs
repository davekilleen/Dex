#!/usr/bin/env node

/**
 * Dex Slack conversational router.
 * Two-pass LLM architecture: classify intent → fetch data → generate response.
 *
 * CLI test mode: node router.cjs "what's on my plate?"
 */

// Load .env early so llm-client picks up API keys at require-time
const path = require('path');
const VAULT_ROOT = path.resolve(__dirname, '../..');
require('dotenv').config({ path: path.join(VAULT_ROOT, '.env') });

const { generateContent, isConfigured } = require('../lib/llm-client.cjs');
const { loadProfile, loadPillars, getCalendarToday, getWeekPriorities, getTasks, lookupPerson, searchVault, createTask, completeTask } = require('./data-sources.cjs');
const { buildClassifyPrompt, buildResponsePrompt } = require('./prompts.cjs');
const { formatDayOverview, formatCalendarView, formatPersonBrief, formatMeetingPrep, formatSearchResults, formatUnknown, formatError, wrapResponse } = require('./formatters.cjs');

// In-memory conversation history per user
const conversationHistory = new Map();
const MAX_HISTORY = 5;
const CONTEXT_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

function addToHistory(userId, role, text) {
  if (!conversationHistory.has(userId)) conversationHistory.set(userId, []);
  const history = conversationHistory.get(userId);
  const now = Date.now();

  // Clear stale context (>30 min gap = new conversation)
  if (history.length > 0) {
    const lastTs = history[history.length - 1].timestamp;
    if (now - lastTs > CONTEXT_TIMEOUT_MS) {
      conversationHistory.set(userId, []);
    }
  }

  const current = conversationHistory.get(userId);
  current.push({ role, text: text.slice(0, 500), timestamp: now });
  if (current.length > MAX_HISTORY) current.shift();
}

function getHistory(userId) {
  const history = conversationHistory.get(userId) || [];
  if (history.length === 0) return [];

  // Check staleness
  const now = Date.now();
  if (now - history[history.length - 1].timestamp > CONTEXT_TIMEOUT_MS) {
    conversationHistory.set(userId, []);
    return [];
  }
  return history;
}

/**
 * Build user context object from profile + pillars.
 */
function getUserContext() {
  const profile = loadProfile();
  const pillarsData = loadPillars();
  return {
    name: profile.name || 'User',
    role: profile.role || 'Professional',
    pillars: (pillarsData.pillars || []).map(p => ({ id: p.id, name: p.name })),
    timezone: profile.timezone || 'UTC',
    calendarBackend: profile.calendar_backend || 'office365',
    workCalendar: (profile.calendar && profile.calendar.work_calendar) || 'Work'
  };
}

/**
 * Classify user intent via LLM.
 * Returns: { intent: string, params: { person_name?, query?, date? } }
 */
async function classifyIntent(text, history, userContext) {
  if (!isConfigured()) {
    return { intent: 'unknown', params: {} };
  }

  const prompt = buildClassifyPrompt(text, history, userContext);

  try {
    const raw = await generateContent(prompt, { maxOutputTokens: 256 });
    // Extract JSON from response (handle markdown code blocks)
    const jsonStr = raw.replace(/```json?\n?/g, '').replace(/```/g, '').trim();
    const parsed = JSON.parse(jsonStr);
    return {
      intent: parsed.intent || 'unknown',
      params: parsed.params || {}
    };
  } catch (e) {
    console.error(`[classify] LLM parse error: ${e.message}`);
    return { intent: 'unknown', params: {} };
  }
}

/**
 * Fetch data based on classified intent.
 */
function fetchData(intent, params) {
  switch (intent) {
    case 'day_overview': {
      const calendar = getCalendarToday();
      const priorities = getWeekPriorities();
      const tasks = getTasks();
      return { calendar: calendar.events, priorities, tasks };
    }
    case 'calendar_query': {
      const calendar = getCalendarToday();
      return { calendar: calendar.events, error: calendar.error };
    }
    case 'person_lookup': {
      const person = lookupPerson(params.person_name);
      return { person };
    }
    case 'meeting_prep': {
      const person = params.person_name ? lookupPerson(params.person_name) : { found: false };
      const calendar = getCalendarToday();
      return { person, calendar: calendar.events };
    }
    case 'search': {
      const query = params.query || params.person_name || '';
      const results = searchVault(query);
      return { results, query };
    }
    default:
      return {};
  }
}

/**
 * Generate LLM response with fetched data.
 */
async function generateResponse(intent, data, userContext) {
  if (!isConfigured()) {
    return 'LLM not configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY in .env';
  }

  const prompt = buildResponsePrompt(intent, data, userContext);

  try {
    let response = await generateContent(prompt, { maxOutputTokens: 1024 });
    // Convert markdown bold **text** to Slack mrkdwn bold *text*
    response = response.replace(/\*\*(.+?)\*\*/g, '*$1*');
    // Convert markdown headers ## to bold
    response = response.replace(/^#{1,3}\s+(.+)$/gm, '*$1*');
    return response;
  } catch (e) {
    console.error(`[respond] LLM error: ${e.message}`);
    return `Couldn't generate response: ${e.message}`;
  }
}

/**
 * Format response into Block Kit based on intent.
 */
function formatResponse(intent, llmResponse) {
  const formatters = {
    day_overview: formatDayOverview,
    calendar_query: formatCalendarView,
    person_lookup: formatPersonBrief,
    meeting_prep: formatMeetingPrep,
    search: formatSearchResults,
    unknown: formatUnknown
  };
  const formatter = formatters[intent] || formatUnknown;
  return formatter(llmResponse);
}

/**
 * Main routing function.
 * Takes user text, returns { blocks, text } for Slack.
 */
async function routeMessage(text, userId) {
  const userContext = getUserContext();
  const history = getHistory(userId || 'default');

  // Pass 1: Classify intent
  const { intent, params } = await classifyIntent(text, history, userContext);
  console.log(`[router] Intent: ${intent}, Params: ${JSON.stringify(params)}`);

  // Direct action intents (no LLM pass 2 — just execute and confirm)
  if (intent === 'task_create') {
    const title = params.task_title || text.replace(/^(create task|add task|remind me to|task)[:\s]*/i, '').trim();
    const pillar = params.pillar || userContext.pillars[0]?.id || 'general';
    const priority = params.priority || 'P2';
    const result = createTask(title, pillar, priority);
    const msg = result.success
      ? `\u2705 *Task created*\n\n*${result.title}*\n${result.pillar} | ${result.priority} | ID: \`${result.task_id}\``
      : `\u274c Couldn't create task: ${result.error}`;
    const formatted = wrapResponse(msg, null, null);
    addToHistory(userId || 'default', 'user', text);
    addToHistory(userId || 'default', 'assistant', formatted.text);
    return formatted;
  }

  if (intent === 'task_complete') {
    const query = params.task_title || text.replace(/^(done with|finished|completed|mark .* as done|mark done)[:\s]*/i, '').trim();
    const result = completeTask(query);
    const msg = result.success
      ? `\u2705 *Done!* Checked off: ${result.title}\n_in ${result.file}_`
      : `\u274c ${result.error}`;
    const formatted = wrapResponse(msg, null, null);
    addToHistory(userId || 'default', 'user', text);
    addToHistory(userId || 'default', 'assistant', formatted.text);
    return formatted;
  }

  // Read intents: fetch data → LLM pass 2 → format
  const data = fetchData(intent, params);
  const llmResponse = await generateResponse(intent, data, userContext);
  const formatted = formatResponse(intent, llmResponse);

  addToHistory(userId || 'default', 'user', text);
  addToHistory(userId || 'default', 'assistant', formatted.text);

  return formatted;
}

module.exports = {
  routeMessage,
  addToHistory,
  getHistory,
  classifyIntent,
  fetchData,
  getUserContext
};

// --- CLI test mode ---
if (require.main === module) {
  const query = process.argv.slice(2).join(' ');
  if (!query) {
    console.log('Usage: node router.cjs "what\'s on my plate?"');
    process.exit(1);
  }

  console.log(`\nRouting: "${query}"\n`);
  routeMessage(query, 'cli-test')
    .then(result => {
      console.log('=== Block Kit ===');
      console.log(JSON.stringify(result.blocks, null, 2));
      console.log('\n=== Text Fallback ===');
      console.log(result.text);
    })
    .catch(e => {
      console.error('Error:', e.message);
      process.exit(1);
    });
}
