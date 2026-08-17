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

## Step 1: Resolve the Local Meeting Sources

Read `System/user-profile.yaml` before looking for notes. Its exact supported
shape is:

```yaml
meeting_sources:
  primary: granola | zoom | teams | exported-folder | wispr | none
  notes_folder: "vault-relative/folder/or/empty"
```

`primary` records provenance; it does not grant access to that recorder or
prove that a matching MCP tool exists. This delegated prompt has the vault and
the inherited Dex tools. It has no general Zoom, Teams, Wispr, email, Drive, or
Notion reader. Never search an external service merely because `primary` names
it. Process only notes already present in the vault.

Resolve `notes_folder` only when it is a non-empty string. It is vault-relative:
reject an absolute path, `..`, the vault root itself, and any symlink whose real
target escapes the vault. Report that invalid configuration, then continue with
the safe default and provider-neutral fallback below. If the profile is missing,
malformed YAML, not an object, `meeting_sources` is not an object, or `primary`
is not one of the supported values, report the configuration problem and use
the same safe fallback. Never guess a path from malformed configuration.

The Granola state file (`.scripts/meeting-intel/processed-meetings.json`) is
optional bookkeeping for Granola sync, not a gate on local notes. Read it when
it exists. If it is absent and `primary` is `granola`, report that background
sync is not set up so the conversation can offer `--setup`; still continue with
any local meeting notes. Its absence must never stop an exported-folder, Zoom,
Teams, manual-note, or provider-neutral local pass.

---

## Step 2: Find Waiting Meetings

Read the processed meetings state:

```bash
cat .scripts/meeting-intel/processed-meetings.json
```

Search candidate folders in this order:

1. the valid configured `notes_folder`, when present
2. `00-Inbox/Meetings/`
3. bounded provider-neutral Markdown discovery elsewhere in the vault, only
   when the first two sources return no candidates

For the fallback, match likely meeting notes by the requested date window plus
meeting title, attendee, or meeting frontmatter. Exclude `.git`, `.claude`,
`.agents`, `.scripts`, `System`, dependency folders, binary files, and archives
outside the requested date. Do not treat arbitrary Markdown as a meeting.

List Markdown meeting files from each local candidate folder without following
directory symlinks. For the default folder that is equivalent to:

```bash
find 00-Inbox/Meetings -name "*.md" -mtime -7 | head -50
```

This includes synced notes in day directories and flat notes in the folder
root. A manual note with no capture id is still a meeting candidate and must be
processed and stamped the same way. Skip notes containing
`<!-- dex:skip-processing -->`.

If `00-Inbox/Meetings/queue/*.json` files exist, consume each queued meeting
first, following the queue rules in this skill's `SKILL.md` (Step 2.5): create
the meeting note from the JSON, and delete the queue file only after its note
has been written successfully.

**Reading `SKILL.md` safely.** You need only the section named above. Ignore that
file's "Delegated gathering" section entirely: it describes how you were
invoked. You ARE the subagent, so you must never call the Agent tool or spawn a
subagent of your own.

For each meeting file:
1. Preserve its actual vault-relative path; never reconstruct it under
   `00-Inbox/Meetings/`. Read frontmatter for `participants`, `company`, `date`,
   and recorder provenance. A capture id is a non-empty scalar frontmatter key
   ending in `_id` (for example `granola_id` or `wispr_id`). When `source` names
   a provider, use only that provider's matching `<source>_id`; if it is absent,
   report the mismatch and use the note path as identity. When `source` is
   absent, use a capture id only when exactly one such key is present. Empty or
   non-scalar values do not count. If multiple capture-id keys remain, report
   the ambiguity and use the note path as identity. The path identity is the
   normalized vault-relative Markdown path, with `/` separators and the `.md`
   extension retained; never reduce it to a basename. A manual note with no
   capture id remains valid.
2. Check whether person/company pages need updating
3. Check whether tasks need extracting (unchecked items in the "For Me"
   section, no `tasks-extracted` marker)

### Match capture identity to Calendar when both inputs exist

This is the only matching boundary. Daily review delegates meeting ingestion
here, and meeting prep has no capture to match, so neither owns a copy of this
policy.

For each synced note with an ISO `capture_started_at` value that includes `Z`
or a numeric UTC offset:

1. Apply CLAUDE.md's **Calendar response confidence contract**, then call
   `calendar_get_events_with_attendees` for that calendar date (fetch once
   per date and reuse the result).
2. Call `match_capture_to_calendar` with a `capture` containing only the note's
   `title`, `capture_started_at` as `start_time`, and attendee identities, plus
   the Calendar response's `events` array as `calendar_events` (not the whole
   Calendar response object).
3. If it returns `status: matched`, use its `identity` only (title, normalized
   start time, attendees) as the meeting identity for the rest of this run. If
   the returned title differs, update the note's title frontmatter and heading
   before the person/company/task steps.
4. If it returns `unmatched` or `ambiguous`, leave the capture identity alone.
   Never widen the five-minute limit or guess a timezone. If Calendar is not
   connected or errors, continue with the capture unchanged.

The matcher owns nearest-time, title, participant, ambiguity, and poor-title
rules. Do not reproduce them in prose or make a second judgment. Import
**identity only**: never copy join URLs, dial-ins, access codes, locations,
descriptions, notes, conferencing data, or any other invite payload into the
meeting note or person/company pages.

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
   - [{Meeting Title}]({actual vault-relative meeting path}) — {date}
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
