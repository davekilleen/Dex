---
type: dashboard
name: CRM Boards
---

# CRM Boards

Dataview boards for the file-first CRM. These use the same paths, `type` values, status fields, and vocabularies as the desktop app.

## People — Bands

```dataview
TABLE rows.name AS Name, rows.priority AS Priority, rows.next_action AS "Next action", rows.next_action_date AS "Next action date"
FROM "05-Areas/People"
WHERE type = "person" AND contains(["hot", "warm", "cool", "cold"], warmth)
GROUP BY warmth AS Band
SORT choice(Band = "hot", 1, choice(Band = "warm", 2, choice(Band = "cool", 3, 4))) ASC
```

## Companies — Funnel

```dataview
TABLE rows.name AS Name, rows.priority AS Priority, rows.next_action AS "Next action"
FROM "05-Areas/Companies"
WHERE type = "company" AND contains(["researching", "outreach", "active", "nurture", "passed"], stage)
GROUP BY stage AS Stage
SORT choice(Stage = "researching", 1, choice(Stage = "outreach", 2, choice(Stage = "active", 3, choice(Stage = "nurture", 4, 5)))) ASC
```

## Opportunities — Pipeline

```dataview
TABLE rows.name AS Name, rows.company AS Company, rows.contact AS Contact, rows.priority AS Priority, rows.next_action AS "Next action"
FROM "05-Areas/Opportunities"
WHERE type = "opportunity" AND contains(["identified", "qualified", "proposal", "negotiation", "won", "lost"], stage)
GROUP BY stage AS Stage
SORT choice(Stage = "identified", 1, choice(Stage = "qualified", 2, choice(Stage = "proposal", 3, choice(Stage = "negotiation", 4, choice(Stage = "won", 5, 6))))) ASC
```
