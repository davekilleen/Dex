---
name: todoist-setup
description: "Connect Todoist so Dex reads and updates your Todoist tasks two ways. Use when the user says 'I use Todoist', 'sync Todoist', or pastes a todoist.com link. Not for Things 3 (`things-setup`) or Trello (`trello-setup`); not for Jira tickets (`atlassian-setup`)."
integration:
  id: todoist
  name: Todoist
  mcp_server: null
  auth: api_key
  enhances:
    - skill: daily-plan
      capability: "Can pull in your Todoist tasks due today when you ask"
    - skill: triage
      capability: "Can route an item to Todoist instead of Dex when you ask"
  new_capabilities:
    - name: On-request Todoist access
      trigger: "Ask Dex to check, create, or complete Todoist tasks in any conversation"
---

# Todoist Setup

Connect your Todoist account so Dex can work with your Todoist tasks whenever you ask — check what's due, create a task there instead of in Dex, or mark something done.

**What this enables (on request):** Once connected, say "sync with Todoist" — Dex pushes
new tasks to the right Todoist project, marks completions, and pulls back tasks you completed
or created in Todoist directly. Sync runs on demand; Dex does not poll Todoist in the
background without you asking.

## What This Enables

Once connected, you can ask Dex to:
- **See what's due**: "What's due in Todoist today?" — including alongside your daily plan
- **Create there instead**: "Add that to Todoist, not Dex" during triage or any conversation
- **Complete from chat**: "Mark the invoice task done in Todoist"
- **Cross-check**: "Anything in Todoist that isn't tracked in Dex?"

## Privacy

- Dex reads and writes your Todoist tasks only when you ask it to
- Your API key stays local in the ignored vault-root `.env` file. Tracked YAML stores only its variable name.
- Dex never shares your Todoist data with third parties

## When to Run

- User types `/todoist-setup`
- User asks about connecting Todoist or task sync
- User wants Todoist tasks in daily plans
- During `/integrate-mcp` if Todoist is mentioned

---

## Setup Flow

### Step 1: Check if Already Connected

1. Check `System/integrations/config.yaml` for a `todoist:` section with `enabled: true`
   through `core.utils.strict_yaml.load_yaml_path`; refuse duplicate keys, aliases, anchors,
   or merge mappings before reading or writing any setup field.
2. If enabled, test authentication with the read-only health check
3. If healthy, skip to **Reconfiguration** section below
4. If not configured or unhealthy, continue to Step 2

### Step 2: Explain What We're Setting Up

Say:

```
**Let's connect Todoist to Dex.**

Once connected, you can ask me to check, create, or complete Todoist tasks
right from our conversations.

**What you'll need:**
- Your Todoist API token (I'll show you where to find it)
- About 2 minutes

**Ready to go?**
```

Wait for confirmation.

### Step 3: Enter the API Key Locally

Guide the user:

```
To get your Todoist API token:

1. Open Todoist (web or app)
2. Go to **Settings** → **Integrations** → **Developer**
3. Copy the **API token** shown there

Do not paste the token into this conversation. Open the ignored vault-root `.env` in your
local editor and replace the placeholder in this line directly:

`TODOIST_API_KEY=<paste token locally here>`

Save the file with mode `0600`, then reply only `saved`. Dex must never echo, read aloud,
log, or include the value in a command, argv, or process environment.
```

Wait only for the non-secret `saved` confirmation. Never ask the user to provide or validate
the token in chat.

### Step 4: Store the Local Credential

Confirm locally that `.env` defines `TODOIST_API_KEY` without printing or returning its value.
Use `python3 -m core.utils.credential_workflow scan` for the redacted authority finding; repair
permissions/ownership before continuing if it reports an invalid `.env` authority.
Preserve unrelated lines and never place the value in `.mcp.json`, tracked YAML, a command,
argv, logs, transcript, or process environment. Existing `.mcp.json` is scan/report-only and
must remain byte-identical.

Before health, update only the non-secret tracked Todoist fields to `enabled: true` and
`api_key_env_var: TODOIST_API_KEY`; do not add an `api_key` field.

