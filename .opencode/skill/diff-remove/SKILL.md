---
name: diff-remove
description: "Remove a previously adopted DexDiff workflow — deletes its generated skills and config, leaves your data untouched. Use when the user says 'remove that workflow', 'undo the adoption'. Not for listing what's installed; use `diff-list`."
---

## What This Command Does

**In plain English:** Undo a DexDiff adoption. Removes the skills, CLAUDE.md sections, and templates that were created when you adopted a workflow. Your data (meeting notes, people pages, etc.) is never deleted.

**When to use it:**
- You adopted a workflow and want to remove it
- You want to clean up before re-adopting an updated version

**How to run it:**
```
/diff-remove meeting-prep
/diff-remove
```

---

## Arguments

`$ARGUMENTS` — The diff ID of the workflow to remove. This is the `id` field from the methodology YAML, logged during adoption.

If no argument is provided, list all installed diffs and let the user pick:
```
You have these adopted workflows:

  meeting-prep    — "Meeting Prep Ritual" (adopted 2026-03-28)
  deal-review     — "Deal Review Ritual" (adopted 2026-03-25)

Which one would you like to remove?
```

To get the list, read all JSON files in **both** adoption locations:
- `.dex/adoptions/` - single-workflow adoptions from `/diff-adopt`
- `System/.dex/adoptions/profiles/` - whole-profile adoptions from `/diff-adopt-profile` (these are profile-level records; removing one means removing the skills generated for that profile's workflows, then deleting the profile log)

---

## Process

### Step 1: Find the Adoption Log

Read `.dex/adoptions/$ARGUMENTS.json`. If it is not there and `$ARGUMENTS` looks like a handle, check `System/.dex/adoptions/profiles/$ARGUMENTS.json` instead.

If the file doesn't exist:
```
No adoption record found for "$ARGUMENTS".

This means either:
- It was never adopted via /diff-adopt
- It was already removed
- The adoption log was deleted

I can't safely remove it without knowing what was created.
If you want to manually clean up, check .claude/skills/ for related skill folders.
```
Stop here. Do not attempt to guess what to delete.

### Step 2: Parse the Log

Extract:
- `files_created` — every file created during adoption
- `folders_created` — every folder created
- `claude_md_sections` — every CLAUDE.md section title added

### Step 3: Check What Still Exists

For each file in `files_created`:
- Check if the file still exists
- If it's been modified since adoption, flag it

For each CLAUDE.md section in `claude_md_sections`:
- Check if the section title still appears in CLAUDE.md

### Step 4: Preview the Removal

```
Removing [diff_name] will:

  Delete files:
    - .claude/skills/meeting-prep/SKILL.md
    - .claude/skills/process-meeting/SKILL.md

  Remove from CLAUDE.md:
    - "Meeting Workflow" section

  NOT deleted (your data is safe):
    - [folders] and everything inside them
    - Any files you created yourself

[If any files were modified:]
  Note: These files were modified after adoption:
    - .claude/skills/meeting-prep/SKILL.md (you may have customised it)

Continue? [Yes, remove] [Cancel]
```

### Step 5: Remove Files

For each file in `files_created`:
- Delete the file
- If the parent directory is now empty AND inside `.claude/skills/`, delete the empty directory
- Do NOT delete directories outside `.claude/skills/`

### Step 6: Remove CLAUDE.md Sections

For each section in `claude_md_sections`:
- Search CLAUDE.md for a heading with that title
- Remove the heading and all content until the next heading of equal or higher level
- If the section can't be found, skip and note it

### Step 7: Clean Up

Delete `.dex/adoptions/$ARGUMENTS.json`.

### Step 8: Confirm

```
Done. [diff_name] removed.

  Files deleted: [count]
  CLAUDE.md sections removed: [count]
  Your data in [folders] was not touched.
```

---

## Important Rules

- **Never delete folders created during adoption.** The user may have added content. Folders are never removed.
- **Never delete files not in the adoption log.** The log is the single source of truth.
- **Never delete without preview and confirmation.** Always show what will be removed first.
- **If the adoption log is missing, stop.** Do not guess.
- **Flag modified files.** If a skill was customised after adoption, warn before deleting.
