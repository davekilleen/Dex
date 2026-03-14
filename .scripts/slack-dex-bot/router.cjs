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
const { callWorkServer } = require('./work-bridge.cjs');
const memory = require('./memory.cjs');
const { buildClassifyPrompt, buildResponsePrompt, buildReasoningPrompt } = require('./prompts.cjs');
const { formatDayOverview, formatCalendarView, formatPersonBrief, formatMeetingPrep, formatSearchResults, formatUnknown, formatError, wrapResponse } = require('./formatters.cjs');

// Persistent conversation history via SQLite (survives restarts)
function addToHistory(userId, role, text, intent) {
  memory.addMessage(userId, role, text, intent);
}

function getHistory(userId) {
  return memory.getRecentHistory(userId, 10, 60);
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
      complexity: parsed.complexity || 'simple',
      params: parsed.params || {}
    };
  } catch (e) {
    console.error(`[classify] LLM parse error: ${e.message}`);
    return { intent: 'unknown', complexity: 'simple', params: {} };
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
    case 'week_progress': {
      return callWorkServer('get_week_progress');
    }
    case 'commitment_check': {
      return callWorkServer('get_commitments_due', { date_range: params.date || 'today' });
    }
    case 'pillar_status': {
      const wp = getWeekPriorities();
      const tasks = getTasks();
      return { priorities: wp, tasks };
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
    week_progress: r => wrapResponse(r, '\ud83d\udcca', 'Week Progress'),
    commitment_check: r => wrapResponse(r, '\ud83d\udccc', 'Commitments'),
    pillar_status: r => wrapResponse(r, '\ud83c\udfaf', 'Pillar Balance'),
    unknown: formatUnknown
  };
  const formatter = formatters[intent] || formatUnknown;
  return formatter(llmResponse);
}

/**
 * Gather data from multiple sub-queries and generate a reasoned response.
 */
async function routeComplexMessage(text, subQueries, params, userContext, userId) {
  const gathered = {};

  // Map sub-query names to data fetchers
  const fetchers = {
    calendar: () => getCalendarToday().events,
    tasks: () => getTasks(),
    week_progress: () => callWorkServer('get_week_progress'),
    commitments: () => callWorkServer('get_commitments_due'),
  };

  // Gather data (sequentially to avoid overwhelming Python calls)
  for (const sq of (subQueries || [])) {
    const key = sq.split(':')[0]; // "person:Eoin" → "person", "search:query" → "search"
    const arg = sq.split(':')[1];

    if (key === 'person' && arg) {
      gathered.person = lookupPerson(arg);
      const prev = memory.getLastInteraction('person', arg);
      if (prev) gathered.person_history = prev;
    } else if (key === 'search' && arg) {
      gathered.search = searchVault(arg);
    } else if (fetchers[key]) {
      gathered[key] = fetchers[key]();
    }
  }

  // Generate reasoned response
  const prompt = buildReasoningPrompt(text, gathered, userContext);
  try {
    let response = await generateContent(prompt, { maxOutputTokens: 1500 });
    response = response.replace(/\*\*(.+?)\*\*/g, '*$1*');
    response = response.replace(/^#{1,3}\s+(.+)$/gm, '*$1*');
    return wrapResponse(response, '\ud83e\udde0', 'Analysis');
  } catch (e) {
    console.error(`[reason] LLM error: ${e.message}`);
    return wrapResponse(`Couldn't complete analysis: ${e.message}`, null, null);
  }
}

/**
 * Main routing function.
 * Takes user text, returns { blocks, text } for Slack.
 */
async function routeMessage(text, userId) {
  const userContext = getUserContext();
  const history = getHistory(userId || 'default');

  // Pass 1: Classify intent + complexity
  const { intent, complexity, params } = await classifyIntent(text, history, userContext);
  console.log(`[router] Intent: ${intent}, Complexity: ${complexity}, Params: ${JSON.stringify(params)}`);

  // Track entity interactions for memory context
  if (params.person_name) memory.trackInteraction('person', params.person_name, intent);

  // Complex multi-step reasoning path
  if (complexity === 'multi_step' && params.sub_queries) {
    const formatted = await routeComplexMessage(text, params.sub_queries, params, userContext, userId);
    addToHistory(userId || 'default', 'user', text, 'complex_query');
    addToHistory(userId || 'default', 'assistant', formatted.text, 'complex_query');
    return formatted;
  }

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
    addToHistory(userId || 'default', 'user', text, intent);
    addToHistory(userId || 'default', 'assistant', formatted.text, intent);
    return formatted;
  }

  if (intent === 'commitment_create') {
    const title = params.task_title || text;
    const pillar = params.pillar || userContext.pillars[0]?.id || 'general';
    const result = createTask(title, pillar, 'P1');
    if (result.success) {
      memory.trackInteraction('commitment', title, params.person_name || 'self');
    }
    const msg = result.success
      ? `\ud83d\udccc *Commitment tracked*\n\n*${result.title}*\n${result.pillar} | ${result.priority} | ID: \`${result.task_id}\`\n\nI'll remind you when it's due.`
      : `\u274c Couldn't track commitment: ${result.error}`;
    const formatted = wrapResponse(msg, null, null);
    addToHistory(userId || 'default', 'user', text, intent);
    addToHistory(userId || 'default', 'assistant', formatted.text, intent);
    return formatted;
  }

  if (intent === 'task_complete') {
    const query = params.task_title || text.replace(/^(done with|finished|completed|mark .* as done|mark done)[:\s]*/i, '').trim();
    const result = completeTask(query);
    const msg = result.success
      ? `\u2705 *Done!* Checked off: ${result.title}\n_in ${result.file}_`
      : `\u274c ${result.error}`;
    const formatted = wrapResponse(msg, null, null);
    addToHistory(userId || 'default', 'user', text, intent);
    addToHistory(userId || 'default', 'assistant', formatted.text, intent);
    return formatted;
  }

  // Read intents: fetch data → LLM pass 2 → format
  const data = fetchData(intent, params);
  const llmResponse = await generateResponse(intent, data, userContext);
  const formatted = formatResponse(intent, llmResponse);

  addToHistory(userId || 'default', 'user', text, intent);
  addToHistory(userId || 'default', 'assistant', formatted.text, intent);

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
