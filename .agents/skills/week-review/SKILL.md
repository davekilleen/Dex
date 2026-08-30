---
name: week-review
description: "Review the week with concrete accomplishments (not fake percentages), pattern detection and goal tracking. Use when the user says 'how was my week', 'week review', or it's their last working day. Also use proactively when a week's priorities are largely resolved. Not for planning the coming week; use `week-plan`."
---

<!-- Generated from `.claude/skills/week-review/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## Execution mode

Run inline in the current conversation by default, so this work can see what the
user has already discussed, decided, or settled this session. Do not fork merely
because this skill was selected. Only run in the background when the user
explicitly asks for a background run or the host has already obtained a specific
background-work approval for this run.

### Delegated gathering (large-vault scaling)

This skill stays inline as described above: it keeps session awareness, it asks
the user the questions, and it owns every interactive step. What it does NOT do
inline is the bulk read-gathering, which on a mature vault (hundreds of notes,
thousands of indexed messages, a live calendar and multiple integrations) can be
large enough to exhaust the main conversation before the useful work starts.

So the gathering phase is delegated to one `general-purpose` subagent via the
Agent tool, using the self-contained prompt in this skill's
`AGENT_INSTRUCTIONS.md`:

1. Read `.agents/skills/week-review/AGENT_INSTRUCTIONS.md`.
2. Substitute its placeholders (`{{TARGET_DATE}}`, `{{WEEK_START_DATE}}`,
   `{{TARGET_DATE_PLUS_1}}`, `{{DAY_NAME}}`, `{{MONTH}}`, `{{DD}}`, `{{YYYY}}`).
3. Call the Agent tool with `subagent_type: "general-purpose"`, that prompt, and
   a short description.
4. Verify it wrote the synthesis to `00-Inbox/Weekly_Synthesis_YYYY-MM-DD.md`,
   then run the interactive review from its structured findings.

The subagent inherits MCP connections, runs in its own context, and that context
is freed when it completes, so only its findings reach this conversation.

**Use `AGENT_INSTRUCTIONS.md` verbatim.** Read the file and pass its content as
the subagent prompt, substituting only the placeholders. Do NOT hand-write a
replacement brief from what you already know about the week: that is how steps
get silently dropped, and the omission looks complete because nothing errors. If
context from this conversation is worth adding, APPEND it to the file's content;
never substitute for it.

**Two caveats that are load-bearing:**

- **Do not count on hooks for the subagent's writes.** The hooks declared in
  this skill's own frontmatter belong to this skill's run, not the subagent's,
  and whether the repository-wide hooks in `the host's lifecycle settings` reach a
  subagent's tool calls is not something a skill should assume either way.
  Nothing in this skill's gathering depends on a hook; the subagent's writes
  must stand on their own.
- **Always fall back.** If the subagent fails, times out, or returns nothing
  usable, say so plainly and run the gathering inline from the same
  `AGENT_INSTRUCTIONS.md`. A missing subagent must never mean a missing result.

**Stays inline:** the whole interactive review, priority-by-priority assessment,
pattern discussion, goal updates, career evidence capture, next week's priority
confirmation, the Dex Inbox check (Step 0.5), clearing completed tasks from
`03-Tasks/Tasks.md` after confirm (the delegated summary names this step), and
the `/identity-snapshot` run that follows the synthesis. The subagent gathers
evidence; it does not make judgements.

## Purpose

Create a synthesis of the week reviewing activity, progress, and what was accomplished. **Uses concrete metrics, not vague percentages.**

Read `working_week.days` in `System/user-profile.yaml` and treat its last working day as the natural review point.

---

## Step 0: Process Unprocessed Meetings

Before gathering data, ensure all meetings from this week are in the vault by running `/process-meetings`. This pulls any unprocessed meetings from the meeting source (Otter.ai, Granola, etc.), creates meeting notes, updates person/company pages, and extracts tasks — so the weekly synthesis has complete data.

