---
name: campaign-email-wrapper
description: Campaign-focused wrapper for the unified email outreach workflow; drafts event and promotion outreach, queues it into the shared dashboard, and lets you review/edit before pushing to Outlook.
---

# Outreach Drafts

Use this skill when the request is about an event, promotion, availability alert, product launch, or other campaign. This is now the campaign-facing entry point for the same dashboard-first workflow used by `/email-queue-manager`.

## Process

### Step 1: Define the Campaign

Ask the user:
1. **What's the event or promotion?** (e.g., "Press Brake Training Course, August 26 at MAM showroom")
2. **Who should receive it?** Describe the targeting criteria — examples:
   - "Accounts with open press brake deals"
   - "TRUMPF customers and prospects"
   - "Anyone I've talked to about lasers in the last 6 months"
   - "All good customers — relationship outreach"
3. **Any specific accounts or contacts to include or exclude?**

### Step 2: Pull Matching Contacts from Salesforce

Use Salesforce MCP tools to find matching contacts based on the criteria:
- `get_opportunities` (salesforce-remote) — filter by account name or stage
- `search_accounts` (salesforce-remote) — get contacts for specific accounts
- `get_account_contacts` (salesforce-remote) — get all contacts under an account
- `search_contacts` (salesforce-remote) — search by name or role
- `sf_get_recent_activity` (local salesforce MCP) — find accounts with recent activity on relevant topics
- `sf_search_assets` (local salesforce MCP) — search assets across all accounts by machine type, builder/manufacturer, sale-or-lease status, or other criteria

Build a tiered target list:
- **Tier 1** — Actively in-market (open opp matching the topic, hot stage)
- **Tier 2** — Have discussed it / have related equipment / recent signals
- **Tier 3** — Good customers / strategic relationship touches

For each contact, collect: Name, Email, Account, relevant context (deal stage, what they're working on).

### Step 3: Draft Personalized Emails

Write one email per contact. Each email should:
- Open with a personal reference (recent call, active deal, tooling discussion, etc.)
- State the event/offer clearly and concisely
- Include a specific call to action (hold spots, reply to confirm, call this week)
- Sign off as Chris Barsanti, Mid Atlantic Machinery

Vary the opening line per contact — never send identical emails to different people.

### Step 4: Queue into the Shared Dashboard

Append the drafted emails to `.scripts/email-drafts/data/drafts.json` using the same queue format as `/email-queue-manager`. Dedup by `campaign` + `to` to avoid duplicate entries.

Then launch the dashboard so the user can review, edit, and push the drafts:
- run `.scripts/email-drafts/launch.bat`
- default push mode is an Outlook draft
- "Send now" is opt-in per email in the dashboard

### Step 5: Flag Missing Contacts

If any target accounts don't have an email address, note them clearly and leave them in the queue with `to: ""` and `status: "needs_email"` so they surface in the dashboard for manual entry.

## Notes

- This skill is intentionally dashboard-first; it should not generate a standalone PowerShell script by default.
- If the user explicitly asks for a one-off push with no review step, a temporary `.ps1` script may be generated, but the preferred path remains the shared dashboard.
- The `-custom` suffix protects this skill from Dex updates.
- To edit this skill: `.claude/skills/campaign-email-wrapper/SKILL.md`
