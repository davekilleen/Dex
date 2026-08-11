# Process Meetings - Agent Instructions

You are processing synced meetings to update the vault. Your job is to find
unprocessed meetings, update person and company pages, extract tasks, and link
everything together.

**IMPORTANT:** Do not count on the parent skill's PostToolUse hook
(`post-meeting-person-update.cjs`) to cover your writes -- it is declared in that
skill's frontmatter and belongs to its run, not yours. Perform person-page
updates directly. Following the line format in Step 3 keeps this safe even if the
hook does also run, because both skip a page that already lists the meeting.

**Arguments:** {{ARGS}}
- No args: process all unprocessed meetings from the last 7 days
- `today`: only process today's meetings
- `"search term"`: find meetings by title or attendee
- `--people-only`: only update person/company pages (skip tasks)
- `--no-todos`: create notes but do not extract tasks

---

## Step 1: Check Background Sync Status

From the vault root:

```bash
ls .scripts/meeting-intel/processed-meetings.json
```

If the state file exists, continue. If not, stop and return a message telling
the conversation that background sync is not set up (the conversation will
guide the user through `--setup`); do not attempt setup yourself.

---

## Step 2: Find Waiting Meetings

Read the processed meetings state:

```bash
cat .scripts/meeting-intel/processed-meetings.json
```

List meeting files:

```bash
find 00-Inbox/Meetings -name "*.md" -mtime -7 | head -50
```

This includes synced notes in day directories and flat notes in the folder
root (manually captured meetings with no `granola_id`); process and stamp those
the same way. Skip notes containing `<!-- dex:skip-processing -->`.

If `00-Inbox/Meetings/queue/*.json` files exist, consume each queued meeting
first, following the queue rules in this skill's `SKILL.md` (Step 2.5): create
the meeting note from the JSON, and delete the queue file only after its note
has been written successfully.

**Reading `SKILL.md` safely.** You need only the section named above. Ignore that
file's "Delegated gathering" section entirely: it describes how you were
invoked. You ARE the subagent, so you must never call the Agent tool or spawn a
subagent of your own.

For each meeting file:
1. Read frontmatter for `granola_id`, `participants`, `company`, `date`
2. Check whether person/company pages need updating
3. Check whether tasks need extracting (unchecked items in the "For Me"
   section, no `tasks-extracted` marker)

---

## Step 3: Update Person Pages

Read `System/user-profile.yaml` to get `email_domain` for Internal/External
routing.

For each participant in synced meetings:

1. **Classify as Internal/External:** participant email domain matches the
   user's domain means Internal; otherwise External
2. **Look up the person** with `lookup_person(name="...")`. If the lookup
   returns `ambiguous: true`, do not create a page; report the possible
   matches in your final output for the user to resolve
3. **If no match exists**, call `create_person` with `name`, `role` when
   known, `emails` from the meeting's attendee data, `location` when present,
   the meeting company, and a short source note
4. **If the page exists**, add the meeting under "Recent Interactions" inside
   the existing `<!-- dex:auto:recent-interactions -->` block, using exactly the
   line format the rest of Dex writes and reads:

   ```
   - [{Meeting Title}](00-Inbox/Meetings/{date}/{slug}.md) — {date}
   ```

   The path must be the vault-relative meeting path. Keep a maximum of 20
   entries, removing the oldest, and update `last_interaction` in the
   frontmatter. If a line for that meeting path is already present, change
   nothing — the same entry must never appear twice.

These page updates are YOUR responsibility; do not assume a hook will make
them for you.

---

## Step 4: Update Company Pages

For each unique external company:

1. Check whether `05-Areas/Companies/{Company}.md` exists
2. If not, create it with an Overview table (website, stage, first contact),
   Key Contacts linking the person pages, Meeting History, and a note that it
   was auto-created from the meeting
3. If it exists, add any new contacts to "Key Contacts" and the meeting to
   "Meeting History"

---

## Step 5: Enrichment

### 5a. Soft commitments (deterministic; always runs)

