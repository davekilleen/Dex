# People Tracker Agent

Track who's waiting on you and who you owe. This agent provides relationship-focused accountability tracking.

## When to Invoke

- During daily planning (weekday mode)
- Before 1:1 meetings to check outstanding items
- Via `/people-tracker` command for standalone check
- When prioritizing what to work on

## Data Sources

### Primary
- `------- OS -------/Inbox/Week Priorities.md` — Look for person names in tasks
- `Inbox/Meeting_Intel/` — Recent meeting action items with `@[[Person]]`
- `People/` pages — Check "Action Items" sections

### Secondary
- `------- OS -------/Inbox/Meetings/` — Older meeting notes with commitments
- `Tasks.md` — Backlog items associated with people

## Detection Logic

### 1. What You Owe Others

Scan for tasks/commitments where you are the owner:
- Week Priorities items mentioning a person name
- Meeting action items assigned to you (from `^mt-` blocks)
- Action items in Person pages under "I owe them" or similar

For each:
- Extract the person name
- Extract the commitment description
- Calculate days since commitment was made
- Link to source

### 2. What Others Owe You

Scan for items where you're waiting:
- Week Priorities items with "waiting on", "blocked by", or person names
- Meeting action items assigned to others
- Person pages under "They owe me" or similar

### 3. Relationship Staleness

Check Person pages for:
- "Last Contact" or "Last Interaction" dates
- Flag key relationships (internal leaders, important customers) with no recent interaction

## Output Schema

```json
{
  "scan_date": "YYYY-MM-DD",
  "you_owe": [
    {
      "person": "Paul Turner",
      "person_link": "People/Internal/Paul_Turner",
      "items": [
        {
          "description": "Update Field CPO offerings",
          "days_old": 4,
          "source": "Week Priorities",
          "priority": "high"
        },
        {
          "description": "Share eval playbook v1",
          "days_old": 2,
          "source": "Meeting#^mt-2026-01-14-a2",
          "priority": "medium"
        }
      ]
    }
  ],
  "waiting_on": [
    {
      "person": "Paul Turner",
      "person_link": "People/Internal/Paul_Turner",
      "items": [
        {
          "description": "Feedback on charter doc",
          "days_waiting": 3,
          "source": "Week Priorities"
        }
      ]
    }
  ],
  "stale_relationships": [
    {
      "person": "Carlos",
      "person_link": "People/External/Carlos",
      "last_contact": "2026-01-02",
      "days_stale": 17,
      "importance": "ProductCon speaker contact"
    }
  ],
  "summary": {
    "people_you_owe": 5,
    "total_items_owed": 12,
    "people_owing_you": 3,
    "stale_relationships": 2
  }
}
```

## Priority Classification

| Priority | Criteria |
|----------|----------|
| **High** | 5+ days old, customer-facing person, or explicitly marked important |
| **Medium** | 3-4 days old, internal stakeholder |
| **Low** | <3 days old, no explicit deadline |

## Markdown Output Format

```markdown
### People Waiting

#### [[People/Internal/Paul_Turner|Paul Turner]]
- [ ] Update Field CPO offerings (4 days)
- [ ] Share eval playbook v1 (2 days)

*You're waiting on:* Feedback on charter doc (3 days)

---

#### [[People/Internal/Jen_Uschold|Jen Uschold]]
- [ ] Confirm podcast recording date (1 day)

*You're waiting on:* Marketing approval for sponsored post

---

### Stale Relationships ⚠️

| Person | Last Contact | Days | Context |
|--------|--------------|------|---------|
| [[Carlos]] | Jan 2 | 17 | ProductCon speaker contact |

**Summary:** You owe 5 people (12 items total). 3 people owe you things. 2 relationships going stale.
```

## Invocation

**Direct:**
> "Run the people-tracker agent"

**Via command:**
> `/people-tracker` (if created)

**Via orchestrator:**
Called automatically by `/daily-plan` in weekday mode.

## Integration Notes

- Output feeds into **FocusContract** agent (high-priority debts become focus candidates)
- Output feeds into **MessageDrafter** agent (generates "I'm behind" and follow-up messages)
- Supersedes/extends the existing `followup-tracker` agent
- Person links should use WikiLinks format: `[[People/path|Name]]`
