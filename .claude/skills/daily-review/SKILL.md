---
name: daily-review
description: End of day review with learning capture, daily plan completion tracking, and meeting follow-up surfacing.
context: fork
---

## Purpose

Conduct an end-of-day review to capture progress, track what you actually accomplished vs. planned, surface meeting follow-ups, and set up tomorrow.

## Tone Calibration

Read `System/user-profile.yaml` → `communication` section and adapt accordingly.

---

## Step 0: Demo Mode Check

Check `System/user-profile.yaml` for `demo_mode`. If true, use demo paths.

---

## Step 1: File Discovery

Find files modified TODAY:

```bash
TODAY=$(date +%Y-%m-%d)
find . -type f -name "*.md" -newermt "$TODAY 00:00:00" ! -newermt "$TODAY 23:59:59" 2>/dev/null
```

**Critical rules:**
1. No truncation — list all modified files
2. Today only — use date-based filtering
3. Verify with user — "These are the files I found. What did you actually work on?"

---

## Step 1.5: Process Today's Meetings

Before gathering context, ensure today's meetings are in the vault by running `/process-meetings today`. This pulls any unprocessed meetings from Otter.ai, creates meeting notes, updates person/company pages, and extracts tasks — so the rest of the review has complete data.

- If no new meetings are found, continue silently
- If meetings are processed, note the count for the review summary
- Do NOT ask for a skill rating after this sub-step — save that for the end of the full review

---

## Step 2: Gather Context

### From 03-Tasks/Tasks.md
- Tasks completed today (look for `✅ YYYY-MM-DD` matching today)
- Tasks started but not finished

### From Weekly Priorities
Read `02-Week_Priorities/Week_Priorities.md` for:
- This week's strategic focus
- How today's work connects to weekly priorities

### From Recent Meetings
Check `00-Inbox/Meetings/` for meeting notes from today (should now include anything just pulled from Otter.ai).

### From ScreenPipe (If Running)

**Check if ScreenPipe is available:**
```bash
curl -s http://localhost:3030/health | jq -r '.status' 2>/dev/null
```

If ScreenPipe is running, gather automatic activity context:

1. **Time Audit** — Query app usage for today:
   ```
   Use: screenpipe_time_audit(start_time="YYYY-MM-DDT09:00:00", end_time="YYYY-MM-DDT18:00:00")
   ```

2. **Activity Summary** — Get narrative of what happened:
   ```
   Use: screenpipe_summarize(start_time="YYYY-MM-DDT09:00:00", end_time="YYYY-MM-DDT18:00:00")
   ```

3. **Surface to User:**
   > "📺 **Screen Activity Summary** (auto-captured):
   > 
   > **Time breakdown:**
   > - VS Code: 3.2 hours (41%)
   > - Slack: 1.5 hours (19%)
   > - Chrome: 2.1 hours (27%)
   > - Zoom: 1.0 hour (13%)
   > 
   > **Activity narrative:**
   > [Generated summary of the day]
   > 
   > **Context switches:** 34 (moderate)
   > **Longest focus session:** 48 minutes
   > 
   > Does this match your sense of the day?"

This provides ground truth for what actually happened vs. what was remembered.

### Commitment Scan (If ScreenPipe Beta Activated & Enabled & Running)

**First, check beta activation:**
```
Use: check_beta_enabled(feature="screenpipe")
```

If beta NOT activated, skip this section entirely.

**Then check if user has opted in:**

Read `System/user-profile.yaml` → `screenpipe.enabled`. If false, skip this section entirely.

**If beta activated AND enabled**, scan for uncommitted asks and promises:

```
Use: scan_for_commitments(
    start_time="YYYY-MM-DDT09:00:00",
    end_time="YYYY-MM-DDT18:00:00",
    apps=["Slack", "Gmail", "Teams", "Notion"]
)
```

Then get pending items:
```
Use: get_uncommitted_items(include_dismissed=false)
```

**Surface to user if items found:**

