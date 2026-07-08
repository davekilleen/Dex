---
type: documentation
name: Companies README
---

# Companies

Organization-level notes and account context.

Use this directory for:
- company profiles
- account strategy notes
- relationship and opportunity context

This directory is part of the core vault path contract and must exist.

## CRM schema

Company pages are Target Companies records for Dex and Obsidian. Use `type: company` in frontmatter.

**Required fields:** `name`, `domains`, `priority`, `stage`

**Status field:** `stage`

**Board:** funnel, grouped by stage

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Display name for the company |
| `domains` | list | Email or web domains associated with the company |
| `priority` | priority | `high`, `medium`, or `low` |
| `stage` | stage | Funnel stage used for CRM boards |
| `next_action` | string | Next concrete follow-up |
| `next_action_date` | date | Due date for the next action |
| `status_changed` | date | Last time `stage` changed |
| `icp_tags` | list of icp_tag | Ideal-customer-profile tags |
| `signal` | string | Current signal or reason to engage |

**Vocabulary**

- `priority`: `high`, `medium`, `low`
- `stage`: `researching`, `outreach`, `active`, `nurture`, `passed`
- `icp_tags`: `enterprise`, `midmarket`, `startup`, `partner`, `strategic`
