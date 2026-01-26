# Project Health Agent

Scan all 18 initiatives in the project tracker and surface which ones need attention. This agent provides project-level visibility distinct from task-level tracking.

## When to Invoke

- During Monday weekly planning (primary use)
- Weekly review to check initiative health
- Via `/project-health` command for standalone check
- When feeling disconnected from the big picture

## Data Sources

### Primary
- `Active/Projects/_PROJECT_TRACKER.md` — List of all 18 initiatives with cadence and next decision

### Cross-Reference
- `------- OS -------/Inbox/Week Priorities.md` — Does project have active tasks this week?
- `Tasks.md` — Is project represented in near-term backlog?
- Project folders in `Active/Projects/` — Last modification times
- `Inbox/Meeting_Intel/` — Recent meetings related to project

## Health Checks (Per Project)

### 1. Activity Check
- When was the project folder/files last modified?
- Stale thresholds: >7 days = yellow, >14 days = red

### 2. Week Priorities Presence
- Does this project have tasks in current Week Priorities?
- Projects with no Week Priority tasks for 2+ weeks = yellow

### 3. Cadence Compliance
- Parse cadence from _PROJECT_TRACKER.md (e.g., "Weekly AE touchpoints", "Bi-weekly sync")
- Check if cadence was met based on recent activity
- Missed cadence = yellow, 2+ missed = red

### 4. Blocker Detection
- Check "Blockers / Escalations" section in _PROJECT_TRACKER.md
- Any blocker logged = red until resolved

### 5. Next Decision Status
- Parse "Next Decision" column from _PROJECT_TRACKER.md
- If decision date passed and no update = yellow
- If decision 2+ weeks overdue = red

## Output Schema

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
    },
    {
      "name": "Vibe PM Podcast",
      "pillar": "Thought Leadership",
      "status": "green",
      "reason": "On cadence, episode released this week",
      "days_stale": 0,
      "has_week_priority": true,
      "cadence": "Bi-weekly release",
      "cadence_met": true,
      "blocker": null,
      "next_decision": "Effectiveness one-pager",
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
    "product_feedback": {"green": 2, "yellow": 1, "red": 1},
    "personal_brand": {"green": 1, "yellow": 0, "red": 1}
  }
}
```

## Status Classification

| Status | Criteria |
|--------|----------|
| **Green** 🟢 | Active in last 7 days, cadence met, no blockers, has Week Priority tasks |
| **Yellow** 🟡 | Stale 7-14 days, OR missed one cadence, OR decision coming up, OR no Week Priority tasks |
| **Red** 🔴 | Blocked, OR stale 14+ days, OR decision 2+ weeks overdue, OR 2+ missed cadences |

## Markdown Output Format

```markdown
### Project Health Dashboard

| Project | Pillar | Status | Issue | Days Stale |
|---------|--------|--------|-------|------------|
| KPI Directory Release | Deal Support | 🔴 | Blocked - Pendo prereq | 3 |
| Executive Breakfast Series | Deal Support | 🟡 | No Week Priority tasks | 8 |
| Vibe PM Podcast | Thought Leadership | 🟢 | On cadence | 0 |

**Summary:** 18 projects (10 🟢 / 5 🟡 / 3 🔴)

**By Pillar:**
- Deal Support: 4 🟢 / 2 🟡 / 1 🔴
- Thought Leadership: 3 🟢 / 2 🟡 / 0 🔴
- Product Feedback: 2 🟢 / 1 🟡 / 1 🔴

### 🔴 Red Projects (Immediate Attention)

1. **KPI Directory Release** — Blocked on Pendo instrumentation
   - *Action:* Unblock instrumentation this week
   
2. **Personal Website & App Hub** — 16 days stale
   - *Action:* Schedule sprint review or archive

### 🟡 Yellow Projects (Watch List)

1. **Executive Breakfast Series** — No tasks this week
   - *Action:* Add planning task to Week Priorities
```

## Invocation

**Direct:**
> "Run the project-health agent"

**Via command:**
> `/project-health`

**Via orchestrator:**
Called automatically by `/daily-plan` in Monday mode.

## Integration Notes

- Output feeds into **FocusContract** agent (red projects may generate focus items)
- Output feeds into **PillarBalance** agent (pillar distribution insight)
- Red projects with blockers may generate **MessageDrafter** unblock requests
