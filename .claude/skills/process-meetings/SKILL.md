---
name: process-meetings
description: Process Granola meetings to extract insights and update person pages
---

---
name: process-meetings
description: Process unprocessed meetings from Granola using Claude directly
---

# Process Meetings from Granola

Process meetings captured by Granola that haven't been analyzed yet. Uses Claude directly — no API key required.

## Task

Find and process all unprocessed meetings from Granola, extracting structured insights, action items, and updating person pages.

## Arguments

- No arguments: Process all unprocessed meetings from the last 7 days (full processing)
- `today`: Only process today's meetings
- `"search term"`: Find and process a specific meeting by title/attendee
- `--people-only`: Create/update person and company pages only, skip meeting notes and todos
- `--no-todos`: Create meeting notes and update person pages, but don't extract todos
- `--days-back=N`: Override default 7-day lookback (e.g., `--days-back=30` or `--days-back=365`)

**Flag combinations:**
- `/process-meetings --people-only --days-back=365` - Backfill all people/companies from history
- `/process-meetings --no-todos --days-back=30` - Create notes from last month without overwhelming todos
- `/process-meetings today --no-todos` - Process today's meetings for notes only

**Parsing logic:**
```python
def parse_arguments(user_input: str) -> dict:
    """Parse /process-meetings arguments"""
    
    flags = {
        'people_only': '--people-only' in user_input,
        'no_todos': '--no-todos' in user_input,
        'days_back': 7,  # default
        'mode': 'all'  # or 'today' or 'search'
    }
    
    # Check for days_back override
    import re
    days_match = re.search(r'--days-back=(\d+)', user_input)
    if days_match:
        flags['days_back'] = int(days_match.group(1))
    
    # Check for special modes
    if 'today' in user_input.lower():
        flags['mode'] = 'today'
    elif '"' in user_input or any(word not in ['--people-only', '--no-todos', '--days-back'] 
                                   for word in user_input.split()):
        # Has search term
        flags['mode'] = 'search'
        flags['search_term'] = extract_search_term(user_input)
    
    return flags
```

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

Parse arguments first:
```python
flags = parse_arguments(user_input)
days_back = flags['days_back']
mode = flags['mode']
```

**If mode == "all" (default):**
```
granola_get_recent_meetings(days_back=days_back, limit=1000)
```

**If mode == "today":**
```
granola_get_today_meetings()
```

**If mode == "search":**
```
granola_search_meetings(query=flags['search_term'], days_back=days_back)
```

### Step 3: Filter to Unprocessed

For each meeting returned, check if it's already been processed:

1. Generate the expected output path: `00-Inbox/Meetings/YYYY-MM-DD/{slugified-title}.md`
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

3. **Analyze the meeting content (conditional based on flags):**

   **If `--people-only` flag:**
   - Skip meeting content analysis
   - Skip to Step 6 (Create/update person pages)
   - Skip meeting note creation (Step 5)
   - Skip todo extraction
   - Only update person and company pages

   **Otherwise, generate structured analysis covering:**

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
   - For the user (with unique task IDs for cross-file sync)
   - For other participants (tagged with @Name)

   **Customer Intelligence** (if enabled in user-profile.yaml)
   - Pain points mentioned
   - Feature requests
   - Competitive mentions

   **Career Development Context** (if Career folder exists in 05-Areas/)
   - If meeting is with manager (check 05-Areas/People/ folder for role="manager"):
     - Feedback received (positive or constructive)
     - Development discussions (skills, growth, goals)
     - Performance-related comments
     - Career advice or guidance
   - Extract ONLY if explicitly mentioned in meeting content

   **Pillar Classification**
   - Which strategic pillar this meeting aligns with
   - Brief rationale

4. **Classify attendees by domain:**

   - Load user's `email_domain` from `System/user-profile.yaml`
   - For each participant with email:
     - Extract domain from email (e.g., "alice@pendo.io" -> "pendo.io")
     - If domain matches user's domain (or in user's domain list) -> **Internal**
     - If domain doesn't match -> **External**
     - Track external domains for company page creation
   
   - For participants without email:
     - Default to **External** (safer assumption)
     - Note for user review in summary