> "🔔 **Uncommitted Items Detected**
>
> ScreenPipe noticed these potential commitments today that don't have matching tasks:
>
> ### Inbound Asks
>
> **1. Sarah Chen** (Slack, 2:34 PM)
> > "Can you review the pricing proposal by Friday?"
>
> 📎 Matches: **Q1 Pricing Project**
> ⏰ Deadline: Friday
>
> → [Create task] [Already handled] [Ignore]
>
> ### Outbound Promises
>
> **2. You → Tom Baker** (Slack, 4:20 PM)
> > "I'll send over the competitive analysis tomorrow"
>
> 📎 Matches: **Acme Deal**
> ⏰ Deadline: Tomorrow
>
> → [Create task] [Already handled] [Ignore]
>
> *2 potential commitments detected. 0 have matching tasks.*"

For each item the user wants to create as a task:
```
Use: process_commitment(commitment_id="comm-XXXXXX-XXX", action="create_task")
Use: create_task(title="...", priority="P2", pillar="...", context="From Slack commitment")
```

For dismissals:
```
Use: process_commitment(commitment_id="comm-XXXXXX-XXX", action="dismiss")
```

---

## Step 2.5: Semantic Context Enrichment (if QMD available)

**Check if semantic search is available** by looking for `qmd` in PATH. If available, use it to map today's work to priorities and goals more intelligently.

### What to search:

1. **Map completed tasks to goals:** For each task completed today, search semantically:
   ```
   qmd query "task description here" --limit 3
   ```
   Look for connections to quarterly goals or weekly priorities that keyword matching would miss. Example: completing "finalize stakeholder deck" might connect to a goal about "executive engagement strategy" — same concept, different words.

2. **Enrich meeting follow-ups:** For each meeting today, search for related past discussions:
   ```
   qmd query "meeting topic" --limit 5
   ```
   Surface any commitments, decisions, or context from previous meetings on the same theme.

3. **Priority alignment check:** For each weekly priority, search for today's work that advanced it:
   ```
   qmd query "priority title/description" --limit 5
   ```
   Catch work that moved the needle but wasn't explicitly tagged to the priority.

### How to use results:

- **Only surface genuinely new connections** — if a task was already linked to a goal, don't repeat it
- Merge insights into the Plan vs. Reality section: "Task X also advanced Goal Y (semantic match)"
- Add to the Weekly Priorities Progress section if semantic search reveals hidden progress
- If QMD is not available, skip this step silently — the review works fine without it

---

## Step 2.6: Reminders Completion Sync (Dex Today → Dex)

Check if tasks were completed on phone since the morning plan:

```
Use: reminders_list_completed(list_name="Dex Today")
```

For each completed item:
- Match to a Dex task by title
- Update task status via Work MCP: `update_task_status(task_title="...", status="d")`
- Surface what was synced:

> "📱 **Synced from phone:**
> - ✅ "Follow up with Hero Coders" — marked done in Dex"

Also check for tasks completed in Dex today that still have active Reminders:

```
# For each task completed today in Dex, check if a matching Reminder exists
Use: reminders_find_and_complete(list_name="Dex Today", title_query="task title")
```

Clean up completed items:
```
Use: reminders_clear_completed(list_name="Dex Today")
```

**If nothing to sync:** Skip silently.

---

## Step 3: Daily Plan Completion Tracking (NEW)

**Compare what you planned vs. what you did.**

### 3.1 Find Today's Plan

