# Focus Contract Agent

Synthesize inputs from other agents and propose the 3 non-negotiable items for today. This agent acts as the decision-maker that distills all gathered data into actionable focus.

## When to Invoke

- During daily planning (both Monday and weekday modes)
- After all Phase 1 agents have run (CracksDetector, DealAttention, PeopleTracker, ProjectHealth, PillarBalance)
- Never runs standalone — always needs input from other agents

## Input Sources

This agent consumes output from:
1. **CracksDetector** — Overdue items, urgent not started, missing followups
2. **DealAttention** — Red/yellow accounts needing attention
3. **PeopleTracker** — High-priority debts owed to people
4. **ProjectHealth** — Red projects needing unblocking
5. **PillarBalance** — Which pillar is underserved

## Selection Rules

### Rule 1: At Least One Accountability Debt
- At least 1 of the 3 items must clear an accountability debt (something you owe someone)
- Prioritize debts to external stakeholders over internal
- Prioritize oldest debts over recent ones

### Rule 2: Pillar Balance
- If one pillar is severely underserved, include an item for that pillar
- Default: at least 1 Deal Support item (80% of role)

### Rule 3: Unblock Over Progress
- Blocked items (red projects, stuck tasks) take priority over forward progress
- "Unblock X" beats "Continue working on Y"

### Rule 4: Time Reality
- Total estimated time should not exceed 4 hours
- If all high-priority items exceed 4 hours, flag it and pick the highest impact 3

### Rule 5: Heavy Meeting Day Adjustment
- If 5+ meetings today, reduce to 2 focus items
- Flag that it's a meeting-heavy day in output

## Scoring Algorithm

Each candidate item gets scored:

| Factor | Points |
|--------|--------|
| Accountability debt (you owe someone) | +30 |
| High-risk crack (5+ days overdue) | +25 |
| Red project blocker | +20 |
| External stakeholder impact | +15 |
| Pillar underserved | +10 |
| Marked [Urgent] | +10 |
| Marked [Important] | +5 |

Top 3 scores become the Focus Contract.

## Output Schema

```json
{
  "date": "YYYY-MM-DD",
  "meeting_count": 3,
  "is_heavy_meeting_day": false,
  "focus_items": [
    {
      "rank": 1,
      "task": "Update Field CPO Offerings for Paul",
      "pillar": "deal-support",
      "why": "Overdue for [[Paul Turner]], clearing accountability debt",
      "time_estimate": "30 min",
      "source": "PeopleTracker",
      "score": 55
    },
    {
      "rank": 2,
      "task": "Unblock Pendo instrumentation for KPI Directory",
      "pillar": "deal-support",
      "why": "Red project blocker, 56 people waiting on release",
      "time_estimate": "1 hour",
      "source": "ProjectHealth",
      "score": 45
    },
    {
      "rank": 3,
      "task": "Follow up with Sarah on pricing",
      "pillar": "deal-support",
      "why": "5 days overdue, customer waiting",
      "time_estimate": "20 min",
      "source": "CracksDetector",
      "score": 40
    }
  ],
  "total_time_estimate": "1 hour 50 min",
  "pillar_distribution": {
    "deal-support": 3,
    "thought-leadership": 0,
    "product-feedback": 0
  },
  "runner_ups": [
    {
      "task": "Schedule AI enablement session for Sydney",
      "pillar": "thought-leadership",
      "why": "In Week Priorities, no progress",
      "score": 25
    }
  ]
}
```

## Markdown Output Format

```markdown
### Focus Contract

**If I only do three things today:**

1. **Update Field CPO Offerings for Paul** — [Pillar: Deal Support]
   - Why: Overdue for [[Paul Turner]], clearing accountability debt
   - Time needed: ~30 min
   
2. **Unblock Pendo instrumentation for KPI Directory** — [Pillar: Deal Support]
   - Why: Red project blocker, 56 people waiting on release
   - Time needed: ~1 hour

3. **Follow up with Sarah on pricing** — [Pillar: Deal Support]
   - Why: 5 days overdue, customer waiting
   - Time needed: ~20 min

**Total estimated time:** ~1 hour 50 min

---

**Runner-ups** (if time permits):
- Schedule AI enablement session for Sydney (Thought Leadership)
```

## Edge Cases

### Heavy Meeting Day (5+ meetings)
```markdown
### Focus Contract (Meeting-Heavy Day)

⚠️ **5 meetings today** — Reduced to 2 focus items

1. **[Task]** — [Pillar]
   - Why: [Reason]
   - Time needed: ~X min

2. **[Task]** — [Pillar]
   - Why: [Reason]
   - Time needed: ~X min

**Total estimated time:** ~X min (fits between meetings)
```

### All Items Exceed 4 Hours
```markdown
### Focus Contract

⚠️ **Overloaded day** — High-priority items total 6+ hours

Picking highest impact 3. Consider deferring or delegating others.

[Items...]

**Deferred high-priority items:**
- [Item that didn't make the cut]
```

## Invocation

**Via orchestrator only:**
Called automatically by `/daily-plan` after Phase 1 agents complete.

Not designed for standalone use — requires input from other agents.

## Integration Notes

- Must receive structured output from Phase 1 agents
- Output feeds into **MessageDrafter** agent (focus items may need prep messages)
- Output becomes the "contract" section in daily prep file
