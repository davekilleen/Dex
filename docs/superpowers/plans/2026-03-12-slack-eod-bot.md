# Slack EOD Check-in Bot Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Dex Slack bot that sends a daily "End of Day Check-in" DM at 17:30 with top 3 triage items from Notion, and handles user replies (OK/Skip/custom list).

**Architecture:** Two-mode single entry point. `index.cjs --eod-now` posts the EOD message via Web API and exits (triggered by `com.dex.slack-eod` LaunchAgent at 17:30). `index.cjs` without flags starts a Bolt Socket Mode app that listens for DM replies (OK/Skip/custom) and updates the local triage accordingly (triggered by `com.dex.slack-bot` KeepAlive LaunchAgent). Both modes share config loading and Notion querying code.

**Tech Stack:** `@slack/bolt` (includes `@slack/web-api`), `@notionhq/client` (existing), `js-yaml` (existing), `dotenv` (existing), `../lib/llm-client.cjs` (existing)

---

## Chunk 1: Foundation + EOD Message Posting

### File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `.scripts/slack-dex-bot/index.cjs` | Entry point: mode routing, config loading, Notion query, LLM selection, Slack posting, Socket Mode listener |
| Modify | `package.json` | Add `@slack/bolt` dependency |
| Modify | `.env` | Add `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_USER_ID`; fill in `NOTION_API_TOKEN`, `NOTION_TRIAGE_DB_ID` |

### Task 1: Install dependency and add credentials

**Files:**
- Modify: `package.json` (add `@slack/bolt`)
- Modify: `.env` (add Slack vars, note Notion vars need real values)

- [ ] **Step 1: Install @slack/bolt**

```bash
cd /Users/tomgreen/Dex && npm install @slack/bolt
```

Expected: `@slack/bolt` added to `package.json` dependencies and `node_modules/`.

- [ ] **Step 2: Add Slack env vars to .env**

Append to `/Users/tomgreen/Dex/.env`:

```bash
# ===========================================
# Slack Bot (EOD Check-in)
# ===========================================
#
# Create a Slack App at https://api.slack.com/apps
# Required scopes: chat:write, im:write, im:history, im:read
# Enable Socket Mode and create an App-Level Token with connections:write scope
#
# Bot token (OAuth & Permissions > Bot User OAuth Token)
SLACK_BOT_TOKEN=xoxb-your-bot-token
# App-level token (Basic Information > App-Level Tokens, scope: connections:write)
SLACK_APP_TOKEN=xapp-your-app-token
# Your Slack user ID (click profile > ... > Copy member ID)
SLACK_USER_ID=your-user-id
```

- [ ] **Step 3: Verify credentials are ready**

Ask the user to fill in the real values for:
- `SLACK_BOT_TOKEN` (they said they have this)
- `SLACK_APP_TOKEN` (needed for Socket Mode — may need to create)
- `SLACK_USER_ID`
- `NOTION_API_TOKEN` (currently placeholder)
- `NOTION_TRIAGE_DB_ID` (currently placeholder — the Handover Tasks DB ID is `64a39ea6-2fb6-83bd-9c9f-0174b589cfc9`, or they may have a different main triage DB)

- [ ] **Step 4: Commit**

```bash
git add package.json package-lock.json
git commit -m "feat: add @slack/bolt dependency for EOD check-in bot"
```

---

### Task 2: Create the bot script — config loading and Notion query

**Files:**
- Create: `.scripts/slack-dex-bot/index.cjs`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p /Users/tomgreen/Dex/.scripts/slack-dex-bot
```

- [ ] **Step 2: Write the script skeleton with config loading and Notion query**

Create `.scripts/slack-dex-bot/index.cjs`:

```javascript
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
const NOTION_TRIAGE_DB_ID = process.env.NOTION_TRIAGE_DB_ID;

