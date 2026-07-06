---
name: email-drafts-custom
description: Generate personalized outreach email drafts from Tasks.md and/or Salesforce campaigns, append them to a shared review queue, and launch the local dashboard where they can be edited and pushed to Outlook (as drafts, or sent directly per email).
---

# Email Drafts Dashboard

Draft outreach emails in Chris's tone, queue them in a shared review file, and launch a local dashboard (`.scripts/email-drafts/`) where each one can be edited and pushed to Outlook — either saved as a draft (default) or sent immediately (opt-in per email).

This skill only **generates and queues** drafts. Reviewing, editing, and pushing to Outlook all happen in the dashboard UI, not here.

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

Run the same targeting conversation as `outreach-drafts-custom` (Steps 1-3 there): confirm the event/promo, targeting criteria, and any specific includes/excludes, then pull matching contacts via Salesforce MCP tools (`get_opportunities`, `search_accounts`, `get_account_contacts`, `search_contacts`, `sf_get_recent_activity`, `sf_search_assets`). Draft one email per contact, following the same tone rules.

### Tone Rules (both modes)

- Open with a personal reference (recent call, active deal, open case, tooling discussion).
- State the ask/offer clearly with a specific CTA (reply to confirm, call this week, hold a spot).
- Vary the opening line — never send near-identical copy to two different people.
- Sign off as `Chris Barsanti\nMid Atlantic Machinery`.
- ASCII only — no em dashes, no smart quotes (matches the existing Outlook COM script convention; non-ASCII characters have caused issues in the push scripts before).

### Step 2: Append to the Queue (with dedup)

Read `.scripts/email-drafts/data/drafts.json` (treat as `[]` if missing). Before adding each new draft:
- Task-sourced: skip if an entry with the same `taskId` already exists in the queue.
- Campaign-sourced: skip if an entry with the same `campaign` + `to` already exists.

Append surviving entries and write the file back (2-space indent). Draft IDs follow `draft-YYYYMMDD-XXX`, zero-padded per day, same convention as task IDs.

### Queue Format

Each entry in `.scripts/email-drafts/data/drafts.json`:

```json
{
  "id": "draft-20260706-001",
  "source": "task",
  "taskId": "task-20260706-117",
  "campaign": null,
  "contactName": "Bill Kovaleski",
  "company": "Pennsylvania Steel Company",
  "to": "bkovaleski@example.com",
  "cc": "",
  "subject": "...",
  "body": "...",
  "sendMode": "draft",
  "status": "queued",
  "error": null,
  "createdAt": "2026-07-06T14:00:00"
}
```

- `source`: `"task"` or `"campaign"`. `taskId` is null for campaign drafts; `campaign` is null for task drafts.
- If the email couldn't be resolved in Step 1, still add the entry with `to: ""` and `status: "needs_email"` so it surfaces in the dashboard for manual entry rather than silently getting dropped.
- Otherwise new entries start at `status: "queued"`, `sendMode: "draft"`.
- Never write `status: "sent"` or `"pushed_draft"` yourself — those are only set by the dashboard after an actual Outlook push.

### Step 3: Show a Summary and Launch the Dashboard

1. Show the user a short table: contact, company, subject, and a flag for any `needs_email` entries that need a manual address.
2. Launch the dashboard so they land on the review screen: run `.scripts/email-drafts/launch.bat`.
3. Remind them: every draft defaults to creating an Outlook draft; "Send now" is opt-in per email in the dashboard and sends immediately with no undo.

## Notes

- The dashboard (`server.cjs` + `public/`) is a small Node app with no external dependencies — it's the only thing that talks to Outlook (via `push-to-outlook.ps1`, COM automation). This skill never touches Outlook directly.
- Classic Outlook desktop must be open for pushes to succeed; that's enforced in the dashboard, not here.
- Re-running this skill is safe — dedup means it only adds genuinely new drafts to the queue.
- For a quick one-off campaign where a review dashboard is overkill, `outreach-drafts-custom` still generates a standalone `.ps1` script as before.
- To edit this skill: `.claude/skills/email-drafts-custom/SKILL.md`
