---
name: service-pulse
description: Cross-reference unanswered customer emails and open Salesforce service cases to surface at-risk accounts, update company pages, and offer follow-up tasks
role_groups: [sales]
jtbd: |
  A customer who emailed you and never heard back, or who has an open service case
  sitting untouched, is a churn risk you won't see in your pipeline. This skill pulls
  both signals together, flags accounts hit by both at once, and keeps company pages
  current without you having to go looking.
time_investment: "2-5 minutes"
---

# Service Pulse — Reply Tracking & Open Case Review

Combines two signals Dex tracks independently — sent emails still awaiting a customer reply, and open Salesforce service Cases — into one account-level view, so you can see which relationships need attention before they go cold.

## Usage

- `/service-pulse` — Full report across all accounts
- `/service-pulse [company]` — Scoped to one account

## Arguments

$COMPANY: Optional account name to scope the report (partial match OK)

---

## Step 1: Gather Unreplied Emails

Call `get_unreplied_emails` (retool-email MCP), default `min_business_days=3`. This only covers emails sent to a matched Salesforce contact — unmatched recipients aren't tracked (see `System/Dex_System/Dex_Technical_Guide.md` for the reply-tracking schema if this needs explaining).

If $COMPANY is set, filter results client-side on `sf_account_name`.

## Step 2: Gather Open Service Cases

Call `sf_get_open_cases` (Salesforce MCP). Pass `account_name=$COMPANY` if scoped. Note `status`, `priority`, `type`, and `reason` for each case — `Escalated` status and `High` priority are the ones that can't wait for a weekly review.

## Step 3: Cross-Reference by Account

Group both lists by account name. Accounts appearing in **both** lists — an unanswered email *and* an open case — are the highest-risk set: something is actively broken and the customer isn't hearing back on either channel.

## Step 4: Present the Report

```
## Service Pulse — [DATE]

### 🚨 Highest Risk — Unanswered Email + Open Case
| Account | Email Waiting | Case | Status | Priority |
|---------|---------------|------|--------|----------|
| [Account] | [X] business days | [CaseNumber] — [Subject] | [Status] | [Priority] |

### 📧 Emails Awaiting Reply
| Account | Subject | Sent | Business Days Waiting |
|---------|---------|------|------------------------|
| [Account or sender] | [Subject] | [Date] | [X] |

### 🔧 Open Service Cases
| Account | Case # | Subject | Status | Priority | Type |
|---------|--------|---------|--------|----------|------|
| [Account] | [CaseNumber] | [Subject] | [Status] | [Priority] | [Type] |

---
Summary: [X] emails awaiting reply | [Y] open cases ([Z] escalated/high-priority) | [N] accounts at highest risk
```

If either list is empty, omit that section rather than showing an empty table. If both are empty, say so briefly and stop — no report needed.

## Step 5: Update Company Pages

For each account with at least one open case, update its page at `People/Companies/[Company_Name].md`:

1. Read the page fully if it exists. If it doesn't, create a stub first (same pattern as `/customer-intel` Step 1):
   ```markdown
   ---
   name: [Company Name]
   type: customer
   ---

   # [Company Name]

   ## Open Service Cases
   *Not yet populated — run `/service-pulse` to build*
   ```
2. Replace or update the `## Open Service Cases` section:
   ```markdown
   ## Open Service Cases
   *Last updated: [YYYY-MM-DD] | Source: Salesforce Case*

   | Case # | Subject | Status | Priority | Type | Opened |
   |--------|---------|--------|----------|------|--------|
   | [CaseNumber] | [Subject] | [Status] | [Priority] | [Type] | [CreatedDate] |
   ```
3. Run the auto-link script after writing:
   ```bash
   node .scripts/auto-link-people.cjs People/Companies/[Company_Name].md
   ```

Skip this step for accounts with zero open cases — don't write an empty section over existing content.

## Step 6: Offer Follow-Up Tasks

For highest-risk accounts (Step 3) and any `Escalated`/`High` priority case, offer to create tasks:

```
Want follow-up tasks for these?

1. [Account] — reply to [X]-day-old email AND check on Case [CaseNumber] ([Subject])
2. [Account] — Case [CaseNumber] escalated, no task yet

Create tasks? (1, 2, all, or skip)
```

Use `create_task` (Work MCP). Infer pillar from case `reason`:
- `Service Request`, `Question`, general service follow-up → **Account Management** pillar
- `Request Quote` → **Pipeline & Revenue** pillar

State the inference before creating, same as the standard task-creation confirmation flow (see `CLAUDE.md` → "Task Creation").

---

## Step 7: Track Usage (Silent)

Update `System/usage_log.md` to mark this skill as used. Call `track_event` with `service_pulse_completed` and properties `emails_awaiting_reply`, `open_cases_count`, `highest_risk_accounts`. Skip silently if analytics is disabled.

---

## Integration with Other Skills

- **`/daily-plan` / `/week-plan`** — surface a one-line count from the same two tools; run `/service-pulse` for the full breakdown
- **`/customer-intel [company]`** — the `## Open Service Cases` section sits alongside `## EDA Intelligence` on the same company page
- **`/meeting-prep [company]`** — open cases and unreplied threads surface automatically once the company page has this section

## MCP Dependencies

| Source | MCP | Tools |
|--------|-----|-------|
| Email reply tracking | retool-email | `get_unreplied_emails` |
| Salesforce Cases | salesforce | `sf_get_open_cases` |
| Tasks | work-mcp | `create_task` |
