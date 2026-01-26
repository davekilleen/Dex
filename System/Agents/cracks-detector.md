# Cracks Detector Agent

Surface commitments that have slipped or are at risk of slipping. This agent finds the gaps between what you promised and what you've delivered.

## When to Invoke

- During daily planning (weekday mode)
- Mid-day when feeling like something was forgotten
- Before end-of-day to ensure nothing slipped
- Via `/cracks` command for standalone check

## Sources to Check

### 1. Stale Meeting Action Items

Scan these locations for `^mt-` block IDs:
- `Inbox/Meeting_Intel/`
- `------- OS -------/Inbox/Meetings/`

**Detection logic:**
- Parse date from block ID format: `^mt-YYYY-MM-DD-xxxx`
- Flag any **unchecked** items where date is 3+ days ago
- Extract the task description and linked person (if any)

### 2. People Without Follow-up

Cross-reference recent meetings against tasks:
- Find people mentioned in meetings from past 5 days
- Check if they have associated tasks in Week Priorities or Tasks.md
- Flag people mentioned in meetings but with no pending task

### 3. Urgent Items Not Started

Scan `------- OS -------/Inbox/Week Priorities.md` for:
- Items marked `[Urgent]` that are still unchecked
- Items with day-specific tags past their date (e.g., "by Wednesday" when it's Thursday)

## Output Schema

```json
{
  "scan_date": "YYYY-MM-DD",
  "overdue_items": [
    {
      "description": "Follow up with Sarah on pricing",
      "source": "Inbox/Meetings/Meeting - Acme Call - 2026-01-14#^mt-2026-01-14-a1",
      "days_old": 5,
      "person": "Sarah",
      "risk": "high"
    }
  ],
  "urgent_not_started": [
    {
      "description": "Review DACH deck",
      "source": "Week Priorities",
      "tag": "[Urgent]",
      "risk": "medium"
    }
  ],
  "missing_followups": [
    {
      "person": "John Smith",
      "last_meeting": "Inbox/Meetings/Meeting - Strategy Call - 2026-01-16",
      "meeting_date": "2026-01-16",
      "risk": "medium"
    }
  ],
  "summary": {
    "total_cracks": 7,
    "high_risk": 2,
    "medium_risk": 4,
    "low_risk": 1
  }
}
```

## Risk Classification

| Risk Level | Criteria |
|------------|----------|
| **High** | 5+ days overdue, customer-facing, or explicitly marked Urgent |
| **Medium** | 3-4 days overdue, internal stakeholder, or approaching deadline |
| **Low** | 3 days old, no explicit deadline, internal only |

## Markdown Output Format

When outputting for human consumption (vs JSON for orchestrator):

```markdown
### Cracks Detected ⚠️

| Item | Age | Source | Risk |
|------|-----|--------|------|
| Follow up with [[Sarah]] on pricing | 5 days | [[Meeting#^mt-2026-01-14-a1]] | High - customer waiting |
| Review DACH deck | 4 days | [[Week Priorities]] | Medium |

**Summary:** 7 cracks detected (2 high, 4 medium, 1 low)
```

## Invocation

**Direct:**
> "Run the cracks-detector agent"

**Via command:**
> `/cracks`

**Via orchestrator:**
Called automatically by `/daily-plan` in weekday mode.

## Integration Notes

- Output feeds into **FocusContract** agent (high-risk cracks prioritized)
- Output feeds into **MessageDrafter** agent (generates "I'm behind" messages)
- Person links should use WikiLinks format: `[[People/path|Name]]`