### Step 5: Test the Connection

Use only Dex's sanitized Python-to-adapter-stdin read-only health path. It resolves `.env`
internally and performs Todoist `GET /projects`; it does not put the token in the command or
environment:

```bash
python3 -c 'from core.integrations.task_sync import check_service_health; print(check_service_health("todoist"))'
```

**If the health result is `{"healthy": True}`:**

```
Connected! Todoist authentication succeeded through the read-only health check.
```

**If it fails:**

```
That API key didn't work. A few things to check:

1. **Copy the full key** — it should be about 40 characters
2. **Check for extra spaces** before or after the key
3. **Regenerate the key** in Todoist Settings → Integrations → Developer

Want to try again?
```

Retry up to 2 times, then offer to skip and come back later.

### Step 6: Choose Default Project

Ask the user which Todoist project should receive Dex tasks:

```
**Which Todoist project should Dex tasks go into?**

The health check does not enumerate projects. Open Todoist locally and enter the exact project
name you want Dex to use without pasting any credential.

You can pick one default project, or map each Dex pillar to a different project.

**Option A:** All Dex tasks go to one project (simplest)
**Option B:** Map each pillar to a project:
  (Read pillar names from `System/pillars.yaml` and list them here)
  - [pillar 1 name] → [project]
  - [pillar 2 name] → [project]
  - [pillar 3 name] → [project]

Which works for you?
```

Save their choices for the config file.

### Step 7: Save Configuration

Write to `System/integrations/config.yaml` — update the todoist section. Build
`pillar_map` dynamically from the user's actual pillars in `System/pillars.yaml`
(one entry per pillar id — never assume fixed pillar names); it's used when the
user asks Dex to file a task in the matching Todoist project.

```yaml
todoist:
  enabled: true
  configured_at: YYYY-MM-DD
  auth_type: api_key
  api_key_env_var: TODOIST_API_KEY
  project: <default project name>
  pillar_map:
    [pillar_id]: <Todoist project name>   # one entry per pillar, from pillars.yaml
```

If the file already exists, only update the `todoist:` section. Preserve other integration configs.

### Step 8: Capability Cascade

Read the integration manifest from this skill's frontmatter. Present:

```
**Todoist is connected!** Here's what you can do now:

- **Ask about Todoist anytime** — "What's due in Todoist today?", "Add that to
  Todoist", "Mark the invoice task done in Todoist".
- **Bring it into your planning** — during `/daily-plan` or `/triage`, ask Dex to
  include or route to Todoist and it will.
- **Sync on demand** — say "sync Dex with Todoist" and new tasks push, completions flow
  both directions, and tasks you added in Todoist come in for review

**Sync is on demand** — say "sync with Todoist" anytime. Dex doesn't poll in the background.
```

---

## Troubleshooting

### API Key Invalid or Expired

Todoist API keys don't expire unless you regenerate them. If you see auth errors:

1. Go to Todoist Settings → Integrations → Developer
2. Copy the current API token (or regenerate if needed)
3. Update the key by running `/todoist-setup` again

### "Dex doesn't see my Todoist tasks"

Dex only reads Todoist when you ask it to — there is no background sync. Ask
directly ("what's in Todoist?") and if that errors, re-run `/todoist-setup` to
check the connection.

### "Todoist credential not found"

Re-run `/todoist-setup` to restore the vault-root `.env` value and tracked reference.

---

## Reconfiguration

If the user runs `/todoist-setup` when already configured:

1. Check current config from `System/integrations/config.yaml`
2. Test the existing API key with the read-only authentication health check
3. Show the current pillar-to-project mapping
4. Offer options:
   - Update project mapping
   - Update API key
   - Disconnect Todoist

### Disconnect Flow

If user wants to disconnect:

1. Update `System/integrations/config.yaml`:
   ```yaml
   todoist:
     enabled: false
   ```
2. Confirm: "Todoist is disconnected. Tasks will no longer sync between systems. Your existing tasks in both Dex and Todoist are unchanged. Run `/todoist-setup` anytime to reconnect."
