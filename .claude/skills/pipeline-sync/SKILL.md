---
name: pipeline-sync
description: Sync Salesforce opportunities into project pages with quotes and contact links
---

Syncs the open Salesforce pipeline into project pages in `Projects/`, using the local SF cache — zero MCP calls for data gathering.

**Design (agentic-OS pattern, see `System/Dex_System/Agentic_Skill_Pattern.md`):** `.scripts/pipeline-sync.py` does all gathering, diffing, and page writing deterministically from `.scripts/salesforce-data/`. AI only handles judgment: quote file downloads, archive decisions, and narrative review. Never fetch opportunities via MCP for this skill.

## Usage

- `/pipeline-sync` — Full sync: all open opps
- `/pipeline-sync Acme` — Sync only opps/accounts matching "Acme"
- `/pipeline-sync --no-download` — Skip quote file downloads

## Process

### Step 1: Run the deterministic sync

```bash
python .scripts/pipeline-sync.py [--filter "NAME"]
```

The script creates new project pages (with contacts and quote metadata from the cache), updates header fields and quote tables on existing pages (never touching Activity Log / Notes / Decisions / Correspondence), creates account hub pages, and prints a summary table.

**Sentinels:**
- `STALE_CACHE` — offer to run `.scripts/automation/run-sf-sync.ps1` first, then re-run.
- `NO_CACHE` — run `python .scripts/sf-pull-sync.py` (needs SF auth via local MCP).
- Use `--dry-run` first if the user wants a preview.

### Step 2: Download quote files (AI judgment — needs local salesforce MCP)

The script ends with a `DOWNLOAD-LIST` of quotes on opps in Favorable/Negotiation/Buying stages. Unless `--no-download`:

1. For each listed quote, call `sf_get_quotes` for the opportunity to get attached document `content_version_id`s.
2. Skip quotes whose File column in the project page already has a link.
3. `sf_download_quote_file` → save to `Projects/{Account}/Quotes/{QuoteNumber}_{Title}.{ext}` and add the link in the page's Quotes table File column.

### Step 3: Archive candidates (AI judgment)

The script lists pages whose opps are now closed. Present the list; on confirmation, move each project folder/page to `Archive/Projects/` and update the account hub. Never archive without confirmation.

### Step 4: Auto-link and activity sync

```bash
node .scripts/auto-link-people.cjs "Projects/<each new/updated file>.md"
python .scripts/sf-activity-sync.py
```

The activity sync pushes `[dex]`-tagged Activity Log entries back to Salesforce (idempotent; `--dry-run` to preview). Tag format:

```markdown
- **2026-06-18** — Call: Discussed quote pricing, customer wants 10% reduction [dex]
```

Subjects: `Call:` / `Meeting:` / `Email:` / `Note:` / `Task:`.

### Step 5: Report

Relay the script's summary table plus what you downloaded/archived. Flag anything odd (e.g., large amount changes, opps missing close dates).

## When to Run

- Start of week during `/week-plan`
- Before important sales meetings
- After a stage change or new quote in Salesforce
- Anytime the user says "sync my pipeline" or "update my deals"

## Integration

- `/daily-plan`, `/meeting-prep`, `/project-health`, `/pipeline-review` all read these pages.

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark pipeline sync as used.
