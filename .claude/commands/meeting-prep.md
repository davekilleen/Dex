# Meeting Prep

Prepare for an upcoming meeting by gathering context on attendees and related topics.

## Arguments

$MEETING: Meeting name or topic
$ATTENDEES: List of attendees (comma-separated)

## What This Does

1. Looks up each attendee in `People/` folder
2. Surfaces recent interactions and open action items
3. Checks for related projects
4. Suggests talking points based on context

## Process

### Step 1: Attendee Lookup

For each attendee in $ATTENDEES:

1. Search `People/Internal/` and `People/External/` for matching names
2. If found, extract:
   - Role and company
   - Last interaction date
   - Open action items involving them
   - Key context or notes

3. If not found, note: "No person page for [Name] - consider creating one after the meeting"

### Step 2: Related Projects

Search `Active/Projects/` for any projects that:
- Mention the attendees
- Relate to the meeting topic ($MEETING)

Extract:
- Project name and status
- Relevant milestones or blockers
- Recent updates

### Step 3: Recent Context

Search `Inbox/Meetings/` for recent meetings with these attendees:
- What was discussed?
- What was decided?
- What follow-ups were committed?

### Step 4: Compile Prep Brief

## Output Format

```markdown
# Meeting Prep: $MEETING

**Date:** [Today's date]
**Attendees:** $ATTENDEES

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


## People Context

### [Attendee Name]
- **Role:** [Role at Company]
- **Last Interaction:** [Date] - [Topic]
- **Open Items:**
  - [ ] [Action item]
- **Notes:** [Key context about this person]

### [Next Attendee]
...

---

## Related Projects

| Project | Status | Relevance |
|---------|--------|-----------|
| [Name]  | [Status] | [Why it relates] |

---

## Recent History

Previous meetings with these attendees:

| Date | Topic | Key Outcomes |
|------|-------|--------------|
| [Date] | [Topic] | [What was decided/discussed] |

---

## Suggested Talking Points

Based on the context above:

1. **Follow up on:** [Open item from last meeting]
2. **Discuss:** [Project-related topic]
3. **Ask about:** [Something from their context]

---

## Questions to Consider

- What's your main goal for this meeting?
- What do you need from these attendees?
- What decisions need to be made?

---

## Post-Meeting

After the meeting:
1. Add notes to `Inbox/Meetings/YYYY-MM-DD - [Topic].md`
2. Update person pages with new context
3. Create tasks for any action items
```

## When to Use

- Before any meeting with multiple attendees
- When meeting someone you haven't seen in a while
- Before important meetings where you want full context

## Tips

- Run this 15-30 minutes before the meeting
- Create person pages for new contacts after meetings
- Update this context regularly for accurate prep
