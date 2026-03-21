---
name: atlassian-setup
description: Connect Jira and Confluence to Dex for project tracking and knowledge search
manifest:
  id: atlassian
  auth: oauth2
  category: project_management
  services:
    - jira
    - confluence
---

# Atlassian Setup

Connect your Jira and Confluence to Dex so your daily plans, project health checks, meeting prep, and weekly reviews get richer context from your Atlassian workspace.

## What This Enables

Once connected, Dex can:
- **Daily Plan:** See your Jira sprint status, assigned tickets, and overdue items
- **Project Health:** Sprint velocity, epic progress, blocked tickets across projects
- **Meeting Prep:** Surface Jira tickets and Confluence docs relevant to attendees
- **Week Review:** Tickets closed this week, sprint progress, velocity trends
- **Task Sync:** Bi-directional sync between Dex tasks and Jira issues (optional)

## Privacy

- Dex reads Jira issues and Confluence pages **on demand** -- nothing is stored permanently
- Data is fetched, summarized, and discarded after the session
- Only YOUR workspace data is accessible (scoped to your OAuth permissions)
- The OAuth token stays local on your machine and is gitignored

## When to Run

- User types `/atlassian-setup`
- User asks about connecting Jira or Confluence
- User wants Jira context in daily plans, project health, or meeting prep
- During `/integrate-mcp` if Jira or Confluence is mentioned

---

## Setup Flow

### Step 1: Check if Already Connected

1. Check `System/integrations/config.yaml` for `atlassian.enabled: true`
2. If enabled, read `System/.atlassian-oauth-token.json` and test the token:
   - Call `https://api.atlassian.com/oauth/token/accessible-resources` with the stored token
   - If valid, skip to **Step 6** (Configure Projects)
3. If the token is missing, expired, or invalid, continue to Step 2

### Step 2: Explain What We're Setting Up

Say:

```
**Let's connect Jira and Confluence to Dex.**

This uses Atlassian's OAuth flow to securely connect your Atlassian Cloud workspace.
No API tokens to manage -- it uses the standard Atlassian authorization flow.

**What you'll need:**
- An Atlassian Cloud account (e.g., yourcompany.atlassian.net)
- Permission to authorize third-party apps (check with your admin if unsure)
- About 3 minutes

**What gets connected:**
- **Jira:** Your assigned issues, sprint status, project health
- **Confluence:** Search for docs relevant to meetings and projects (read-only)

**Ready to go?**
```

Wait for confirmation.

### Step 3: Add the Atlassian MCP Server

Check the user's MCP configuration. If an Atlassian MCP server is not listed:

1. Explain what we're adding:

```
I need to add the Atlassian connector to your Dex configuration.

This uses the official Atlassian Remote MCP server which handles OAuth
authentication and provides secure access to your Jira and Confluence data.
```

2. Add to the user's `.mcp.json`:

```json
{
  "atlassian": {
    "command": "npx",
    "args": ["-y", "mcp-remote@latest", "https://mcp.atlassian.com/v1/sse"]
  }
}
```

3. Tell the user the MCP server needs to restart for changes to take effect.

### Step 4: Authenticate

Guide the user through the OAuth flow:

1. The Atlassian MCP server will open a browser window for authorization
2. User logs in to Atlassian and grants access
3. The MCP server stores the token locally

After auth completes, verify:
- Call the accessible-resources endpoint to confirm the token works
- Save token data to `System/.atlassian-oauth-token.json`

**If authentication succeeds:**
```
Connected! I can see your Atlassian workspace: [workspace-name]
```

**If it fails:**
```
Hmm, that didn't work. A few things to check:

1. **Are you logged in to Atlassian Cloud?** (Not Server/Data Center -- Cloud only)
2. **Does your account have permission to authorize apps?** Check with your admin
3. **Try the auth flow again** -- sometimes it takes two tries

Want to retry?
```

Retry up to 2 times, then offer to skip and come back later.

### Step 5: Select Cloud Site

If the user has access to multiple Atlassian sites:

```
You have access to multiple Atlassian sites:

1. acme-corp.atlassian.net
2. acme-sandbox.atlassian.net

Which site should Dex connect to?
```

Save the selected `cloud_id` for API calls.

### Step 6: Configure Jira Project

```
**Which Jira project should Dex sync with?**

This is the project where your tasks and issues live. I'll use it for:
- Sprint status in your daily plan
- Task sync (if you enable it)
- Project health checks

**Enter a project key** (e.g., ACME, PROD, ENG) or say "show me what's available"
```

If they say "show me what's available":
- Call the Jira projects API to list accessible projects
- Show the list and let them pick

### Step 7: Configure Confluence Space (Optional)

