---
name: process-meetings
description: Process synced Granola meetings to update person pages, extract tasks, and organize meeting notes
model_hint: balanced
context: fork
hooks:
  PostToolUse:
    - matcher: Write
      type: command
      command: "node .claude/hooks/post-meeting-person-update.cjs"
---

# Process Meetings

Process meetings that have been synced from Granola by the background automation. Updates person pages, extracts tasks, and organizes meeting notes.

## Background Execution

This skill supports background execution. When invoked:
1. Acknowledge: "Processing [N] meetings in the background. I'll let you know when done."
2. Process all meetings
3. On completion, provide summary: "[N] meetings processed. [X] person pages updated. [Y] action items created."

## How It Works

Meetings are synced automatically every 30 minutes by a background process. This command reads those synced files and:
- Creates/updates person and company pages
- Extracts action items to 03-Tasks/Tasks.md
- Links everything together

**No terminal commands are shown** - the heavy lifting happens in the background.

## Arguments

- No arguments: Process all unprocessed meetings from the last 7 days
- `today`: Only process today's meetings
- `"search term"`: Find meetings by title/attendee
- `--people-only`: Only update person/company pages (skip tasks)
- `--no-todos`: Create notes but don't extract tasks
- `--setup`: Install/check background automation

## Pre-flight: Granola Check

Granola sync uses the official Granola public API. Desktop and mobile recordings both come through it once your Granola API key is connected. If `GRANOLA_API_KEY` isn't set (checked in the environment, then the `.env` file at the vault root), say: "Granola isn't connected yet — run `/granola-setup` to add your Granola API key (requires a Granola Business plan)." and continue with any meetings already synced.

---

## Process

### Step 1: Check Background Sync Status

First, check if background sync is set up:

```bash
# Check for state file (indicates sync has run)
ls .scripts/meeting-intel/processed-meetings.json
```

**If state file exists:** Background sync is working. Continue to Step 2.

**If state file doesn't exist:**
> "Background meeting sync isn't set up yet. This runs automatically every 30 minutes so `/process-meetings` doesn't need terminal commands.
>
> **To set up (one-time, takes 30 seconds):**
> ```bash
> cd .scripts/meeting-intel && ./install-automation.sh
> ```
>
> Or run `/process-meetings --setup` and I'll do it for you.
>
> **Requirements:**
> - A Granola Business plan, with your Granola API key connected via `/granola-setup`
> - An LLM API key in `.env` (GEMINI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY)"

If user runs `--setup`:
```bash
cd .scripts/meeting-intel && ./install-automation.sh
```

### Step 2: Find Synced Meetings

Read the processed meetings state:
```javascript
const state = JSON.parse(fs.readFileSync('.scripts/meeting-intel/processed-meetings.json'));
```

List meeting files in `00-Inbox/Meetings/`:
```bash
find 00-Inbox/Meetings -name "*.md" -mtime -7 | head -50
```

For each meeting file:
1. Read frontmatter to get `granola_id`, `participants`, `company`, `date`
2. Check if person/company pages need updating
3. Check if tasks need extracting (look for unchecked items in "For Me" section)

Report findings:
> "Found X synced meetings from the last 7 days. Y need person page updates, Z have unextracted tasks."

### Step 3: Update Person Pages

For each participant in synced meetings:

1. **Load user profile** for email domain:
   ```
   Read System/user-profile.yaml → get email_domain
   ```

2. **Classify as Internal/External:**
   - If participant email domain matches user's domain → Internal
   - Otherwise → External

3. **Look up the person with the Work MCP `lookup_person` tool.**
   - If lookup returns `ambiguous: true`, do not create a page. Surface the possible matches to the user.
   - If a match exists, update that existing page.

4. **If no match exists, call the Work MCP `create_person` tool:**
   - Pass `name`, `role` when known, `emails` from the meeting's `attendees` block, and `location` from that attendee's `location` field.
   - Pass the meeting company and a short source note when available.

<!-- What the create_person tool creates (reference only; do not hand-write this template). -->
   ```markdown
   ---
   type: person
   name: "{Name}"
   role: null
   company: "{company from meeting}"
   company_page: null
   emails: ["{lowercased email, if available}"]
   aliases: []
   location: {internal|external}
   last_interaction: {meeting date}
   ---
   # {Name}

   ## Notes

   *Auto-created from meeting on {date}*

   ## Recent Interactions

   <!-- dex:auto:recent-interactions -->
   - [{Meeting Title}](00-Inbox/Meetings/{date}/{slug}.md) — {date}
   <!-- /dex:auto -->

   ## Key Context
    ```

5. **If page exists, add meeting to Recent Interactions:**
   - Read existing page
   - Add new meeting link under "## Recent Interactions"
   - Keep max 20 entries (remove oldest if needed)
   - Update "Last Interaction" in frontmatter

### Step 4: Update Company Pages

For each unique external company domain:

1. **Check if company page exists:** `05-Areas/Companies/{Company}.md`

2. **If doesn't exist, create it:**
   ```markdown
   ---
   type: company
   name: "{Company Name}"
   domains: ["{lowercased domain}"]
   website: "{website, if known}"
   status: "Prospect"
   ---
   # {Company Name}

   ## Key Contacts

   <!-- dex:auto:key-contacts -->
   - [[05-Areas/People/External/{Person}|{Person}]]
   <!-- /dex:auto -->

   ## Meeting History

   <!-- dex:auto:meeting-history -->
   - [{Meeting Title}](00-Inbox/Meetings/{date}/{slug}.md) — {date}
   <!-- /dex:auto -->

   ## Notes

   *Auto-created from meeting on {date}*
   ```

