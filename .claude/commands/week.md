# Weekly Synthesis

Create a synthesis of the week reviewing activity, progress, and planning for the week ahead.

## Data Sources

### 1. Task Progress

```
Tasks.md                              # Task completion status
Inbox/Week Priorities.md              # Weekly priorities
```

**Extract:**
- Tasks completed vs planned
- Tasks carried over
- New tasks added during the week
- Blocked items

### 2. Project Activity

```
Active/Projects/**/*.md               # Modified this week (check mtime)
```

**Extract:**
- Projects with activity
- Milestones reached
- Blockers identified
- Status changes

### 3. Meetings & People

```
Inbox/Meetings/*.md                   # Meeting notes from this week
People/**/*.md                        # Person pages updated
```

**Extract:**
- Meetings held
- Key discussions and decisions
- New contacts made
- Follow-up actions

### 4. Learnings Captured

```
Resources/Learnings/**/*.md           # New learnings from this week
```

**Extract:**
- Patterns identified
- Preferences documented
- Insights worth remembering

---

## Analysis Process

1. **Task Review**
   - Count completed vs planned from Week Priorities
   - Identify what carried over and why
   - Note any scope creep (tasks added mid-week)

2. **Project Scan**
   - Check modification dates on project files
   - Note status changes and progress
   - Identify blocked projects

3. **Meeting Analysis**
   - Review meeting notes from the week
   - Extract action items and commitments
   - Note key decisions made

4. **Learning Compilation**
   - Review any new entries in Learnings
   - Extract themes or patterns

---

## Output Format

Create `Inbox/Weekly_Synthesis_YYYY-MM-DD.md`:

```markdown
# Weekly Synthesis - Week of [Date]

## TL;DR

- **Tasks:** [X completed] / [Y planned] — [Z%] completion
- **Meetings:** [N total]
- **Projects touched:** [count]
- **Key wins:** [1-2 bullets]
- **Carried over:** [1-2 items that didn't get done]

---

## Task Completion

### Done This Week
- [x] [Task from Week Priorities]
- [x] [Task from Week Priorities]

### Carried Over
- [ ] [Task] - [reason not completed]

### Added Mid-Week
- [Task that wasn't planned but got done]

### Blocked
- [ ] [Task] - blocked by [reason]

---

## Project Progress

### Active Projects

| Project | Status | This Week | Next Steps |
|---------|--------|-----------|------------|
| [Name]  | [On track/At risk] | [What happened] | [Next action] |

### Milestones Reached
- [Project]: [Milestone achieved]

### Blockers
- [Project]: [What's blocking progress]

---

## Meetings & People

### Meetings Held

| Date | Topic | Attendees | Key Outcome |
|------|-------|-----------|-------------|
| [Day] | [Topic] | [Names] | [Decision/insight] |

### New Contacts
- [Name] at [Company] - [context]

### Action Items from Meetings
- [ ] [Action] - for [who] - due [when]

---

## Learnings

### This Week I Learned
- [Insight or pattern noticed]

### Working Preferences Updated
- [Any new preferences documented]

---

## Next Week

### Top 3 Priorities
1. [Most important thing]
2. [Second priority]
3. [Third priority]

### Upcoming Meetings
- [Day]: [Meeting]
- [Day]: [Meeting]

### Blocked Items Needing Resolution
| Item | Blocked Since | What Would Unblock It |
|------|---------------|-----------------------|
| [Item] | [Date] | [Action needed] |

---

## Energy Check (Optional)

<details>
<summary>Click to expand</summary>

### What Gave Energy
- [Activity that was energizing]

### What Drained Energy  
- [Activity that was draining]

### Adjustment for Next Week
- [What to do differently]

</details>
```

---

## Follow-up Actions

After synthesis:
1. Update Tasks.md with new priorities
2. Archive completed items from Week Priorities
3. Update project pages with status changes
4. Schedule meetings for blocked items if needed
