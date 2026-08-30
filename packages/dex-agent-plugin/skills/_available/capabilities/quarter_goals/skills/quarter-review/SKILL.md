---
name: quarter-review
description: Review quarter completion and capture learnings
---

<!-- Generated from `.claude/skills/_available/capabilities/quarter_goals/skills/quarter-review/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## Purpose

Review and synthesize the quarter that just ended. Evaluates goal completion, captures learnings, and suggests focus for next quarter.

## Usage

- `/quarter-review` — Review current/recently ended quarter
- `/quarter-review Q4 2025` — Review specific past quarter

---

## Method

Verify the room, fiscal boundaries, target quarter, and source availability before
counting anything. Build a dated evidence ledger across goals, tasks, projects,
meetings, syntheses, reminders, and backlog records. Report unavailable sources
as `Unknown` with their coverage impact; never infer completion percentages from
activity or modification times. Walk through each goal with the user, separating
recorded status, observed evidence, and their assessment. Apply only configured,
dated backlog policies. Preview and confirm each processing, archive, reminder,
task, or backlog mutation separately, make archives idempotent, and read back
every destination.

## Output contract

Return the quarter calculation, source/tool coverage, goal-by-goal evidence and
user assessment, exact status counts with denominator, unknowns, contradictions,
learnings, pillar context, and backlog observations under the named policy source
and policy date. Unavailable sources remain visible and excluded from affected
counts. Never output an inferred completion percentage. End with separate mutation
receipts for every confirmed write or external action; label partial or failed
operations explicitly, and call the archive verified only after byte-for-byte
read-back.

## Step 0: Check if Quarterly Planning is Enabled

Read `System/user-profile.yaml`:

1. Check `capabilities.quarter_goals.enabled`; only when that key is absent, honor legacy `quarterly_planning.enabled`.
2. **If `false`:**
   - Display: "The Quarter Goals room is off. Enable it with `/manage-capabilities` when you want it."
   - End command
3. **If `true`:** Continue to Step 1

---

## Step 1: Determine Target Quarter

**If no parameter:**
- Calculate current quarter based on `q1_start_month`
- Assume reviewing current or just-ended quarter

**If parameter provided (e.g., "Q4 2025"):**
- Parse quarter and year
- Review that specific quarter

Calculate:
- `target_quarter`: "Q1 2026"
- `quarter_start`: "2026-01-01"
- `quarter_end`: "2026-03-31"

Use the configured fiscal start month and explicit three-month fiscal-quarter
boundaries, including year rollover. Record the source of the setting and the
calculation `as-of` date/time; do not substitute calendar dates silently.

---

## Step 2: Context Gathering

### Quarter Goals File

Check for `01-Quarter_Goals/Quarter_Goals.md`:

**If exists and matches target quarter:**
- Extract goals that were set
- Record any progress percentage exactly as reported, with its source, source date,
  and `as-of` time; do not treat it as independently verified
- List milestones and completion status

**If missing or wrong quarter:**
- Check `07-Archives/Reviews/[quarter]-goals.md` (archived version)
- If still missing: "No goals found for this quarter"

### Dex Inbox Check (Phone Captures)

Before reviewing, check for tasks captured from phone that haven't been triaged:

```
Use: reminders_list_items(list_name="Dex Inbox")
```

**If the tool is unavailable or errors** (Apple Reminders phone-capture is optional and may not be set up on this machine): record `Dex Inbox: Unknown — source unavailable` in the coverage summary. Do not present it as an error the user caused, and exclude phone captures from any completeness claim.

If items found:
- Surface them: "📱 **Phone captures not yet triaged** (X items in Dex Inbox)"
- Suggest a pillar without treating the suggestion as a decision; obtain separate
  user consent before creating each task and before marking each Reminder complete
- Complete this before the review so task counts are accurate

**If empty:** Record `Dex Inbox: 0 items` with the successful query time in the
coverage summary, then continue without a separate alert.

### Process Unprocessed Meetings

Before scanning meeting data, ensure all recent meetings are in the vault by running `/process-meetings`. This pulls any unprocessed meetings from the meeting source (Otter.ai, Granola, etc.), creates meeting notes, updates person/company pages, and extracts tasks — so the quarterly review has complete meeting data.

Treat processing as a mutation: preview the affected paths and obtain explicit
confirmation before running it when it will write notes, pages, or tasks. Verify
the processed sources and dates afterward; do not call the review complete merely
because the command returned.

- If no new meetings are found, record the checked sources and a zero result
- If meetings are processed, note the count

### Task Completion

Scan `03-Tasks/Tasks.md` for tasks completed during quarter:
- Count completed tasks in date range
- Major completions
- Tasks that were blocked

### Project Activity

Scan `04-Projects/` for activity during quarter:
- Modified files in date range
- Projects launched
- Projects completed
- Projects stalled

### Meetings & People

Scan `00-Inbox/Meetings/` for quarter date range:
- Total meetings held
- Key discussions and decisions
- New relationships formed

### Weekly Syntheses

Look for `00-Inbox/Weekly_Synthesis_*.md` files in quarter:
- Extract recurring themes
- Compile learnings
- Note energy patterns

---

## Step 2.5: Semantic Context Enrichment (if QMD available)

**Check if semantic search is available** by looking for `qmd` in PATH.

If available, enhance the quarterly review with meaning-based analysis:

1. **Link lessons to goals:** For each major learning captured this quarter, search:
   ```
   qmd query "learning description" --limit 3
   ```
   against `01-Quarter_Goals/Quarter_Goals.md`. Discover which goals a learning actually impacted, even without explicit tags.
   - Evidence template: `[learning text from source]` may match `[goal text from the authoritative goal file]`. Label the match `Inferred`, retain `[source ID]`, `[source date]`, `[as-of date]`, and the query result, and do not claim impact from similarity alone.

2. **Detect hidden goal progress:** For each quarterly goal, search across all meeting notes and tasks:
   ```
   qmd query "goal success criteria" --limit 5
   ```
   Find work that advanced the goal but wasn't explicitly linked.
   - Evidence template: `[goal text from source]` has `[observed result references]` returned by QMD. Cite each result ID/date, deduplicate it, and keep contribution `Unknown` until the underlying source proves that it advanced the goal.

3. **Cross-goal connections:** Search for themes that span multiple goals:
   ```
   qmd query "recurring theme from the quarter" --limit 5
   ```
   Surface a candidate such as `[theme inferred from cited query results]` across
   `[goal IDs returned by the search]`; label it `Inferred` and retain the same
   source/date/as-of provenance before asking the user whether it is meaningful.

**Integration:** Add a "Semantic Discoveries" subsection under each goal assessment showing work that contributed but wasn't explicitly tracked. Also add a "Cross-Goal Themes" section to the quarterly review output.

**If QMD unavailable:** Record semantic enrichment as `Unknown — source unavailable`
and state its coverage impact. Goal assessment may continue from explicit data,
but must not claim that hidden progress or cross-goal links were comprehensively checked.

---

## Step 3: Goal Assessment

For each goal from `01-Quarter_Goals/Quarter_Goals.md`:

**Evaluate:**
- ✅ **Completed:** Fully achieved
- 🔄 **Partial:** Made significant progress but not done
- ❌ **Not Started:** Didn't get to it
- 🚫 **Deprioritized:** Intentionally stopped

For each, capture:
- What was accomplished
- What blocked progress (if incomplete)
- Key learnings

---

## Step 4: Interactive Review

**Goal-by-goal walkthrough:**

> "Goal 1: [Goal title]
> 
> Progress indicator reported: [value, source, source date, and as-of time] (omit this line when unavailable; never calculate it)
> Milestones: [Y of Z completed]
> 
> How would you assess this goal?
> - ✅ Completed
> - 🔄 Partial (describe what is done and what remains; do not infer a percentage)
> - ❌ Didn't get to it
> - 🚫 Deprioritized"

Wait for user response, then:

> "What happened with this goal? (Key wins, blockers, learnings)"

Capture narrative for each goal.

**Overall quarter reflection:**

> "Stepping back, how did this quarter go?
> 
> - What were your biggest wins?
> - What drained energy or didn't work?
> - What would you do differently?
> - What surprised you?"

---

## Step 5: Pillar Balance Review

Read `System/pillars.yaml` and assess:

> "Pillar balance this quarter:
> - [Pillar 1]: [Goals + activity level]
> - [Pillar 2]: [Goals + activity level]
> - [Pillar 3]: [Goals + activity level]
> 
> Any pillar that needs more attention next quarter?"

After presenting the balance, prompt:

> "Do your strategic pillars still reflect your focus? If your role or priorities have shifted significantly this quarter, now is a good time to update them before planning next quarter. Just tell me 'I need to reconfigure my strategic pillars' and I'll walk you through it."

---

## Step 5.5: System Health & Backlog Review

Review the Dex system itself and improvement backlog.

### Check Dex Backlog

Read `System/Dex_Backlog.md` if it exists:

**Extract:**
- Total ideas in backlog
- Ideas matching the configured priority policy, when a policy source and policy date exist
- Ideas captured during this quarter
- Ideas marked as implemented

**Present to user:**

> "**Dex System Improvement Backlog:**
> 
> - Total ideas captured: [count]
> - Policy-matched priority ideas: [count, configured policy source, policy date; otherwise Unknown]
> - Implemented this quarter: [count]
> 
> Looking at your Dex backlog:
> - Any 1-2 high-impact improvements to prioritize next quarter?
> - Any ideas that meet your configured, dated staleness policy to review? If no policy exists, which review rule would you like to use?"

Wait for user input on:
- Which 1-2 ideas to tackle next quarter
- Any ideas to archive or refine

### Suggest Backlog Review

**If the configured, dated policy identifies more priority items than the user
wants to inspect here:**

> "💡 Consider running `/dex-backlog` soon to re-rank ideas based on updated system state."

**If no Dex_Backlog.md exists:**
- In review document, note: "Dex backlog system not yet in use"

---

## Step 6: Generate Quarterly Review

Create `07-Archives/Reviews/[Quarter].md`:

Before creating or updating the archive, preview the exact destination and
complete bytes. If that destination already contains the same review, report it
as already archived and do not write again. If it contains different bytes,
preserve the existing file and stop for a user decision; do not overwrite, merge,
or create a duplicate path silently.

```markdown
---
quarter: Q1 2026
start_date: 2026-01-01
end_date: 2026-03-31
reviewed_on: [date]
---

