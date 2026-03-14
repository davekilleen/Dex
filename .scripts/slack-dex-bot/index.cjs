#!/usr/bin/env node

/**
 * Dex Slack Bot — End of Day Check-in
 *
 * Modes:
 *   node index.cjs              — Start Socket Mode listener (KeepAlive)
 *   node index.cjs --eod-now    — Send EOD check-in message and exit
 *
 * Required env vars:
 *   SLACK_BOT_TOKEN   — Bot OAuth token (xoxb-...)
 *   SLACK_APP_TOKEN   — App-level token for Socket Mode (xapp-...)
 *   SLACK_USER_ID     — User to DM
 *   NOTION_API_TOKEN  — Notion integration token
 *   NOTION_TRIAGE_DB_ID — Notion triage database ID
 */

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

// Configuration
const VAULT_ROOT = path.resolve(__dirname, '../..');
require('dotenv').config({ path: path.join(VAULT_ROOT, '.env') });

const { generateContent, isConfigured } = require('../lib/llm-client.cjs');

// Paths
const PILLARS_FILE = path.join(VAULT_ROOT, 'System', 'pillars.yaml');
const PROFILE_FILE = path.join(VAULT_ROOT, 'System', 'user-profile.yaml');
const STATE_DIR = path.join(__dirname, 'state');

// Reply classification
const OK_SYNONYMS = new Set(['ok', 'ok!', 'ok.', 'yes', 'sure', 'sounds good', 'confirmed', 'lgtm']);
const SKIP_SYNONYMS = new Set(['skip', 'skip it', 'nah', 'pass', 'no', 'not today']);

// Env vars
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN;
const SLACK_APP_TOKEN = process.env.SLACK_APP_TOKEN;
const SLACK_USER_ID = process.env.SLACK_USER_ID;
const NOTION_API_TOKEN = process.env.NOTION_API_TOKEN;
// Notion v5: dataSources.query needs the collection ID, not the database URL ID
const NOTION_TRIAGE_DS_ID = process.env.NOTION_TRIAGE_DS_ID || '';

// Notion client
let notion = null;
if (NOTION_API_TOKEN && NOTION_API_TOKEN !== 'your_notion_token_here') {
  const { Client } = require('@notionhq/client');
  notion = new Client({ auth: NOTION_API_TOKEN });
}

/**
 * Log with timestamp (LaunchAgent plists capture stdout to log files)
 */
