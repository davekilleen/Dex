# Daily Review - Agent Instructions

You are gathering context for a daily review. Collect data from all available
sources, then write a DRAFT review file. You gather evidence; you do not make
the assessments the user should be part of. Interactive sections are left as
placeholders for the main conversation to complete. Be direct and concise. Skip
any section gracefully if a tool fails; never error out.

**Target date:** {{TARGET_DATE}} ({{DAY_NAME}}, {{MONTH}} {{DD}}, {{YYYY}})

**Note:** PostToolUse hooks from the parent skill do not fire in this subagent
context. Do not rely on hook-driven side effects for any write you make.

---

## Step 0: Meeting Catch-Up (not same-day only)

Check for meetings that have not yet reached the vault. Process every
unprocessed meeting since the last one that did, NOT only {{TARGET_DATE}}: find
the newest dated folder under `00-Inbox/Meetings/`; the catch-up window runs
from that date to {{TARGET_DATE}} inclusive. If the window is wider than seven
days, process the most recent seven days and REPORT the older backlog rather
than silently skipping it.

Why the window matters: a same-day filter loses meetings permanently on any day
the review does not run.

If the meeting source (Granola via `GRANOLA_API_KEY`, or another configured
source) has unprocessed meetings in the window, process them following the
conventions in `.claude/skills/process-meetings/AGENT_INSTRUCTIONS.md`,
including updating person pages directly (hooks do not fire in this context).
Note which meetings were processed. If no source is connected or nothing is
unprocessed, skip silently.

---

## Step 1: File Discovery

From the vault root, find files modified on the target date:

```bash
find . -type f -name "*.md" -newermt "{{TARGET_DATE}} 00:00:00" ! -newermt "{{TARGET_DATE}} 23:59:59" 2>/dev/null | grep -v node_modules | grep -v .git
```

List ALL modified files, without truncation.

---

## Step 2: Gather Context

### 2.1 Tasks

Read `03-Tasks/Tasks.md` and extract:
- Tasks completed on the target date (lines containing `{{TARGET_DATE}}` with
  done markers)
- Tasks started but not finished (status `s`)
- Tasks blocked (status `b`)

### 2.2 Weekly Priorities

Call `get_week_progress()` for priority status and how the day connects to
weekly goals. Also call `get_week_priorities()` for the full list.

### 2.3 Meetings

Check `00-Inbox/Meetings/{{TARGET_DATE}}/` for meeting notes. Also call
`calendar_get_today()` for the calendar view. Combine meetings processed in
Step 0 with any manually created notes.

### 2.4 Semantic Context Enrichment (if QMD available)

Check the QMD `status` tool. If available:

1. **Map completed tasks to goals:** for each task completed today, `query`
   with the task description; look for connections to quarterly goals or weekly
   priorities that keyword matching misses.
2. **Enrich meeting context:** for each meeting today, `query` with the meeting
   topic for related past discussions.
3. **Priority alignment check:** for each weekly priority, `query` for today's
   work that advanced it.

Only note genuinely new connections. If QMD is unavailable, skip silently.

### 2.5 Reminders Completion Sync

1. Call `reminders_list_completed(list_name="Dex Today")`
2. For each completed reminder, match to a task by title and call
   `update_task_status(task_title="...", status="d")`; record what was synced
3. For each task completed today in the vault, call
   `reminders_find_and_complete(list_name="Dex Today", title_query="...")`
4. Call `reminders_clear_completed(list_name="Dex Today")`

If the Reminders tools are unavailable, skip silently.

### 2.6 Email End-of-Day Review (if connected)

Check `System/integrations/config.yaml`. If an email integration is enabled and
its MCP is healthy:

1. Get today's received and sent emails
2. Analyse: counts, received emails with no matching reply (needs response),
   sent emails awaiting a response, action items in received mail ("Can
   you...", "Please...", "By Friday..."), outbound promises in sent mail
   ("I'll send...", "Will follow up...")
3. Cross-reference senders with `lookup_person()` and promises against
   `03-Tasks/Tasks.md`
4. Record the summary for the review file

If not connected or unhealthy, skip silently.

---

## Step 3: Daily Plan Completion Tracking

1. Read `07-Archives/Plans/{{TARGET_DATE}}.md` if it exists
2. Extract the planned focus items from "Today's Focus"
3. For each, check `03-Tasks/Tasks.md` completion timestamps and the modified
   files for evidence; classify as Complete, In Progress (estimate %), or Not
   Started; calculate the completion rate
4. Identify significant work done today that was NOT in the plan

---

## Step 4: Progress Assessment (evidence only)

Synthesise from the gathered context: what was accomplished, what moved against
weekly priorities, what got stuck, what unexpected things came up, and any
connections discovered. Report evidence and flag contradictions; leave
judgement calls to the conversation.

---

## Step 5: Week Progress Check

Call `get_week_progress()`. Record the status of each weekly priority, days
remaining, and which priorities need attention tomorrow.

---

## Step 6: Tomorrow's Shape

Call `analyze_calendar_capacity(days_ahead=1)` and/or:

```
calendar_get_my_events(start_date="{{TOMORROW_DATE}}", end_date="{{TOMORROW_DATE_PLUS_1}}")
```

Record: meeting count, free blocks, day type (stacked / moderate / open).

---

## Write the Draft Review File

Using the Write tool, create:
`07-Archives/Reviews/Daily_Review_{{TARGET_DATE}}.md`

Use the review template from this skill's `SKILL.md` (Output Format section):
frontmatter with `plan_completion_rate`, Plan vs. Reality, Accomplished,
Progress Made, Weekly Priorities Progress, Meeting Follow-Ups, Insights,
Blocked/Stuck, Discovered Questions, Tomorrow's Focus, Open Loops. Add an Email
Summary section only when email data was gathered.

**Output rules:**
- Omit any section where no data was available
- Use real data for every section you have data for
- Leave placeholder markers ONLY for `Meeting Follow-Ups` and `Tomorrow's
  Focus`; mark them `<!-- PLACEHOLDER: interactive step will complete this -->`
  with suggested content where the data supports it
- Be direct and concise; bullet points, not paragraphs

---

## Final Output

After writing the draft, return a structured summary:

```
AGENT COMPLETE

Draft review written: 07-Archives/Reviews/Daily_Review_{{TARGET_DATE}}.md

Summary:
- Meetings processed in catch-up: [N] (window: [dates]; older backlog: [N or none])
- Files modified today: [N]
- Tasks completed: [N]
- Plan completion rate: [X]%
- Weekly priorities status: [brief]
- Emails: [X] received, [Y] sent, [Z] need reply (or "not connected")
- Reminders synced: [N]
- Semantic connections found: [N]
- Sections needing interactive input: Meeting Follow-Ups, Tomorrow's Focus

[Any warnings or issues encountered]
```

This summary tells the conversation what to focus on in the interactive steps.
