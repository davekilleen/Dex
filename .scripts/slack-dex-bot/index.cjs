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

// Env vars
const SLACK_BOT_TOKEN = process.env.SLACK_BOT_TOKEN;
const SLACK_APP_TOKEN = process.env.SLACK_APP_TOKEN;
const SLACK_USER_ID = process.env.SLACK_USER_ID;
const NOTION_API_TOKEN = process.env.NOTION_API_TOKEN;
// Notion v5: dataSources.query needs the collection ID, not the database URL ID
const NOTION_TRIAGE_DS_ID = process.env.NOTION_TRIAGE_DS_ID || '0bc99573-8ad4-4c94-a794-dd518848c646';

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
    const jsonMatch = raw.match(/\[[\s\S]*\]/);
    if (!jsonMatch) throw new Error('No JSON array in LLM response');
    const selections = JSON.parse(jsonMatch[0]);

    return selections.slice(0, 3).map(sel => {
      const item = items[sel.index - 1];
      if (!item) return null;
      return { title: item.title, reason: sel.reason, url: item.url };
    }).filter(Boolean);
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

/**
 * Send EOD check-in message to user's DM
 */
async function sendEodCheckin() {
  const { WebClient } = require('@slack/web-api');
  const slack = new WebClient(SLACK_BOT_TOKEN);

  log('Starting EOD check-in...');

  // 1. Load context
  const pillars = loadPillars();
  const profile = loadProfile();

  // 2. Fetch triage items
  const items = await fetchTriageItems();
  log(`Fetched ${items.length} triage items from Notion`);

  if (items.length === 0) {
    log('No triage items found. Sending minimal message.');
    await slack.chat.postMessage({
      channel: SLACK_USER_ID,
      text: '\uD83C\uDFAF End of Day Check-in: Your triage is empty! Nice work.',
    });
    return;
  }

  // 3. Select top 3
  const topThree = await selectTopThree(items, pillars, profile);
  log(`Selected top 3: ${topThree.map(t => t.title).join(', ')}`);

  // 4. Build and send message
  const blocks = buildEodBlocks(topThree, items);
  const result = await slack.chat.postMessage({
    channel: SLACK_USER_ID,
    text: '\uD83C\uDFAF End of Day Check-in \u2014 3 suggested items for tomorrow',
    blocks
  });

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
    log('Add them to /Users/tomgreen/Dex/.env');
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

  const { App } = require('@slack/bolt');

  const app = new App({
    token: SLACK_BOT_TOKEN,
    appToken: SLACK_APP_TOKEN,
    socketMode: true
  });

  // Global error handler
  app.error(async (error) => {
    logError(`Bolt error: ${error.message}`);
  });

  /**
   * Handle DM messages as potential EOD replies
   */
  app.message(async ({ message, say }) => {
    // Only handle DMs from the configured user
    if (message.channel_type !== 'im') return;
    if (message.user !== SLACK_USER_ID) return;
    if (message.subtype) return; // Ignore bot messages, edits, etc.

    const text = (message.text || '').trim().toLowerCase();

    if (text === 'ok') {
      log('User confirmed EOD suggestions');
      await say('\u2705 Locked in! Tomorrow\'s Must Complete Today items are confirmed.');
    } else if (text === 'skip') {
      log('User skipped EOD check-in');
      await say('\u23ED Skipped. No items locked in for tomorrow. You can always run your daily plan in the morning.');
    } else if (/^\d+[\.\)]\s/.test(text)) {
      // Parse numbered list (requires "1. " or "1) " format)
      const lines = text.split('\n').filter(l => /^\d+[\.\)]\s/.test(l.trim()));
      log(`User provided custom list: ${lines.length} items`);
      const formatted = lines.map(l => l.replace(/^\d+[\.\)]\s*/, '').trim()).filter(Boolean);
      if (formatted.length > 0) {
        await say(
          `\u2705 Custom list locked in:\n${formatted.map((item, i) => `*${i + 1}.* ${item}`).join('\n')}`
        );
      } else {
        await say('Hmm, I couldn\'t parse that list. Try numbering items like:\n1. First item\n2. Second item\n3. Third item');
      }
    }
    // Ignore other messages — don't respond to general chat
  });

  // Start the app
  (async () => {
    await app.start();
    log('Dex Slack bot running in Socket Mode. Listening for EOD replies...');
  })();
}