function log(msg) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] ${msg}`);
}

function logError(msg) {
  const ts = new Date().toISOString();
  console.error(`[${ts}] ERROR: ${msg}`);
}

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

// ============================================================
// State file helpers
// ============================================================

function readPendingCheckin() {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(STATE_DIR, 'pending-checkin.json'), 'utf-8'));
    if (data.date !== todayStr()) return null;
    return data;
  } catch { return null; }
}

function writePendingCheckin(ts, topThree) {
  fs.writeFileSync(path.join(STATE_DIR, 'pending-checkin.json'), JSON.stringify({
    date: todayStr(), ts, topThree
  }, null, 2));
}

function clearPendingCheckin() {
  try { fs.unlinkSync(path.join(STATE_DIR, 'pending-checkin.json')); } catch {}
}

function commitPriorities(items, source) {
  fs.writeFileSync(path.join(STATE_DIR, 'confirmed-priorities.json'), JSON.stringify({
    date: todayStr(), items, source
  }, null, 2));
  log(`Confirmed priorities written (${items.length} items, source: ${source})`);
}

function hasEodLock() {
  const lockFile = path.join(STATE_DIR, `last-eod-${todayStr()}`);
  return fs.existsSync(lockFile);
}

function writeEodLock() {
  fs.writeFileSync(path.join(STATE_DIR, `last-eod-${todayStr()}`), todayStr());
}

function classifyReply(text) {
  if (OK_SYNONYMS.has(text)) return 'confirm';
  if (SKIP_SYNONYMS.has(text)) return 'skip';
  if (/^\d+[\.\)]\s/.test(text)) return 'custom';
  return 'unknown';
}

// ============================================================
// Crash counter (protects against KeepAlive tight loops)
// ============================================================

function checkCrashCounter() {
  const counterFile = path.join(STATE_DIR, 'crash-counter.json');
  try {
    const data = JSON.parse(fs.readFileSync(counterFile, 'utf-8'));
    const elapsed = Date.now() - (data.lastCrash || 0);
    if (elapsed < 60000) {
      data.count = (data.count || 0) + 1;
      if (data.count > 5) {
        logError('Crash loop detected (>5 rapid restarts). Self-disabling. Fix credentials and restart manually.');
        fs.writeFileSync(counterFile, JSON.stringify(data, null, 2));
        process.exit(0);
      }
    } else {
      data.count = 1;
    }
    data.lastCrash = Date.now();
    fs.writeFileSync(counterFile, JSON.stringify(data, null, 2));
  } catch {
    fs.writeFileSync(counterFile, JSON.stringify({ count: 1, lastCrash: Date.now() }, null, 2));
  }
}

function resetCrashCounter() {
  try { fs.unlinkSync(path.join(STATE_DIR, 'crash-counter.json')); } catch {}
}

/**
 * Load strategic pillars from YAML
 */
function loadPillars() {
  try {
    const data = yaml.load(fs.readFileSync(PILLARS_FILE, 'utf-8'));
    return data.pillars || [];
  } catch (e) {
    log(`Warning: Could not load pillars: ${e.message}`);
    return [];
  }
}

/**
 * Load user profile from YAML
 */
function loadProfile() {
  try {
    return yaml.load(fs.readFileSync(PROFILE_FILE, 'utf-8'));
  } catch (e) {
    log(`Warning: Could not load profile: ${e.message}`);
    return {};
  }
}

/**
 * Fetch open triage items from Notion (Dex Triage database)
 * Returns array of { id, title, priority, pillar, company, status, due, rank, url }
 */
async function fetchTriageItems() {
  if (!notion || !NOTION_TRIAGE_DS_ID) {
    throw new Error('Notion not configured: need NOTION_API_TOKEN and NOTION_TRIAGE_DS_ID');
  }

  // Notion SDK v5: databases.query → dataSources.query
  const response = await notion.dataSources.query({
    data_source_id: NOTION_TRIAGE_DS_ID,
    filter: {
      property: 'Status',
      select: { does_not_equal: 'Done' }
    },
    page_size: 30
  });

  // Priority values are "P0 - Urgent", "P1 - Important", etc.
  const priorityOrder = { 'P0 - Urgent': 0, 'P1 - Important': 1, 'P2 - Normal': 2, 'P3 - Backlog': 3 };

  return response.results.map(page => {
    const props = page.properties;
    return {
      id: page.id,
      title: extractTitle(props),
      priority: extractSelect(props, 'Priority'),
      pillar: extractSelect(props, 'Pillar'),
      company: extractText(props, 'Company'),
      status: extractSelect(props, 'Status'),
      due: props.Due && props.Due.date ? props.Due.date.start : null,
      rank: props.Rank && props.Rank.number != null ? props.Rank.number : null,
      url: page.url
    };
  }).sort((a, b) => (priorityOrder[a.priority] ?? 99) - (priorityOrder[b.priority] ?? 99));
}

// --- Notion property extractors ---

function extractTitle(props) {
  for (const [, prop] of Object.entries(props)) {
    if (prop.type === 'title' && prop.title) {
      return prop.title.map(t => t.plain_text).join('');
    }
  }
  return 'Untitled';
}

function extractSelect(props, name) {
  const prop = props[name];
  if (prop && prop.type === 'select' && prop.select) return prop.select.name;
  if (prop && prop.type === 'status' && prop.status) return prop.status.name;
  return null;
}

function extractText(props, name) {
  const prop = props[name];
  if (prop && prop.type === 'rich_text' && prop.rich_text) {
    return prop.rich_text.map(t => t.plain_text).join('');
  }
  return '';
}

/**
 * Use LLM to select top 3 "Must Complete Today" items from triage
 * Returns array of { title, reason, url }
 */
async function selectTopThree(items, pillars, profile) {
  if (!isConfigured()) {
    log('Warning: No LLM configured, returning first 3 items by priority');
    return items.slice(0, 3).map(item => ({
      title: item.title,
      reason: `${item.priority || 'No priority'} — ${item.pillar || 'General'}`,
      url: item.url
    }));
  }

  const dayOfWeek = new Date().toLocaleDateString('en-US', { weekday: 'long' });
  const pillarSummary = pillars.map(p => `- ${p.name}: ${p.description}`).join('\n');
  const itemList = items.map((item, i) =>
    `${i + 1}. "${item.title}" [Priority: ${item.priority || '?'}, Pillar: ${item.pillar || '?'}, Company: ${item.company || '?'}, Status: ${item.status || '?'}${item.due ? `, Due: ${item.due}` : ''}]`
  ).join('\n');

  const prompt = `You are a personal executive assistant. Today is ${dayOfWeek}.

