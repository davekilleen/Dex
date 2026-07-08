---
type: documentation
name: Opportunities README
---

# Opportunities

Pipeline records for consulting, advisory, fractional, fundraising, and role conversations.

## What Goes Here

Each opportunity page tracks:
- The target company and primary contact
- How the opportunity came in
- Pipeline stage and priority
- Next action and due date
- Recent contact history and notes

## Naming Convention

Use a clear opportunity name, usually `Company_Opportunity.md` or `Company_Role.md`.

## Workflow

1. **Capture** — Create an opportunity when a conversation becomes worth tracking separately from the person or company.
2. **Link** — Set `company` and `contact` to the relevant company and person pages.
3. **Advance** — Update `stage`, `next_action`, and `next_action_date` after each meaningful touch.
4. **Review** — Use `05-Areas/CRM_Boards.md` in Obsidian to scan the pipeline.

## CRM schema

Opportunity pages use `type: opportunity` in frontmatter.

**Required fields:** `name`, `company`, `contact`, `route`, `stage`, `priority`

**Status field:** `stage`

**Board:** pipeline, grouped by stage

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Display name for the opportunity |
| `company` | link to company page | Wiki link to a page in `05-Areas/Companies/` |
| `contact` | link to person page | Wiki link to a page in `05-Areas/People/` |
| `route` | route | How the opportunity started |
| `stage` | stage | Pipeline stage used for CRM boards |
| `priority` | priority | `high`, `medium`, or `low` |
| `next_action` | string | Next concrete follow-up |
| `next_action_date` | date | Due date for the next action |
| `last_contact` | date | Most recent meaningful contact |
| `status_changed` | date | Last time `stage` changed |
| `tags` | list of opp-tag | Opportunity category tags |

**Vocabulary**

- `priority`: `high`, `medium`, `low`
- `route`: `cold`, `warm`
- `stage`: `identified`, `qualified`, `proposal`, `negotiation`, `won`, `lost`
- `tags`: `consulting`, `advisory`, `fractional`, `fundraising`, `role`