// Notion client
let notion = null;
if (NOTION_API_TOKEN) {
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
  console.error(`[${ts}] ${msg}`);
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
 * Fetch open triage items from Notion
 * Returns array of { title, priority, area, notes, url }
 */
async function fetchTriageItems() {
  if (!notion || !NOTION_TRIAGE_DB_ID) {
    throw new Error('Notion not configured: need NOTION_API_TOKEN and NOTION_TRIAGE_DB_ID');
  }

  const response = await notion.databases.query({
    database_id: NOTION_TRIAGE_DB_ID,
    filter: {
      property: 'Status',
      status: { does_not_equal: 'Done' }
    },
    page_size: 30
  });

  const priorityOrder = { P0: 0, P1: 1, P2: 2, P3: 3 };

  // Sort client-side since Notion sorts select by option order, not semantic priority
  return response.results.map(page => {
    const props = page.properties;
    return {
      id: page.id,
      title: extractTitle(props),
      priority: extractSelect(props, 'Priority'),
      area: extractMultiSelect(props, 'Area'),
      notes: extractText(props, 'Notes'),
      action: extractSelect(props, 'Action'),
      status: extractStatus(props, 'Status'),
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

function extractStatus(props, name) {
  const prop = props[name];
  if (prop && prop.type === 'status' && prop.status) return prop.status.name;
  return null;
}

function extractMultiSelect(props, name) {
  const prop = props[name];
  if (prop && prop.type === 'multi_select' && prop.multi_select) {
    return prop.multi_select.map(o => o.name);
  }
  return [];
}

function extractText(props, name) {
  const prop = props[name];
  if (prop && prop.type === 'rich_text' && prop.rich_text) {
    return prop.rich_text.map(t => t.plain_text).join('');
  }
  return '';
}
```

- [ ] **Step 3: Verify the script loads without syntax errors**

```bash
cd /Users/tomgreen/Dex && node --check .scripts/slack-dex-bot/index.cjs && echo "Syntax OK"
```

Expected: "Syntax OK" (validates syntax without executing top-level code).

- [ ] **Step 4: Commit**

```bash
git add .scripts/slack-dex-bot/index.cjs
git commit -m "feat: add slack bot skeleton with config loading and Notion query"
```

---

### Task 3: Add LLM top-3 selection and Slack message formatting

**Files:**
- Modify: `.scripts/slack-dex-bot/index.cjs`

- [ ] **Step 1: Add the LLM selection function**

Append to `index.cjs` (after the Notion extractors):

```javascript
/**
 * Use LLM to select top 3 "Must Complete Today" items from triage
 * Returns array of { title, reason } for the top 3
 */
async function selectTopThree(items, pillars, profile) {
  if (!isConfigured()) {
    log('Warning: No LLM configured, returning first 3 items by priority');
    return items.slice(0, 3).map(item => ({
      title: item.title,
      reason: `${item.priority || 'No priority'} — ${item.area.join(', ') || 'General'}`
    }));
  }

  const dayOfWeek = new Date().toLocaleDateString('en-US', { weekday: 'long' });
  const pillarSummary = pillars.map(p => `- ${p.name}: ${p.description}`).join('\n');
  const itemList = items.map((item, i) =>
    `${i + 1}. "${item.title}" [Priority: ${item.priority || '?'}, Area: ${item.area.join(', ') || '?'}, Action: ${item.action || '?'}]${item.notes ? ` Notes: ${item.notes}` : ''}`
  ).join('\n');

  const prompt = `You are a personal executive assistant. Today is ${dayOfWeek}.

The user is ${profile.name || 'a professional'}, ${profile.role || 'in a leadership role'}.

Their strategic pillars:
${pillarSummary}

Here are their current open triage items:
${itemList}

Select exactly 3 items that MUST be completed tomorrow. Consider:
- Priority level (P0 > P1 > P2 > P3)
- Action type (Action Required > Review for updates > For reference only)
- Day of week (${dayOfWeek} → what makes sense for tomorrow)
- Pillar balance
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
```

- [ ] **Step 2: Add the Slack Block Kit message builder**

Append to `index.cjs`:

```javascript
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

  // Add top 3 as numbered items in a two-column layout
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
```

- [ ] **Step 3: Commit**

```bash
git add .scripts/slack-dex-bot/index.cjs
git commit -m "feat: add LLM selection and Slack Block Kit message builder"
```

---

### Task 4: Add EOD send function and --eod-now mode

**Files:**
- Modify: `.scripts/slack-dex-bot/index.cjs`

- [ ] **Step 1: Add the EOD send function and main entry point**

Append to `index.cjs`:

```javascript
/**
 * Send EOD check-in message to user's DM
 */
async function sendEodCheckin() {
  const { WebClient } = require('@slack/bolt');
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
    text: '\uD83C\uDFAF End of Day Check-in — 3 suggested items for tomorrow',
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
  if (!NOTION_API_TOKEN) missing.push('NOTION_API_TOKEN');
  if (!NOTION_TRIAGE_DB_ID) missing.push('NOTION_TRIAGE_DB_ID');
  if (needSocketMode && !SLACK_APP_TOKEN) missing.push('SLACK_APP_TOKEN');

  if (missing.length > 0) {
    log(`ERROR: Missing env vars: ${missing.join(', ')}`);
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
      log(`ERROR: EOD check-in failed: ${err.message}`);
      process.exit(1);
    });
} else {
  // --- Socket Mode listener (Task 5 will add the Bolt app here) ---
  log('Socket Mode listener not yet implemented. Use --eod-now for EOD check-in.');
  process.exit(0);
}
```

- [ ] **Step 2: Test the EOD mode with a dry run check**

```bash
cd /Users/tomgreen/Dex && node .scripts/slack-dex-bot/index.cjs --eod-now 2>&1
```

Expected: Will fail with "Missing env vars: ..." if credentials aren't set, which confirms the validation works. If credentials are set, it should send the message.

- [ ] **Step 3: Commit**

```bash
git add .scripts/slack-dex-bot/index.cjs
git commit -m "feat: add EOD send function and --eod-now entry point"
```

---

## Chunk 2: Socket Mode Reply Handling

### Task 5: Add Socket Mode Bolt app for reply handling

**Files:**
- Modify: `.scripts/slack-dex-bot/index.cjs` (replace the Socket Mode placeholder)

- [ ] **Step 1: Replace the Socket Mode placeholder with Bolt app**

In `index.cjs`, replace the `else` block at the bottom (the "Socket Mode listener not yet implemented" section) with:

```javascript
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
      // TODO: Future — write confirmed items to 03-Tasks/Tasks.md or update Notion status
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
```

- [ ] **Step 2: Test Socket Mode startup**

```bash
cd /Users/tomgreen/Dex && timeout 5 node .scripts/slack-dex-bot/index.cjs 2>&1 || true
```

Expected: If credentials are set, should print "Dex Slack bot running in Socket Mode" before timeout kills it. If not set, should print the missing env vars error.

- [ ] **Step 3: Commit**

```bash
git add .scripts/slack-dex-bot/index.cjs
git commit -m "feat: add Socket Mode reply handling for EOD check-in"
```

---

### Task 6: Reload LaunchAgents and verify end-to-end

**Files:** No code changes — operational verification only.

- [ ] **Step 1: Unload and reload the LaunchAgents**

```bash
launchctl unload ~/Library/LaunchAgents/com.dex.slack-bot.plist 2>/dev/null
launchctl unload ~/Library/LaunchAgents/com.dex.slack-eod.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.dex.slack-bot.plist
launchctl load ~/Library/LaunchAgents/com.dex.slack-eod.plist
```

- [ ] **Step 2: Verify the KeepAlive bot is running**

```bash
launchctl list | grep dex.slack
```

Expected: `com.dex.slack-bot` with exit code `0` (running). `com.dex.slack-eod` with `-` (waiting for schedule).

- [ ] **Step 3: Check the log for successful startup**

```bash
tail -5 /Users/tomgreen/Library/Logs/dex-slack-bot.log
```

Expected: "Dex Slack bot running in Socket Mode. Listening for EOD replies..."

- [ ] **Step 4: Manually trigger an EOD check-in**

```bash
cd /Users/tomgreen/Dex && node .scripts/slack-dex-bot/index.cjs --eod-now
```

Expected: Should send the EOD message to your Slack DMs. Verify in Slack.

- [ ] **Step 5: Test reply handling**

In Slack, reply to the EOD message with:
1. `OK` → should get confirmation
2. `Skip` → should get skip acknowledgment
3. A numbered list → should get custom list confirmation

- [ ] **Step 6: Final commit**

```bash
git add .scripts/slack-dex-bot/
git commit -m "feat: complete Slack EOD check-in bot with reply handling"
```

---

## Credential Setup Reference

Before any of the testing steps work, the user must fill in `.env` with real values:

| Variable | Where to get it | Currently |
|----------|----------------|-----------|
| `SLACK_BOT_TOKEN` | Slack App > OAuth & Permissions > Bot User OAuth Token | User says they have it |
| `SLACK_APP_TOKEN` | Slack App > Basic Information > App-Level Tokens (scope: `connections:write`) | May need to create |
| `SLACK_USER_ID` | Slack > Click your profile > ... > Copy member ID | Need to fill in |
| `NOTION_API_TOKEN` | notion.so/my-integrations > Create integration > Copy token | Placeholder in .env |
| `NOTION_TRIAGE_DB_ID` | The Notion triage database ID (from URL or ask user) | Placeholder in .env |

**Slack App required scopes:** `chat:write`, `im:write`, `im:history`, `im:read`
**Slack App required features:** Socket Mode enabled, App-Level Token with `connections:write`

---

## What This Does NOT Cover (Future Work)

- Writing confirmed items back to `03-Tasks/Tasks.md` (currently just acknowledges)
- Updating Notion task status based on replies
- Meeting prep integration via Slack
- Calendar integration
- Multi-message threading (currently sends flat DM)
