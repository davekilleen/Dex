---
name: diff-generate
description: Generate a DexDiff methodology document from your vault customisations: package how you use Dex so others can replicate it
---

## What This Command Does

**In plain English:** You've built a workflow in Dex that works well. This command scans your vault, identifies what you've customised, and writes a methodology document describing how it works. That document can be published to heydex.ai/diff so others can adopt a similar setup using `/diff-adopt`.

**When to use it:**
- You want to share a workflow with someone else
- You want to document how a part of your system works
- You want to package your setup for your team

**How to run it:**
```
/diff-generate "my meeting prep workflow"
/diff-generate
```

---

## Arguments

`$ARGUMENTS`: Optional description of the workflow to package.

- If provided: used to identify which components belong to this workflow
- If omitted: scans everything custom and asks what to package

---

## Process

### Step 1: Discover Customisations

Scan these locations for custom components:

```
.claude/skills/          - custom or modified skills
.claude/hooks/           - custom hooks
CLAUDE.md                - custom sections
.claude/CLAUDE.md        - local extensions
```

To identify what's custom vs. baseline dex-core:
- Skills with `-custom` suffix are always custom
- Skills with `-dave` or other personal suffixes are custom
- Hooks are almost always custom
- CLAUDE.md sections that reference specific folders, people, or workflows are custom

Present findings:

```
I found these customisations in your vault:

Skills ([count] custom):
  [skill-name]  - [one-line description]
  ...

Hooks ([count]):
  [hook-name]   - [one-line description]
  ...

CLAUDE.md extensions ([count] custom sections detected)

What would you like to package?
- Describe a workflow (e.g. "my meeting prep")
- Or pick from the list above
```

### Step 2: Group into a Workflow

If the user provided a description, use it to identify related components.

**Grouping heuristic: components belong together if:**
- They serve the same job to be done (meeting prep, deal review, weekly planning)
- Skills reference the same vault paths
- A hook fires on output from a skill in the same group
- A CLAUDE.md section describes when to use skills in the group
- Skills are typically run in sequence

Present the proposed grouping and let the user adjust.

### Step 3: Write the Methodology

For the selected components, generate a methodology YAML following the v2.0 schema.

**How to write each section:**

- **`methodology.problem`**: What was life like before this workflow? Write from the user's perspective.
- **`methodology.solution`**: What does the workflow do end to end? Describe the experience, not the code.
- **`methodology.user_experience.commands`**: For each skill: name, trigger, description, realistic example input/output.
- **`methodology.vault_structure`**: For each folder the skills reference: purpose, typical path, required/optional.
- **`methodology.data_patterns`**: For each data format expected: description, realistic example (anonymised).
- **`methodology.integrations`**: For each MCP or tool: name, examples, value add, required/optional.
- **`methodology.behaviors`**: For each automatic action: what happens, when, automatic or manual.

**Anonymise real data.** Use realistic but anonymised names, companies, and dates in examples.

### Step 4: Ask for Identity Fields

```
A few details for the methodology:

  Diff ID (URL-safe, kebab-case):  [suggest]
  Display name:                     [suggest]
  Description (1-2 sentences):      [draft]
  Tags:                             [suggest]

Edit any of these, or accept the defaults.
```

### Step 5: Review and Save

Display the complete methodology YAML. Ask:

```
Methodology drafted. What would you like to do?

  [Save]        - saves to the DexDiff draft area (`DEXDIFF_DIFFS_DIR`, default `04-Projects/DexDiff/beta/diffs/[id].yaml`)
  [Edit first]  - adjust any section before saving
  [Test it]     - run /diff-adopt against this to see what it generates
```

---

## Publishing to Heydex (optional)

After the methodology YAML is saved, publishing is optional.

If the user wants to publish it, use the terminal bridge that ships with this skill:

1. Check whether `~/.dex/heydex-auth.json` exists and is less than 30 days old.
2. If it is missing or stale, tell the user to open `https://heydex.ai/connect/?cli=true`, sign in, create a sign-in code, then run:

```
python3 .claude/skills/diff-generate/scripts/publish_diff.py link --code ABC123
```

3. Once the terminal is linked, run:

```
python3 .claude/skills/diff-generate/scripts/publish_diff.py publish <path-to-yaml>
```

The script opens a browser review page. Tell the user that page is where they can edit the workflow and choose Publish. Nothing is shared without their explicit approval on that page.

---

## Important Rules

- **Anonymise real data.** Never include real customer names, deal values, or sensitive context in examples.
- **Describe, don't copy.** The methodology describes how the workflow works, it doesn't contain literal skill code.
- **Err toward inclusion.** If a component might be related, include it and let the user remove it.
- **Use the v2.0 schema.** Always set `dexdiff_schema: "2.0"`. See `04-Projects/DexDiff/design/methodology-schema.md` for the full spec.
