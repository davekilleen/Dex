# Daily Review

Conduct an end-of-day review to capture progress and set up tomorrow.

## Step 0: File Discovery

**Find files modified TODAY:**

```bash
# Get today's date and find files modified today
TODAY=$(date +%Y-%m-%d)
find . -type f -name "*.md" -newermt "$TODAY 00:00:00" ! -newermt "$TODAY 23:59:59" 2>/dev/null | grep -v "node_modules" | xargs ls -lt 2>/dev/null
```

**Critical rules:**
1. **No truncation** — Do NOT use `head` limits on file discovery
2. **Today only** — Use date-based filtering, NOT `-mtime 0` (which captures 24-hour rolling window)
3. **Verify with user** — After listing files, ASK: "These are the files I found modified today. What did you actually work on?"
4. **Don't infer** — File timestamps tell you what changed, not what matters. Wait for user confirmation.

## Step 1: Gather Context

### Weekly Priorities
Read `Inbox/Week Priorities.md` for:
- This week's strategic focus
- Commitments and deadlines
- Key people involved

### Recent Meetings
Check `Inbox/Meetings/` for any meeting notes from today.

## Step 2: User Verification

**Present findings to user:**
> "Based on file timestamps, these notes were modified today: [list]
> 
> What did you actually work on today that should be captured in the review?"

Wait for user response before proceeding.

## Step 3: Progress Assessment

With user-verified information:
- What was accomplished?
- What progress was made against weekly priorities?
- What got stuck or blocked?
- What unexpected discoveries emerged?

## Step 4: Auto-Extract Session Learnings

**Scan today's conversation for learnings:**

Before asking the user anything, reflect on today's session and automatically extract:

1. **Mistakes or corrections**
   - Did the user have to correct any assumptions?
   - Did something not work as expected?
   - Were there misunderstandings to document?

2. **Preferences mentioned**
   - Did the user express how they like to work?
   - Were tool preferences or workflow patterns mentioned?
   - Any communication style notes?

3. **Documentation gaps**
   - Did you have to explain something that should be documented?
   - Were there questions about how the system works?
   - Missing templates or unclear processes?

4. **Workflow inefficiencies**
   - Did any task take longer than it should?
   - Were there repetitive manual steps?
   - Opportunities for automation?

**For each learning identified, write to `Inbox/Session_Learnings/YYYY-MM-DD.md`:**

```markdown
## HH:MM - [Short title]

**What happened:** [Specific situation from today's session]
**Why it matters:** [Impact on workflows/system]
**Suggested fix:** [Specific action with file paths if applicable]
**Status:** pending

---
```

**Then ask the user:** "I captured [N] learnings from today's session. Anything else you'd like to add?"

**This ensures learnings persist for:**
- Weekly synthesis (`/week`)
- System improvement reviews (`/whats-new`)
- Future reference

## Step 4b: Additional Insights

- Key realizations or connections from user input
- Questions that arose

## Step 5: Tomorrow's Setup

- Top 3 priorities (aligned with weekly focus)
- Open loops to close
- Questions to explore

## Output Format

Create daily note at `Inbox/Daily_Reviews/Daily_Review_[YYYY-MM-DD].md`:

```markdown
---

---

## Demo Mode Check

Before executing, check if demo mode is active:

1. Read `System/user-profile.yaml` and check `demo_mode`
2. **If `demo_mode: true`:**
   - Display: "Demo Mode Active — Using sample data"
   - Use `System/Demo/` paths instead of root paths
   - Write any output to `System/Demo/` subdirectories
3. **If `demo_mode: false`:** Use normal vault paths

date: [YYYY-MM-DD]
type: daily-review
---

# Daily Review — [Day], [Month] [DD], [YYYY]

## Accomplished

- ✓ [Completed item 1]
- ✓ [Completed item 2]

## Progress Made

| Area | Movement |
|------|----------|
| **[Area 1]** | [What moved forward] |
| **[Area 2]** | [What moved forward] |

## Weekly Priorities Progress

> Reference: Inbox/Week Priorities.md

- **[Priority 1]:** [Status/progress]
- **[Priority 2]:** [Status/progress]

## Insights

- [Key realization or connection]
- [Important learning]

## Blocked/Stuck

| Item | Blocker | Status |
|------|---------|--------|
| [Item] | [What's blocking] | [Status] |

## Discovered Questions

1. [New question that emerged]
2. [Thing to research]

## Tomorrow's Focus

1. [Priority 1 — tied to weekly focus]
2. [Priority 2]
3. [Priority 3]

## Open Loops

- [ ] [Thing to remember]
- [ ] [Person to follow up with]
- [ ] **Awaiting:** [What you're waiting on from others]
```

## Important Reminders

- **Verify, don't infer** — Always confirm with user what they worked on
- **Weekly alignment** — Connect daily progress to weekly priorities
- **Day of week** — Use system date metadata, verify before writing