- If no new meetings are found, continue silently
- If meetings are processed, note the count for the synthesis
- Do NOT ask for a skill rating after this sub-step — save that for the end of the full review

---

## Step 0.5: Dex Inbox Check (Phone Captures)

After processing meetings, check for tasks captured from phone that haven't been triaged:

```
Use: reminders_list_items(list_name="Dex Inbox")
```

**If the tool is unavailable or errors** (Apple Reminders phone-capture is optional and may not be set up on this machine): skip this step silently — do not surface an error for a feature the user never enabled.

If items found:
- Surface them: "📱 **Phone captures not yet triaged** (X items in Dex Inbox)"
- Run triage flow: infer pillar, confirm with user, create task, mark Reminder complete
- If user wants to defer: leave in Dex Inbox

**If empty:** Skip silently.

---

## Data Sources

### 1. Task Progress
- `03-Tasks/Tasks.md` — Task completion status
- `02-Week_Priorities/Week_Priorities.md` — Weekly priorities

### 2. Project Activity
- `04-Projects/**/*.md` — Modified this week

### 3. Meetings & People
- `00-Inbox/Meetings/*.md` — Meeting notes from this week
- `People/**/*.md` — Person pages updated

### 4. Learnings
- `06-Resources/Learnings/**/*.md` — Explicit learnings
- `System/Session_Learnings/*.md` — Auto-captured session learnings

### 5. Daily Plans & Reviews
- `00-Inbox/Daily_Plans/YYYY-MM-DD.md` — This week's daily plans (primary record of planning ritual)
- `07-Archives/Reviews/Daily_Review_YYYY-MM-DD.md` — This week's reviews

### 6. Journals (If Enabled)
- `00-Inbox/Journals/YYYY/MM-Month/` — Morning/evening journals

---

## Analysis Process

### 1. Weekly Priority Completion (Concrete, Not Percentages)

**Don't say:** "Goal X went from 40% to 55%"
**Do say:** "You completed 2 of 3 weekly priorities"

```
Use: get_week_progress()
```

For each weekly priority:
- **Complete:** ✅ What was the deliverable? When did you finish?
- **In Progress:** 🔄 What specifically got done? What's left?
- **Not Started:** ❌ Why? Should it carry forward?

**Surface concrete accomplishments:**

> "**This week's priorities:**
> 
> 1. ✅ **Ship pricing page** — Complete (pushed to prod Wednesday)
>    - Deliverable: New pricing page live at /pricing
>    - Tasks completed: 5 of 5
> 
> 2. 🔄 **Write Q1 strategy doc** — 60% complete
>    - Done: Outline, competitive analysis, recommendations
>    - Remaining: Executive summary, financial projections
>    - 2 tasks left
> 
> 3. ❌ **Customer interviews** — Not started
>    - Reason: Calendar was too stacked
>    - Recommendation: Carry to next week with protected time"

### 1.5 Semantic Goal-to-Work Mapping (if QMD available)

**Check if semantic search is available** by looking for `qmd` in PATH.

If available, enhance the weekly priority review with meaning-based analysis:

1. **Auto-detect goal contributions:** For each completed task this week, search:
   ```
   qmd query "task title/description" --limit 3
   ```
   against quarterly goals. Catch tasks that advanced goals without explicit links.
   - Example: "Built customer health dashboard" semantically matches goal "Improve NPS tracking" — different words, same work.

2. **Cross-priority connections:** Search for work that bridges multiple priorities:
   ```
   qmd query "priority 1 description" --limit 5
   ```
   Surface tasks that contributed to more than one priority.

3. **Thematic patterns:** Search for recurring themes across the week's work:
   ```
   qmd query "common theme from meetings/tasks" --limit 5
   ```
   Detect patterns like "most of your work this week clustered around customer retention" even when tasks used different terminology.

**Integration:** Merge findings into the Quarterly Goals table — add a "Hidden contributions" row for semantically-detected but not explicitly-linked work. Only show genuinely new connections, not things already captured by keyword matching.

