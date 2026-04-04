# Level-Up Feature: Data Collection Verification

**Purpose:** Verify that usage tracking works correctly to power `/dex-level-up` recommendations.

---

## Data Flow Architecture

```
User Action → Command Execution → Usage Log Update → /dex-level-up Analysis → Recommendations
```

---

## Tracking Points

### 1. Core Workflow Commands (Explicit Tracking)

These commands have explicit tracking steps added:

| Command | Tracking Step | Usage Log Entry |
|---------|---------------|-----------------|
| `/daily-plan` | Step 7 | `- [x] Daily planning (/daily-plan)` |
| `/review` | Step 6 | `- [x] Daily review (/review)` |
| `/week-plan` | Step 5 | `- [x] Weekly planning (/week-plan)` |
| `/week-review` | After synthesis | `- [x] Weekly review (/week-review)` |

**Verification:**
- Each command file has a "Track Usage (Silent)" step
- Updates `System/usage_log.md` after completion
- No announcement to user

### 2. System Behavior (CLAUDE.md Guidance)

CLAUDE.md (lines 173-186) instructs Dex to track usage automatically:

> **Usage Tracking (Silent)**
> Track feature adoption in `System/usage_log.md` to power `/dex-level-up` recommendations:
> 
> **When to update (automatically, no announcement):**
> - User runs a command → Check that command's box
> - User creates person/project page → Check corresponding box
> - Work MCP tools used → Check task management boxes
> - Journaling prompts completed → Check journal boxes

**Verification:**
- Guidance exists in CLAUDE.md
- Applies to all commands, even those without explicit tracking steps
- Updates happen silently in background

### 3. Feature Detection (Implicit Tracking)

Some features are tracked by detecting their existence in the vault:

| Feature | Detection Method | Usage Log Entry |
|---------|------------------|-----------------|
| Person pages | Count files in `People/` | `- [x] Person page created` |
| Project pages | Count files in `04-Projects/` | `- [x] Project page created` |
| Tasks created | Check 03-Tasks/Tasks.md or MCP history | `- [x] Task created (via MCP)` |

**Verification:**
- `/dex-level-up` can read file system to detect usage
- No explicit tracking needed for these features

---

## Scenario Testing

### Scenario 1: New User (Week 1)

**Actions:**
1. User completes onboarding → No boxes checked yet
2. Runs `/daily-plan` for 7 consecutive days
3. Creates 2 tasks via MCP
4. Runs `/dex-level-up`

**Expected State in `System/usage_log.md`:**

```markdown
## Core Workflows
- [x] Daily planning (/daily-plan)  ← Checked after first run
- [ ] Daily review (/review)
- [ ] Weekly planning (/week-plan)
- [ ] Weekly review (/week-review)
...

## System Features
- [x] Task created (via MCP)  ← Detected from 03-Tasks/Tasks.md
- [ ] Task completed (via MCP)
...

## Tracking Metadata
- Last dex-level-up prompt: (not yet prompted)
- First daily plan: 2026-01-21
- Setup date: 2026-01-20
```

**Expected `/dex-level-up` Output:**

Recommendations:
1. **Daily Review** - Complete the planning loop
2. **Person Pages** - Track relationships
3. **Meeting Processing** - Extract value from meetings

**Verification Steps:**
1. Check `usage_log.md` has correct checked boxes
2. `/dex-level-up` correctly counts 2 of ~25 features used
3. Recommendations are relevant to daily planning habit
4. No mention of weekly/quarterly planning (too early)

---

### Scenario 2: Intermediate User (Week 4)

**Actions:**
1. Daily plans: 28 consecutive days
2. Daily reviews: 28 consecutive days
3. Weekly planning: 4 weeks
4. Meeting processing: 3 times
5. Person pages: 5 created
6. Tasks: 23 created, 15 completed
7. Runs `/dex-level-up`

**Expected State in `System/usage_log.md`:**

```markdown
## Core Workflows
- [x] Daily planning (/daily-plan)
- [x] Daily review (/review)
- [x] Weekly planning (/week-plan)
- [ ] Weekly review (/week-review)  ← Not used yet
- [ ] Quarterly planning (/quarter-plan)
- [ ] Quarterly review (/quarter-review)

## Meeting Workflows
- [ ] Meeting prep (/meeting-prep)
- [x] Meeting processing (/process-meetings)
- [x] Person page created  ← 5 created
- [x] Person page updated

## System Features
- [x] Task created (via MCP)
- [x] Task completed (via MCP)
- [ ] Project page created  ← Missing
...
```

**Expected `/dex-level-up` Output:**

Recommendations:
1. **Weekly Review** - Natural next step after weekly planning
2. **Project Tracking** - Organize 23 tasks into projects
3. **Quarterly Planning** - Think 3 months out

**Verification Steps:**
1. System detects 5 person pages exist (file count in `People/`)
2. Recognizes weekly planning without weekly review = gap
3. Suggests project tracking (has tasks but no projects)
4. Recommendations build on established habits

---

### Scenario 3: Power User (Month 3)

**Actions:**
1. All daily/weekly/quarterly workflows used
2. 15 person pages maintained
3. 6 project pages tracked
4. 47 meetings processed
5. Journaling enabled (morning & evening)
6. 12 insights saved
7. 156 tasks created, 134 completed
8. Runs `/dex-level-up`

**Expected State in `System/usage_log.md`:**

