---
name: process-meetings
description: Process unprocessed meetings from Granola using Claude directly
---

# Process Meetings from Granola

Process meetings captured by Granola that haven't been analyzed yet. Uses Claude directly — no API key required.

## Task

Find and process all unprocessed meetings from Granola, extracting structured insights, action items, and updating person pages.

## Arguments

- No arguments: Process all unprocessed meetings from the last 7 days
- `today`: Only process today's meetings
- `"search term"`: Find and process a specific meeting by title/attendee

## Process

### Step 1: Check Granola Availability

First, verify Granola is installed and has data:

```
granola_check_available()
```

If not available, say:
> "Granola doesn't appear to be installed, or hasn't captured any meetings yet. 
> 
> **To use Granola:**
> 1. Download from [granola.ai](https://granola.ai)
> 2. Run it during your next meeting
> 3. Come back and run `/process-meetings` again
>
> Want me to help with something else instead?"

### Step 2: Get Meetings to Process

**If no arguments (default):**
```
granola_get_recent_meetings(days_back=7, limit=50)
```

**If "today":**
```
granola_get_today_meetings()
```

**If search term provided:**
```
granola_search_meetings(query="search term", days_back=30)
```

### Step 3: Filter to Unprocessed

For each meeting returned, check if it's already been processed:

1. Generate the expected output path: `Inbox/Meetings/YYYY-MM-DD/{slugified-title}.md`
2. Check if that file exists
3. If it exists, check frontmatter for matching `granola_id`
4. If match found → skip (already processed)
5. If no match → add to processing queue

Report what was found:
> "Found X meetings from Granola, Y already processed, Z to process."

If nothing to process:
> "All caught up! No new meetings to process."

### Step 4: Process Each Meeting

For each unprocessed meeting:

1. **Get full details:**
   ```
   granola_get_meeting_details(meeting_id="...")
   ```

2. **Read user profile for context:**
   - Load `System/user-profile.yaml` for name, role, intelligence preferences
   - Load `System/pillars.yaml` for pillar classification

3. **Analyze the meeting content:**

   Generate structured analysis covering:

   **Summary** (2-3 sentences)
   - What was the meeting about?
   - What were the key outcomes?

   **Key Discussion Points**
   - Major topics with context
   - Important details mentioned

   **Decisions Made**
   - Explicit decisions that were made
   - Who made them / who agreed

   **Action Items**
   - For the user (with block IDs for task tracking)
   - For other participants (tagged with @Name)

   **Customer Intelligence** (if enabled in user-profile.yaml)
   - Pain points mentioned
   - Feature requests
   - Competitive mentions

   **Pillar Classification**
   - Which strategic pillar this meeting aligns with
   - Brief rationale

4. **Create meeting note:**

   Write to `Inbox/Meetings/YYYY-MM-DD/{slug}.md` with:

   ```markdown
   ---
   date: YYYY-MM-DD
   time: HH:MM
   type: meeting-note
   source: granola
   title: "Meeting Title"
   participants: ["Name 1", "Name 2"]
   company: "Company Name"
   pillar: pillar-id
   granola_id: original-id
   processed: ISO-timestamp
   ---

   # Meeting Title

   **Date:** YYYY-MM-DD HH:MM
   **Participants:** [[People/External/Name_1|Name 1]], [[People/External/Name_2|Name 2]]
   **Company:** [[Active/Relationships/Companies/Company|Company]]

   ---

   ## Summary

   [Generated summary]

   ## Key Discussion Points

   ### [Topic 1]
   [Details]

   ## Decisions Made

   - [Decision 1]

   ## Action Items

   ### For Me
   - [ ] [Task] ^mt-YYYY-MM-DD-xxxx

   ### For Others
   - [ ] @Name: [Task]

   ## Customer Intelligence

   **Pain Points:**
   - [Pain point or "None identified"]

   **Feature Requests:**
   - [Request or "None identified"]

   **Competitive Mentions:**
   - [Mention or "None identified"]

   ---

   ## Raw Content

   <details>
   <summary>Original Notes</summary>

   [Original notes from Granola]

   </details>

   <details>
   <summary>Transcript (X words)</summary>

   [Transcript excerpt]

   </details>

   ---
   *Processed by Dex Meeting Intelligence*
   ```

5. **Update person pages:**

   For each participant:
   - Check if person page exists in `People/External/` or `People/Internal/`
   - If exists, add meeting reference to their "Recent Interactions" section
   - If doesn't exist and seems significant (multiple meetings, key stakeholder), note it for user

### Step 5: Summary Report

After processing all meetings, provide a summary:

```
## Meeting Processing Complete ✅

**Processed:** X meetings
**Skipped:** Y (already processed)

### Meetings Processed

| Meeting | Date | Participants | Pillar |
|---------|------|--------------|--------|
| [Title] | Jan 22 | Alice, Bob | deal-support |
| [Title] | Jan 21 | Carol | product-feedback |

### Action Items Extracted

**For you:**
- [ ] [Task from meeting 1]
- [ ] [Task from meeting 2]

**For others:**
- @Alice: [Task]
- @Bob: [Task]

### New People Detected

These participants don't have person pages yet:
- **Alice Smith** (alice@acme.com) - 2 meetings
- **Bob Jones** (bob@bigco.com) - 1 meeting

Want me to create person pages for any of them?
```

## Error Handling

**If Granola cache is corrupted:**
> "Had trouble reading Granola's data. Try quitting and reopening Granola, then run `/process-meetings` again."

**If meeting has no content:**
Skip silently (brief meetings without notes/transcript aren't worth processing)

**If analysis fails for a meeting:**
Log the error, continue with remaining meetings, report at end:
> "Processed X meetings successfully. 1 meeting couldn't be processed: [title] - [reason]"

## Examples

**Process everything:**
```
/process-meetings
```
> "Found 12 meetings from the last 7 days. 8 already processed, 4 to process..."

**Just today:**
```
/process-meetings today
```
> "Found 3 meetings from today. Processing..."

**Find specific meeting:**
```
/process-meetings "Acme"
```
> "Found 2 meetings matching 'Acme'. Processing..."