**If QMD unavailable:** Skip silently. Task completion stats still work fine.

### 2. Task Completion Stats (Concrete Numbers)

Scan `03-Tasks/Tasks.md` for completion timestamps from this week:
- Count tasks completed (look for `✅ YYYY-MM-DD` in date range)
- Count tasks added mid-week
- Count tasks carried over

**Surface:**

> "**Tasks this week:**
> - Completed: 14 tasks
> - Added mid-week: 6 tasks (scope creep?)
> - Carried over: 3 tasks
> 
> **Completion rate:** 82% (14 of 17 planned)"

### 3. Quarterly Goals Progress (Concrete Milestones)

**Don't use fake percentages.** Use milestone counts and specific accomplishments.

```
Use: get_quarterly_goals()
Use: get_goal_status(goal_id) for each goal
```

For each goal:
- Milestones completed this week
- Total milestones done vs. total
- Weeks since last milestone
- Specific accomplishments that moved the goal

> "**Quarterly Goals Progress:**
> 
> | Goal | Milestones | This Week | Status |
> |------|------------|-----------|--------|
> | Launch v2.0 | 3 of 5 | +1 (Pricing page shipped) | On track |
> | Improve NPS | 1 of 4 | No change | ⚠️ Stalled (3 weeks) |
> | Team Capacity | 2 of 3 | No change | On track |
> 
> **Goal 1** advanced because you completed Priority 1.
> **Goal 2** needs attention — no linked work completed this week."

### 4. Daily Completion Rate Trend

**First check `00-Inbox/Daily_Plans/` for this week's daily plans.** Count how many days had a `/daily-plan` generated. If daily reviews also exist, cross-reference plan focus items against review completion. If only plans exist (no corresponding review), still count the plan as evidence of the planning ritual and note which focus items were checked off in the plan file itself.
Calculate completion trends:

> "**Daily plan completion this week:**
> 
> | Day | Planned | Done | Rate |
> |-----|---------|------|------|
> | Mon | 3 | 2 | 67% |
> | Tue | 3 | 3 | 100% |
> | Wed | 3 | 2 | 67% |
> | Thu | 3 | 1 | 33% |
> | Fri | 3 | 2 | 67% |
> 
> **Week average:** 67%
> **Pattern:** Thursday was rough (too many meetings?)"

### 5. Meeting Analysis

Review meeting notes from the week:
- Meetings held
- Key decisions
- Action items created
- Follow-ups that might have slipped

### 5.5 Email Communication Stats (if connected)

Check `System/integrations/config.yaml` for `google-workspace.enabled: true`. Also treat a
registered `apple-mail-mcp` server as connected. Before querying a connected email source,
run `python3 core/utils/doctor.py --deep`; Apple Mail search is usable only when the
`mail.apple-search` check reports `OK` / `feature_status: ok`.

If connected and healthy:
- **Emails sent this week** — count of sent messages in the review period
- **Average response time** — how quickly you replied to incoming emails
- **Threads still open** — conversations with no resolution (back-and-forth still active)
- **Follow-up detection** — emails waiting > 48h for a reply from you or from others

Surface in the review:

> "**Email this week:**
>
> | Metric | Value |
> |--------|-------|
> | Emails sent | 47 |
> | Avg response time | 3.2 hours |
> | Open threads | 12 |
> | Awaiting your reply (> 48h) | 3 |
>
> **Observation:** You have 3 emails waiting for replies longer than 48 hours. Consider clearing those early next week."

For Apple Mail, never interpret an empty search as "no matching mail" unless that check is OK.
If a connected source is broken or could not be checked, **do not silently skip**: include one
calm "Email review omitted" line with Doctor's `user_message` or fix path. If the source is not
connected (`OFF`), omit the section without noise.

### 6. Learning Compilation & Pattern Detection

Review `System/Session_Learnings/` files from this week:

