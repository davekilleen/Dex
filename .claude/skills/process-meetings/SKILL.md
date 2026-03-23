---
name: process-meetings
description: Process meetings from Otter.ai to update person pages, extract tasks, and organize meeting notes
model_hint: balanced
context: fork
hooks:
  PostToolUse:
    - matcher: Write
      type: command
      command: "node .claude/hooks/post-meeting-person-update.cjs"
  Stop:
    - type: command
      command: "node .claude/hooks/meeting-summary-generator.cjs"
---

# Process Meetings (Otter.ai)

Fetch and process meetings from Otter.ai via the connected MCP. Updates person pages, extracts tasks, and organizes meeting notes in the vault.

**No background sync needed** — Otter.ai MCP pulls meetings on-demand from the cloud.

## Background Execution

This skill supports background execution. When invoked:
1. Acknowledge: "Processing [N] meetings in the background. I'll let you know when done."
2. Process all meetings
3. On completion, provide summary: "[N] meetings processed. [X] person pages updated. [Y] action items created."

## Arguments

- No arguments: Process all unprocessed meetings from the last 7 days
- `today`: Only process today's meetings
- `"search term"`: Find meetings by title/attendee/topic
- `--people-only`: Only update person/company pages (skip tasks)
- `--no-todos`: Create notes but don't extract tasks

## Process

### Step 1: Get User Context

Call `mcp__claude_ai_Otter_ai__get_user_info()` to get the current user's name and email. This is required before searching.

### Step 2: Search for Meetings

Call `mcp__claude_ai_Otter_ai__search()` with appropriate date filters:

- **Default (no args):** `created_after` = 7 days ago, `created_before` = today
- **`today`:** `created_after` = today, `created_before` = today
- **`"search term"`:** Pass as `query` parameter with 7-day date range
- Set `username` to the name from Step 1
- Set `include_shared_meetings` to `true`

Date format for Otter.ai: `YYYY/MM/DD`

### Step 3: Check Already-Processed Meetings

Read `00-Inbox/Meetings/` to find existing meeting notes. Compare Otter.ai meeting IDs (stored in frontmatter `otter_id`) against search results to skip already-processed meetings.

If no new meetings found:
> "No new meetings to process. All [X] meetings from the last 7 days are already in your vault."

### Step 4: Fetch Full Transcripts

For each unprocessed meeting, call `mcp__claude_ai_Otter_ai__fetch(id)` using the speech OTID from search results.

### Step 5: Create Meeting Notes

For each fetched meeting, create a note at `00-Inbox/Meetings/YYYY-MM-DD - {Meeting Title}.md`:

```markdown
---
date: YYYY-MM-DD
otter_id: "{meeting_id}"
source: otter
participants:
  - Name1
  - Name2
company: "{inferred from participants/context}"
pillar: "{inferred from content}"
---

# {Meeting Title}

**Date:** YYYY-MM-DD
**Participants:** Name1, Name2, ...

## Summary

{Otter.ai summary or AI-generated summary from transcript}

## Key Discussion Points

{Extracted from outline/transcript}

## Decisions

{Decisions made during the meeting}

## Action Items

### For Me

- [ ] {action item} ^task-YYYYMMDD-XXX

### For Others

- [ ] {person}: {action item}

## Notes

{Additional context, quotes, or details worth preserving}

<!-- processed: {ISO timestamp} -->
```

**Content extraction guidance:**
- Use Otter.ai's built-in summary, outline, and action items as starting points
- Enhance with transcript context where the summary is thin
- Apply meeting intelligence settings from `System/user-profile.yaml` (extract_customer_intel, extract_competitive_intel, etc.)
- Infer pillar from content using keywords in `System/pillars.yaml`

### Step 6: Update Person Pages

For each participant in processed meetings:

1. **Load user profile** for email domain:
   ```
   Read System/user-profile.yaml → get email_domain
   ```

2. **Classify as Internal/External:**
   - If participant email domain matches user's domain → Internal
   - Otherwise → External
   - If no email available, default to External

3. **Check if person page exists:**
   - Internal: `05-Areas/People/Internal/{Firstname_Lastname}.md`
   - External: `05-Areas/People/External/{Firstname_Lastname}.md`

