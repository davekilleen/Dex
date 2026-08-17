---
name: quarter-plan
description: Set 3-5 strategic goals for the quarter
---

## Purpose

Set 3-5 strategic goals for the quarter. Runs at the start of each quarter (or mid-quarter if starting fresh).

## Usage

- `/quarter-plan` — Plan current or upcoming quarter
- `/quarter-plan next` — Plan next quarter (run in last week of current quarter)

---

## Method

Verify the Quarter Goals room, fiscal start-month source, and target-quarter
boundaries before gathering context. Build a dated ledger from pillars, prior
goals, current commitments, and user input; preserve conflicts and keep missing
capacity or outcomes unknown. Help the user choose three to five goals without
turning suggestions into decisions. Define each goal's source-backed outcome,
milestones, owner, and review signal. Preview configuration, archive, and goal
mutations independently, preserve existing bytes on conflict, obtain explicit
confirmation for each operation, and read back every confirmed destination.

## Output contract

Return room readiness, fiscal-quarter calculation with source and `as-of` time,
context coverage, unresolved carry-over items, and the user's chosen goals with
pillars, success criteria, milestones, owners, and unknowns. Do not invent
capacity, dates, percentages, or alignment. End with a per-operation mutation
ledger covering profile configuration, any archive, and the active goals file.
Only read-back-matched paths may be labelled verified; conflicts, declined writes,
and partial failures remain explicit and must not be summarized as a completed
quarter plan.

## Step 0: Confirm the Quarter Goals room is enabled

Read `System/user-profile.yaml`:

1. Check `capabilities.quarter_goals.enabled`; only when that key is absent, honor legacy `quarterly_planning.enabled`.
2. **If disabled:** Explain that the room can be enabled with `/manage-capabilities`, then end.
3. **If enabled:** Continue to Step 0.5 when fiscal-quarter setup is still needed; otherwise continue to Step 1.

---

## Step 0.5: Quarterly Planning Onboarding (First Time)

> "Quarterly planning helps you set 3-5 big goals every 3 months. Your weekly plans will then tie back to these goals.
> 
> **When does your Q1 start?**
> 1. January (calendar year)
> 2. February  
> 3. April (common fiscal year)
> 4. Other month
> 5. I don't want quarterly planning"

**Interpret the response:** Treat the selected month as the first month of the
configured fiscal year, not as a calendar-quarter preference.

- **Before saving:** preview the exact `System/user-profile.yaml` bytes or patch,
  obtain explicit confirmation from the human user, then write and read back the
  configuration.

**Capture response:**
- If 1-4: propose saving the month to config after the preview and confirmation
- If 5: preview setting `enabled: false`, obtain confirmation, then apply it and end

**Calculate quarter dates using fiscal-quarter boundaries:**
```
If Q1 starts in January:
  Q1: Jan-Mar, Q2: Apr-Jun, Q3: Jul-Sep, Q4: Oct-Dec
  
If Q1 starts in February:
  Q1: Feb-Apr, Q2: May-Jul, Q3: Aug-Oct, Q4: Nov-Jan
  
If Q1 starts in April:
  Q1: Apr-Jun, Q2: Jul-Sep, Q3: Oct-Dec, Q4: Jan-Mar

For any configured start month, each fiscal quarter is exactly three calendar
months starting on the first day of its first month and ending on the last day of
its third month. Handle year rollover explicitly (for example, a November Q1
ends in January of the following year). Show the resulting start and end dates
and the calculation `as-of` date; do not silently substitute calendar quarters.
```

**Proposed config for `System/user-profile.yaml` (write only after preview and confirmation):**
```yaml
quarterly_planning:
  enabled: true
  q1_start_month: 1  # 1=Jan, 2=Feb, 4=Apr, etc
  prompted: true
```

---

## Step 1: Determine Target Quarter

**Calculate current quarter** based on `q1_start_month`:
- Example: If q1_start_month=1 and today is Jan 28:
  - Current quarter: Q1 2026
  - Quarter dates: 2026-01-01 to 2026-03-31

**If no parameter or "current":**
- Plan current quarter

**If parameter is "next":**
- Plan next quarter (for end-of-quarter planning)

Store:
- `target_quarter`: "Q1 2026"
- `quarter_start`: "2026-01-01"
- `quarter_end`: "2026-03-31"

Confirm that the stored dates follow the configured fiscal-quarter boundaries
before using them in prompts, archive names, or MCP payloads.

---

## Step 2: Context Gathering

### Check for Last Quarter's Review

Look for `07-Archives/Reviews/[last-quarter].md`:

**If exists, extract:**
- Completed goals
- Incomplete goals
- "Next Quarter Suggestions" section
- Key learnings