**Pattern Detection:**
- **Recurring issues:** Same mistake 2+ times? Suggest adding to Mistake_Patterns.md
- **Consistent preferences:** User repeatedly mentioned a workflow preference?

> "This week's session learnings revealed:
> 
> **Recurring Issues:**
> - Calendar overload (mentioned 3 times) — Consider blocking focus time
> 
> **Workflow Preferences:**
> - Prefer morning for deep work (mentioned 2 times)
> 
> Should I add these to your pattern files?"

---

## Output Format

Create `00-Inbox/Weekly_Synthesis_YYYY-MM-DD.md`:

```markdown
# Weekly Synthesis — Week of [Date]

## TL;DR

- **Weekly priorities:** [X] of 3 complete
- **Tasks:** [X] completed / [Y] planned — [Z]% completion
- **Meetings:** [N] total
- **Key wins:** [1-2 bullets]
- **Carried over:** [1-2 items]

---

## 🎯 Weekly Priorities

### 1. [Priority 1] — ✅ Complete

**Deliverable:** [What was shipped/finished]
**Completed:** [Day]
**Tasks:** 5 of 5

### 2. [Priority 2] — 🔄 In Progress (60%)

**Done this week:**
- [Specific accomplishment]
- [Specific accomplishment]

**Remaining:**
- [Specific task]
- [Specific task]

### 3. [Priority 3] — ❌ Not Started

**Why:** [Reason]
**Recommendation:** [Carry forward / Deprioritize / Defer]

---

## 📊 Task Completion

| Metric | Count |
|--------|-------|
| Tasks completed | 14 |
| Tasks added mid-week | 6 |
| Tasks carried over | 3 |
| **Completion rate** | **82%** |

**Observation:** [Any patterns — e.g., lots of scope creep]

---

## 🎯 Quarterly Goals

| Goal | Milestones | This Week | Status |
|------|------------|-----------|--------|
| [Goal 1] | X of Y | +Z | [Status] |
| [Goal 2] | X of Y | — | [Status] |
| [Goal 3] | X of Y | +Z | [Status] |

**Goals advancing:** [Which ones moved]
**Goals stalled:** [Which ones need attention]

---

## 📊 Daily Completion Trend

| Day | Planned | Done | Rate |
|-----|---------|------|------|
| Mon | 3 | 2 | 67% |
| Tue | 3 | 3 | 100% |
| Wed | 3 | 2 | 67% |
| Thu | 3 | 1 | 33% |
| Fri | 3 | 2 | 67% |

**Week average:** [X]%
**Observation:** [Pattern noticed]

---

## 📅 Meetings & People

### Meetings Held

| Date | Topic | Key Outcome |
|------|-------|-------------|
| [Day] | [Topic] | [Decision/insight] |

### New Contacts
- [Name] at [Company] — [context]

### Action Items from Meetings
- [ ] [Action] — for [who] — due [when]

---

## 💡 Learnings

### Session Learnings (Auto-Captured)
- [Learning 1]
- [Learning 2]

### Patterns Identified
- **Recurring issue:** [Issue] (appeared X times)
- **Preference noted:** [Preference]

### Actionable Improvements
- [ ] [Specific improvement to make]

---

## 📊 Pillar Balance

| Pillar | Tasks Done | Focus |
|--------|------------|-------|
| [Pillar 1] | X tasks | Heavy |
| [Pillar 2] | X tasks | Light |
| [Pillar 3] | X tasks | None |

**Observation:** [Balance assessment]

---

## ➡️ Next Week

### Suggested Priorities

Based on this week's progress:

1. **[Priority]** — [Why: carries over / goal needs attention / commitment]
2. **[Priority]** — [Why]
3. **[Priority]** — [Why]

### Blocked Items Needing Resolution

| Item | Blocked Since | What Would Unblock It |
|------|---------------|-----------------------|
| [Item] | [Date] | [Action needed] |

---

## 🏆 Career Evidence (If Career System Enabled)

**Significant accomplishments worth capturing:**

- [Accomplishment] — demonstrates [skill]
- [Accomplishment] — shows [impact]

> "Want to save any of these as career evidence?"

---

*Generated: [timestamp]*
*Weekly completion: X of 3 priorities*
*Task completion: X%*
```

