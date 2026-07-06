---
name: week-plan
description: Create a weekly plan by pulling email, calendar, pipeline opportunities, and open tasks.
---

## Purpose

Build a focused weekly plan from four sources: email, calendar, Salesforce opportunities, and open tasks. No fluff — just what you need to see to set the week up right.

## Usage

- `/week-plan` — Plan current week (or next week if run Friday/weekend)
- `/week-plan next` — Explicitly plan next week

---

## Step 1: Determine Target Week

Calculate the Monday start date for the target week. If today is Friday, Saturday, or Sunday, default to next week unless the user says otherwise.

---

## Step 2: Gather Context

Pull all four sources in parallel.

### 2.1 Calendar

Use the calendar MCP to get all events for the target week (Monday–Friday). For each day, note:
- Meetings (time, attendees, topic)
- Deep work blocks (2+ hour gaps between meetings)
- Days that are stacked vs. open

### 2.2 Email

Use the email MCP (retool-email or gmail) to get recent emails (last 3–5 days) and surface:
- Anything requiring a response or action
- Follow-ups you owe someone
- Threads with customers, prospects, or leadership that need attention this week

Also call `get_unreplied_emails` (retool-email MCP, default 3 business days) for a count of sent emails still awaiting a customer reply — this feeds the one-line pulse in Step 3, not a full breakdown (that's `/service-pulse`).

### 2.3 Salesforce Opportunities

Call `get_opportunities` from the salesforce-remote MCP to pull open opportunities. Focus on:
- Deals with close dates this week or next
- Opportunities in late stages (Proposal, Negotiation, Verbal)
- Any deals with recent activity or stale follow-ups
- Quotes pending, demos scheduled

### 2.4 Open Tasks

Use `list_tasks(include_done=False)` from Work MCP. Group by:
- P0 / must do this week
- P1 / should do this week
- Anything that's been sitting more than 2 weeks (flag it)

### 2.5 Open Service Cases

Call `sf_get_open_cases` from the Salesforce MCP. Note the count, and flag anything with `status = "Escalated"` or `priority = "High"` by name — these belong in the week's priorities, not just the tally. Full per-account detail lives in `/service-pulse`, not here.

---

## Step 3: Build the Week Plan

Synthesize everything into a plan. Present it as a draft for the user to confirm or adjust before writing the file.

**Structure:**

1. **Key priorities** — 3–5 things that matter most this week, informed by all four sources
2. **Calendar summary** — Meeting-heavy days vs. open time, deep work windows
3. **Pipeline actions** — Specific deal-by-deal actions for the week (follow-up, send quote, schedule call)
4. **Task list** — P0 and P1 tasks, with suggested day assignments based on calendar shape
5. **Email/follow-ups** — Things sitting in inbox that need action

Ask: "Does this look right, or anything you want to adjust?"

---

## Step 4: Write the Week Priorities File

Archive existing `Planning/Week_Priorities.md` to `Archive/Plans/YYYY-Wxx.md`, then write the new file:

```markdown
# Week Priorities

**Week of:** [Monday YYYY-MM-DD]  
*Generated: [Timestamp]*

---

## 🎯 Top Priorities This Week

1. **[Priority]** — [Why it matters / what it unblocks]
2. **[Priority]** — [Why it matters]
3. **[Priority]** — [Why it matters]

---

## 📅 Calendar Shape

| Day | Load | Deep Work? | Key Meetings |
|-----|------|------------|--------------|
| Mon | [light/moderate/stacked] | [✅/❌] | [Meetings] |
| Tue | | | |
| Wed | | | |
| Thu | | | |
| Fri | | | |

---

## 💼 Pipeline — This Week's Actions

| Deal | Stage | Action | By When |
|------|-------|--------|---------|
| [Company] | [Stage] | [What to do] | [Day] |

---

## 📋 Tasks

### P0 — Must Do
- [ ] [Task] — **[Day]**

### P1 — Should Do
- [ ] [Task] — **[Day]**

### Backlog (Flagged)
- [ ] [Task — sitting since YYYY-MM-DD]

---

## 📬 Email / Follow-ups

- [ ] Reply to [person] re: [topic]
- [ ] Follow up with [person] on [topic]

**Reply/Service Pulse:** [X] sent emails awaiting reply · [Y] open service cases ([Z] escalated)

---

## 🏁 End of Week

*Fill in Friday*

### Done
- 

### Didn't finish
- 

### Next week
- 
```

---

## Step 5: Track Usage (Silent)

Update `System/usage_log.md`. Call `track_event` with `week_plan_completed`.

---

## Step 6: Confirm

> "Week planned. Saved to `Planning/Week_Priorities.md`
>
> **Top priorities:**
> 1. [P1]
> 2. [P2]
> 3. [P3]
>
> **Pipeline actions:** [X deals need attention]
> **Open tasks:** [X P0, Y P1]
> **Reply/Service Pulse:** [X] awaiting reply, [Y] open cases ([Z] escalated)"

---

## MCP Dependencies

| Source | MCP | Tools |
|--------|-----|-------|
| Calendar | calendar-mcp | `get_events` for target week |
| Email | retool-email or gmail | recent inbox, action items |
| Salesforce | salesforce | open opportunities, close dates, `sf_get_open_cases` |
| Tasks | work-mcp | `list_tasks` |
| Email Reply Tracking | retool-email | `get_unreplied_emails` |
