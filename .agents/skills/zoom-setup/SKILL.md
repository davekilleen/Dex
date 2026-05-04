---
name: zoom-setup
description: Connect your Zoom account to Dex so your meeting prep, reviews, and process-meetings workflows get direct access to Zoom recordings, transcripts, and scheduling.
integration:
  id: zoom
  name: Zoom
  mcp_server: zoom-mcp
  auth: oauth2
  category: meetings
  sync_direction: bidirectional
  enhances:
  - skill: meeting-prep
    capability: Shows last Zoom with each attendee, surfaces recording summaries
  - skill: process-meetings
    capability: Zoom recordings as alternative meeting source alongside Granola
  - skill: week-review
    capability: Meeting time stats from Zoom (hours, count, distribution)
  new_capabilities:
  - name: Recording Search
    trigger: During /meeting-prep, search Zoom recordings for past meetings with attendees
  - name: Zoom Scheduling
    trigger: Schedule Zoom meetings directly from Dex with confirmation
---

# Zoom Setup

Connect your Zoom account to Dex so your meeting prep, reviews, and process-meetings workflows get direct access to Zoom recordings, transcripts, and scheduling.

## What This Enables

Once connected, Dex can:

**Read:**
- List recordings and transcripts from past meetings
- Search meeting content by keyword or participant
- Get participant lists and meeting metadata
- Pull meeting summaries and action items from recordings

**Write (always with your confirmation):**
- Schedule Zoom meetings (Dex will always confirm before creating)
- Add meeting notes or summaries to Zoom

**Skill Enhancements:**
- **Meeting Prep** (`$meeting-prep`) shows: "Your last Zoom with Sarah: Jan 15. Recording summary available."
- **Process Meetings** (`$process-meetings`) can process Zoom recordings directly as an alternative to Granola
- **Week Review** (`$week-review`) includes meeting time stats from Zoom

**New Capabilities:**
- **Recording Search:** During `$meeting-prep`, search Zoom recordings for past meetings with attendees and surface summaries

## Privacy

Dex accesses your Zoom account to read recordings and schedule meetings. No recordings are stored locally. Recordings are fetched, summarized, and discarded after the session. Only YOUR account is accessible (scoped to your OAuth login). The OAuth token stays local on your machine and is gitignored.

## When to Run

- User types `$zoom-setup`
- User asks about connecting Zoom
- User wants Zoom recording context in meeting prep
- During `$integrate-mcp` if Zoom is mentioned

---

## Setup Flow

### Step 1: Check if Already Connected

1. Check `System/integrations/config.yaml` for `zoom.enabled: true`
2. If enabled, try a test query via Zoom MCP (e.g., list recent recordings)
3. If healthy and responding, skip to **Step 5** (Configure Preferences)
4. If the tool is not available or errors, continue to Step 2

### Step 2: Smart Granola Detection

Before explaining the full setup, check if Granola is already connected:

1. Read `System/integrations/config.yaml` for a `granola` section
2. Check if Granola MCP tools are available (try `granola_check_available()`)

**If Granola IS connected:**

```
You already have Granola connected -- it captures your Zoom meetings automatically.

Zoom integration would add:
- Meeting scheduling directly from Dex
- Access to Zoom cloud recordings (if Granola misses one)
- Participant metadata (invited vs. attended)

Still want to connect? [Yes / Skip for now]
```

If user says "Skip for now", confirm and exit:
> "No problem. Granola has your meeting capture covered. Run `$zoom-setup` anytime if you want scheduling or recording access later."

**If user says "Yes" (Granola connected), continue with adjusted messaging:**

```
**Let's connect Zoom to Dex.**

Since Granola handles meeting capture, Zoom adds scheduling and direct recording access.

**What you'll need:**
- A Zoom account (Pro or higher for cloud recordings)
- About 3 minutes for the OAuth flow

**Ready to go?**
```

**If Granola is NOT connected:**

```
**Let's connect Zoom to Dex.**

This gives Dex access to your Zoom recordings, transcripts, and scheduling.

**What you'll need:**
- A Zoom account (Pro or higher for cloud recordings)
- About 3 minutes for the OAuth flow

**What Dex will be able to do:**
- Access your Zoom recordings and transcripts
- Search meeting content by keyword or participant
- Schedule Zoom meetings (with your confirmation)
- Enrich meeting prep with recording summaries

**Ready to go?**
```

Wait for confirmation.

### Step 3: Add the Zoom MCP Server

Check the user's MCP configuration. If `zoom-mcp` is not listed:

1. Explain what we're adding:

```
I need to add the Zoom connector to your Dex configuration.

This uses an MCP bridge that connects to Zoom's APIs via OAuth.
Your credentials stay on your machine.
```

2. Add to the user's `.mcp.json` (use the `$dex-add-mcp` skill or manual edit):

```json
{
  "zoom-mcp": {
    "command": "npx",
    "args": ["-y", "zoom-mcp"],
    "env": {}
  }
}
```

3. Tell the user the MCP server needs to restart for changes to take effect.

### Step 4: Authenticate via OAuth

1. Run the Zoom MCP server -- this starts the OAuth flow
2. A browser window opens for Zoom sign-in
3. The user authorizes the requested scopes (recordings, meetings, users)
4. The token is saved locally

**If OAuth succeeds:**
```
Connected! I can see your Zoom account.
```