# Q1 2026 Quarterly Review

**Jan 1 - Mar 31, 2026**

---

## TL;DR

- **Goals:** [count of each reviewed status, sourced from the goal records and user answers]
- **Key win:** [Biggest accomplishment]
- **Key learning:** [Most important insight]
- **Pillar balance:** [Assessment]

---

## Goal Completion

### Goal 1: [Goal Title] — **[Pillar]**

**Status:** ✅ Completed / 🔄 Partial / ❌ Not Started / 🚫 Deprioritized

**Original success criteria:**
[What was defined in 01-Quarter_Goals/Quarter_Goals.md]

**What happened:**
[Narrative from user + gathered context]

**Key wins:**
- [Specific accomplishment]

**Blockers/Challenges:**
- [What got in the way]

**Learnings:**
- [What was learned]

---

### Goal 2: [Goal Title] — **[Pillar]**

[Same structure]

---

### Goal 3: [Goal Title] — **[Pillar]**

[Same structure]

---

## Quarter Highlights

### Major Accomplishments
- [Project/initiative completed]
- [Milestone reached]
- [Key decision made]

### Projects Shipped
- [Project 1] — [Brief description]
- [Project 2] — [Brief description]

### New Relationships
- [Person] at [Company] — [Context]

### Key Meetings/Decisions
- [Date]: [Meeting/decision] — [Impact]

