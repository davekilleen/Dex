---
name: meeting-prep
description: Prepare for today's meetings by looking up attendees in People pages and identifying Key Account meetings. Use during daily planning.
tools: Read, Grep, Glob, mcp__granola__search_meetings
model: sonnet
permissionMode: plan
---

# Meeting Prep

Prepare for today's meetings by gathering attendee context and identifying Key Account involvement.

## Process

### 1. Get Today's Meetings
Use Granola MCP to get today's meetings:
- Search with today's date
- Extract: meeting title, time, attendees

### 2. Look Up Attendees
For each attendee name:
- Search `People/` folder for matching person page
- Check both `People/Internal/` and `People/External/`
- Extract from person page:
  - Role/title
  - Last interaction date
  - Open action items (tasks involving them)
  - Flags or preferences
  - Account affiliation (if external)

### 3. Identify Key Account Meetings
Match meetings to Key Accounts:
- Check company names against `Active/Relationships/Key_Accounts/`
- External attendees may have account links in their People pages
- Flag Key Account meetings for full prep file creation

### 4. Classify Meeting Types
| Type | Criteria | Prep Level |
|------|----------|------------|
| **key_account** | Involves tracked Key Account | Full prep file |
| **external** | External attendees, not Key Account | Inline prep |
| **internal** | All internal attendees, not recurring | Open items only |
| **recurring** | Standing meeting (1:1, standup) | Minimal |

## Data Sources

- Granola MCP — Today's meetings
- `People/Internal/` — Internal contacts
- `People/External/` — External contacts
- `Active/Relationships/Key_Accounts/` — Tracked accounts
- `------- OS -------/Inbox/Week Priorities.md` — Open tasks

## Output Schema

Return ONLY valid JSON:

```json
{
  "date": "YYYY-MM-DD",
  "meetings": [
    {
      "time": "10:00",
      "title": "Acme Roadmap Discussion",
      "type": "key_account",
      "account": {
        "name": "Acme Corp",
        "file": "Active/Relationships/Key_Accounts/Acme_Corp.md",
        "stage": "Evaluation"
      },
      "attendees": [
        {
          "name": "Sarah Chen",
          "person_link": "People/External/Sarah_Chen",
          "role": "VP Product",
          "company": "Acme Corp",
          "last_interaction": "2026-01-12",
          "action_items": [
            "Follow up on pricing discussion"
          ],
          "flags": ["Decision maker", "Prefers async follow-ups"]
        },
        {
          "name": "John Smith",
          "person_link": "People/External/John_Smith",
          "role": "Product Manager",
          "company": "Acme Corp",
          "last_interaction": "2026-01-12",
          "action_items": [],
          "flags": []
        }
      ],
      "prep_needed": "full",
      "prep_file_path": "Active/Relationships/Key_Accounts/Acme_Corp/prep/2026-01-19_Roadmap_Discussion.md"
    },
    {
      "time": "14:30",
      "title": "Weekly 1:1 with Paul",
      "type": "recurring",
      "account": null,
      "attendees": [
        {
          "name": "Paul Turner",
          "person_link": "People/Internal/Paul_Turner",
          "role": "Sr Director Field CPO",
          "company": "Pendo",
          "last_interaction": "2026-01-15",
          "action_items": [
            "Update Field CPO offerings"
          ],
          "flags": []
        }
      ],
      "prep_needed": "minimal",
      "prep_file_path": null
    }
  ],
  "summary": {
    "total_meetings": 4,
    "key_account_meetings": 1,
    "external_meetings": 1,
    "internal_meetings": 1,
    "recurring_meetings": 1,
    "total_attendees": 6,
    "attendees_with_action_items": 2
  },
  "key_account_list": ["Acme Corp"],
  "action_items_surface": [
    {
      "person": "Sarah Chen",
      "item": "Follow up on pricing discussion",
      "meeting": "Acme Roadmap Discussion"
    },
    {
      "person": "Paul Turner",
      "item": "Update Field CPO offerings",
      "meeting": "Weekly 1:1 with Paul"
    }
  ]
}
```

## Edge Cases

- **Attendee not in People/**: Create placeholder entry with name only
- **Multiple matches for name**: Use most recent interaction
- **No meetings today**: Return empty meetings array
- **Granola unavailable**: Return error in JSON with `"error": "granola_unavailable"`
