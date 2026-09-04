---
name: process-meetings
description: "Turn synced meetings into updated person pages, extracted tasks and organized notes. Use when the user says 'process my meetings', 'catch up my notes', or after Granola/Otter syncs. Also use proactively when unprocessed meetings exist. Not for prepping an upcoming meeting; use `meeting-prep`."
model_hint: balanced
---

<!-- Generated from `.claude/skills/process-meetings/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## Execution mode

Run inline in the current conversation by default, so this work can see what the
user has already discussed, decided, or settled this session. Do not fork merely
because this skill was selected. Only run in the background when the user
explicitly asks for a background run or the host has already obtained a specific
background-work approval for this run.

### Delegated gathering (large-vault scaling)

This skill stays inline as described above: it keeps session awareness, it asks
the user the questions, and it owns every interactive step. What it does NOT do
inline is the bulk read-gathering, which on a mature vault (hundreds of notes,
thousands of indexed messages, a live calendar and multiple integrations) can be
large enough to exhaust the main conversation before the useful work starts.

So the gathering-and-processing phase is delegated to one `general-purpose`
subagent via the Agent tool, using the self-contained prompt in this skill's
`AGENT_INSTRUCTIONS.md`:

1. Read `.agents/skills/process-meetings/AGENT_INSTRUCTIONS.md`.
2. Substitute its placeholders (`{{ARGS}}`, the arguments passed to this skill).
3. Call the Agent tool with `subagent_type: "general-purpose"`, that prompt, and
   a short description.
4. Display its summary report.

The subagent inherits MCP connections, runs in its own context, and that context
is freed when it completes, so only its findings reach this conversation.

**Use `AGENT_INSTRUCTIONS.md` verbatim.** Read the file and pass its content as
the subagent prompt, substituting only the placeholders. Do NOT hand-write a
replacement brief from what you already know about the meetings: that is how
steps get silently dropped, and the omission looks complete because nothing
errors. If context from this conversation is worth adding, APPEND it to the
file's content; never substitute for it.

**Two caveats that are load-bearing:**

- **Do not count on this skill's hook for the subagent's writes.** The
  PostToolUse hook `post-meeting-person-update.cjs` is declared in this
  SKILL.md's frontmatter, so it belongs to this skill's run and must not be
  assumed to cover a subagent's writes. `AGENT_INSTRUCTIONS.md` therefore has
  the subagent update person pages itself. Do not remove that instruction
  believing the hook covers it. It is also safe if the hook does run for those
  writes: both write the same "Recent Interactions" line format, and both skip
  a person page that already references the meeting, so the entry cannot be
  added twice.
- **Always fall back.** If the subagent fails, times out, or returns nothing
  usable, say so plainly and run the processing inline from the same
  `AGENT_INSTRUCTIONS.md`. A missing subagent must never mean a missing result.

**Stays inline:** the background-sync status check when it needs setup guidance
(`--setup`), the Granola pre-flight message when no API key is connected,
confirming each detected soft commitment before any task is created, resolving
ambiguous person matches and entity suggestions, and presenting the final
summary report.

**Check the report for unstamped meetings.** The subagent leaves a meeting
without its `tasks-extracted` marker whenever a task failed to create or stamp,
and reports the exact failing line. Surface those lines rather than burying
them: an unstamped meeting is the safe state, but it stays flagged as waiting
until someone resolves it.

**The report is a claim, not evidence — check it before repeating it.** This
subagent writes to the vault, and its summary states counts the user will act
on. Before displaying it, verify the claims cheaply against the vault:

- Every task it says it created: confirm the ID appears in `03-Tasks/Tasks.md`
  (`list_tasks`, or read the file).
- Every meeting it says it stamped: confirm the `tasks-extracted` marker is
  actually in that note.
- Every person or company page it says it created: confirm the file exists.

If a claim does not hold, say so plainly in the summary you present and treat
that meeting as unprocessed. Never pass an unverified count to the user as fact,
and never repeat "processing complete" on the strength of the report alone.

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

## Pre-flight: Local Source Check

Read `meeting_sources` in `System/user-profile.yaml` before assuming a recorder.
The configured `primary` is provenance, not permission or tool access. A valid
vault-relative `notes_folder` outranks the default landing zone. Missing or
malformed config, an invalid primary, an absolute path, `..`, the vault root, or
a symlink escape must be reported and ignored; continue with safe local notes.
Never widen into an external service just because the profile names it.

For `primary: granola`, Granola sync uses the official public API. If
`GRANOLA_API_KEY` is absent, offer `/granola-setup` and continue with local
notes. Other primaries do not inherit a direct reader from this setting.

---

## Process

### Step 1: Check Source and Sync Status

Resolve `meeting_sources.notes_folder` using the rules above: only a valid
vault-relative folder is accepted; missing or malformed config, an absolute
path, `..`, the vault root, or a symlink escape falls back safely. The configured
primary does not grant access to an external service. Then check whether
Granola background sync has left its optional state file:

```bash
# Check for state file (indicates sync has run)
ls .scripts/meeting-intel/processed-meetings.json
```

**If the state file exists:** Granola background sync has run. Continue to Step 2.

**If it does not exist and Granola is the configured source:** offer setup, but
continue with local notes. The missing file is not a gate for an
`exported-folder`, Zoom, Teams, manual note, or provider-neutral local source.

For Granola setup guidance:
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
> - An LLM API key in the vault-root `.env` (GEMINI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY) — keep that file owner-only (`chmod 600 .env`)"

If user runs `--setup`:
```bash
cd .scripts/meeting-intel && ./install-automation.sh
```

### Step 2: Find Waiting Meetings

Read the processed meetings state when it exists:
```javascript
const state = JSON.parse(fs.readFileSync('.scripts/meeting-intel/processed-meetings.json'));
```

Search the valid configured folder first, then `00-Inbox/Meetings/`. If neither
contains a candidate, use bounded provider-neutral Markdown discovery in the
vault by date plus title, attendee, or meeting frontmatter. Exclude Dex
internals, dependencies, binaries, and archives outside the requested window;
never treat arbitrary Markdown as a meeting. For the default folder:
```bash
find 00-Inbox/Meetings -name "*.md" -mtime -7 | head -50
```

This includes synced notes in day directories and flat `*.md` notes in the
folder root. A manual note with no capture id is valid; process and stamp it
with the same `tasks-extracted` marker as any other meeting note. The `queue/`
subfolder is handled in Step 2.5.

For each meeting file, skip notes containing `<!-- dex:skip-processing -->`:
1. Preserve the actual vault-relative source path. Read `participants`,
   `company`, `date`, and any non-empty scalar key ending in `_id`. Prefer the
   key matching a string `source`; if that key is absent, report the mismatch
   and use the note path. When `source` is absent, use an id only when exactly
   one non-empty scalar candidate is present. `granola_id` and `wispr_id` are
   examples, not a closed list. Empty or non-scalar values do not count;
   multiple ids fall back to note-path identity.
   The path identity is the normalized vault-relative Markdown path, with `/`
   separators and the `.md` extension retained; never reduce it to a basename
2. Check if person/company pages need updating
3. Check if tasks need extracting (look for unchecked items in "For Me" section)

Report findings:
> "Found X waiting meetings from the last 7 days. Y need person page updates, Z have unextracted tasks."

#### Match capture identity to Calendar

For a synced note with an aware ISO `capture_started_at`, call
`calendar_get_events_with_attendees` for that date after applying CLAUDE.md's
**Calendar response confidence contract**, then call the Work MCP
`match_capture_to_calendar` tool with the capture title, start time, attendees,
and the Calendar response's `events` array as `calendar_events` (not the whole
response object). Use a matched result's **identity only** (title, normalized
start, attendees); if the safe title differs, carry it into the note. Leave an
unmatched or ambiguous capture unchanged, and continue unchanged when Calendar
is unavailable. The matcher owns the hard five-minute limit, timezone parsing,
tie order, poor-title rule, and ambiguity decision—never redo or stretch them.
Never copy join URLs, dial-ins, access codes, location, notes, descriptions,
conferencing fields, or any other invite payload.

### Step 2.5: Consume Queued Meetings (manual mode)

If `00-Inbox/Meetings/queue/*.json` files exist, consume each queued meeting
before continuing:

1. Read the complete JSON: `id`, `title`, `createdAt`, `participants`,
   `attendees`, `company`, `notes`, and `transcript`.
2. Check whether a meeting note with that JSON object's `id` as its
   `granola_id` already exists. If it does, delete the queue JSON and continue
   to the next one.
3. Otherwise, create the meeting note under
   `00-Inbox/Meetings/{date}/` (with `{date}` and `time` derived from
   `createdAt`) in the standard format, including frontmatter for `date`,
   `time`, `type: meeting-note`, `source: granola`, `title`, `participants`,
   `attendees`, `company`, and `granola_id` from the JSON `id`. Include the
   queued `notes` and `transcript` in the note body.
4. Delete the queue JSON only after its note has been written successfully.

The new note then flows through the normal processing steps. Never delete a queue file before its meeting note is written.

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

**Deterministic soft-commitment pass (always runs):** Independently of QMD
availability, run the `detect_soft_commitments` Work-MCP tool over each meeting's
discussion notes. Add matches to the action-items list marked
"*(soft commitment — confirm before creating)*" so Step 5 confirms, creates, and
reads back every task ID. QMD is the semantic complement; NEVER auto-create.

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

   A user can add `<!-- dex:skip-processing -->` to any meeting note to
   permanently exclude it from processing and from the session-start sweep.
   Skip such notes entirely: do not extract tasks or add a completion stamp.

   Only after every action item is verified, add this comment to the meeting note:
   ```markdown
   <!-- tasks-extracted: 2026-02-03T10:30:00Z -->
   ```

   **Also stamp meetings with nothing to extract.** If a meeting note has no
   action items (or you just added AI analysis to a basic note and found none),
   add the same `tasks-extracted` comment once processing is complete. The
   session-start check uses this marker to know a meeting is done — an
   unstamped note keeps being flagged as waiting.

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

Call the `mark_feature_used` tool on the `dex-analytics` MCP server with `process-meetings`. This ticks the feature's box in `System/usage_log.md`, which is what `/dex-level-up` reads to recommend features that have not been tried. It writes locally and sends nothing, so it runs whether or not analytics is enabled.

**Analytics (Silent):**

Call `track_event` with event_name `meeting_processed` and properties:
- `meetings_count`: number of meetings processed
- `people_created`: number of new person pages created
- `todos_extracted`: number of tasks extracted

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
