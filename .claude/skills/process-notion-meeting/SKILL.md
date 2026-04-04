---
name: process-notion-meeting
description: Process a Notion meeting note — extract tasks, update person pages, and link to projects
context: fork
---

Process a meeting note from Notion. Reads the page, extracts action items, updates person pages, and links to relevant projects.

## Arguments

**Optional:** $PAGE (Notion page URL or title)

If not provided, ask: "Which meeting should I process? Share the Notion page URL or title."

## Process

### Step 1: Find the Notion Page

**If $PAGE is a URL:**
- Use `notion_get_page` with the page ID extracted from the URL
  - Notion page IDs are the last 32 hex chars in the URL (with or without hyphens)

**If $PAGE is a title or description:**
- Use `notion_search` with the title as the query
- Present matches and ask user to confirm the right one

### Step 2: Read the Page Content

Use `notion_get_page_content` (or equivalent block-reading tool) to retrieve the full page text.

Extract:
- **Meeting title** (page title or first heading)
- **Date** (from title, page properties, or content — format as YYYY-MM-DD)
- **Attendees** (look for attendee/participants section, or names mentioned)
- **Topics discussed** (headings, sections)
- **Decisions made** (look for "Decision:", "Decided:", "Agreed:" patterns)
- **Action items** (look for checkboxes, "Action:", "TODO:", "AI:", "Follow-up:" patterns, or any task-like lines)

### Step 3: Extract Action Items

For each action item found:
- Identify **owner** (who is responsible — default to user if unclear)
- Identify **description** (what needs to be done)
- Identify **due date** if mentioned

**Items owned by user** → add to `03-Tasks/Tasks.md` using `work_mcp_create_task`
**Items owned by others** → note in the meeting summary as "waiting on [person]"

### Step 4: Update Person Pages

For each attendee identified:

1. Look up their person page in `05-Areas/People/Internal/` or `05-Areas/People/External/`
2. If page exists, append to their Meeting History section:
   ```
   - [[YYYY-MM-DD]] - [Meeting Title] (Notion: [page URL])
   ```
3. If page doesn't exist, ask: "No person page for [Name] — want me to create one?"
   - If yes, create a basic page with name, any role/company info found in the notes

### Step 5: Link to Projects

Search `04-Projects/` for projects related to topics discussed.
If found, note the meeting in the project file under a "Recent Meetings" or "Activity" section.

### Step 6: Summary

Output a brief summary:

```
✅ Processed: [Meeting Title] ([Date])

**Attendees:** [Names]

**Tasks created ([N]):**
- [ ] [Task description] (owner: you)
- [ ] ...

**Waiting on:**
- [Person]: [what they committed to]

**Person pages updated:** [Names]
**Projects linked:** [Names]

**Key decisions:**
- [Decision 1]
- [Decision 2]
```

Then ask: "Anything I missed or got wrong?"
