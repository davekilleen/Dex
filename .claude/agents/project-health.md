---
name: project-health
description: Scan all initiatives and surface which need attention. Check activity, cadence compliance, blockers. Use for Monday planning or weekly reviews.
tools: Read, Grep, Glob
model: sonnet
permissionMode: plan
---

# Project Health

Scan all initiatives in the project tracker and surface which ones need attention. Project-level visibility distinct from task-level tracking.

## Data Sources

### Primary
- `Active/Projects/_PROJECT_TRACKER.md` — All initiatives with cadence and next decision

### Cross-Reference
- `------- OS -------/Inbox/Week Priorities.md` — Does project have active tasks?
- `Tasks.md` — Is project in near-term backlog?
- Project folders in `Active/Projects/` — Last modification times
- `Inbox/Meeting_Intel/` — Recent meetings related to project

## Health Checks (Per Project)

### 1. Activity Check
- When was project folder/files last modified?
- >7 days = yellow, >14 days = red

### 2. Week Priorities Presence
- Does project have tasks in current Week Priorities?
- No tasks for 2+ weeks = yellow

### 3. Cadence Compliance
- Parse cadence from _PROJECT_TRACKER.md
- Check if cadence was met based on recent activity
- Missed cadence = yellow, 2+ missed = red

### 4. Blocker Detection
- Check "Blockers / Escalations" section
- Any blocker = red until resolved

### 5. Next Decision Status
- Parse "Next Decision" column
- If decision date passed with no update = yellow
- If 2+ weeks overdue = red

## Status Classification

| Status | Criteria |
|--------|----------|
| **green** | Active in last 7 days, cadence met, no blockers, has Week Priority tasks |
| **yellow** | Stale 7-14 days, OR missed one cadence, OR no Week Priority tasks |
| **red** | Blocked, OR stale 14+ days, OR decision 2+ weeks overdue |

## Output Schema

Return ONLY valid JSON:

```json
{
  "scan_date": "YYYY-MM-DD",
  "projects": [
    {
      "name": "KPI Directory Release",
      "pillar": "Deal Support",
      "status": "red",
      "reason": "Blocked - Pendo instrumentation prerequisite",
      "days_stale": 3,
      "has_week_priority": true,
      "cadence": "Build / customer tests",
      "cadence_met": false,
      "blocker": "Pendo instrumentation incomplete",
      "next_decision": "Define production handoff",
      "next_decision_overdue": false
    }
  ],
  "summary": {
    "total": 18,
    "green": 10,
    "yellow": 5,
    "red": 3
  },
  "by_pillar": {
    "deal_support": {"green": 4, "yellow": 2, "red": 1},
    "thought_leadership": {"green": 3, "yellow": 2, "red": 0},
    "product_feedback": {"green": 2, "yellow": 1, "red": 1}
  }
}
```
