---
name: trello-setup
description: Connect Trello so Dex can read your boards and manage cards on request
manifest:
  id: trello
  auth: api_key_token
  category: task_access
  mcp_server: mcp-server-trello
  runtime: bun
---

# Trello Setup

Connect your Trello boards so Dex can work with them whenever you ask — check board status, create cards, or move them.

**What this is not (honesty first):** there is no automatic background sync. Dex tasks don't become Trello cards by themselves, and moving a card to Done doesn't automatically update Dex. Everything happens on request, in conversation. If automatic two-way sync matters to you, tell Dex — "I wish Dex synced with Trello automatically" gets it captured on the improvement backlog.

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

**Paste your API key and token when ready.**
```

Wait for the user to provide both values.

### Step 4: Add the MCP Server

Check the user's MCP configuration. If `mcp-server-trello` is not listed:

1. Explain what we're adding:

```
I'll add the Trello connector to your Dex configuration.
This uses mcp-server-trello which runs on Bun for fast performance.
```

2. Add to the user's `.mcp.json`:

```json
{
  "mcp-server-trello": {
    "command": "bunx",
    "args": ["-y", "mcp-server-trello"],
    "env": {
      "TRELLO_API_KEY": "<user's api key>",
      "TRELLO_TOKEN": "<user's token>"
    }
  }
}
```

3. Tell the user the MCP server needs to restart for changes to take effect.

### Step 5: Test the Connection

Run a quick test to confirm everything works:

1. List the user's boards via the Trello MCP
2. Show a brief summary:

```
**Connection test:**
- Found [N] boards: [Board Name 1], [Board Name 2], ...
- API access confirmed

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

Here are your boards:
1. [Board Name 1]
2. [Board Name 2]
3. [Board Name 3]

Pick a board (or say "show all" for the full list).

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
  api_key: <user's api key>
  token: <user's token>
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

One honest note: there's no automatic background sync — I work with Trello
when you ask, not on my own. Want automatic two-way sync? Say so and I'll
capture it on the improvement backlog.

You can adjust settings anytime by running `/trello-setup` again.
```

---

## Troubleshooting

### Token Expired

Trello tokens can be set to expire. If you see auth errors:

1. Go to https://trello.com/power-ups/admin
2. Generate a new token
3. Update `System/integrations/config.yaml` with the new token
4. Restart MCP server

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
- Are the list names matching? (List mapping is case-insensitive but names must partially match)

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
