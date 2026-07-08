---
type: documentation
name: People README
---

# People

Everyone you work with—colleagues, customers, partners, stakeholders.

## Subfolders

- **Internal/** — Colleagues, teammates, managers, cross-functional partners
- **External/** — Customers, prospects, partners, vendors, community

## What Goes Here

Each person page tracks:
- Name, role, and company
- Meeting history (auto-linked from `00-Inbox/Meetings/`)
- Key context (what they care about, relationship notes)
- Action items involving them
- Ongoing threads and topics

## Naming Convention

`Firstname_Lastname.md`

## Why Person Pages?

Person pages aggregate everything related to someone in one place. Instead of searching through meeting notes, you have a single page with:
- Full relationship history
- What you've discussed
- What you owe them / they owe you
- Context for your next interaction

## Workflow

1. **Auto-creation** — Dex creates/updates person pages when processing meetings (via `/process-meetings`)
2. **Prep** — Before meetings, check their page for context (via `/meeting-prep`)
3. **Manual updates** — Add context as you learn more about them

## Pro Tip

Always check `05-Areas/People/` FIRST when looking for context. Person pages are often the fastest path to relevant information because they aggregate meeting history and context over time.

## Integration

- Meeting notes auto-link to person pages
- Tasks reference people involved
- `/meeting-prep` pulls from person pages
- Action items surface on relevant person pages

## CRM schema

Person pages are CRM contact records for Dex and Obsidian. Use `type: person` in frontmatter.

**Required fields:** `name`, `priority`, `warmth`, `next_action`, `next_action_date`

**Status field:** `warmth`

**Board:** band, grouped by warmth

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Display name for the person |
| `email` | string | Primary email address |
| `priority` | priority | `high`, `medium`, or `low` |
| `warmth` | warmth | Relationship band used for CRM boards |
| `next_action` | string | Next concrete follow-up |
| `next_action_date` | date | Due date for the next action |
| `last_contact` | date | Most recent meaningful contact |
| `status_changed` | date | Last time `warmth` changed |
| `tags` | list of tag | CRM tags for the relationship |

**Vocabulary**

- `priority`: `high`, `medium`, `low`
- `warmth`: `hot`, `warm`, `cool`, `cold`
- `tags`: `champion`, `buyer`, `connector`, `advisor`, `candidate`