**If missing:**
- Note: No previous quarter review found
- This is likely first time using quarterly planning

### Check Current Quarter Goals (if mid-quarter update)

If `01-Quarter_Goals/Quarter_Goals.md` exists with current quarter:
- Read current goals
- Note progress made
- Ask if updating or replacing

### Check Pillars

Read `System/pillars.yaml`:
- Strategic pillars
- Check recent activity across pillars
- Identify any neglected areas

### Scan Recent Projects

Look at `04-Projects/` for active initiatives:
- What's in flight?
- What needs to land this quarter?
- Any new initiatives starting?

### Check Career Goals (if Career system enabled)

Look for `05-Areas/Career/Growth_Goals.md`:

**If exists, extract:**
- Long-term vision (1-3 years)
- Target role/level
- Development focus areas (skills to develop)
- Impact goals
- Career milestones

**If missing:**
- Skip this section (career system not initialized)

---

## Step 3: Interactive Goal Setting

### Review Last Quarter (if available)

> "Last quarter ([quarter from canonical source]) goals were:
> 1. [Goal from source] — [observed status; source ID: [source ID]; source date: [source date]; as-of: [as-of date]]
> 2. [Goal from source] — [observed status or Unknown, with the same provenance fields]
> 3. [Goal from source] — [observed status or Unknown, with the same provenance fields]
> 
> Anything to carry forward into this quarter?"

Wait for user input.

### Present Context

> "Looking at [Quarter] [Year] ([Start Date] - [End Date]):
> 
> **Active projects:**
> - [Project 1]
> - [Project 2]
> 
> **Pillars to consider:**
> - [Pillar 1]: [Recent activity level]
> - [Pillar 2]: [Recent activity level]
> - [Pillar 3]: [Recent activity level]

**If career goals exist, add:**

> **Your career direction (1-3 years):**
> - Target role: [Role/Level from Growth_Goals.md]
> - Skills to develop: [Key development areas]
> - Impact you want: [Impact goals]
> 
> Keep these in mind as we plan this quarter — your quarterly goals should advance your career goals.

**Then continue:**

> **Let's work backwards from impact:**
> 
> Imagine it's [Quarter End Date] and you're looking back on this quarter feeling incredibly happy with what you accomplished.
> 
> - What outcomes would accelerate your career and impact in your current role?
> - What would you be proud to have delivered?
> - What would matter most to the people you serve?
> 
> What are the 3-5 most important outcomes you want this quarter?"

### Guide Goal Definition

For each goal (aim for 3-5):

> "Goal [N]: What's the outcome?"

Then follow up:
- "Which pillar does this support?"
- "How will you measure success?"
- "What does 'done' look like?"
- "Any key milestones along the way?"

**If career goals exist, also ask:**
- "Does this goal help develop any skills you're targeting? (e.g., [skill1], [skill2] from your career plan)"
- "Does this advance your path to [target role]? How?"

**Note responses for Phase 2 metadata.**

### Pillar Balance Check

After goals defined:

> "Here's how your Q1 goals map to pillars:
> - [Pillar 1]: [X] goals
> - [Pillar 2]: [Y] goals  
> - [Pillar 3]: [Z] goals
> 
> Does this feel like the right balance?"

Allow adjustment.

---

## Step 4: Archive Old Quarter Goals

**If `01-Quarter_Goals/Quarter_Goals.md` exists:**
1. Determine the quarter it represents
2. Preview the exact source bytes and destination
   `07-Archives/Reviews/[old-quarter]-goals.md`, then obtain explicit human
   confirmation before moving it
3. Note: This preserves what was PLANNED vs what ACTUALLY happened (from review)

If the archive destination already exists, stop on the conflict and preserve the
existing bytes; do not overwrite, merge, or delete either version without a new
user decision and preview.

---

## Step 5: Generate Quarter Goals

Use the `create_quarterly_goal` MCP tool for each goal collected in Step 3.

Before every mutation, preview every mutation: the exact MCP payload, target
quarter, destination path(s), and any archive or goal-file bytes that will change.
Obtain explicit confirmation from the human user before each call or an explicitly
enumerated batch. A recommendation about a goal is not a human decision or
authority to create it.

**For each goal, call the tool with:**
- `title`: Goal title
- `pillar`: Pillar ID
- `success_criteria`: What done looks like
- `milestones`: Array of milestone objects
- `quarter`: Quarter string (e.g., "Q1 2026")

**If career goals exist, also include:**
- `career_goal_id`: Which career goal this advances (from Growth_Goals.md)
- `skills_developed`: Array of skills this goal develops (e.g., ["System Design", "Technical Leadership"])
- `impact_level`: "high" (promotion evidence), "medium" (solid contribution), or "low" (tactical)

**The MCP tool will generate markdown like:**