The user is ${profile.name || 'a professional'}, ${profile.role || 'in a leadership role'}.

Their strategic pillars:
${pillarSummary}

Here are their current open triage items:
${itemList}

Select exactly 3 items that MUST be completed tomorrow. Consider:
- Priority level (P0 - Urgent > P1 - Important > P2 - Normal > P3 - Backlog)
- Status (Triage and Doing items over Someday)
- Due dates (overdue items are urgent)
- Day of week (${dayOfWeek} — what makes sense for tomorrow)
- Pillar balance across their strategic areas
- Items that are closable (not vague or ongoing)

Return ONLY valid JSON, no other text:
[
  { "index": 1, "reason": "brief reason (max 10 words)" },
  { "index": 2, "reason": "brief reason" },
  { "index": 3, "reason": "brief reason" }
]

Where "index" is the 1-based item number from the list above.`;

  try {
    const raw = await generateContent(prompt, { maxOutputTokens: 512 });
    const jsonMatch = raw.match(/\[[\s\S]*?\]/);
    if (!jsonMatch) throw new Error('No JSON array in LLM response');
    const selections = JSON.parse(jsonMatch[0]);

    const validated = selections.slice(0, 3).map(sel => {
      const idx = Number(sel.index);
      if (!Number.isInteger(idx) || idx < 1 || idx > items.length) return null;
      return { title: items[idx - 1].title, reason: sel.reason || '', url: items[idx - 1].url };
    }).filter(Boolean);

    while (validated.length < 3 && validated.length < items.length) {
      const used = new Set(validated.map(v => v.title));
      const next = items.find(it => !used.has(it.title));
      if (!next) break;
      validated.push({ title: next.title, reason: `${next.priority || 'Triage'} priority`, url: next.url });
    }

    return validated;
  } catch (e) {
    log(`LLM selection failed: ${e.message}. Falling back to priority sort.`);
    return items.slice(0, 3).map(item => ({
      title: item.title,
      reason: `${item.priority || 'Triage'} priority`,
      url: item.url
    }));
  }
}

/**
 * Build Slack Block Kit message for EOD check-in
 */
function buildEodBlocks(topThree, allItems) {
  const blocks = [
    {
      type: 'header',
      text: { type: 'plain_text', text: '\uD83C\uDFAF End of Day Check-in', emoji: true }
    },
    {
      type: 'section',
      text: {
        type: 'mrkdwn',
        text: "Time to lock in tomorrow's *Must Complete Today* items.\n\nHere are my suggestions based on your Triage:"
      }
    }
  ];

  // Add top 3 as numbered items
  for (let i = 0; i < topThree.length; i++) {
    const item = topThree[i];
    blocks.push({
      type: 'section',
      text: {
        type: 'mrkdwn',
        text: `*${i + 1}.* ${item.url ? `<${item.url}|${item.title}>` : item.title}`
      }
    });
  }

  blocks.push({ type: 'divider' });

  blocks.push({
    type: 'section',
    text: {
      type: 'mrkdwn',
      text: 'Reply with:\n' +
        '\u2022 `OK` to confirm\n' +
        '\u2022 Your own 3 items (numbered list)\n' +
        '\u2022 `Skip` to skip today'
    }
  });

  // Add truncated triage summary
  const triageSummary = allItems.slice(0, 12).map(item =>
    item.title.length > 40 ? item.title.slice(0, 37) + '...' : item.title
  ).join(', ');

  if (triageSummary) {
    blocks.push({
      type: 'context',
      elements: [{
        type: 'mrkdwn',
        text: `\uD83D\uDCCA *Top Triage items:* ${triageSummary}`
      }]
    });
  }

  return blocks;
}

function buildDegradedBlocks(errorType) {
  return [
    { type: 'header', text: { type: 'plain_text', text: '\uD83C\uDFAF End of Day Check-in', emoji: true } },
    { type: 'section', text: { type: 'mrkdwn', text:
      `Couldn\u2019t reach your triage board (${errorType}).\n\n` +
      'Take 2 minutes \u2014 pick your top 3 for tomorrow and reply with a numbered list:'
    } },
    { type: 'section', text: { type: 'mrkdwn', text:
      '```1. First priority\n2. Second priority\n3. Third priority```'
    } },
    { type: 'context', elements: [{ type: 'mrkdwn', text: 'Or reply `Skip` to skip today.' }] }
  ];
}

/**
 * Send EOD check-in message to user's DM
 */
async function sendEodCheckin() {
  const { WebClient } = require('@slack/web-api');
  const slack = new WebClient(SLACK_BOT_TOKEN);

  log('Starting EOD check-in...');

  if (hasEodLock()) {
    log('EOD already sent today (idempotency lock). Skipping.');
    return;
  }

  const pillars = loadPillars();
  const profile = loadProfile();

  let items;
  let errorType = null;
  try {
    items = await fetchTriageItems();
    log(`Fetched ${items.length} triage items from Notion`);
  } catch (e) {
    const msg = e.message || '';
    if (msg.includes('401') || msg.includes('unauthorized')) errorType = 'auth expired';
    else if (msg.includes('429') || msg.includes('rate')) errorType = 'rate limited';
    else if (msg.includes('404')) errorType = 'database not found';
    else errorType = 'network error';
    logError(`Notion fetch failed (${errorType}): ${msg}`);
  }

  if (errorType) {
    const blocks = buildDegradedBlocks(errorType);
    const result = await slack.chat.postMessage({
      channel: SLACK_USER_ID,
      text: '\uD83C\uDFAF End of Day Check-in \u2014 Notion unavailable, pick your own 3',
      blocks
    });
    writePendingCheckin(result.ts, []);
    writeEodLock();
    log(`Degraded EOD message sent: ts=${result.ts}`);
    return result;
  }

  if (items.length === 0) {
    log('No triage items found. Sending minimal message.');
    await slack.chat.postMessage({
      channel: SLACK_USER_ID,
      text: '\uD83C\uDFAF End of Day Check-in: Your triage is empty! Nice work.',
    });
    writeEodLock();
    return;
  }

  const topThree = await selectTopThree(items, pillars, profile);
  log(`Selected top 3: ${topThree.map(t => t.title).join(', ')}`);

  const blocks = buildEodBlocks(topThree, items);
  const result = await slack.chat.postMessage({
    channel: SLACK_USER_ID,
    text: '\uD83C\uDFAF End of Day Check-in \u2014 3 suggested items for tomorrow',
    blocks
  });

  writePendingCheckin(result.ts, topThree);
  writeEodLock();
  log(`EOD message sent: ts=${result.ts}, channel=${result.channel}`);
  return result;
}

// ============================================================
// Main entry point
// ============================================================

const args = process.argv.slice(2);
const isEodNow = args.includes('--eod-now');

function validateConfig(needSocketMode) {
  const missing = [];
  if (!SLACK_BOT_TOKEN) missing.push('SLACK_BOT_TOKEN');
  if (!SLACK_USER_ID) missing.push('SLACK_USER_ID');
  if (!notion) missing.push('NOTION_API_TOKEN (missing or placeholder)');
  if (!NOTION_TRIAGE_DS_ID) {
    missing.push('NOTION_TRIAGE_DS_ID');
  }
  if (needSocketMode && !SLACK_APP_TOKEN) missing.push('SLACK_APP_TOKEN');

  if (missing.length > 0) {
    logError(`Missing env vars: ${missing.join(', ')}`);
    log('Add them to your .env file in the Dex root directory');
    process.exit(1);
  }
}

if (isEodNow) {
  // --- EOD trigger mode ---
  validateConfig(false);
  sendEodCheckin()
    .then(() => {
      log('EOD check-in complete.');
      process.exit(0);
    })
    .catch(err => {
      logError(`EOD check-in failed: ${err.message}`);
      process.exit(1);
    });

} else {
  // --- Socket Mode listener ---
  validateConfig(true);
  checkCrashCounter();

  const { App, Assistant } = require('@slack/bolt');
  const { routeMessage } = require('./router.cjs');
  const { formatError } = require('./formatters.cjs');

  const app = new App({
    token: SLACK_BOT_TOKEN,
    appToken: SLACK_APP_TOKEN,
    socketMode: true
  });

  app.error(async (error) => {
    logError(`Bolt error: ${error.message}`);
  });

  // --- Assistant API handler (Chat tab) ---
  const assistant = new Assistant({
    threadStarted: async ({ say, setSuggestedPrompts }) => {
      try {
        await say('Hey! What do you need?');
        await setSuggestedPrompts({
          prompts: [
            { title: "What's on my plate?", message: "What's on my plate today?" },
            { title: 'Meetings today', message: 'What meetings do I have today?' },
            { title: 'Search vault', message: 'Search: ' },
          ],
          title: 'Try one of these:',
        });
      } catch (e) {
        logError(`Assistant threadStarted error: ${e.message}`);
      }
    },

    userMessage: async ({ message, say, setTitle, setStatus }) => {
      if (!message.text || !message.thread_ts) return;

      try {
        await setTitle(message.text.slice(0, 60));
        await setStatus('Thinking...');

        log(`[assistant] Routing: "${message.text.slice(0, 80)}"`);
        const result = await routeMessage(message.text.trim(), message.user);
        await say({ text: result.text });
      } catch (e) {
        logError(`Assistant userMessage error: ${e.message}`);
        await say({ text: 'Something went wrong. Try again or check Dex in Claude Code.' });
      }
    },
  });

  app.assistant(assistant);

  /**
   * Check if a message looks like an EOD check-in reply.
   * Only matches OK/Skip/numbered-list patterns — everything else falls through to conversational router.
   */
  function isEodReply(text) {
    const lower = text.toLowerCase().trim();
    if (OK_SYNONYMS.has(lower)) return true;
    if (SKIP_SYNONYMS.has(lower)) return true;
    // Numbered list (at least one line starting with digit + period/paren)
    if (/^\d+[\.\)]\s/m.test(text)) return true;
    return false;
  }

  app.message(async ({ message, say, client }) => {
    if (message.channel_type !== 'im') return;
    if (message.user !== SLACK_USER_ID) return;
    if (message.subtype) return;

    const text = (message.text || '').trim();
    const pending = readPendingCheckin();

    // --- EOD flow: handle if pending AND message looks like an EOD reply ---
    if (pending && isEodReply(text)) {
      const lowerText = text.toLowerCase();
      const eodIntent = classifyReply(lowerText);

      try {
        if (eodIntent === 'confirm') {
          log('User confirmed EOD suggestions');
          commitPriorities(pending.topThree, 'eod-confirm');
          clearPendingCheckin();
          await say('\u2705 Locked in! Tomorrow\'s Must Complete Today items are confirmed.');

        } else if (eodIntent === 'skip') {
          log('User skipped EOD check-in');
          clearPendingCheckin();
          await say('\u23ED Skipped. No items locked in for tomorrow. You can always run your daily plan in the morning.');

        } else if (eodIntent === 'custom') {
          const lines = lowerText.split('\n').filter(l => /^\d+[\.\)]\s/.test(l.trim()));
          const formatted = lines.map(l => l.replace(/^\d+[\.\)]\s*/, '').trim()).filter(Boolean);
          if (formatted.length > 0) {
            log(`User provided custom list: ${formatted.length} items`);
            commitPriorities(formatted.map(t => ({ title: t })), 'eod-custom');
            clearPendingCheckin();
            await say(`\u2705 Custom list locked in:\n${formatted.map((item, i) => `*${i + 1}.* ${item}`).join('\n')}`);
          } else {
            await say('Hmm, I couldn\'t parse that list. Try numbering items like:\n1. First item\n2. Second item\n3. Third item');
          }
        }
      } catch (e) {
        logError(`EOD reply handler failed: ${e.message} (user sent: "${text.slice(0, 50)}")`);
      }
      return;
    }

    // --- Conversational flow ---
    try {
      // Add eyes reaction to show we're processing
      try {
        await client.reactions.add({
          channel: message.channel,
          timestamp: message.ts,
          name: 'eyes'
        });
      } catch { /* reaction failed, non-critical */ }

      log(`[convo] Routing: "${text.slice(0, 80)}"`);
      const result = await routeMessage(text, message.user);
      await say({ blocks: result.blocks, text: result.text });

      // Remove eyes reaction
      try {
        await client.reactions.remove({
          channel: message.channel,
          timestamp: message.ts,
          name: 'eyes'
        });
      } catch { /* non-critical */ }

    } catch (e) {
      logError(`Router failed: ${e.message}`);
      const errResult = formatError(e.message);
      await say({ blocks: errResult.blocks, text: errResult.text });
    }
  });

  // --- Proactive intelligence engine ---
  const proactive = require('./proactive.cjs');

  (async () => {
    await app.start();
    resetCrashCounter();
    log('Dex Slack bot running in Socket Mode. Listening for messages...');

    // Start proactive checks (meeting briefs, stale priorities, commitments, meeting synthesis)
    const { WebClient } = require('@slack/web-api');
    proactive.startAll(new WebClient(SLACK_BOT_TOKEN), SLACK_USER_ID);
  })();
}
