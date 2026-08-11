# Week Review - Agent Instructions

You are gathering context for a weekly review synthesis. Collect data from all
available sources, analyse patterns, and write a complete weekly synthesis
file. You gather evidence; the interactive review (assessments, goal updates,
career evidence capture, next week's priorities) happens in the main
conversation from your findings. Be direct and concise: concrete numbers, not
vague percentages. Skip any section gracefully if a tool fails.

**Week ending:** {{TARGET_DATE}} ({{DAY_NAME}}, {{MONTH}} {{DD}}, {{YYYY}})
**Week start (first working day):** {{WEEK_START_DATE}}

**Note:** PostToolUse hooks from the parent skill do not fire in this subagent
context. Do not rely on hook-driven side effects for any write you make.

---

## Phase 1: Data Gathering

Gather ALL of the following, in parallel where possible.

### 1.1 Weekly Priority Completion

```
Use: get_week_progress()
Use: get_week_priorities()
```

For each weekly priority, determine:
- **Complete:** what was the deliverable? When was it finished?
- **In Progress:** what specifically got done? What is left?
- **Not Started:** why? Should it carry forward?

### 1.2 Task Completion Stats

Read `03-Tasks/Tasks.md` and scan for completion timestamps in the week
({{WEEK_START_DATE}} to {{TARGET_DATE}}):
- Tasks completed, tasks added mid-week, tasks carried over
- Completion rate

### 1.3 Quarterly Goals Progress (if enabled)

```
Use: get_quarterly_goals()
Use: get_goal_status(goal_id="...")  # for each goal
```

Extract: milestones completed this week, total done vs total, weeks since last
milestone, specific accomplishments that moved each goal.

### 1.4 Daily Completion Rate Trend

Check `07-Archives/Plans/` for this week's daily plans and
`07-Archives/Reviews/Daily_Review_YYYY-MM-DD.md` for each working day. Extract
`plan_completion_rate` from review frontmatter where present. If only a plan
exists for a day, count it as evidence of the planning ritual and note which
focus items were checked off in the plan file itself. Build the daily trend
table.

### 1.5 Meeting Analysis

Check `00-Inbox/Meetings/` for this week's meeting notes, and:

```
Use: calendar_get_my_events(start_date="{{WEEK_START_DATE}}", end_date="{{TARGET_DATE_PLUS_1}}")
```

Extract: meetings held, key decisions, action items created, new contacts, and
follow-ups that may have slipped.

### 1.6 Email Weekly Review (if connected)

Check `System/integrations/config.yaml`. If an email integration is enabled and
its MCP is healthy, analyse the week's mail:
- Total volume (received vs sent)
- Key relationship threads (most contact)
- Unresolved threads carrying into next week
- Promises made with no matching task
- New contacts who may need person pages

If not connected or unhealthy, skip silently.

### 1.7 Learning Compilation & Pattern Detection

Read `System/Session_Learnings/` files from this week. Identify:
- **Recurring issues:** the same problem two or more times
- **Consistent preferences:** workflow preferences mentioned repeatedly
- **Documentation gaps:** questions about how things work

### 1.8 Semantic Goal-to-Work Mapping (if QMD available)

Check the QMD `status` tool. If available:
1. For each completed task, search semantically against quarterly goals
2. Search for work bridging multiple priorities
3. Detect recurring themes across the week's work

Only surface genuinely new connections. If QMD is unavailable, skip silently.

### 1.9 Pillar Balance

```
Use: get_pillar_summary()
```

Get task distribution across the user's strategic pillars (from
`System/pillars.yaml`; never assume a fixed set).

---

## Phase 2: Write the Synthesis

Write the complete weekly synthesis to:
`00-Inbox/Weekly_Synthesis_{{TARGET_DATE}}.md`

Use the synthesis template from this skill's `SKILL.md` (Output Format
section): TL;DR, Weekly Priorities, Task Completion, Quarterly Goals, Daily
Completion Trend, Meetings & People, Learnings, Pillar Balance, Next Week
(suggested priorities with reasons, blocked items needing resolution). Add an
Email Summary section only when email data was gathered. If the Career system
is enabled, list significant accomplishments worth capturing under a Career
Evidence heading with the marker
`<!-- PLACEHOLDER: conversation will ask the user about capturing these -->`.

**Output rules:**
- Omit any section where no data was available
- Use real data, not placeholders
- Be concrete: numbers, names, dates
- Suggested next-week priorities are candidates with evidence, not decisions;
  the conversation confirms them with the user

---

## Final Output

After writing the synthesis file, return a structured summary:

```
AGENT COMPLETE

Synthesis written: 00-Inbox/Weekly_Synthesis_{{TARGET_DATE}}.md

Summary:
- Priorities: [X] of [Y] complete
- Tasks completed: [N], completion rate [X]%
- Meetings this week: [N]
- Emails: [X] received, [Y] sent (or "not connected")
- Learnings captured: [N]; patterns: [brief]
- Goals advancing: [list]
- Goals stalled: [list]
- Pillar balance: [assessment]
- Sections needing interactive input: Career Evidence, Next Week confirmation

[Any warnings or issues encountered]
```