---

## What Didn't Work

### Incomplete Goals
- [Goal] — [Why it didn't happen]

### Stalled Projects
- [Project] — [What blocked it]

### Time Drains
- [Activity that consumed time without value]

---

## Learnings & Insights

### Process Learnings
- [What worked well]
- [What to change]

### Personal Insights
- [Self-awareness gained]

### System Improvements
- [Dex system improvements identified]

---

## System Health & Improvement Backlog

### Dex Backlog Activity
- **Ideas captured:** [Count during quarter]
- **Ideas implemented:** [Count marked as completed]
- **Current policy-matched priority ideas:** [Count, policy source, policy date; otherwise Unknown]

### Improvements Implemented This Quarter
- **[idea-XXX]** [Title] — [Brief description of what was built]
- **[idea-YYY]** [Title] — [Impact it had]

### Next Quarter Priorities
Based on backlog review, prioritize these improvements:
1. [Idea to tackle] — [Why now]
2. [Idea to tackle] — [Why now]

*Run `/dex-backlog` for full ranked list*

---

## Pillar Assessment

| Pillar | Goals | Activity | Assessment |
|--------|-------|----------|------------|
| [Pillar 1] | [X goals] | [High/Med/Low] | [Balanced / Over-indexed / Neglected] |
| [Pillar 2] | [Y goals] | [High/Med/Low] | [Assessment] |
| [Pillar 3] | [Z goals] | [High/Med/Low] | [Assessment] |

**Next quarter adjustment:**
[Which pillar needs more/less focus]

---

## Stats

- **Weeks in quarter:** [Count, with source and as-of date]
- **Meetings held:** [Count, with source and as-of date]
- **Tasks completed:** [Count, with source and as-of date]
- **Projects shipped:** [Count, with source and as-of date]
- **Weekly syntheses:** [Count completed, with source and as-of date]

---

## Next Quarter Suggestions

Based on this quarter's learnings:

### Carry Forward
- [ ] [Incomplete goal to continue]
- [ ] [Unfinished initiative]

### New Opportunities
- [Area to explore next quarter]
- [Project idea that emerged]

### Focus Areas
1. [Suggested priority 1]
2. [Suggested priority 2]
3. [Suggested priority 3]

### Process Changes
- [Adjustment to workflow]
- [System improvement to implement]

---

## Unknowns and contradictions

List every material unknown, unavailable source, stale result, and contradiction
that affected the review. Include the source identifier or path, source date, and
review `as-of` date/time. Do not convert an unknown into zero, a missing source
into a negative result, or a contradiction into a single invented value.

---

## Energy Assessment

<details>
<summary>Click to expand</summary>

### What Gave Energy
- [Activities/projects that were energizing]

### What Drained Energy
- [Activities that felt like a slog]

### Adjustment for Next Quarter
- [More of X, less of Y]

</details>

---

*Generated: [timestamp]*
*Command: /quarter-review*
```

---

## Step 7: Next Quarter Planning Prompt

After review is complete:

> "Quarter reviewed and verified at `07-Archives/Reviews/Q1-2026.md`
> 
> **Ready to plan next quarter (Q2 2026)?**
> 
> I have suggestions based on what you learned this quarter.
> 
> [Yes, let's plan Q2] [No, I'll do it later]"

**If yes:** Flow directly into `/quarter-plan next`

---

## Follow-up Actions

After review:
1. Propose archiving old `01-Quarter_Goals/Quarter_Goals.md` if not already done;
   do not assume the review confirmation authorizes this separate mutation
2. Propose updating `System/user-profile.yaml` with the completed quarter only
   after a separate preview and consent
3. Suggest running `/quarter-plan` for next quarter

---

## Integration Points

**Called at end of quarter:**
- Natural time: Last week of quarter
- Can run anytime after quarter ends

**Feeds into `/quarter-plan`:**
- Next quarter planning reads this review
- Suggestions inform new goals

**References:**
- `01-Quarter_Goals/Quarter_Goals.md` — Original plan
- Weekly syntheses — Week-by-week activity
- Task completions — Actual work done
- Meeting notes — Context gathered

---

## Graceful Degradation

### Missing Goals File
- Can still review based on tasks, projects, meetings
- Notes that no formal goals were set

### First Quarter
- No previous quarter to compare to
- Focus on establishing baseline

### Incomplete Data
- Works with whatever data is available
- Prompts user to fill in gaps

---

## Evidence, authority, and recovery

- Source every statistic: record the source path, tool query, or user answer, its
  source date, and the review or retrieval `as-of` date/time. If a source or date
  is absent, write `unknown`; if sources contradict, expose both versions and ask
  the user how to proceed. Never invent counts, dates, outcomes, or explanations.
- Never infer completion percentages. Use explicit status words from the goal
  record or the user's answer; do not calculate a percentage from milestones,
  elapsed time, task counts, or a status label. If the user supplies a percentage,
  label it as a user-supplied estimate with its source and as-of time. Keep the
  archive idempotent and never infer a completion percentage just to fill a
  template or analytics field.
- Make the archive operation idempotent: if the canonical review already exists
  with the same bytes, report it and perform no write; on any conflict, preserve
  existing bytes and stop. Do not overwrite, merge, duplicate, or rename around a
  conflict without a new explicit choice.
- Before each mutation, show an exact preview of every destination and new bytes
  or patch. Obtain separate consent for each mutation—task creation, Reminder
  completion, meeting processing, review archive, profile update, usage-log
  update, and analytics action—from the human user. Recommendations are not human
  decisions or authority, and consent for the review does not authorize follow-up
  writes.
- After every confirmed mutation, read back the affected file, record, or tool
  result and compare it with the preview. If any write, archive, tool call, or
  read back fails, surface the exact failure, preserve existing bytes, and do not
  claim completion. List partial confirmed changes and offer a fresh preview to
  resume; retry only after explicit human confirmation.

---

## Track Usage (Silent)

"Silent" does not bypass the mutation boundary: include the exact
`System/usage_log.md` patch in the preview, honor analytics opt-in, obtain human
confirmation, read it back, and surface any failure before claiming it was updated.

**Analytics (Silent):**

Call `track_event` with event_name `quarter_review_completed` and properties:
- goals_assessed
- completion_status_summary (statuses only; never an inferred completion percentage)

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
