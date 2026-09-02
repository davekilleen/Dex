---
name: diff-list
description: Show all adopted DexDiff workflows — what's installed, when it was adopted, and what it includes
---

## What This Command Does

**In plain English:** Shows you everything you've adopted via `/diff-adopt` — which workflows are installed, when you adopted them, and what skills they added.

**How to run it:**
```
/diff-list
```

---

## Arguments

None.

---

## Process

### Step 1: Read Adoption Logs (both locations)

Adoptions live in two places - read **both**:

1. `.dex/adoptions/` - single-workflow adoptions from `/diff-adopt` (one JSON per workflow)
2. `System/.dex/adoptions/profiles/` - whole-profile adoptions from `/diff-adopt-profile` (one JSON per profile, with `workflow_ids` inside)

If neither directory exists or both are empty:
```
No workflows adopted yet.

Browse workflows at heydex.ai/diff, then use:
  /diff-adopt @[handle]/[workflow-id]
or adopt someone's whole setup:
  /diff-adopt-profile @[handle]
```

### Step 2: Display Summary

For each single-workflow adoption log, show:

```
Adopted workflows:

  meeting-prep
    "Meeting Prep Ritual" by Dave Killeen
    Adopted: 2026-03-28
    Skills: /meeting-prep, /process-meeting
    Source: DexDiff draft area (`DEXDIFF_DIFFS_DIR`, default `04-Projects/DexDiff/beta/diffs/meeting-prep.yaml`)

To remove a workflow: /diff-remove [id]
```

For each profile adoption log, show the profile as a group:

```
Adopted profiles:

  @davekilleen - Dave Killeen
    Adopted: 2026-06-16
    Workflows: meeting-intelligence, deal-intelligence, operating-rhythm, ...
    Bundle saved at: 04-Projects/DexDiff/beta/profile/adopted/davekilleen/
```

### Step 3: Health Check (Optional)

For each adopted workflow, quickly verify:
- Do the installed skill files still exist?
- If any are missing (manually deleted), flag it:

```
  ⚠ meeting-prep — .claude/skills/process-meeting/SKILL.md is missing
    (may have been manually deleted — run /diff-remove meeting-prep to clean up)
```