**If it fails:**
```
The OAuth flow didn't complete. A few things to check:

1. **Did the browser open?** If not, try copying the URL from the terminal output
2. **Did you approve all permissions?** Dex needs recording and meeting access
3. **Zoom Pro required?** Cloud recordings require a Pro (or higher) Zoom plan
4. **Corporate SSO?** Your Zoom admin may restrict OAuth apps

Want to retry?
```

Retry up to 2 times, then offer to skip and come back later.

### Step 5: Configure Preferences

Once connected, determine feature defaults based on Granola status:

**Feature defaults (with Granola):**
- `zoom_recordings: false` -- Granola handles transcription; Zoom recordings are a backup
- `zoom_scheduling: true` -- scheduling is always useful

**Feature defaults (without Granola):**
- `zoom_recordings: true` -- primary source for meeting recordings
- `zoom_scheduling: true`

Then ask about scheduling behavior:

```
**For scheduling Zoom meetings:**

Would you prefer:
1. **Auto-schedule** -- I'll create the meeting and show you the link
2. **Ask each time** -- I'll confirm before creating any meetings

(You can change this anytime by re-running $zoom-setup)
```

Save their preference. Map choice 1 to `auto_schedule: true`, choice 2 to `auto_schedule: false`.

### Step 6: Test the Connection

Run a quick test to confirm everything works:

1. List recent recordings (last 7 days)
2. Verify meeting list access

Show a brief summary:

```
**Quick test results:**
- Recordings: Found [N] recent recordings
- Meeting list: Working

Everything looks good!
```

If either fails, troubleshoot before proceeding.

### Step 7: Save Configuration

Write to `System/integrations/config.yaml` -- update the zoom section:

```yaml
zoom:
  enabled: true
  configured_at: YYYY-MM-DD
  mcp_server: zoom-mcp
  auth_type: oauth2
  account: user@example.com
  granola_coexists: true   # or false -- tracks whether Granola was connected at setup time
  features:
    zoom_recordings: true   # false if Granola connected
    zoom_scheduling: true
    auto_schedule: false    # or true based on user preference
```

If the file already exists, only update the `zoom:` section. Preserve other integration configs.

### Step 8: Confirm with Capability Cascade

**If Granola IS connected:**

```
**Zoom is connected!**

Here's what just got enhanced:

- **Meeting Prep** (`$meeting-prep`) now includes Zoom context:
  - Zoom recording links when Granola transcript isn't available
  - Participant attendance (invited vs. joined)
  - Scheduling directly from prep

- **Process Meetings** (`$process-meetings`) gains a Zoom fallback:
  - If Granola missed a meeting, Zoom cloud recording steps in
  - Same output format (decisions, actions, key points)

- **Week Review** (`$week-review`) now includes Zoom stats:
  - Total meeting hours
  - Recording count

Granola remains your primary meeting capture tool. Zoom fills in the gaps.

You can adjust settings anytime by running `$zoom-setup` again.
```

**If Granola is NOT connected:**

```
**Zoom is connected!**

Here's what just got enhanced:

- **Meeting Prep** (`$meeting-prep`) now shows Zoom recording context:
  - Last Zoom meeting with each attendee
  - Recording summary if available
  - Participant attendance (invited vs. joined)

- **Process Meetings** (`$process-meetings`) can now use Zoom recordings:
  - Pull transcripts directly from Zoom cloud recordings
  - Same output format (decisions, actions, key points)

- **Week Review** (`$week-review`) now includes Zoom meeting stats:
  - Total meeting hours from Zoom
  - Number of recordings this week
  - Meeting distribution

You can adjust settings anytime by running `$zoom-setup` again.
```

---

## Troubleshooting

### OAuth Token Expired

Zoom OAuth tokens expire periodically. If you see auth errors:

1. Run `$zoom-setup` to trigger a token refresh
2. If the refresh token is also expired, you'll need to re-authorize through the browser
3. This is rare -- usually happens after extended periods or if you revoked access in Zoom settings

### "Zoom MCP not found"

The server might not be in your configuration. Re-run `$zoom-setup` and it will detect and fix this.

### No Recordings Found

A few possibilities:
- **Free plan:** Cloud recordings require Zoom Pro or higher
- **Recording disabled:** Check your Zoom settings to ensure cloud recording is enabled
- **Retention policy:** Your Zoom admin may auto-delete recordings after a period

### Corporate Zoom Restrictions

Some organizations restrict OAuth access for third-party apps:

1. Check with your IT admin if OAuth is allowed for Zoom
2. They may need to whitelist the zoom-mcp client ID
3. Some orgs require admin pre-approval for OAuth apps

### Rate Limiting

Zoom APIs have per-second and daily limits. If you see rate errors:

1. Wait 60 seconds and retry
2. If persistent, you may be hitting an account-level quota
3. This rarely happens during normal Dex usage

---

## Reconfiguration

If the user runs `$zoom-setup` when already configured:

1. Check current status via a test query
2. Show current config from `System/integrations/config.yaml`
3. Offer options:
   - Change scheduling preferences (auto-schedule vs ask each time)
   - Toggle recording access (especially if Granola status changed)
   - Re-authenticate (if token expired)
   - Disconnect Zoom

### Disconnect Flow

If user wants to disconnect:

1. Update `System/integrations/config.yaml`:
   ```yaml
   zoom:
     enabled: false
   ```
2. Confirm: "Zoom is disconnected. Your meeting prep and reviews will no longer include Zoom recording context. Run `$zoom-setup` anytime to reconnect."