Look for `07-Archives/Plans/YYYY-MM-DD.md` (today's date).

### 3.2 Extract Planned Focus

From the "Today's Focus" section, extract the 3 items you planned to focus on.

### 3.3 Track Completion

For each planned focus item:
- Check if it was completed (look in Tasks.md for completion timestamps)
- Check if it was started but not finished
- Check if it was blocked or deferred

**Surface this:**

> "📊 **Daily Plan Completion:**
> 
> You planned 3 focus items this morning:
> 
> 1. ✅ **Prep for Acme meeting** — Complete
> 2. 🔄 **Write pricing proposal** — In progress (about 60% done)
> 3. ❌ **Reply to Mike** — Didn't get to it
> 
> **Completion rate today:** 1 of 3 (33%)
> 
> What happened with #3? Should it carry to tomorrow?"

### 3.4 Track Over Time (Optional)

If tracking completion rates:
- Update `System/metrics/daily-completion.md` with today's rate
- Surface patterns: "Your average completion rate this week is 67%"

---

## Step 4: Meeting Follow-Up Surfacing (NEW)

**For each meeting you had today, surface follow-ups.**

### 4.1 Identify Today's Meetings

From calendar or meeting notes, list meetings that happened today.

### 4.2 For Each Meeting, Ask:

```
Use: get_meeting_context(meeting_title="...", attendees=[...])
```

Then prompt:

> "📍 **You met with Sarah Chen today** (Acme Quarterly Review)
> 
> **Any follow-ups to capture?**
> - Action items you committed to?
> - Things they owe you?
> - Decisions that need documentation?
> 
> (Type your follow-ups or 'none')"

### 4.3 Create Follow-Up Tasks

For any follow-ups mentioned:
- Add to Tasks.md with appropriate priority
- Link to the person page
- Add due date if mentioned

---

## Step 5: Progress Assessment

With user-verified information:
- What was accomplished?
- What progress was made against weekly priorities?
- What got stuck or blocked?
- What unexpected things came up?

---

## Step 6: Week Progress Check (Midweek Context)

```
Use: get_week_progress()
```

Show how today's work moved weekly priorities:

> "**Week Progress Update:**
> 
> After today, you're at:
> - Priority 1: ✅ Complete (finished today!)
> - Priority 2: 🔄 60% (moved from 40%)
> - Priority 3: ⚠️ Still not started
> 
> You have 2 days left. Tomorrow should focus on Priority 3."

---

## Step 7: Auto-Extract Session Learnings

Scan today's conversation for learnings:

1. **Mistakes or corrections** — Did something not work as expected?
2. **Preferences mentioned** — Did you express how you like to work?
3. **Documentation gaps** — Were there questions about how the system works?
4. **Workflow inefficiencies** — Did any task take longer than it should?

Write to `System/Session_Learnings/YYYY-MM-DD.md`.

Then ask: "I captured [N] learnings from today's session. Anything else you'd like to add?"

---

## Step 8: Categorize Learnings (If Applicable)

Check if any learnings should be elevated to pattern files:
- **Recurring mistakes** → `06-Resources/Learnings/Mistake_Patterns.md`
- **Workflow preferences** → `06-Resources/Learnings/Working_Preferences.md`

Get user confirmation before adding.

---

## Step 9: Tomorrow's Setup

Based on:
- Incomplete items from today
- Weekly priorities (especially lagging ones)
- Commitments due tomorrow
- Tomorrow's calendar shape

Suggest 3 focus items for tomorrow:

> "**Suggested focus for tomorrow (Thursday):**
> 
> 1. **Priority 3** — It's been untouched all week and you have 2 days left
> 2. **Finish pricing proposal** — 40% left, should be quick to complete
> 3. **Reply to Mike** — Carried from today
> 
> Tomorrow's shape: Moderate (4 meetings). You have a 2-hour block in the afternoon.
> 
> Does this feel right?"

---

## Step 9.5: Retrospective Insight (Innovation Concierge)

At the end of the review, check if there's a relevant backlog idea to surface:

1. Call `list_ideas(status="active", min_score=70)` from Improvements MCP
2. Look for ideas that connect to today's work or learnings:
   - Did the user work on tasks related to a backlog idea?
   - Did learnings captured today strengthen an existing idea?
   - Is there a "Why Now?" idea with fresh evidence?
3. If a relevant match exists, surface it briefly:

> **Retrospective Insight:** Today's meeting processing struggles connect to idea-027 (RAG-Powered Vault Search) — semantic search could make finding meeting context much faster. Worth exploring? Run `/dex-improve idea-027`.

**Rules:**
- Show at most 1 insight per review
- Only show if genuinely connected to today's work (not random)
- Frame as retrospective — "based on what you just did, here's what could help"
- If no connection, skip entirely
- Keep it to 1-2 lines max

---

## Step 10: Track Usage (Silent)

Update `System/usage_log.md` to mark daily review as used.

**Analytics (Silent):**

Call `track_event` with event_name `daily_review_completed` and properties:
- `wins_count`
- `learnings_count`

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".

---

## Step 11: Evening Journal (If Enabled)

If `journaling.evening: true`, prompt for evening reflection.

---

## Output Format

Create `07-Archives/Reviews/Daily_Review_YYYY-MM-DD.md`:

```markdown
---
date: YYYY-MM-DD
type: daily-review
plan_completion_rate: X%
---

# Daily Review — [Day], [Month] [DD], [YYYY]

## 📊 Plan vs. Reality

**Planned focus:**
1. [x] [Planned item 1] — ✅ Complete
2. [ ] [Planned item 2] — 🔄 In progress (X%)
3. [ ] [Planned item 3] — ❌ Didn't start

**Completion rate:** X of 3 (X%)

**What happened:** [Brief explanation of deviations]

---

## ✅ Accomplished

- ✓ [Completed item 1]
- ✓ [Completed item 2]

---

## 🔄 Progress Made

| Area | Movement |
|------|----------|
| [Priority 1] | [What moved forward] |
| [Priority 2] | [What moved forward] |

---

## 📊 Weekly Priorities Progress

After today:
- **Priority 1:** [Status/progress] — [emoji]
- **Priority 2:** [Status/progress] — [emoji]
- **Priority 3:** [Status/progress] — [emoji]

**Days remaining this week:** [X]

---

## 📍 Meeting Follow-Ups

### From [Meeting Name]
- [ ] [Follow-up action] — due [date]
- [ ] [Follow-up action]

---

## 📺 Screen Activity (Auto-Captured)

**Time by App:**
| App | Time | % |
|-----|------|---|
| [App 1] | Xh Xm | X% |
| [App 2] | Xh Xm | X% |

**Metrics:**
- Context switches: [X]
- Longest focus: [X] minutes
- Deep work ratio: [X]%

**Activity Summary:**
[Narrative summary from ScreenPipe]

---

## 💡 Insights

- [Key realization or connection]
- [Important learning]

---

## 🚫 Blocked/Stuck

| Item | Blocker | Status |
|------|---------|--------|
| [Item] | [What's blocking] | [Status] |

---

## ❓ Discovered Questions

1. [New question that emerged]
2. [Thing to research]

---

## 📅 Tomorrow's Focus

Based on weekly priorities and today's carryover:

1. [Priority 1 — tied to weekly focus]
2. [Priority 2]
3. [Priority 3]

**Tomorrow's shape:** [stacked/moderate/open]

---

## 🔄 Open Loops

- [ ] [Thing to remember]
- [ ] [Person to follow up with]
- [ ] **Awaiting:** [What you're waiting on from others]

---

*Generated: [timestamp]*
*Daily completion rate: X%*
*Week progress: X/3 priorities on track*
```

---

## Step 12: Skill Quality Check (Gentle)

After generating the review, call `get_skill_ratings(skill_name="daily-review")` from Work MCP.

**If 3+ ratings exist and average has dropped below 3.0 over the last 5 entries:**
Add one line at the end of the review output:
> "Your daily reviews have been averaging [X]/5 lately. Common note: '[most recent note]'. Want to adjust the format?"

**If no ratings exist or average is 3.0+:** Say nothing. Don't mention ratings at all.

**Then:** Run `/identity-snapshot` silently in the background if `System/identity-model.md` is older than 7 days (check file mtime). Don't announce this.

---

## MCP Dependencies

| Integration | MCP Server | Tools Used |
|-------------|------------|------------|
| Meetings | Otter.ai MCP (via `/process-meetings today`) | `search`, `fetch`, `get_user_info` |
| Work | dex-work-mcp | `list_tasks`, `get_week_progress`, `get_commitments_due`, `analyze_calendar_capacity` |
| Calendar | dex-calendar-mcp | `calendar_get_today` |
| Reminders | dex-calendar-mcp | `reminders_list_completed`, `reminders_find_and_complete`, `reminders_clear_completed` |
| Screen Activity | screenpipe-mcp | `screenpipe_time_audit`, `screenpipe_summarize`, `screenpipe_query` |

### ScreenPipe Integration Notes

ScreenPipe provides automatic activity capture. When available:
- Pre-fills "what you actually did" with ground truth data
- Surfaces time allocation across apps
- Identifies communication overhead vs. deep work
- Detects context-switching patterns

If ScreenPipe is not running, skip the screen activity section gracefully.