```markdown
## Core Workflows
- [x] Daily planning (/daily-plan)
- [x] Daily review (/review)
- [x] Weekly planning (/week-plan)
- [x] Weekly review (/week-review)
- [x] Quarterly planning (/quarter-plan)
- [x] Quarterly review (/quarter-review)

## Meeting Workflows
- [x] Meeting prep (/meeting-prep)
- [x] Meeting processing (/process-meetings)
- [x] Person page created
- [x] Person page updated

## Organization
- [x] Inbox triage (/triage)
- [x] Learning capture (/save-insight)
- [x] Project tracking (/project-health)
- [ ] Product brief (/product-brief)

## Journaling
- [x] Morning journal
- [x] Evening journal
- [ ] Weekly journal

## System Features
- [x] Task created (via MCP)
- [x] Task completed (via MCP)
- [x] Project page created
- [ ] Content tracking used
- [x] Relationship tracking used

## Advanced
- [ ] Custom MCP created (/create-mcp)  ← Only unchecked advanced feature
- [ ] System improvements (/dex-improve)
- [ ] Prompt improvement (/prompt-improver)
- [x] Demo mode (/dex-demo)
```

**Expected `/dex-level-up` Output:**

Recommendations:
1. **Custom MCP Integration** - Automate CRM sync
2. **System Customization** - Make Dex yours

Celebration message: "You're using Dex like a pro! 🎉"

**Verification Steps:**
1. System recognizes power user status (21+ features checked)
2. Suggests only advanced features (custom MCPs, system improvements)
3. Acknowledges mastery
4. Suggests sharing knowledge with others

---

## Critical Verification Points

### ✅ 1. Usage Log Gets Updated

**Test:**
- Fresh install → `usage_log.md` has all boxes unchecked
- Run `/daily-plan` → Box gets checked
- Run again → Box stays checked (idempotent)

**Files:**
- `System/usage_log.md` (the data)
- `.claude/commands/daily-plan.md` Step 7 (the update logic)

---

### ✅ 2. /dex-level-up Can Read Usage Log

**Test:**
- `/dex-level-up` command reads `System/usage_log.md`
- Parses markdown checkboxes correctly
- Counts checked vs unchecked items

**Files:**
- `.claude/skills/dex-level-up/SKILL.md` Step 1 (read logic)

---

### ✅ 3. Recommendations Are Contextual

**Test:**
- New user with only daily planning → Suggests daily review (close the loop)
- User with daily + weekly planning → Suggests weekly review (natural next step)
- User with tasks but no projects → Suggests project tracking

**Files:**
- `.claude/skills/dex-level-up/SKILL.md` Step 2 (pattern analysis)
- `.claude/skills/dex-level-up/SKILL.md` Step 3 (recommendation generation)

---

### ✅ 4. Smart Triggers Work

**Test:**
- Day 1-6: No prompt in `/daily-plan`
- Day 8+: Prompt appears if 3+ features unused
- After prompt: `last_dex_level_up_prompt` date updated
- Next 7 days: No prompt (respects cooldown)

**Files:**
- `.claude/skills/daily-plan/SKILL.md` Step 3.5 (trigger logic)
- `System/usage_log.md` Tracking Metadata section

---

### ✅ 5. Tracking Is Silent

**Test:**
- User runs `/daily-plan`
- Gets daily plan output
- No mention of "Updated usage log" or tracking
- Check `usage_log.md` → Box is checked

**Behavior:**
- All tracking updates are silent
- No user-facing announcements
- Updates happen in background

---

## Edge Cases

### Empty Usage Log (First Time)

**Expected:**
- `/dex-level-up` shows: "Looks like you're just getting started!"
- Recommends 3 essentials: daily planning, task management, meeting capture

### All Features Used

**Expected:**
- `/dex-level-up` shows celebration: "You're using every feature in Dex! 🎉"
- Suggests custom MCPs, system improvements, sharing knowledge

### User Says "Show Me Everything"

**Expected:**
- `/dex-level-up` says: "I could, but that's overwhelming..."
- Points to CLAUDE.md, .claude/skills/, and System Guide

---

## Implementation Checklist

- [x] Created `System/usage_log.md` with all features listed
- [x] Added explicit tracking to core commands (daily-plan, review, week-plan, week-review)
- [x] Added CLAUDE.md guidance for system-wide tracking behavior
- [x] Created `/dex-level-up` command with pattern analysis logic
- [x] Added [[README]] section highlighting feature discovery
- [x] Added onboarding mention of `/dex-level-up`
- [x] Added smart trigger to `/daily-plan` (7-day cooldown)
- [x] Tested scenario recommendations (examples in dex-level-up.md)

---

## Maintenance Notes

**To add a new trackable feature:**

1. Add entry to `System/usage_log.md` in appropriate section
2. Update CLAUDE.md if it's a new pattern (optional)
3. Consider explicit tracking in command file if it's a core workflow
4. Update `/dex-level-up` command if new progression patterns emerge

**No need to:**
- Update every single command file manually
- Create complex tracking infrastructure
- Store detailed analytics (simple binary checkboxes work)

---

## Success Criteria

✅ New users discover features they didn't know existed
✅ Intermediate users progress naturally through workflows
✅ Power users find advanced capabilities when ready
✅ No feature blindness — everyone gets to full value
✅ Never overwhelming — 2-3 suggestions at a time
✅ Tracking is silent — no interruption to user flow

**Result:** Users get to value faster, system delivers on its promise, no FOMO.