5. **Create meeting note:**

   Write to `00-Inbox/Meetings/YYYY-MM-DD/{slug}.md` with:

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
   **Participants:** [[05-Areas/People/Internal/Name_1|Name 1]], [[05-Areas/People/External/Name_2|Name 2]]
   **Company:** [[05-Areas/Companies/Company|Company]]

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
   - [ ] [Task description] ^task-YYYYMMDD-XXX

   ### For Others
   - [ ] @Name: [Task description]

   ## Customer Intelligence

   **Pain Points:**
   - [Pain point or "None identified"]

   **Feature Requests:**
   - [Request or "None identified"]

   **Competitive Mentions:**
   - [Mention or "None identified"]

   ## Career Development

   *(Included only if meeting is with manager AND career-related topics discussed)*

   **Feedback Received:**
   - [Positive feedback or "None"]
   - [Constructive feedback or "None"]

   **Development Discussion:**
   - [Topics covered or "None"]

   **Action Items for Growth:**
   - [Career-related actions or "None"]

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

5. **Create tasks in 03-Tasks/Tasks.md (conditional):**

   **If `--no-todos` flag is set:**
   - Skip task creation entirely
   - Meeting notes will show action items but they won't be added to 03-Tasks/Tasks.md
   - Useful for backfilling meeting history without overwhelming task list

   **Otherwise, for each "For Me" action item extracted:**
   - Generate a unique task ID using the format: `task-YYYYMMDD-XXX` (sequential number for the day)
   - Add the task ID to the action item in the meeting note
   - Use the Work MCP `create_task` tool to create the task in `03-Tasks/Tasks.md` with:
     - Title: The action item description
     - Task ID: The same ID used in the meeting note (include in the task line)
     - Pillar: Auto-classified based on meeting content
     - Priority: Guessed from context (P0 for urgent, P1 for follow-ups, P2 default)
     - People: Link to relevant person pages from the meeting
   - This ensures tasks appear in both the meeting note AND 03-Tasks/Tasks.md with the same ID for sync

6. **Create/update person pages with domain routing:**

   For each participant:
   - Determine Internal vs External from step 4 classification
   - Check if person page exists:
     - `05-Areas/People/Internal/{Name}.md` (if internal)
     - `05-Areas/People/External/{Name}.md` (if external)
   - If doesn't exist and has email:
     - Create person page in appropriate folder
     - Extract company from email domain (e.g., "acme.com" -> "Acme")
     - Link to company page: `05-Areas/Companies/{Company}.md`
   - If exists, add meeting reference to "Recent Interactions" section
   - Track newly created people for summary report

7. **Create/update company pages for external domains:**

   For each unique external domain detected:
   - Generate company name from domain (e.g., "acme.com" -> "Acme Corp")
   - Check if company page exists: `05-Areas/Companies/{Company_Name}.md`
   - If doesn't exist:
     - Create from `System/Templates/Company.md`
     - Populate:
       - Company name (derived from domain)
       - Website (domain)
       - Domains field (list of domains, e.g., "acme.com, acme.io")
       - Stage: "Unknown" (user can update later)
     - Add placeholder in "Key Contacts" section
   - If exists:
     - Verify domain is in "Domains" field, add if missing
   - Link person pages to company page
   - Track newly created companies for summary report

8. **Update career files (if applicable):**

   If the meeting contained career development context:
   - Check if `05-Areas/Career/` folder exists
   - If yes and feedback was received, append to `05-Areas/Career/Review_History.md`:
     
     ```markdown
     ## YYYY-MM-DD - 1:1 with [Manager Name] (Informal)
     
     **Feedback Received:**
     - [Feedback points]
     
     **Development Discussion:**
     - [Topics]
     
     **Action Items:**
     - [ ] [Actions]
     
     *Source: [Link to meeting note]*
     
     ---
     ```
   
   - Suggest capturing significant achievements as career evidence:
     > "This meeting mentioned [ACHIEVEMENT]. Want to save this to Career Evidence?"

### Step 8: Summary Report

After processing all meetings, provide a summary adapted to the processing mode:

