---
name: pipeline-sync
description: Sync Salesforce opportunities into project pages with quotes and contact links
---

Pulls your open Salesforce pipeline and creates/updates project pages in `Projects/` for each opportunity. Downloads quote documents and links contacts to People pages.

## What This Does

1. Fetches open opportunities from Salesforce (`sf_get_pipeline`)
2. For each opportunity, creates or updates a project page in `Projects/`
3. Pulls quotes and their attached documents (`sf_get_quotes`)
4. Downloads quote PDFs into each opportunity's `Quotes/` subfolder (`sf_download_quote_file`)
5. Links Salesforce contacts to People pages in `People/`
6. Flags closed/won/lost opps for archival to `Archive/Projects/`

## Usage

- `/pipeline-sync` — Full sync: all open opps, quotes, and documents
- `/pipeline-sync Acme` — Sync only opportunities matching "Acme"
- `/pipeline-sync --no-download` — Sync metadata only, skip file downloads

## Arguments

$FILTER: Optional. Opportunity name filter (partial match). Default: all open opps.
$FLAGS: Optional. `--no-download` to skip quote file downloads.

## Prerequisites

- Salesforce MCP must be authenticated (`sf_authenticate`)
- `SF_OWNER_ID` env var should be set to scope to your pipeline

## Process

### Step 1: Fetch Pipeline

Call `sf_get_pipeline` from the Salesforce MCP. If $FILTER is provided, pass it as the `stage` or use it to filter results by opportunity name.

If not authenticated, tell the user to run `sf_authenticate` first.

### Step 2: Diff Against Existing Projects

Scan `Projects/` for existing opportunity project pages. Match by the `sf_opportunity_id` in frontmatter.

Categorize each opp:
- **New** — No matching project page exists → create
- **Update** — Page exists, Salesforce data has changed (stage, amount, close date) → update
- **Unchanged** — Page exists and data matches → skip
- **Archive candidate** — Project page exists but opp is no longer in open pipeline → flag

### Step 3: Create/Update Project Pages

For each new or updated opportunity:

1. Call `sf_get_opportunity` to get full details (contacts, quotes, activity)
2. Create the project folder: `Projects/{Account_Name} - {Opportunity_Name} - {Vendor__c}/`
3. Write the project page using the template below
4. For each contact with an OpportunityContactRole:
   - Check if a People page exists in `People/External/`
   - If not, create a stub page with name, title, email, company
   - Wiki-link the contact in the project page

### Step 4: Download Quote Documents

Unless `--no-download` is set:

**Only download quote files for opportunities in these stages:** Favorable, Negotiation, Buying.
For all other stages (Discovery, Quoting, Active Project, etc.), sync quote metadata (number, status, total) into the project page but skip the actual file download.

1. Call `sf_get_quotes` for each opportunity
2. For each quote with attached documents:
   - If opp stage is Favorable, Negotiation, or Buying:
     - Create `Projects/{folder}/Quotes/` if needed
     - Call `sf_download_quote_file` with the `content_version_id`
     - Save as `{QuoteNumber}_{Title}.{FileType}` (e.g., `Q-00123_Proposal.pdf`)
     - Link the file in the project page's Quotes section
   - Otherwise: record quote metadata in the project page but do not download files

### Step 5: Sync Activity Back to Salesforce

After pulling the pipeline, run the activity sync to push any Dex-originated entries back to Salesforce:

```bash
python .scripts/sf-activity-sync.py
```

This scans project pages for activity entries tagged `[dex]` that haven't been synced yet (no `<!-- sf:TASK_ID -->` marker) and creates Salesforce Tasks linked to the opportunity. Each entry is marked after sync so it's idempotent on re-run.

**To preview without writing:** `python .scripts/sf-activity-sync.py --dry-run`
**To sync a single project:** `python .scripts/sf-activity-sync.py --project "Acme Corp"`

**Tagging activity for sync:** When you add an activity line to a project page's `## Activity Log` section, append `[dex]` to queue it for sync on next run:

```markdown
## Activity Log

- **2026-06-18** — Call: Discussed quote pricing, customer wants 10% reduction [dex]
- **2026-06-17** — Meeting: Site visit walkthrough, 3 stakeholders attended [dex]
- **2026-02-20** — Email: Re: Steel Tech (pulled from Salesforce, no tag)
```

**Activity subject formats:**
- `Call: [summary]` for phone calls
- `Meeting: [summary]` for meetings
- `Email: [summary]` for email follow-ups
- `Note: [summary]` for general notes/decisions
- `Task: [summary]` for completed action items

### Step 6: Summary

Output a table:

```markdown
### Pipeline Sync Complete

| Opportunity | Account | Stage | Action |
|-------------|---------|-------|--------|
| Widget Deal | Acme Corp | Proposal | Created |
| Service Contract | Beta Inc | Negotiation | Updated (stage changed) |
| Old Project | Gamma LLC | — | Archive candidate |

**Created:** X | **Updated:** Y | **Unchanged:** Z | **Archive candidates:** W
**Quote files downloaded:** N
```

## Project Page Template

Use this template when creating new opportunity project pages:

```markdown
---
sf_opportunity_id: {Opportunity.Id}
sf_account_id: {Account.Id}
sf_last_synced: {ISO timestamp}
---

# {Opportunity.Name}

**Account:** [[{Account_Name}]]
**Stage:** {StageName}
**Amount:** ${Amount}
**Close Date:** {CloseDate}
**Probability:** {Probability}%
**Owner:** {Owner.Name}
**Lead Source:** {LeadSource}
**Type:** {Type}

## Next Steps

{NextStep from Salesforce, or "— TBD —"}

## Key Contacts

| Name | Role | Title |
|------|------|-------|
| [[{Contact_Name}]] | {OpportunityContactRole.Role} | {Contact.Title} |

## Quotes

| Quote # | Status | Total | Expiration | File |
|---------|--------|-------|------------|------|
| {QuoteNumber} | {Status} | ${GrandTotal} | {ExpirationDate} | [[Quotes/{filename}]] |

## Correspondence & Files

_Link emails (from Retool email MCP) and OneDrive documents here._

- 

## Activity Log

_Recent Salesforce activity synced automatically._

{Recent tasks/events from sf_get_opportunity}

## Decisions

- 

## Notes

- 
```

## Folder Structure

After sync, `Projects/` looks like:

```
Projects/
  README.md
  Acme Corp - Widget Deal - WidgetCo/
    Acme Corp - Widget Deal - WidgetCo.md
    Quotes/
      Q-00123_Proposal.pdf
      Q-00124_Revised_Proposal.pdf
  Beta Inc - Service Contract - ServicePro/
    Beta Inc - Service Contract - ServicePro.md
    Quotes/
      Q-00200_SOW.pdf
```

## Integration with Other Skills

- **`/daily-plan`** — Pipeline opps surface in daily plans when close dates are near
- **`/meeting-prep`** — When meeting attendees match opp contacts, the opp page is pulled for context
- **`/project-health`** — Opp project pages are included in the health scan
- **`/pipeline-review`** — Sales-specific pipeline analysis (separate skill, uses these pages as input)

## When to Run

- Start of week during `/week-plan`
- Before important sales meetings
- After a stage change or new quote in Salesforce
- Anytime you say "sync my pipeline" or "update my deals"

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark pipeline sync as used.
