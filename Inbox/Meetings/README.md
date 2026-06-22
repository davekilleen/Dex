# Meetings

Meeting notes, summaries, and decisions.

## What Goes Here

- **Meeting notes** — Captured during or after meetings
- **Granola imports** — Processed via `/process-meetings`
- **Meeting prep** — Context gathered via `/meeting-prep`
- **Key decisions** — Important choices made in meetings
- **Action items** — Tasks that came out of meetings

## Folder Structure

Meeting notes are organized in date-based subfolders:

```
00-Inbox/Meetings/
├── 2026-01-28/
│   ├── Product_Review.md
│   └── Customer_Call_Acme.md
├── 2026-01-29/
│   └── 1on1_with_Manager.md
```

This structure is automatically created by `/process-meetings` when importing from Granola or creating meeting notes. It keeps meetings organized by date while allowing multiple meetings per day.

## Naming Convention

`YYYY-MM-DD - Meeting Topic.md` or `YYYY-MM-DD - Person Name.md`

## Workflow

1. **Before** — Run `/meeting-prep` to gather context on attendees
2. **During** — Capture notes (or let Granola record)
3. **After** — Run `/process-meetings` to extract insights and update person pages

## What Happens During Processing

When you process meetings, Dex automatically:
- Extracts action items → links to person pages
- Identifies key decisions → surfaces in summaries
- Updates person pages with meeting history
- Links to relevant projects and context
- Captures career development discussions (if 05-Areas/Career/ exists)

## Retention

Meeting notes stay in Inbox until:
- Old meetings (90+ days) can optionally move to 07-Archives/
- Or keep them searchable in Inbox indefinitely

Most useful: Keep recent meetings in Inbox, archive older ones to reduce clutter.
