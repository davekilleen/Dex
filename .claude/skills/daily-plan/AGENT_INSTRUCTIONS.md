# Daily Plan - Agent Instructions

You are gathering context for the user's daily plan. You have access to the same
MCP tools as the main conversation. Your job is to gather context from every
available source, assemble it, and write a draft daily plan file. You gather and
assemble; you do not make judgement calls the user should confirm. Anything that
needs the user (triage decisions, task creation confirmations, goal-link
confirmations) is flagged in your final report and handled by the main
conversation.

**Target date:** {{TARGET_DATE}} ({{DAY_NAME}}, {{MONTH}} {{DD}})

**Write the draft plan to:** `07-Archives/Plans/{{TARGET_DATE}}.md`

**Note:** PostToolUse hooks from the parent skill do not fire in this subagent
context. Do not rely on hook-driven side effects for any write you make.

---

## Phase 1: Context Gathering

Gather ALL of the following, in parallel where possible. If any source fails or
an optional integration is not set up, skip it silently and note the skipped
source in your final report. Never error to the user.

### 1.1 Week Progress

```
Use: get_week_progress()
```

Extract: day of week, days remaining, priority status (complete / in_progress /
not_started), warnings for priorities with no activity.

### 1.2 Calendar + Capacity

```
Use: calendar_get_events_with_attendees(start_date="{{TARGET_DATE}}", end_date="{{TARGET_DATE_PLUS_1}}")
Use: analyze_calendar_capacity(days_ahead=1, events=[...from above...])
```

Apply CLAUDE.md's **Calendar response confidence contract** before consuming
events or passing them to `analyze_calendar_capacity`.

Get: meetings with times and attendees, day type (stacked / moderate / open),
free blocks, deep work opportunities. Verify every event's date against the
target date; exclude events that bled in from adjacent days.

### 1.3 Meeting Intelligence

For each meeting on the target date:

```
Use: get_meeting_context(meeting_title="...", attendees=[...])
```

Get: related project, project status, outstanding tasks with attendees, prep
suggestions.

### 1.4 Commitments Due

```
Use: get_commitments_due(date_range="today")
```

Also read these feeds when present and fresh (read-only; degrade silently when
absent or empty):

- `System/.dex/entity-suggestions.json` - suggested person pages
- `System/.dex/entity-cooling.json` - people or accounts going cold
- `System/.dex/entity-relationships.json` - relationships to confirm

Record what they contain; the main conversation decides what to do with them.

### 1.5 Tasks + Scheduling

```
Use: list_tasks(priority="P0")
Use: list_tasks(priority="P1")
Use: suggest_task_scheduling(include_all_tasks=False, calendar_events=[...])
```

Also collect open tasks whose `metadata_source` points at a recent meeting, and
open tasks where `goal_tentative` is true. Report both lists; do not confirm or
clear goal links yourself.

### 1.6 Work Summary

```
Use: get_work_summary()
```

Get: quarterly goals context, weekly priorities, task counts.

### 1.7 Reminders Sync (Phone -> Vault)

```
Use: reminders_list_completed(list_name="Dex Today")
```

For each completed item, match it to an existing task by title and update it:
`update_task_status(task_title="...", status="d")`. This is a mechanical sync of
completions the user already made; record what was synced. If the Reminders
tools are unavailable, skip silently.

### 1.8 Mobile Capture Check

```
Use: reminders_list_items(list_name="Dex Inbox")
```

If items are found, list them in your report for triage. Do NOT create tasks
from them; triage is an interactive step in the main conversation.

### 1.9 Email Intelligence (if connected)

Check `System/integrations/config.yaml`. Also treat a registered `apple-mail-mcp`
server as connected. Before querying any connected email source, run
`python3 core/utils/doctor.py --check mail.apple-search` — a focused local check,
not `--deep`. Apple Mail search is usable only when the
`mail.apple-search` check reports `OK` / `feature_status: ok`.

If the source is connected and healthy:

- Get unread count and priority emails
- Flag emails needing reply (received more than 48 hours ago, from key contacts
  in `05-Areas/People/`)
- Surface threads involving the target date's meeting attendees

For Apple Mail, do not interpret an empty search as an empty mailbox unless that
check is OK. If a connected source is broken or unknown, **do not silently skip**:
report it under `Sources skipped` with Doctor's `user_message` or fix path. If the
source is not connected (`OFF`), omit it without noise.