---

## Innovation Concierge: Top 3 This Week

At the end of the weekly review, surface the top backlog ideas:

1. Call `list_ideas(status="active", min_score=70)` from Improvements MCP
2. Pick the top 3 ideas by score that haven't been surfaced in the last week review
3. Include in the output format as a section:

```markdown
## 🤖 Top 3 Dex Improvement Ideas

Your AI-curated backlog has surfaced these high-impact ideas:

1. **[idea-XXX]** Title (Score: XX)
   Why now: [Brief evidence or timeliness reason]

2. **[idea-XXX]** Title (Score: XX)
   Why now: [Brief evidence]

3. **[idea-XXX]** Title (Score: XX)
   Why now: [Brief evidence]

> Interested? Run `/dex-improve [idea-id]` to workshop any of these.
> Run `/dex-backlog` to see the full ranked backlog.
```

**Rules:**
- Only show ideas with score >= 70 (don't surface low-value noise)
- Prefer ideas with recent "Why Now?" evidence
- If fewer than 3 qualifying ideas, show however many exist
- If no qualifying ideas, skip this section entirely
- This is a gentle nudge, not a sales pitch

---

## Skill Quality Insights

After generating the synthesis, call `get_skill_ratings()` from Work MCP (no filter — get all skills).

**If ratings exist for any skills:**
Add a section to the review:

```markdown
## Skill Quality This Week

| Skill | Avg Rating | Trend | Note |
|-------|-----------|-------|------|
| [skill] | [avg]/5 | [improving/stable/declining] | [most recent note] |
```

**Only surface skills that are declining or below 3.0.** If everything is stable/good, skip this section entirely. One line for healthy, only details for problems.

**Then:** Run `/identity-snapshot` to update `System/identity-model.md` with fresh data from this week.

---

## Follow-up Actions

The delegated gatherer's structured summary names the Tasks.md clear-down
as required interactive input. Do not skip it after a delegated run.

After synthesis:
1. Update Tasks.md with new priorities
2. Clear completed tasks out of `03-Tasks/Tasks.md` — **remove whole task blocks, never
   individual lines.** Tasks.md entries can span multiple lines: the `- [x]` checkbox
   line plus its indented sub-lines (priority, due date, notes) and any continuation
   paragraphs. A task's block runs from its checkbox line down to (but not including)
   the next non-indented line — the next task's checkbox, a heading, or a blank line
   followed by unindented content. When removing a completed task, remove that entire
   block together so no orphaned sub-lines are left behind. Never do a per-line sweep
   of `[x]` lines: that strands sub-lines, and it also removes completed sub-checkboxes
   out from under tasks that are still open (only remove a block whose own top-level
   checkbox is `[x]`). Before deleting anything, tell the user how many completed tasks
   you're clearing and confirm.
3. Update project pages with status changes
4. Offer to run `/week-plan` for next week

---

## MCP Dependencies

| Integration | MCP Server | Tools Used |
|-------------|------------|------------|
| Work | work-mcp | `list_tasks`, `get_week_progress`, `get_quarterly_goals`, `get_goal_status` |
| Calendar | calendar-mcp, or google-workspace-mcp when `calendar.provider` is `google` | Apple: `calendar_get_events_with_attendees`. Google: `list_calendars`, `get_events` |
| Improvements | dex-improvements-mcp | `list_ideas` |
| Analytics | dex-analytics | `track_event` |

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark weekly review as used.

**Analytics (Silent):**

Call `track_event` with event_name `week_review_completed` and properties:
- `priorities_completed`: number of priorities completed
- `priorities_total`: total number of priorities
- `tasks_completed`: number of tasks completed this weekThis only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