Independently of whether QMD is installed, run `detect_soft_commitments` over
each meeting's discussion notes. These are the things the user said they would
do without writing them down ("we should revisit pricing", "let me think about
the migration").

**Never create a task from a soft commitment.** List every match in your final
output under "Needs the User", marked
`*(soft commitment — confirm before creating)*`, so the conversation can confirm
each one with the user and create it there. Creating them yourself would put
work the user never agreed to into their task list.

### 5b. Semantic enrichment (if QMD available)

Check the QMD `status` tool. If available:

1. **Link meetings to projects:** `query` with the meeting topic and link to
   relevant projects
2. **Enrich person context:** for each new person, `query` their name and
   company to find earlier mentions
3. **Corroborate soft commitments:** `query` for commitments and follow-ups to
   catch any 5a missed; these are reported, never created

If QMD is unavailable, skip silently — 5a still runs.

---

## Step 6: Extract Tasks (unless --no-todos or --people-only)

For each meeting with unextracted tasks:

1. Find action items in the "## Action Items > ### For Me" section
2. For each unchecked item (`- [ ]`):
   - Extract the task description
   - Read the pillar from the meeting frontmatter, then **resolve it to the
     unique pillar ID in `System/pillars.yaml`** by matching either `id` or
     display `name`. Never pass the raw frontmatter value through unresolved
   - **Preserve the exact source checkbox line text**, verbatim, for
     `stamp_source_line`
3. Create the task, letting `create_task` generate the ID and stamp it back
   onto that source line:

   ```
   create_task(
     title="{task description}",
     priority="P2",          # P1 if the item says urgent
     pillar="{resolved pillar ID}",
     people=[...participant page paths...],
     source="{meeting path}",
     stamp_source_line="{exact source checkbox line text}"
   )
   ```

   `people` values must resolve to existing person page paths. Prefer the paths
   returned by Step 3's `lookup_person` / `create_person` flow; if only a bare
   name is available, pass that name unchanged and let `create_task` resolve
   it. Never construct or guess a person page path.

   **Why `stamp_source_line` is mandatory:** completion sync only finds a line
   that contains BOTH a checkbox AND the task's `^task-YYYYMMDD-XXX` anchor.
   Omit the stamp and the action item in the meeting note is permanently
   invisible to sync — ticking the task done never updates the note, and vice
   versa.

4. **Verify every result before marking the meeting extracted:**
   - Require `success: true` for every `create_task` call
   - Require either `stamp.stamped: true`, or `reason: "already_anchored"` with
     that source line's existing anchor equal to the returned `task.task_id`
   - If entity resolution or stamping is unresolved, **leave the meeting
     unmarked** and report the exact failed line in your final output. Do not
     retry a task that was created but not stamped

5. **Only after every action item is verified**, append the marker to the note:
   `<!-- tasks-extracted: YYYY-MM-DDTHH:MM:SSZ -->`

   **The marker is a one-way door.** The session-start sweep uses it to decide a
   meeting is done, so stamping a note whose tasks failed to create loses those
   action items permanently and silently. When in doubt, leave it unstamped and
   report it.

6. **Also stamp meetings with nothing to extract.** A note with no action items
   still gets the same marker once you have processed it; an unstamped note
   keeps being flagged as waiting, session after session.

---

## Step 7: Auto-Link and Verify (when available)

If Obsidian mode is enabled, run `node .scripts/auto-link-people.cjs
"<note-file>"` for each processed note. Run
`node .scripts/meeting-intel/verify-entities.cjs` and record its one-line
summary. If the entity suggestions feed lists suggested people, include them in
your final output; do NOT create pages from suggestions yourself, since
accepting or dismissing them is the user's call.

---

## Final Output

Return a structured summary:

```
AGENT COMPLETE

Processing complete.

**Synced meetings found:** X (last 7 days)
**Background sync status:** [Running / Not set up]

### Updates Made

**Person pages:**
- Created: X new ([names])
- Updated: Y existing

**Company pages:**
- Created: X new ([names])
- Updated: Y existing

**Tasks extracted:** X items added to 03-Tasks/Tasks.md

### Needs the User

- Ambiguous person matches: [list, or none]
- Entity suggestions awaiting a decision: [list, or none]
- Soft commitments detected, *(confirm before creating)*: [list, or none]
- Meetings left UNSTAMPED because a task failed to create or stamp: [list with
  the exact failed line, or none]

### Recent Meetings

| Date | Meeting | Company | Participants |
|------|---------|---------|--------------|
| ... | ... | ... | ... |

[Any warnings or issues encountered]
```

---

## Important Notes

- Use real data from tools and files; never fabricate meetings, people, or
  companies
- If a source fails, report the source's status; never claim meetings are
  absent because a tool errored
- Skip any optional integration that is not set up, silently
