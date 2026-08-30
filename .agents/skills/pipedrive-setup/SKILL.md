---
name: pipedrive-setup
description: "Connect Pipedrive CRM for a live pipeline view and confirm-gated deal updates. Use when the user says 'connect Pipedrive', 'link my CRM', 'sync my pipeline with Pipedrive'. Not for pipeline analysis without a CRM; use `pipeline-health`. Not for reconciling an already-connected CRM; use `pipeline-sync`."
integration:
  id: pipedrive
  name: Pipedrive
  mcp_server: pipedrive-mcp
  auth: api_key
  enhances:
    - skill: pipeline-sync
      capability: "Live pipeline view + drift reconciliation against your local pipeline tracker"
    - skill: week-review
      capability: "Reconciles deal numbers (stage/value/probability) against the CRM"
    - skill: meeting-prep
      capability: "Pulls live deal context (stage, value, last activity) for the company"
    - skill: process-meetings
      capability: "Offers to push meeting outcomes as deal notes/activities after you confirm"
    - skill: daily-plan
      capability: "Surfaces focus deals with stale activity or overdue next actions"
  new_capabilities:
    - name: Confirm-gated CRM writes
      trigger: "Dex drafts a note/activity/field change, shows the payload, writes only on your OK"
  sync:
    direction: bidirectional
    entities: deals, notes, activities
---

<!-- Generated from `.claude/skills/pipedrive-setup/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

# Pipedrive Setup

Connect your Pipedrive CRM to Dex. This gives Dex a **live view of your pipeline** and the ability to **push notes, activities and field updates into the deals you're working on**, always after showing you exactly what it will send.

## Design (read this: it shapes the setup)

- **Hybrid source of truth.** Pipedrive owns the canonical *numbers* (stage, value, probability, close date, owner, activities). Your local pipeline tracker note (default `04-Projects/Pipeline_Tracker.md`, configurable via `tracker_path` in `System/integrations/pipedrive.yaml`) keeps the *strategy* (per-deal narrative, coverage, positioning) and **defines the focus list**: the deals you're actively working drive which Pipedrive deals Dex syncs.
- **Confirm every write.** Nothing is written to the CRM without Dex showing you the exact payload first (the write tools support `dry_run` previews).
- **Creation is opt-in.** By default Dex can only annotate and update deals that already exist. If you want Dex to be able to *create* deals or organisations, that is a separate, deliberate switch (`writes.allow_create`), because many CRMs are shared with colleagues.
- **Scope = your focus list**, mapped deal-by-deal in `/pipeline-sync`. There is no blanket auto-sync of the whole organisation.

## What This Enables

- **`/pipeline-sync`**: "show me my pipeline", reconcile live CRM numbers against your tracker, flag drift, push confirmed updates.
- **`/week-review`**: reconcile sub-step surfaces deal-number drift.
- **`/meeting-prep`**: live deal context for a deal-linked company.
- **`/process-meetings`**: offers to push meeting outcomes to the deal (confirmed).
- **`/daily-plan`**: read-only nudge on stale/overdue focus deals.

## Privacy & Security

- Your access token is stored in the **macOS Keychain** (service `dex-pipedrive`) on a Mac, or in the gitignored vault-root `.env` file (`PIPEDRIVE_API_TOKEN=...`) on other systems. It is **never committed**.
- Non-secret settings (your Pipedrive domain, stage/owner mappings) live in `System/integrations/pipedrive.yaml`.
- The token is **never** placed in `.mcp.json` or `config.yaml` (both are committed to git).
- Every write is confirm-gated. Dex uses `dry_run` previews so you always see the payload before it sends.

## When to Run

- User types `/pipedrive-setup`
- User asks to connect Pipedrive / their CRM
- User wants a live pipeline view in Dex
- During `/integrate-mcp` if Pipedrive is mentioned

---

## Setup Flow

> Throughout this flow, **Dex performs every file action for the user**. They only ever paste their token into the chat; Dex does the rest.

### Step 1: Check if Already Connected

1. Read `System/integrations/config.yaml` -> `pipedrive.enabled`.
2. If `true`, run `pipedrive_status()`. If it returns `connected: true`, jump to **Reconfiguration**.
3. Otherwise continue to Step 2.

### Step 2: Explain What We're Setting Up

Say:

```
**Let's connect Pipedrive to Dex.**

You'll get a live view of your pipeline, and Dex can push notes / activities /
field updates into your deals, always showing you exactly what it'll send first.

Your local pipeline tracker stays the home of your strategy and focus list.
Pipedrive becomes the source of truth for the deal *numbers*.