```
**Want to connect Confluence too?** (Optional)

If connected, Dex will search Confluence docs when prepping for meetings --
finding relevant pages shared with attendees or related to your projects.

**Enter a space key** (e.g., TEAM, DOCS, KB) or say "skip" or "show me what's available"
```

If they say "show me what's available":
- Call the Confluence spaces API to list accessible spaces
- Show the list and let them pick

### Step 8: Configure Task Sync Trust Level

```
**How should Dex handle Jira task sync?**

When you create tasks in Dex or complete issues in Jira, Dex can keep them in sync.

Choose your trust level:

1. **Auto-sync** -- Dex automatically syncs issues and tasks (recommended for personal projects)
2. **Ask each time** -- Dex shows you what changed and asks before syncing
3. **Read-only** -- Dex reads Jira data but never writes back (safest)

Which do you prefer? [1/2/3]
```

### Step 9: Save Configuration

Write to `System/integrations/config.yaml` -- update the atlassian section:

```yaml
atlassian:
  enabled: true
  configured_at: YYYY-MM-DD
  cloud_id: <cloud-id>
  site_url: <site>.atlassian.net
  jira:
    project_key: ACME
    issue_type: Task
    task_sync: true
    trust_level: auto  # auto | ask | readonly
  confluence:
    enabled: true
    space_key: TEAM
  pillar_map:
    deal_support: SALES
    thought_leadership: CONTENT
    product_feedback: PROD
  features:
    daily_sprint: true
    project_health: true
    meeting_prep: true
    week_review: true
```

If the file already exists, only update the `atlassian:` section. Preserve other integration configs.

### Step 10: Test the Connection

Run quick tests to confirm everything works:

1. **Jira:** Fetch the configured project to verify access
2. **Jira:** Search for issues assigned to the user
3. **Confluence** (if enabled): Search the configured space

Show a brief summary:

```
**Quick test results:**
- Jira project [KEY]: Found, [N] open issues assigned to you
- Confluence space [KEY]: Found, [N] pages accessible
- Sprint status: [Current sprint name], [N] days remaining

Everything looks good!
```

If any test fails, troubleshoot before proceeding.

### Step 11: Confirm

```
**Atlassian is connected!**

Here's what changes now:

- **Daily Plan** (`/daily-plan`) shows Jira sprint status and assigned tickets
- **Project Health** (`/project-health`) includes sprint velocity and blocked tickets
- **Meeting Prep** (`/meeting-prep`) surfaces Jira tickets and Confluence docs for attendees
- **Week Review** (`/week-review`) includes tickets closed and sprint progress

Trust level: [auto/ask/read-only]

You can adjust settings anytime by running `/atlassian-setup` again.
```

---

## Capability Cascade

When Atlassian is connected, these skills automatically gain new powers:

| Skill | What Atlassian Adds |
|-------|---------------------|
| `/daily-plan` | Sprint status, assigned tickets, overdue issues |
| `/project-health` | Sprint velocity, epic progress, blocked tickets |
| `/meeting-prep` | Jira tickets involving attendees, Confluence docs |
| `/week-review` | Tickets closed, sprint velocity, progress trends |
| `/triage` | Incoming Jira issues to triage alongside inbox |

---

## Troubleshooting

### Token Expired

Atlassian OAuth tokens expire periodically. If you see auth errors:

1. Run `/atlassian-setup`
2. It will detect the expired token and guide you through re-auth
3. Takes about 30 seconds

### "No accessible resources"

Your Atlassian account may not have the right permissions:
- You need at least **read** access to the Jira project
- For Confluence, you need **read** access to the space
- Check with your Atlassian admin if you're missing permissions

### Rate Limiting

Atlassian Cloud allows about 100 requests per minute. If you see rate limit errors, wait 60 seconds and retry. This rarely happens during normal use.

### "Atlassian MCP not found"

The server might not be in your configuration. Re-run `/atlassian-setup` and it will detect and fix this.

### Jira Server / Data Center

This integration only supports **Atlassian Cloud**. Jira Server and Data Center use different APIs and authentication. If you're on-premise, this setup won't work.

---

## Reconfiguration

If the user runs `/atlassian-setup` when already configured:

1. Check current status by testing the token
2. Show current config from `System/integrations/config.yaml`
3. Offer options:
   - Change Jira project
   - Change Confluence space
   - Update trust level
   - Update pillar mapping
   - Re-authenticate (if token expired)
   - Disconnect Atlassian

### Disconnect Flow

If user wants to disconnect:

1. Update `System/integrations/config.yaml`:
   ```yaml
   atlassian:
     enabled: false
   ```
2. Confirm: "Atlassian is disconnected. Your daily plans and meeting prep will no longer include Jira/Confluence context. Run `/atlassian-setup` anytime to reconnect."