### 1.10 Chat Intelligence (if connected)

Check `System/integrations/config.yaml` for enabled chat integrations (Slack,
Teams). For each enabled and healthy MCP: unread counts, DMs needing response,
mentions, and threads with today's meeting attendees. Label context by source.
Skip silently when not connected.

### 1.11 Semantic Enrichment (if QMD available)

Check the QMD `status` tool. If available:

- For each meeting: `query` with the meeting topic and attendee names
- For each lagging priority: `query` with the priority description
- Cross-topic scan: `query` combining the day's key themes

Only record genuinely new insights not already found in earlier steps, and mark
them as semantic results. If QMD is unavailable, skip silently.

### 1.12 Innovation Spotlight

```
Use: list_ideas(status="active", min_score=70)
```

Pick at most one high-scoring idea with recent "Why Now?" evidence. Skip if
nothing noteworthy.

---

## Phase 2: Assembly

Combine all context into:

### Focus Candidates (Top 3)

Based on: P0 tasks (highest weight), weekly priority alignment (especially
lagging priorities), meeting prep needs, commitments due. State the evidence for
each candidate so the main conversation can confirm or adjust the selection.

**Task IDs are mandatory on focus items that map to existing tasks.** For each
candidate that matches a task in `03-Tasks/Tasks.md`, write it in the plan as a
`- [ ]` checkbox line with that task's `^task-YYYYMMDD-XXX` anchor at the end of
the same line (dash checkbox, not a numbered one; the ID never goes on its own
line).

For candidates with no existing task, do NOT create one, and **do NOT write them
as a checkbox.** Write the line without any checkbox and end it with the literal
marker `<!-- NEEDS TASK -->`, and flag it in your report as "needs a task".

Why this matters: completion sync only matches a line holding both a checkbox and
a `^task-...` anchor. A checkbox with no anchor never syncs in either direction,
looks exactly like a working one, and can never be repaired after the fact
because nothing marks it as broken. The marker is what lets the main conversation
find the line and rewrite it once the user has confirmed the task.

Candidates that are not tasks at all (for example "protect the 2-4pm free block")
get neither a checkbox, nor an ID, nor the marker.

### Meeting Prep

For each meeting: attendees with person-page context, related project status,
outstanding tasks, prep suggestions.

### Heads Up

Flag: lagging weekly priorities, commitments due today, back-to-back meetings,
P0 items with no time blocked, deep work tasks with no suitable slot, plus any
cooling entities or relationship suggestions from the feeds in 1.4.

---

## Phase 3: Write the Draft Plan

Write the complete draft to `07-Archives/Plans/{{TARGET_DATE}}.md` using the
plan template from this skill's `SKILL.md` (Step 7: frontmatter, TL;DR, Week
Progress, Today's Shape, Commitments Due, Today's Focus, Meetings with Context,
Task Scheduling, Heads Up).

**Reading `SKILL.md` safely.** You need only the section named above. Ignore that
file's "Delegated gathering" section entirely: it describes how you were
invoked. You ARE the subagent, so you must never call the Agent tool or spawn a
subagent of your own.

If Dex Inbox items were found, append a "Mobile Capture (Dex Inbox)" section
listing them for triage. If an Innovation Spotlight was selected, append it as a
one-to-two line section.

---

## Final Output

After writing the draft, return a structured summary to the conversation:

```
AGENT COMPLETE

Draft plan written: 07-Archives/Plans/{{TARGET_DATE}}.md

Summary:
- Meetings today: [N], day type [stacked/moderate/open]
- Week progress: [X]/[Y] priorities on track
- Commitments due: [N]
- Focus candidates: [3 one-liners, each noting existing-task anchor or "needs a task"]
- Dex Inbox items awaiting triage: [N]
- Tentative goal links awaiting confirmation: [N]
- Email/chat: [brief, or "not connected"]
- Sources skipped: [list, with reason]

[Any warnings or issues encountered]
```

---

## Important Notes

- Write the plan file with the Write tool; do not paste its full content back
  into the conversation
- Be concise in meeting sections: three to four lines per meeting unless there
  is critical context
- Use real data from tools; never fabricate meetings, tasks, or people
- If a tool fails, skip that section; the plan should degrade gracefully
- Match the user's communication preferences from `System/user-profile.yaml`
