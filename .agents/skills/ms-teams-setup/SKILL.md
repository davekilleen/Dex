---
name: ms-teams-setup
description: Connect your Microsoft Teams workspace to Dex so your daily plans, meeting prep, and people pages get richer context from Teams conversations.
integration:
  id: teams
  name: Microsoft Teams
  mcp_server: teams-mcp
  auth: oauth2
  enhances:
  - skill: daily-plan
    capability: "Teams digest alongside Slack \u2014 unread chats, mentions, and priority channel activity"
  - skill: meeting-prep
    capability: Teams conversation context with attendees, recent threads, and channel decisions
  new_capabilities:
  - name: teams-digest
    trigger: Automatically included in /daily-plan when Teams is connected
  - name: teams-person-context
    trigger: Person pages enriched with latest Teams conversations
  sync:
    direction: read
    entities: messages, channels, presence
---

# Teams Setup

Connect your Microsoft Teams workspace to Dex so your daily plans, meeting prep, and people pages get richer context from Teams conversations.

## What This Enables

Once connected, Dex can:
- **Meeting Prep:** See recent Teams conversations with attendees before your meeting
- **Daily Plan:** Surface unread chats and mentions that need your attention
- **Person Context:** Know what you last discussed with someone in Teams

## Privacy

- Dex reads Teams messages **on demand** -- nothing is stored permanently
- Messages are fetched, summarized, and discarded after the session
- Only YOUR tenant messages are accessible (scoped to your account)
- The OAuth token stays local on your machine and is gitignored

## When to Run

- User types `$ms-teams-setup`
- User asks about connecting Teams
- User wants Teams context in daily plans or meeting prep
- During `$integrate-mcp` if Teams is mentioned

---

## Setup Flow

### Step 1: Check if Already Connected

1. Try calling `teams_health_check()` from the Teams MCP server
2. If healthy and responding, skip to **Step 5** (Configure Channels)
3. If the tool is not available or errors, continue to Step 2

### Step 2: Explain What We're Setting Up

Say:

```
**Let's connect Microsoft Teams to Dex.**

This uses an OAuth 2.0 flow through Microsoft Entra ID (Azure AD) to securely
access your Teams messages and channels.

**What you'll need:**
- Your Microsoft 365 / Teams account credentials
- About 5 minutes (may need admin consent depending on your org)

**Ready to go?**
```

Wait for confirmation.

### Step 3: Add the Teams MCP Server

Check the user's MCP configuration. If `teams-mcp` is not listed:

1. Explain what we're adding:

```
I need to add the Teams connector to your Dex configuration.

This adds a bridge that lets Dex read your Teams messages and channels
through the Microsoft Graph API using OAuth 2.0.
```

2. Add to the user's `.mcp.json` (use the `$dex-add-mcp` skill or manual edit):

```json
{
  "teams-mcp": {
    "command": "npx",
    "args": ["-y", "teams-mcp"],
    "env": {
      "TEAMS_TENANT_ID": "<tenant-id>",
      "TEAMS_CLIENT_ID": "<client-id>"
    }
  }
}
```

3. Tell the user the MCP server needs to restart for changes to take effect.

### Step 4: Authenticate via OAuth 2.0

1. Guide the user through the OAuth flow:

```
**Microsoft Entra ID Authentication**

You'll need to authorize Dex to read your Teams data. This opens a browser
window where you sign in with your Microsoft account.

**Steps:**
1. I'll start the auth flow -- a browser window will open
2. Sign in with your Microsoft 365 account
3. Grant the requested permissions (read messages, channels, presence)
4. The token will be saved locally on your machine

**Starting now...**
```

2. Run the Teams MCP auth command (e.g., `teams_authenticate()`)
3. Verify with `teams_health_check()`

**If health check succeeds:**
```
Connected! I can see your Teams tenant.
```

**If it fails -- admin consent required:**
```
Hmm, your organization requires admin consent for this app.

**Options:**
1. **Ask your IT admin** to approve the app in Entra ID (Azure AD)
   - App permissions needed: Chat.Read, ChannelMessage.Read, User.Read, Presence.Read
2. **Use a personal account** if this is for personal Teams
3. **Skip for now** and come back after admin approval

Which would you prefer?
```

**If it fails -- other error:**
```
That didn't work. A few things to check:

1. **Are you signed into the right Microsoft account?**
2. **Is your organization using Microsoft 365?** (Teams needs an M365 license)
3. **Try signing out of all Microsoft accounts** in your browser, then retry

Want to retry?
```

Retry up to 2 times, then offer to skip and come back later.

