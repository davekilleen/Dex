---
name: things-setup
description: Connect Things 3 so Dex can read and update your Things tasks on request
manifest:
  id: things
  auth: none
  category: task_access
  platform: macos
  mcp_server: things3-mcp
---

# Things 3 Setup

Connect Things 3 so Dex can work with your Things tasks whenever you ask. No account needed. Everything stays on your Mac. Works offline.

**What this enables (on request):** Once connected, say "sync with Things" — Dex pushes new
tasks to the right Things Area (mapped from your pillars), marks completions via AppleScript,
and pulls tasks you completed or added to Things Inbox. Everything stays local — no network
calls, no accounts. Sync runs on demand when you ask.

## What This Enables

Once connected, you can ask Dex to:
- **See your Things lists:** "What's in my Things Today list?" — including alongside your daily plan
- **Create there instead:** "Put that in Things, not Dex" in any conversation
- **Complete from chat:** "Mark the deck task done in Things"
- **Cross-check:** "Anything in Things that isn't tracked in Dex?"

## Privacy

- Everything is local. Things 3 uses AppleScript — no cloud API, no tokens, no accounts
- Dex reads and writes Things only when you ask. Nothing leaves your machine
- No credentials to store. No tokens to expire. No OAuth flows
- Works completely offline

## When to Run

- User types `/things-setup`
- User asks about connecting Things 3
- User wants Dex working with a Mac-native task app
- During `/integrate-mcp` if Things is mentioned
- During onboarding if user mentions Things 3

---

## Setup Flow

### Step 1: Platform Check

Things 3 is macOS only. Verify:

1. Check if running on macOS (`process.platform === 'darwin'` or `uname` check)
2. **If not macOS:**
   ```
   Things 3 is a macOS-only app. It won't work on this platform.

   For a cross-platform task app connection, consider:
   - /todoist-setup (works everywhere)
   - /trello-setup (web-based)
   ```
   Stop here.

### Step 2: Check if Already Connected

1. Read `System/integrations/config.yaml`
2. If `things.enabled: true`, skip to **Step 7** (Reconfigure)
3. If not configured, continue

### Step 3: Check if Things 3 is Installed

Run a quick AppleScript test:

```bash
osascript -e 'tell application "System Events" to (name of processes) contains "Things3"'
```

Or check if the app exists:

```bash
ls /Applications/Things3.app 2>/dev/null || ls "$HOME/Applications/Things3.app" 2>/dev/null
```

**If Things 3 is not found:**

```
I can't find Things 3 on your Mac.

Things 3 is available from the Mac App Store:
https://apps.apple.com/app/things-3/id904280696

Once installed, run /things-setup again.
```

Stop here.

**If found:**

```
Things 3 detected. This is the simplest integration to set up — no accounts or API keys needed.

Everything stays on your Mac and works offline. Ready?
```

Wait for confirmation.

### Step 4: Add the things3-mcp Server

Check the user's MCP configuration. If `things3-mcp` is not listed:

1. Explain:

```
I need to add the Things 3 connector to your Dex configuration.

This uses a lightweight AppleScript bridge — no accounts, no API keys.
It talks directly to Things 3 on your Mac.
```

2. Add to the user's `.mcp.json`:

```json
{
  "things3-mcp": {
    "command": "npx",
    "args": ["-y", "things3-mcp"],
    "env": {}
  }
}
```

3. Tell the user the MCP server needs to restart for changes to take effect.

### Step 5: Test the Connection

Run a quick test to verify AppleScript access:

1. List Things Areas:
   ```bash
   osascript -e 'tell application "Things3" to get name of areas'
   ```

2. List Things Projects:
   ```bash
   osascript -e 'tell application "Things3" to get name of projects'
   ```

**If macOS prompts for AppleScript permission:**

```
macOS is asking for permission to control Things 3. Click "OK" to allow.

This is a one-time prompt. Things 3 uses AppleScript for local communication —
no network access is involved.
```

**Show results:**

```
Connection test passed.

Your Things 3 setup:
- Areas: [list of areas]
- Projects: [list of projects]
```

If the test fails, jump to Troubleshooting.

### Step 6: Configure Mapping

First, read `System/pillars.yaml` and extract the user's pillar `id` and `name` fields. If pillars are empty/not yet configured, prompt the user to run `/quarter-plan` first.

Map Dex pillars to Things Areas:

```
Now let's map your Dex pillars to Things Areas.

Your Dex pillars (from System/pillars.yaml):
[list each pillar name, numbered]

Your Things Areas:
[list from Step 5]

I'll suggest a mapping — adjust if needed:

| Dex Pillar | Things Area |
|------------|-------------|
| [pillar 1 name] | [best match or "[pillar 1 name]"] |
| [pillar 2 name] | [best match or "[pillar 2 name]"] |
...

Does this mapping look right? I can create any missing Areas in Things.
```

If areas don't exist, offer to create them (run once per missing pillar):

```bash
osascript -e 'tell application "Things3" to make new area with properties {name:"[pillar name]"}'
```

### Step 7: Save Configuration

Write to `System/integrations/config.yaml` — update the things section. Build `area_mapping` dynamically from the user's pillars: use each pillar's `id` as the key and the confirmed Things Area name as the value (used when the user asks Dex to file something in Things under the right Area).

```yaml
things:
  enabled: true
  configured_at: YYYY-MM-DD
  mcp_server: things3-mcp
  auth_type: none
  area_mapping:
    [pillar_id]: [Things Area name]   # one entry per pillar
```

If the file already exists, only update the `things:` section. Preserve other integration configs.

### Step 8: Capability Cascade

Now that Things is connected, highlight what changes:

```
Things 3 is connected.

Here's what you can do now:

- **Ask about Things anytime** — "What's in my Today list?", "Put that in
  Things", "Mark the deck task done in Things"
- **Bring it into planning** — during /daily-plan, ask me to include your
  Things tasks and I will
- **Right Area, automatically** — when I file something in Things for you,
  your pillars map to your Things Areas
- **Sync on demand** — say "sync Dex with Things" and Dex pushes pending tasks, marks
  completions, and reviews anything new in your Things Inbox

No accounts. No tokens. No expiration. Works offline.

**Sync is on demand** — say "sync with Things" anytime. No background polling.
```

---

## Troubleshooting

### Things 3 Not Installed

Things 3 must be installed from the Mac App Store. It's a paid app (~$49.99).
Once installed, run `/things-setup` again.

### AppleScript Permission Denied

macOS may block AppleScript access. To fix:

1. Open **System Settings** > **Privacy & Security** > **Automation**
2. Find your terminal app (Terminal, iTerm2, etc.)
3. Enable the toggle for **Things3**
4. Retry the setup

### "Things3 got an error" Messages

Things 3 must be running for AppleScript to work. Open Things 3, then retry.

### Areas Not Showing

If no Areas appear during setup:

1. Open Things 3
2. Go to Settings > General
3. Make sure Areas are enabled
4. Create at least one Area, then retry

---

## Reconfiguration

If the user runs `/things-setup` when already configured:

1. Show current config from `System/integrations/config.yaml`
2. Offer options:
   - Update pillar-to-area mapping
   - Re-test the connection
   - Disconnect Things

### Disconnect Flow

If user wants to disconnect:

1. Update `System/integrations/config.yaml`:
   ```yaml
   things:
     enabled: false
   ```
2. Confirm: "Things 3 is disconnected. Tasks will no longer sync. Run `/things-setup` anytime to reconnect."
