# Projects

Time-bound initiatives with clear goals and deliverables.

## What Makes Something a Project?

A project has:
- **Clear outcome** — Specific deliverable or result
- **End date** — Defined completion point
- **Active work** — You're currently working on it

When a project is done, move it to `07-Archives/Projects/`.

## Salesforce Opportunities

Active Salesforce opportunities are synced here as project folders via `/pipeline-sync`. Each opportunity gets:
- A project page with stage, amount, contacts, and next steps from Salesforce
- A `Quotes/` subfolder with downloaded quote documents (PDFs)
- Wiki-links to People pages for key contacts
- A correspondence section for email threads and OneDrive file links

### Folder Structure

```
04-Projects/
  Acme Corp - Widget Deal - WidgetCo/
    Acme Corp - Widget Deal - WidgetCo.md      ← synced from Salesforce
    Quotes/
      Q-00123_Proposal.pdf                      ← downloaded from Salesforce ContentDocument
      Q-00124_Revised.pdf
  Beta Inc - Service Contract - ServicePro/
    Beta Inc - Service Contract - ServicePro.md
    Quotes/
      Q-00200_SOW.pdf
```

### Keeping It Current

- Run `/pipeline-sync` to pull latest from Salesforce (stages, amounts, new quotes)
- The sync uses `sf_opportunity_id` in frontmatter to match pages to Salesforce records
- Stage changes and new quotes are detected automatically
- Closed opportunities are flagged for archival

### Manual Enrichment

The sync handles Salesforce data, but you add the context Salesforce can't hold:
- **Correspondence:** Link key email threads (use Retool email MCP to search)
- **OneDrive files:** Paste share links to proposals, contracts, SOWs stored in OneDrive
- **Decisions:** Log key decisions and their rationale
- **Notes:** Strategy, competitive intel, relationship context

## Non-Sales Projects

Any time-bound initiative can also live here — product launches, migrations, campaigns. These follow the simpler flat-file convention below.

## Template (Non-Sales)

Each project should track:
- **Status** — Current state and progress
- **Next actions** — What needs to happen next
- **Key stakeholders** — Who's involved
- **Timeline** — Important dates and milestones
- **Related meetings** — Links to meeting notes
- **Decisions** — Key choices made along the way

## Naming Convention

- **Salesforce opps:** `{Account_Name} - {Salesforce Opportunity Name} - {Vendor__c}/` (folder with .md and Quotes/)
- **Other projects:** `Project_Name.md` or `YYYY-MM-DD - Project_Name.md`

## vs. Areas

**Project** = has an end ("Ship payments redesign", "Close Acme deal")  
**Area** = ongoing responsibility ("Customer success management")

If it never "finishes," it belongs in `05-Areas/`, not here.