**Standard mode (full processing):**
```
## Meeting Processing Complete ✅

**Processed:** X meetings (from last [days_back] days)
**Skipped:** Y (already processed)

### Meetings Processed

| Meeting | Date | Participants | Pillar |
|---------|------|--------------|--------|
| [Title] | Jan 22 | Alice, Bob | deal-support |
| [Title] | Jan 21 | Carol | product-feedback |

### Action Items Created

**For you (added to 03-Tasks/Tasks.md):**
- [ ] [Task from meeting 1] ^task-YYYYMMDD-001
- [ ] [Task from meeting 2] ^task-YYYYMMDD-002

*Tasks are synced between meeting notes and 03-Tasks/Tasks.md via task IDs*

**For others:**
- @Alice: [Task]
- @Bob: [Task]

### People & Companies

**Internal colleagues (05-Areas/People/Internal/):**
- Alice Smith (alice@pendo.io)
- Bob Jones (bob@pendo.io)

**External contacts (05-Areas/People/External/):**
- Carol Chen (carol@acme.com) - Acme Corp
- David Kim (david@bigco.com) - BigCo Inc

**External companies (05-Areas/Companies/):**
- Acme Corp (acme.com) - 3 attendees
- BigCo Inc (bigco.com) - 1 attendee

**Needs review (no email provided):**
- Eve Martinez - Defaulted to External, please review
```

**People-only mode (`--people-only`):**
```
## People & Companies Update Complete ✅

**Processed:** X meetings (from last [days_back] days)
**Mode:** People and companies only (no meeting notes or todos created)

### People Updated

**Internal colleagues (05-Areas/People/Internal/):**
• Created: [N] new pages
• Updated: [M] existing pages
• Total internal: [I] people

**External contacts (05-Areas/People/External/):**
• Created: [N] new pages
• Updated: [M] existing pages
• Total external: [E] people

### Companies Updated

**External companies (05-Areas/Companies/):**
• Created: [N] new pages
• Updated: [M] existing pages
• Domains tracked: [list]

**Next steps:**
• Run `/process-meetings --no-todos --days-back=30` to backfill meeting notes
• Or `/process-meetings` to process with full todos going forward
```

**No-todos mode (`--no-todos`):**
```
## Meeting Processing Complete ✅

**Processed:** X meetings (from last [days_back] days)
**Mode:** Notes and people (no todos created)

### Meetings Processed

| Meeting | Date | Participants | Notes |
|---------|------|--------------|-------|
| [Title] | Jan 22 | Alice, Bob | Created in 00-Inbox/Meetings/ |
| [Title] | Jan 21 | Carol | Created in 00-Inbox/Meetings/ |

### Action Items (documented but not tracked)

Action items were documented in meeting notes but NOT added to 03-Tasks/Tasks.md:
- Meeting 1: [X] action items identified
- Meeting 2: [Y] action items identified

**To track these tasks:** Review meeting notes and manually add relevant items

### People & Companies

[Standard people/companies summary]

**Next steps:**
• Review meeting notes in 00-Inbox/Meetings/
• Manually add relevant action items to 03-Tasks/Tasks.md
• Or run `/process-meetings` without flags to track todos going forward
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

**Process everything (default):**
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

**Backfill people and companies from all history:**
```
/process-meetings --people-only --days-back=365
```
> "Processing 342 meetings (people-only mode)..."
> "Created 87 person pages, 23 company pages. No meeting notes or todos created."

**Backfill meeting notes without overwhelming todos:**
```
/process-meetings --no-todos --days-back=30
```
> "Processing 45 meetings from last 30 days (no-todos mode)..."
> "Created 45 meeting notes, updated person pages. Action items documented but not tracked."

**Process last 90 days with full tracking:**
```
/process-meetings --days-back=90
```
> "Processing 67 meetings from last 90 days..."
> "Created 67 meeting notes, extracted 89 todos, updated 34 person pages."

**Today's meetings, notes only:**
```
/process-meetings today --no-todos
```
> "Processing today's 3 meetings (no-todos mode)..."
> "Created 3 meeting notes. Action items documented in notes but not tracked."