```markdown
---
quarter: Q1 2026
start_date: 2026-01-01
end_date: 2026-03-31
created: [timestamp]
---

# Q1 2026 Goals

**Jan 1 - Mar 31, 2026**

---

## 🎯 Quarter Objectives

### 1. [Goal 1 Title] — **[Pillar]**

**What success looks like:**
[Specific, measurable outcome]

**Key milestones:**
- [ ] [Milestone 1] — By [rough timing]
- [ ] [Milestone 2] — By [rough timing]

**Progress:** 0% 🔴

---

### 2. [Goal 2 Title] — **[Pillar]**

**What success looks like:**
[Specific, measurable outcome]

**Key milestones:**
- [ ] [Milestone 1]
- [ ] [Milestone 2]

**Progress:** 0% 🔴

---

### 3. [Goal 3 Title] — **[Pillar]**

**What success looks like:**
[Specific, measurable outcome]

**Key milestones:**
- [ ] [Milestone 1]
- [ ] [Milestone 2]

**Progress:** 0% 🔴

---

[Repeat for goals 4-5 if applicable]

---

## 📊 Pillar Alignment

| Pillar | Goals | Balance |
|--------|-------|---------|
| [Pillar 1] | [Goal numbers] | [# of goals] |
| [Pillar 2] | [Goal numbers] | [# of goals] |
| [Pillar 3] | [Goal numbers] | [# of goals] |

---

## 🔄 Carried From Last Quarter

[Items from Q4 2025 that are continuing]

- [ ] [Item] — [Context]

---

## 📝 Notes & Context

[Any additional context about the quarter]

---

## 🏁 End of Quarter

*Fill this in when running `/quarter-review`*

### Completed
- 

### Incomplete
- 

### Key Wins
- 

### Learnings
- 

---

*Generated: [timestamp]*
*Command: /quarter-plan*
```

---

## Step 6: Summary & Next Steps

Display summary:

> "Q1 2026 goals set and verified in `01-Quarter_Goals/Quarter_Goals.md`
> 
> **Your focus this quarter:**
> 1. [Goal 1]
> 2. [Goal 2]
> 3. [Goal 3]
> 
> **Pillar balance:** [Note any imbalances]
> 
> **Next steps:**
> - These goals will appear in your weekly planning
> - Update progress notes as you make progress
> - Run `/quarter-review` at end of quarter (Mar 31)
> 
> Ready to plan this week? Run `/week-plan`"

---

## Integration Points

**Called by `/week-plan`:**
- Weekly planning reads from `01-Quarter_Goals/Quarter_Goals.md`
- Prompts user to connect weekly priorities to quarterly goals

**Updated manually:**
- User can update progress percentages
- Check off milestones as they complete

**Reviewed by `/quarter-review`:**
- End of quarter review references these goals
- Compares plan vs actual accomplishment

---

## Graceful Degradation

### First Quarter
- No previous quarter to reference
- Start fresh with current context

### Mid-Quarter Start
- Can run anytime
- Adjust goals for remaining time in quarter
- Note when goals were set

### Disabled State
- Command prompts to enable
- Can enable at any time
- Doesn't affect weekly/daily planning

---

## Evidence, authority, and recovery

- For the configured quarter, record the source of the fiscal setting, the source
  date, and the calculation `as-of` date/time. For every goal, pillar, success
  criterion, and milestone, preserve the source path or user statement and its
  date. If a value is absent, label it `unknown`; if sources contradict, show the
  contradiction and ask the user which value to use. Never invent goals, dates,
  metrics, owners, or completion facts.
- Preview every mutation: configuration changes, archive moves, MCP goal creation,
  generated goal files, usage-log updates, and analytics actions. Show exact paths,
  payloads, and new bytes, then obtain explicit confirmation from the human user;
  recommendations are not human decisions.
- On conflict, preserve existing bytes. If a source, destination, MCP record, or
  expected quarter differs from the preview, stop without overwriting or silently
  reconciling it and ask for a new choice.
- After each confirmed mutation, read back the affected configuration, archive,
  MCP record, and goal file and compare it with the confirmed result before saying
  it was saved. If a write, tool call, or read back fails, surface the exact
  failure, preserve existing bytes, and do not claim completion. List any partial
  results and offer a fresh preview to resume; retry only after explicit human
  confirmation.

---

## Track Usage (Silent)

"Silent" does not bypass the mutation boundary: include the exact
`System/usage_log.md` patch in the preview, honor analytics opt-in, obtain human
confirmation, read it back, and surface any failure before claiming it was updated.

**Analytics (Silent):**

Call `track_event` with event_name `quarter_plan_completed` and properties:
- `goals_count`: number of goals set
- `pillars_covered`: number of pillars with goals

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