### Step 5: Configure Channels

Once connected, ask:

```
**Which Teams channels matter most for your work?**

I'll prioritize these when building your daily digest and meeting prep.

Some common choices:
- Your 1:1 chats (always included automatically)
- Team channels (e.g., General, your department)
- Project-specific channels
- Customer or deal channels

**Which channels should I watch?** (Just list names, or say "show me what's available")
```

If they say "show me what's available":
- Run `teams_list_channels()` or equivalent
- Show the list and let them pick

Save their choices for the config file.

### Step 6: Test the Connection

Run a quick test to confirm everything works:

1. `teams_list_chats(limit=3)` -- verify chats load
2. `teams_search_messages(query="test", count=1)` -- verify search works

Show a brief summary:

```
**Quick test results:**
- Chats: Found [N] recent conversations
- Search: Working

Everything looks good!
```

If either fails, troubleshoot before proceeding.

### Step 7: Save Configuration

Write to `System/integrations/config.yaml` -- update the teams section:

```yaml
teams:
  enabled: true
  configured_at: YYYY-MM-DD
  priority_channels:
    - channel-name-1
    - channel-name-2
  features:
    teams_digest: true
    meeting_prep: true
    person_enrichment: true
```

If the file already exists, only update the `teams:` section. Preserve other integration configs.

### Step 8: Coexistence Check (Slack + Teams)

Check if Slack is also enabled in config.yaml. If so:

```
**Both Slack and Teams are now connected!**

Here's how they work together:
- **Daily Plan** shows both digests, clearly labeled: "**Slack:**" and "**Teams:**"
- **Meeting Prep** searches both for attendee context
- No duplication -- each source is labeled and deduplicated where the same person appears in both
- You can disable either one anytime without affecting the other
```

When both Slack AND Teams are enabled:
- `$daily-plan` shows both digests side by side
- `$meeting-prep` checks both for attendee context
- No duplication -- each source is labeled
- If the same person appears in both Slack and Teams, context is merged with source labels

### Step 9: Capability Cascade (Confirm)

```
**Teams is connected!**

Here's what just changed:

### Enhanced
- **`$daily-plan`** -- Now includes a Teams digest with unread chats and mentions
- **`$meeting-prep`** -- Searches Teams for recent threads with attendees

### New Superpowers
- **Teams Digest** -- Appears automatically in your daily plans
- **Teams Person Context** -- People pages include latest Teams conversations

### How It Works
- **Reading:** Teams context appears automatically in your plans and prep
- **Privacy:** Messages are fetched on demand, summarized, then discarded. Nothing stored permanently.

You can adjust settings anytime by running `$ms-teams-setup` again.
```

---

## Troubleshooting

### Token Expired

OAuth tokens expire periodically (typically every 60-90 minutes, with a refresh token lasting longer). If you see auth errors:

1. Run `$ms-teams-setup`
2. The OAuth flow will refresh your token automatically
3. If refresh fails, you'll need to sign in again

This is normal -- Microsoft OAuth tokens have shorter lifespans than some other services.

### Admin Consent Required

Your Microsoft 365 admin may need to approve the app. Common permissions needed:
- `Chat.Read` -- Read your chat messages
- `ChannelMessage.Read.All` -- Read channel messages
- `User.Read` -- Read your profile
- `Presence.Read` -- Read presence status

Ask your IT team to approve these in **Entra ID > Enterprise Applications**.

### "Teams MCP not found"

The server might not be in your configuration. Re-run `$ms-teams-setup` and it will detect and fix this.

### Rate Limiting

Microsoft Graph API has throttling limits. If you see 429 errors, wait a few minutes and retry. This rarely happens during normal use.

### No Messages Found

A few possibilities:
- Your tenant may restrict API access. Check with your IT/admin team.
- Ensure your account has a Teams license (not just Outlook).
- Try `teams_search_messages(query="hello", count=1)` as a basic test.

---

## Reconfiguration

If the user runs `$ms-teams-setup` when already configured:

1. Check current status with `teams_health_check()`
2. Show current config from `System/integrations/config.yaml`
3. Offer options:
   - Update priority channels
   - Toggle features (digest, meeting prep, person enrichment)
   - Re-authenticate (if token expired)
   - Disconnect Teams

### Disconnect Flow

If user wants to disconnect:

1. Update `System/integrations/config.yaml`:
   ```yaml
   teams:
     enabled: false
   ```
2. Confirm: "Teams is disconnected. Your daily plans and meeting prep will no longer include Teams context. Run `$ms-teams-setup` anytime to reconnect."