**What you'll need:**
- Your Pipedrive personal API token (I'll show you where)
- About 3 minutes

**Ready?**
```

Wait for confirmation.

### Step 3: Get the API Token + Domain

Guide the user:

```
To get your Pipedrive API token:

1. In Pipedrive, click your profile (top right) -> **Personal preferences**
2. Open the **API** tab
3. Copy **Your personal API token**

Also tell me your Pipedrive web address, the bit before .pipedrive.com
(e.g. if you log in at https://yourcompany.pipedrive.com, the domain is "yourcompany").
```

Capture:
- `api_token`: validate non-empty (Pipedrive tokens are ~40-character hexadecimal).
- `company_domain`: the subdomain only.

### Step 4: Store the Token Securely

**On macOS**, store it in the Keychain (service `dex-pipedrive`, account `api`) as a small JSON blob so the domain travels with it:

```bash
security add-generic-password -U -s dex-pipedrive -a api \
  -w '{"api_token": "<token>", "company_domain": "<domain>"}'
```

**On other systems** (or if the Keychain write fails), append to the gitignored vault-root `.env` file instead:

```
PIPEDRIVE_API_TOKEN=<token>
```

Then `chmod 600 .env` and confirm it is gitignored (`git check-ignore .env` should echo the path). Never ask the user to edit files themselves.

### Step 5: Register the MCP Server (idempotent)

Check `.mcp.json` for a `pipedrive-mcp` entry under `mcpServers`. If missing, add (note: **VAULT_PATH only, no token**), substituting the real vault path:

```json
"pipedrive-mcp": {
  "type": "stdio",
  "command": "<vault path>/.venv/bin/python",
  "args": ["<vault path>/core/integrations/pipedrive/pipedrive_server.py"],
  "env": { "VAULT_PATH": "<vault path>" }
}
```

If already present, leave it. Tell the user the MCP server picks up the token on the next session restart.

This step is how an existing install gets Pipedrive: an update never adds a server to a
vault's `.mcp.json`, so the entry above is added here, when the user chooses to connect.

### Step 6: Enable + Test

1. Set `pipedrive.enabled: true` in `System/integrations/config.yaml` (add the `pipedrive:` section if it is missing).
2. Run `pipedrive_status()`.
   - **Success** (`connected: true`): show the authenticated user's name. Continue.
   - **Failure**: surface the error message. Common fixes: full token copied, no trailing spaces, correct domain. Retry up to twice, then offer to come back later (leave `enabled: false`).

### Step 7: Build Stage + Owner Mappings

These let Dex translate your tracker's language to Pipedrive ids and back.

1. Run `pipedrive_list_stages()` and `pipedrive_list_users()`.
2. Propose a `stage_mapping` from the stage phrases used in the user's tracker to Pipedrive stage ids, and an `owner_mapping` from the owner names in the tracker to Pipedrive user ids. Show the proposal and let the user correct it.
3. Optionally capture per-stage default probabilities into `stages:` (the API does not return them, so ask the user to read them from Pipedrive's pipeline settings if they want stage-inherited probabilities).
4. Write `System/integrations/pipedrive.yaml`, following the commented template at `System/integrations/pipedrive.yaml.example`.

Leave any mapping the user is unsure about empty; reconciliation degrades gracefully without a complete map.

### Step 8: Creation Permission (deliberate choice)

Ask:

```
One more choice: do you want Dex to be able to CREATE deals and organisations
in Pipedrive, or only update existing ones?

Default is update-only. If your Pipedrive is shared with colleagues, an
AI-created deal can be a governance problem, so most people leave this off.
Either way, every single write is previewed and only sent on your explicit yes.
```

- **Update-only (default):** leave `writes.allow_create: false` in `pipedrive.yaml`.
- **Allow creation:** set `writes.allow_create: true` and note it can be switched off again at any time.

### Step 9: Capability Cascade

Tell the user what just lit up:

```
Pipedrive connected.

Now available:
- /pipeline-sync: live pipeline + reconcile drift vs your tracker (run this next to map your focus deals)
- /week-review now reconciles deal numbers against the CRM
- /meeting-prep pulls live deal context for deal-linked companies
- /process-meetings offers to push meeting outcomes to deals (you confirm)
- /daily-plan flags focus deals going stale

Next step: run /pipeline-sync to match your focus deals to their
Pipedrive records so the two stay in sync from here on.
```

---

## Reconfiguration

If already connected and the user runs this again, offer:
1. **Test**: run `pipedrive_status()`.
2. **Re-enter token**: repeat Step 4.
3. **Rebuild mappings**: re-run Step 7.
4. **Change creation permission**: re-run Step 8.
5. **Disconnect**: set `pipedrive.enabled: false`. Optionally delete the Keychain item (`security delete-generic-password -s dex-pipedrive -a api`) or the `.env` line. Leave the MCP entry and `pipedrive.yaml` in place (harmless; tools degrade gracefully).

## Troubleshooting

- **`feature_status: off`** -> token missing or `pipedrive.enabled` not true. Re-run Steps 4-6.
- **401** -> token invalid/expired. Regenerate in Pipedrive -> Personal preferences -> API.
- **403** -> token lacks permission for that action (e.g. editing a deal owned by a colleague). Surface honestly; don't retry blindly.
- **"Deal creation is disabled"** -> `writes.allow_create` is false. That is the safe default; only flip it if the user genuinely wants Dex creating CRM records (Step 8).
- **Wrong numbers** -> check `company_domain`/`base_url` point at the right Pipedrive account.