4. **If page doesn't exist, create it:**
   ```markdown
   # {Name}

   ## Overview

   | Field | Value |
   |-------|-------|
   | **Company** | {company from meeting} |
   | **Email** | {if available} |
   | **First Met** | {meeting date} |

   ## Recent Interactions

   - [{Meeting Title}](00-Inbox/Meetings/{filename}) — {date}

   ## Notes

   *Auto-created from meeting on {date}*
   ```

5. **If page exists, add meeting to Recent Interactions:**
   - Read existing page
   - Add new meeting link under "## Recent Interactions"
   - Keep max 20 entries (remove oldest if needed)
   - Update "Last Interaction" in frontmatter

### Step 7: Update Company Pages

For each unique external company:

1. **Check if company page exists:** `05-Areas/Companies/{Company}.md`

2. **If doesn't exist, create it:**
   ```markdown
   # {Company Name}

   ## Overview

   | Field | Value |
   |-------|-------|
   | **Website** | {domain if known} |
   | **Stage** | Unknown |
   | **First Contact** | {date} |

   ## Key Contacts

   - [[05-Areas/People/External/{Person}|{Person}]]

   ## Meeting History

   - [{Meeting Title}](00-Inbox/Meetings/{filename}) — {date}

   ## Notes

   *Auto-created from meeting on {date}*
   ```

3. **If exists, update:**
   - Add any new contacts to "Key Contacts"
   - Add meeting to "Meeting History"

### Step 7.5: Semantic Enrichment (if QMD available)

**Check if semantic search is available** by looking for `qmd` in PATH.

If available, enhance meeting processing with meaning-based intelligence:

1. **Detect implicit commitments:** Search semantically for soft language like "we should circle back on..." or "let me think about..." that regex misses.

2. **Link meetings to projects:** Search `04-Projects/` for thematically related projects.

3. **Enrich person context:** Find if participants have been mentioned in other notes.

**Integration:**
- Add implicit commitments to action items with note: "*(detected — not explicitly stated)*"
- Add project links to meeting frontmatter
- Merge person context into newly-created person pages
- If QMD unavailable, skip silently

### Step 8: Extract Tasks (unless --no-todos or --people-only)

For each meeting with action items:

1. **Find action items** in the "## Action Items > ### For Me" section
2. **For each unchecked item** (`- [ ]`):
   - Extract task description
   - Get task ID (format: `^task-YYYYMMDD-XXX`)
   - Read pillar from meeting frontmatter

3. **Create task** using Work MCP:
   ```
   create_task(
     title: "Task description",
     priority: "P2",  // default, P1 if "urgent" mentioned
     pillar: "{from meeting}",
     people: ["{participants}"],
     source: "meeting:{meeting-path}"
   )
   ```

4. **Mark as extracted** by adding comment to meeting note:
   ```markdown
   <!-- tasks-extracted: {ISO timestamp} -->
   ```

### Step 9: Summary Report

```
## Meeting Processing Complete ✅

**Meetings found:** X (last 7 days)
**New meetings processed:** Y
**Source:** Otter.ai

### Updates Made

**Person pages:**
- Created: N new (names...)
- Updated: N existing

**Company pages:**
- Created: N new (names...)
- Updated: N existing

**Tasks extracted:** N items added to 03-Tasks/Tasks.md

### Processed Meetings

| Date | Meeting | Participants |
|------|---------|--------------|
| Mar 14 | Product Review | Alice, Bob |
| Mar 13 | Strategy Call | Carol |
```

## Error Handling

**If no meetings found:**
> "No meetings found in Otter.ai for the last 7 days. Make sure your meetings are being recorded in Otter.ai."

**If Otter.ai MCP is not connected:**
> "Otter.ai MCP is not available. Make sure it's connected in your Claude settings."

## Examples

```
/process-meetings
```
> "Found 8 meetings in Otter.ai. 5 are new. Processing..."

```
/process-meetings today
```
> "Found 2 meetings from today. Processing..."

```
/process-meetings "product review"
```
> "Found 3 meetings matching 'product review'. Processing..."

```
/process-meetings --people-only
```
> "Updating person and company pages only (skipping task extraction)..."

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark meeting processing as used.

**Analytics (Silent):**

Call `track_event` with event_name `meetings_processed` and properties:
- `meetings_count`: number of meetings processed
- `people_created`: number of new person pages created
- `todos_extracted`: number of tasks extracted

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