3. **If exists, update:**
   - Add any new contacts to "Key Contacts"
   - Add meeting to "Meeting History"

### Step 4.5: Semantic Enrichment (if QMD available)

**Check if semantic search is available** by looking for `qmd` in PATH.

If available, enhance meeting processing with meaning-based intelligence:

1. **Detect implicit commitments:** For each meeting's discussion notes, search semantically:
   ```
   qmd query "we should circle back on..." --limit 3
   qmd query "let me think about..." --limit 3
   ```
   Catch soft commitments that regex action-item extraction misses.
   - Examples: "we should probably revisit the pricing model" → implicit action item
   - "I need to noodle on the migration approach" → implicit commitment
   - "Let's reconnect after the board meeting" → implicit follow-up

2. **Link meetings to projects:** For the meeting topic, search:
   ```
   qmd query "meeting topic/title" --limit 3
   ```
   against `04-Projects/` to auto-link the meeting to relevant projects that keyword matching would miss.

3. **Enrich person context:** For each new person encountered, search:
   ```
   qmd query "person name + company" --limit 3
   ```
   Find if they've been mentioned in other meetings/notes, even if they weren't a direct participant.

**Integration:**
- Add implicit commitments to the action items list with a note: "*(detected — not explicitly stated)*"
- Add project links to meeting frontmatter
- Merge person context into newly-created person pages
- If QMD unavailable, skip silently — regex extraction still works

### Step 5: Extract Tasks (unless --no-todos or --people-only)

For each meeting with unextracted tasks:

1. **Find action items** in the "## Action Items > ### For Me" section
2. **For each unchecked item** (`- [ ]`):
   - Extract task description
   - Read pillar from meeting frontmatter, then resolve it to the unique pillar
     ID in `System/pillars.yaml` by matching either `id` or display `name`
   - Preserve the exact source checkbox line text for `stamp_source_line`
   - Let `create_task` generate the task ID and stamp it back onto that line

3. **Create task** using Work MCP:
   ```
   create_task(
     title: "Task description",
     priority: "P2",  // default, P1 if "urgent" mentioned
     pillar: "{resolved pillar ID}",
     people: ["{participant page paths}"],
     source: "{meeting path}",
     stamp_source_line: "{exact source checkbox line text}"
   )
   ```

   `people` values must resolve to existing person page paths. Prefer the paths
   returned by Step 3's `lookup_person`/`create_person` flow; if only a bare
   participant name is available, pass that name unchanged and let `create_task`
   resolve it. Never construct or guess a person page path.

4. **Verify every result before marking the meeting extracted:**
   - Require `success: true` for every `create_task` call.
   - Require either `stamp.stamped: true`, or `reason: "already_anchored"`
     with the exact source line's existing anchor equal to the returned
     `task.task_id`.
   - If entity resolution or stamping is unresolved, surface the exact failed
     line and leave the meeting unmarked for reconciliation. Do not blindly
     retry a task that was created but not stamped.

   Only after every action item is verified, add this comment to the meeting note:
   ```markdown
   <!-- tasks-extracted: 2026-02-03T10:30:00Z -->
   ```

### Step 6: Auto-link People in Processed Notes

After finishing edits to each processed meeting note, run this once for every processed note:
```bash
node .scripts/auto-link-people.cjs "<note-file>"
```

Use `node .scripts/auto-link-people.cjs --dry-run "<note-file>"` to preview what would be linked without changing the file.

### Step 7: Verify Entity Coverage

Run `node .scripts/meeting-intel/verify-entities.cjs` and show its one-line summary.
If `ENTITY_SUGGESTIONS_FILE` contains suggested people, list them and ask: "Want me to create these pages? (creates via `create_person`; `dismiss` or `never` also fine)"

- Accepted: call `create_person`, set the suggestion to `accepted`, and set the contact state to `created` with its page path.
- Dismissed: set the suggestion to `dismissed`.
- Never: set the suggestion to `suppressed`.

### Step 8: Summary Report

```
## Meeting Processing Complete ✅

**Synced meetings found:** X (last 7 days)
**Background sync status:** Running (last sync: 10 min ago)

### Updates Made

**Person pages:**
- Created: 3 new (Alice Chen, Bob Smith, Carol Wang)
- Updated: 5 existing

**Company pages:**
- Created: 1 new (Acme Corp)
- Updated: 2 existing

**Tasks extracted:** 7 items added to 03-Tasks/Tasks.md

### Recent Meetings

| Date | Meeting | Company | Participants |
|------|---------|---------|--------------|
| Feb 3 | Product Review | Acme | Alice, Bob |
| Feb 2 | Strategy Call | BigCo | Carol |

---
*Background sync runs every 30 min. Check status: `.scripts/meeting-intel/install-automation.sh --status`*
```

## Error Handling

For MCP responses, follow CLAUDE.md's `feature_status` rendering convention before applying these fallbacks.

**If no meetings found:**
> "No meetings synced in the last 7 days. Make sure:
> 1. Your Granola API key is connected (run `/granola-setup` if not)
> 2. Background sync is set up (run `/process-meetings --setup`)
> 3. Check logs: `.scripts/logs/meeting-intel.stdout.log`"

**If background sync isn't running:**
> "Background sync appears to be stopped. To restart:
> ```bash
> cd .scripts/meeting-intel && ./install-automation.sh
> ```"

## Examples

```
/process-meetings
```
> "Found 8 synced meetings. Updating 12 person pages, extracting 5 tasks..."

```
/process-meetings today
```
> "Found 2 meetings from today. Processing..."

```
/process-meetings --setup
```
> "Installing background automation..." [runs install script]

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
