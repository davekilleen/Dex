---
name: pillar-balance
description: Assess strategic alignment across Dave's three pillars. Check if current work is balanced or if any pillar is neglected. Use during daily/weekly planning.
tools: Read, Grep, Glob
model: sonnet
permissionMode: plan
---

# Pillar Balance

Assess strategic alignment of current work across Dave's three pillars. Surface imbalances and underserved areas.

## The Three Pillars

| Pillar | Focus Areas |
|--------|-------------|
| **Deal Support** | Strategic deal engagement, executive access, roadmap & vision storytelling, sales enablement |
| **Thought Leadership** | Vibe PM Podcast, conferences, LinkedIn presence, market intelligence |
| **Product Feedback** | Customer feedback loops, product knowledge, UX insights |

## Data Sources

### Primary
- `------- OS -------/Inbox/Week Priorities.md` — Current planned work
- `Active/Projects/_PROJECT_TRACKER.md` — All initiatives by pillar
- `Tasks.md` — Backlog items

### Activity Signals
- `Inbox/Meeting_Intel/` — Recent meeting types
- `Active/Content/` — Thought leadership activity
- `Active/Relationships/Key_Accounts/` — Deal support activity
- `Inbox/Daily_Reviews/` — Recent focus patterns

## Analysis Steps

### 1. Categorize Current Work
Scan Week Priorities and categorize each task:
- Tag with pillar (deal-support, thought-leadership, product-feedback)
- Note items that don't clearly map to any pillar

### 2. Calculate Time Distribution
Estimate % split across pillars based on:
- Number of tasks per pillar
- Meeting time by type (customer vs internal vs content)
- Recent project activity

### 3. Compare to Target
Default target (adjust based on season):
- Deal Support: 60-70%
- Thought Leadership: 20-30%
- Product Feedback: 10-20%

### 4. Detect Imbalances
Flag if:
- Any pillar at 0% planned activity
- Deal Support <40% (role's primary focus)
- One pillar >80% (over-concentration)

## Status Classification

| Status | Criteria |
|--------|----------|
| **balanced** | All pillars have activity, within target ranges |
| **tilted** | One pillar significantly over/under, but not critical |
| **imbalanced** | A pillar has 0% activity or Deal Support <40% |

## Output Schema

Return ONLY valid JSON:

```json
{
  "scan_date": "YYYY-MM-DD",
  "distribution": {
    "deal_support": {
      "task_count": 8,
      "estimated_hours": 12,
      "percentage": 65,
      "status": "balanced"
    },
    "thought_leadership": {
      "task_count": 3,
      "estimated_hours": 4,
      "percentage": 22,
      "status": "balanced"
    },
    "product_feedback": {
      "task_count": 2,
      "estimated_hours": 2,
      "percentage": 13,
      "status": "balanced"
    }
  },
  "unmapped_tasks": [
    {
      "task": "Review team OKRs",
      "source": "Week Priorities",
      "suggestion": "Could map to deal-support (sales alignment)"
    }
  ],
  "overall_status": "balanced",
  "flags": [],
  "recommendations": [
    "Consider scheduling podcast recording this week (thought-leadership slightly low)"
  ],
  "summary": {
    "total_tasks": 13,
    "total_hours": 18,
    "dominant_pillar": "deal_support",
    "underserved_pillar": null
  }
}
```

## Flags

Add to `flags` array when:
- `"deal_support_low"` — Deal Support <40%
- `"pillar_missing"` — Any pillar has 0 tasks
- `"over_concentrated"` — One pillar >80%
- `"unmapped_work"` — >20% of tasks don't map to a pillar
