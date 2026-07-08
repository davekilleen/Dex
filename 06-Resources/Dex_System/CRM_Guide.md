---
type: documentation
name: CRM Guide
---

# CRM Guide

Dex CRM is file-first: the desktop app and Obsidian read the same markdown files, frontmatter fields, paths, and vocabularies.

## Entity Roots

| Entity | Path | Frontmatter type | Board |
|--------|------|------------------|-------|
| People | `05-Areas/People/` | `person` | Band by `warmth` |
| Target Companies | `05-Areas/Companies/` | `company` | Funnel by `stage` |
| Opportunities | `05-Areas/Opportunities/` | `opportunity` | Pipeline by `stage` |

## Shared Fields

Use `priority` for importance: `high`, `medium`, or `low`.

Use `next_action` and `next_action_date` to make every relationship review actionable. Use `status_changed` when the board status changes so sweeps can tell what moved recently.

## Entity Vocabularies

**People**
- `warmth`: `hot`, `warm`, `cool`, `cold`
- `tags`: `champion`, `buyer`, `connector`, `advisor`, `candidate`

**Target Companies**
- `stage`: `researching`, `outreach`, `active`, `nurture`, `passed`
- `icp_tags`: `enterprise`, `midmarket`, `startup`, `partner`, `strategic`

**Opportunities**
- `route`: `cold`, `warm`
- `stage`: `identified`, `qualified`, `proposal`, `negotiation`, `won`, `lost`
- `tags`: `consulting`, `advisory`, `fractional`, `fundraising`, `role`

## Capture And Sweep

Capture a person first, then add a company or opportunity when the relationship needs account or pipeline tracking. Link opportunities to both `company` and `contact` so the desktop app and Obsidian graph stay connected.

During a sweep, update the status field, `priority`, `next_action`, and `next_action_date`. Keep vocab values exact; changing `warmth`, `stage`, or `route` to a synonym creates a separate bucket in Dataview and the desktop CRM.

## Obsidian Boards

Open `05-Areas/CRM_Boards.md` with the Dataview plugin enabled to see the People band board, Target Companies funnel, and Opportunities pipeline.
