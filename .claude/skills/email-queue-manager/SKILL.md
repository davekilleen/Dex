---
name: email-queue-manager
description: Unified email outreach skill for task follow-ups and campaign/event outreach; queues personalized drafts into the shared dashboard for review, editing, and Outlook push.
---

# Email Outreach Dashboard

Use this as the single entry point for email outreach. It covers:
- task-based follow-ups from `Planning/Tasks.md`
- event, promotion, and availability campaigns from Salesforce
- relationship touches and one-off outreach waves

This is the canonical workflow: generate drafts, queue them in the shared dashboard, and let the user review/edit/push from the browser UI. It should not create standalone Outlook scripts by default.

## Process

### Step 0: Pick a Source

Ask the user (or infer from how they framed the request):
- **From Tasks** — scan `Planning/Tasks.md` for outstanding outreach tasks (default when they just say "draft some emails" or reference tasks)
- **From a campaign** — an event/promo targeting a group of contacts (when they mention an event, promotion, or "everyone who...")
- **Both** — run both flows and merge into the same queue

### Step 1a: Task-Sourced Drafts

1. Read `Planning/Tasks.md`. Candidate tasks are open (`- [ ]`, not `[STALE]` unless the user says to include stale ones) whose title or sub-bullets read as outreach — keywords like Call, Email, Visit, Follow up, Reach out, or the presence of a `Contact:` sub-bullet.
2. For each candidate:
   - Extract the task ID anchor (`^task-YYYYMMDD-XXX`).
   - Extract the contact name from the `Contact:` sub-bullet, if present.
   - Resolve an email address: try `lookup_person` (Work MCP) first. If no match, read `People/External/*.md` / `People/Internal/*.md` frontmatter directly (the `email:` field) using a fuzzy name match against filenames — do **not** rely on `System/People_Index.json` alone, its `email` field is currently null for everyone. If still unresolved, leave `to` blank and flag the draft (see Queue Format).
   - Pull context for the email: the person page (role, recent notes), the linked company page (relationship notes, open deals/cases), and any case/opportunity number mentioned in the task.
3. Draft one email per task, following the tone rules below.

### Step 1b: Campaign-Sourced Drafts

Use the same targeting conversation as `campaign-email-wrapper`: confirm the event/promo, targeting criteria, and any specific includes/excludes, then pull matching contacts via Salesforce MCP tools (`get_opportunities`, `search_accounts`, `get_account_contacts`, `search_contacts`, `sf_get_recent_activity`, `sf_search_assets`). Draft one email per contact, following the same tone rules.

### Tone Rules (both modes)

- Open with a personal reference (recent call, active deal, open case, tooling discussion).
- State the ask/offer clearly with a specific CTA (reply to confirm, call this week, hold a spot).
- Vary the opening line — never send near-identical copy to two different people.
- Sign off as `Chris Barsanti\nMid Atlantic Machinery`.
- ASCII only — no em dashes, no smart quotes.

### Step 2: Append to the Queue (with dedup)

Read `.scripts/email-drafts/data/drafts.json` (treat as `[]` if missing). Before adding each new draft:
- Task-sourced: skip if an entry with the same `taskId` already exists in the queue.
- Campaign-sourced: skip if an entry with the same `campaign` + `to` already exists.

Append surviving entries and write the file back (2-space indent). Draft IDs follow `draft-YYYYMMDD-XXX`, zero-padded per day, same convention as task IDs.

### Step 3: Show a Summary and Launch the Dashboard

1. Show the user a short table: contact, company, subject, and a flag for any `needs_email` entries that need a manual address.
2. Launch the dashboard so they land on the review screen: run `.scripts/email-drafts/launch.bat`.
3. Remind them: every draft defaults to creating an Outlook draft; "Send now" is opt-in per email in the dashboard and sends immediately with no undo.

## Notes

- The dashboard (`server.cjs` + `public/`) is the only thing that talks to Outlook (via `push-to-outlook.ps1`, COM automation). This skill never touches Outlook directly.
- Classic Outlook desktop must be open for pushes to succeed; that's enforced in the dashboard, not here.
- Re-running this skill is safe — dedup means it only adds genuinely new drafts to the queue.
- If the user explicitly asks for a quick one-off push with no review step, a temporary PowerShell script can be generated, but the default path remains the dashboard.
- To edit this skill: `.claude/skills/email-queue-manager/SKILL.md`
