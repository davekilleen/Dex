---
name: trello-setup
description: Connect Trello so Dex can read your boards and manage cards on request
manifest:
  id: trello
  auth: api_key_token
  category: task_access
  mcp_server: null
---

# Trello Setup

Connect your Trello boards so Dex can work with them whenever you ask — check board status, create cards, or move them.

**What this enables (on request):** Once connected, say "sync with Trello" — Dex pushes new
tasks as cards in the right list (Backlog/In Progress/Blocked/Done), marks completions by
moving cards to Done, and pulls cards you moved or created in Trello. Sync runs on demand.

## What This Enables

Once connected, you can ask Dex to:
- **See board status:** cards by list, blocked items, stale cards — "how's the launch board looking?"
- **Create cards:** "Add a card for the pricing review to the backlog list"
- **Update from chat:** "Move the onboarding card to Done" (and, if you ask, mark the matching Dex task complete)
- **Prep with context:** "Which cards are blocked before my 2pm?"

## Privacy

- Dex reads and writes your boards only when you ask it to
- Your API key and token stay local on your machine and are gitignored
- No attachments or comments are read unless you ask
- Only boards you explicitly configure are accessed

## When to Run

- User types `/trello-setup`
- User asks about connecting Trello
- User wants Kanban board context in daily plans or project health
- During `/integrate-mcp` if Trello is mentioned

---

## Setup Flow

### Step 1: Check if Already Connected

1. Check `System/integrations/config.yaml` for a `trello:` section with `enabled: true`
2. If found, skip to **Step 6** (Configure Board Mapping)
3. If not found, continue to Step 2

### Step 2: Explain What We're Setting Up

Say:

```
**Let's connect Trello to Dex.**

This links your Trello boards so you can ask Dex to check board status,
create cards, and move them — right from our conversations.

**What you'll need:**
- A Trello account with at least one board
- Your Trello API key and token (I'll walk you through getting these)
- About 3 minutes

**Ready to go?**
```

Wait for confirmation.

### Step 3: Get API Credentials

Walk the user through getting their Trello API key and token:

```
**Step 1: Get your API Key**

1. Go to https://trello.com/power-ups/admin
2. Click "New" to create a new Power-Up (or use an existing one)
3. Copy your **API Key** from the Power-Up settings

**Step 2: Generate a Token**

1. On the same page, click the link to generate a **Token**
2. Authorize the app when prompted
3. Copy the token that appears

Do not paste either value into this conversation. Open the ignored vault-root `.env` in your
local editor and replace these placeholders directly:

`TRELLO_API_KEY=<paste key locally here>`
`TRELLO_TOKEN=<paste token locally here>`

Save the file with mode `0600`, then reply only `saved`. Dex must never echo, read aloud,
log, or include either value in a command, argv, or process environment.
```

Wait only for the non-secret `saved` confirmation. Never ask the user to provide or validate
either value in chat.

### Step 4: Store Local Credentials

Confirm locally that `.env` defines `TRELLO_API_KEY` and `TRELLO_TOKEN` without printing or
returning either value. Preserve unrelated lines. Never copy either value to `.mcp.json`,
tracked YAML, commands, argv, logs, transcript, or process environment. Existing `.mcp.json`
is scan/report-only and must remain byte-identical.

Before health, update only the non-secret tracked Trello fields to `enabled: true`,
`api_key_env_var: TRELLO_API_KEY`, and `token_env_var: TRELLO_TOKEN`; do not add raw `api_key`
or `token` fields.

### Step 5: Test the Connection

Run a quick test through only Dex's sanitized Python-to-adapter-stdin read-only health path.
It resolves `.env` internally and performs Trello `GET /members/me?fields=id`; never test
through an ambient or external MCP:

```bash
python3 -c 'from core.integrations.task_sync import check_service_health; print(check_service_health("trello"))'
```

1. Confirm the returned health result
2. Show a brief summary:

```
**Connection test:**
- Trello authentication succeeded through the read-only health check

Everything looks good!
```

