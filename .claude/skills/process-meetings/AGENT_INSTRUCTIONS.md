# Process Meetings - Agent Instructions

You are processing synced meetings to update the vault. Your job is to find
unprocessed meetings, update person and company pages, extract tasks, and link
everything together.

**IMPORTANT:** PostToolUse hooks from the parent skill
(`post-meeting-person-update.cjs`) do NOT fire in this subagent context. You
must perform person-page updates directly; the hook will not do it for you.

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
4. **If the page exists**, add the meeting under "Recent Interactions" (keep a
   maximum of 20 entries, removing the oldest) and update the interaction date

Because hooks do not fire here, these page updates are YOUR responsibility; do
not assume anything else will make them.

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

## Step 5: Semantic Enrichment (if QMD available)

Check the QMD `status` tool. If available:

1. **Detect implicit commitments:** for each meeting's notes, `query` for
   commitments and follow-ups; catch soft commitments that action-item
   extraction misses
2. **Link meetings to projects:** `query` with the meeting topic and link to
   relevant projects
3. **Enrich person context:** for each new person, `query` their name and
   company to find earlier mentions

If QMD is unavailable, skip silently.

---

## Step 6: Extract Tasks (unless --no-todos or --people-only)

For each meeting with unextracted tasks:

1. Find action items in the "Action Items > For Me" section
2. For each unchecked item (`- [ ]`), extract the description and read the
   pillar from the meeting frontmatter
3. Create the task via `create_task(title="...", priority="P2",
   pillar="{from meeting}", people=[...participants...])`
4. Mark the note as extracted by appending:
   `<!-- tasks-extracted: YYYY-MM-DDTHH:MM:SSZ -->`

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