If it fails, troubleshoot:

```
That didn't work. A few things to check:

1. **API Key correct?** Should be a 32-character string
2. **Token correct?** Should be a longer string (64+ characters)
3. **Account access?** Make sure the token has read/write permissions

Want to re-enter your credentials?
```

Retry up to 2 times, then offer to skip and come back later.

### Step 6: Configure Board Mapping

Ask the user which board to sync:

```
**Which Trello board should Dex sync with?**

The health check does not enumerate boards. Open Trello locally and enter the exact board name
and board ID you want Dex to use without pasting either credential.

You can add more boards later by running `/trello-setup` again.
```

After they choose a board:

```
**Now let's map your lists to Dex statuses.**

I'll look at the lists on [Board Name]:
- "To Do" -> Backlog (not started)
- "In Progress" -> Started
- "Review" -> (unmapped -- keep or map to Blocked?)
- "Done" -> Done

Does this mapping look right? Or should I adjust?
```

Let the user confirm or customize the mapping. Default status list names:
- Backlog / To Do / TODO -> status `n`
- In Progress / Doing / Active -> status `s`
- Blocked / On Hold / Waiting -> status `b`
- Done / Complete / Finished -> status `d`

### Step 7: Save Configuration

Write to `System/integrations/config.yaml` -- update the trello section (the list
mapping is used when the user asks Dex to file or move cards):

```yaml
trello:
  enabled: true
  configured_at: YYYY-MM-DD
  api_key_env_var: TRELLO_API_KEY
  token_env_var: TRELLO_TOKEN
  default_board: <board id>
  board_name: <board name>
  list_mapping:
    backlog: <list id for Backlog>
    in_progress: <list id for In Progress>
    blocked: <list id for Blocked>
    done: <list id for Done>
```

If the file already exists, only update the `trello:` section. Preserve other integration configs.

### Step 8: Confirm

```
**Trello is connected!**

Here's what you can do now:

- **Ask about your board anytime** — "How's the [Board Name] board looking?",
  "Add a card to the backlog", "Move the onboarding card to Done"
- **Bring it into planning** — during /daily-plan or /project-health, ask me
  to include your Trello cards and I will
- **Meeting prep with context** — ask which cards are blocked before a meeting
- **Sync on demand** — say "sync Dex with Trello" and Dex pushes pending tasks, moves
  completions to Done, and reviews cards you created in Trello

**Sync is on demand** — say "sync with Trello" anytime. Dex doesn't poll in the background.

You can adjust settings anytime by running `/trello-setup` again.
```

---

## Troubleshooting

### Token Expired

Trello tokens can be set to expire. If you see auth errors:

1. Go to https://trello.com/power-ups/admin
2. Generate a new token
3. Update `TRELLO_TOKEN` in the vault-root `.env`

### Board Not Found

If the configured board was deleted or renamed:

1. Run `/trello-setup` to reconfigure
2. Select the new board
3. Remap lists if needed

### Rate Limiting

Trello allows 100 requests per 10 seconds. This is generous -- you'd only hit it when asking Dex to make many changes at once. If you see rate limit errors, wait 10 seconds and retry.

### Cards Not Syncing

Check:
- Is the board ID correct in config.yaml?
- Does the token have write access?
- Are the list IDs under `list_mapping` still current? Re-run `/trello-setup` if the
  board's lists were recreated or changed.

---

## Reconfiguration

If the user runs `/trello-setup` when already configured:

1. Show current config from `System/integrations/config.yaml`
2. Offer options:
   - Change the connected board
   - Update list mapping
   - Re-authenticate (new API key/token)
   - Add additional boards
   - Disconnect Trello

### Disconnect Flow

If user wants to disconnect:

1. Update `System/integrations/config.yaml`:
   ```yaml
   trello:
     enabled: false
   ```
2. Confirm: "Trello is disconnected. Your daily plans and project health will no longer include Trello context. Run `/trello-setup` anytime to reconnect."
