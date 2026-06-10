---
name: diff-adopt
description: Adopt a DexDiff methodology — guided onboarding that reads a workflow description, adapts it to your role and vault, and walks you through setup
---

## What This Command Does

**In plain English:** Someone figured out a great way to use Dex for a specific job — like prepping for meetings, reviewing deals, or building performance evidence. This command reads their methodology and walks you through setting up a similar workflow in your vault. It adapts to your role, your tools, and your folder structure. Nothing is copied from their system — your Dex generates everything fresh, tailored to you.

**When to use it:**
- Dex suggested a workflow you might like
- You found a workflow on heydex.ai/diff
- Someone shared a methodology URL or file path with you

**How to run it:**
```
/diff-adopt @davekilleen/meeting-intelligence
/diff-adopt https://heydex.ai/diff/@davekilleen/meeting-intelligence
/diff-adopt 04-Projects/DexDiff/beta/diffs/meeting-prep.yaml
```

---

## Arguments

`$ARGUMENTS` — A reference to one methodology document:
- A hosted reference `@<handle>/<diff-id>` — fetch the raw methodology from the API host:
  `GET https://api.heydex.ai/api/diff?author=<handle>&id=<diff-id>`
- A page URL like `https://heydex.ai/diff/@<handle>/<diff-id>` — parse out the handle and diff id, then make the same API call. Never WebFetch the page itself: heydex.ai pages are a React app shell and contain no methodology text. The API lives on `api.heydex.ai`; the website host has no `/api/*` routes.
- A local path from the DexDiff draft area, usually under `DEXDIFF_DIFFS_DIR` (default `04-Projects/DexDiff/beta/diffs/meeting-prep.yaml`) (read directly)

The argument is always an explicit location — never a bare name.

Fetch failures must stop the flow with a plain explanation, never silently:
- HTTP 404 — "That workflow was not found. Check the handle and workflow id — the author may have unpublished it."
- Network failure — "Could not reach api.heydex.ai — check your connection and try again. Nothing was changed."
- The response should be a full methodology document carrying `dexdiff_schema: "2.0"`. If it is a short one-line summary instead, say so plainly: "This workflow was published in an old thin format that cannot be regenerated faithfully — ask the author to re-publish it." Do not invent the missing methodology.

If no argument or invalid input:
```
/diff-adopt expects a workflow reference, URL, or file path.

Examples:
  /diff-adopt @davekilleen/meeting-intelligence
  /diff-adopt https://heydex.ai/diff/@davekilleen/meeting-intelligence
  /diff-adopt 04-Projects/DexDiff/beta/diffs/meeting-prep.yaml
```

---

## The Onboarding Flow

This is a guided conversation, not a transaction. Walk the user through each phase. Be warm, clear, and educational. The user may not know what skills, hooks, or CLAUDE.md sections are — explain in plain language what each thing DOES, not what it IS.

---

### Phase 1: Introduce the Job

Read the YAML file and parse it. Confirm `dexdiff_schema: "2.0"`.

Present the workflow by leading with the PROBLEM it solves and what it UNLOCKS — not technical details:

```
[name] — by [author.display_name], [author.role]

THE PROBLEM
[methodology.problem — full text, this is the hook]

WHAT PEOPLE SAY
"[love_letter.text]"
— [love_letter.author]

[love_letter.metrics as bullet points]

WHAT THIS UNLOCKS
After setup, you'll be able to:
  /[command-1]  — [one-line description]
  /[command-2]  — [one-line description]

Want to set this up? [Yes, let's go] [Tell me more first]
```

**If "Tell me more first":** Show `methodology.solution` in full, walk through each command's example output, explain the integrations that enhance it. Then ask again.

**If "Yes, let's go":** Proceed to Phase 2.

---

### Phase 2: Discover Together

Scan the vault and EXPLAIN what you find to the user as you go. This is educational — the user learns about their own setup through the process.

**2a. Understand the user's role**

Check if `System/user-profile.yaml` exists and has a role. If it does, use it. If not, ask:

```
Quick question — what's your role? This helps me tailor the workflow to what matters most to you.

[Show roles from methodology.roles if available, otherwise free text]
```

Look up the matching role in `methodology.roles` to get the adaptation guidance.

**2b. Scan folders**

```
Let me look at your vault structure...

[For each folder in methodology.vault_structure.folders:]
  ✓ [purpose]: Found at [actual path]
  OR
  ○ [purpose]: Not found — I'll create [typical_path] (or suggest a location)
```

**2c. Check integrations**

```
Checking your connected tools...

[For each integration in methodology.integrations:]
  ✓ [name] — connected. [one-line value statement]
  OR
  ○ [name] — not connected. [what the workflow does WITHOUT it]
     (You can add this later with /integrate-mcp)
```

**2d. Check existing skills**

```
Checking for existing workflows...

[For each command in methodology.user_experience.commands:]
  ○ /[name] — you don't have this yet, I'll create it
  OR
  ⚡ /[name] — you already have this! [explain whether to skip, enhance, or replace]
```

**2e. Summarise the discovery**

```
Here's what I found:

  Your role: [role] — I'll frame everything around [adaptation summary]
  Your data: [list connected integrations]
  Missing (but optional): [list unconnected integrations]
  Your folders: [list matched folders with actual paths]
  Existing workflows: [list any that overlap]

Ready to see the plan? [Yes] [I want to adjust something]
```

---

### Phase 3: Customise

Ask the user targeted questions about how they want the workflow to work. Only ask questions where the methodology has genuine choices — don't ask about things that have obvious defaults.

```
A few choices before I set things up:

[For each folder that wasn't found — ask where to create it]
  Where should [purpose] go? [[typical_path]]

[For each behavior where automatic: true]
  [description] — want this to happen automatically? [Yes/No]
  (If yes, I'll set up a hook. If no, I'll add it as a reminder.)

[For conflicting skills]
  You already have /[name]. Want me to enhance it or create a separate one?
```

---

### Phase 4: Preview and Explain

Show what will be created. For each item, explain what it DOES — not just the file path. The user should understand the value of each component.

```
Here's your setup plan:

WORKFLOWS
  /[command-1] — [what it does in plain English]
    Uses: [list data sources it pulls from]
    Framed for: [role] ([adaptation summary])
    Location: .claude/skills/[name]/SKILL.md

  /[command-2] — [what it does in plain English]
    Uses: [list data sources]
    Location: .claude/skills/[name]/SKILL.md

BEHAVIOURS
  [For each approved automatic behavior:]
  After [trigger], Dex will [action].

GUIDANCE
  A "Meeting Workflow" section will be added to your CLAUDE.md so
  Dex always knows when and how to use these workflows.

[If any folders need creating:]
FOLDERS
  + [path] — [purpose]

[If any templates needed:]
TEMPLATES
  + [path] — [purpose]

Ready? [Yes, set it up] [Let me adjust] [Show me the full skill content]
```

If "Show me the full skill content": display the generated SKILL.md text for each skill before creating files.

If "Let me adjust": ask what to change and update the plan.

---

### Phase 5: Build

Once approved, create everything:

1. **Create skill directories and SKILL.md files** — generate each skill tailored to this vault's paths, role adaptation, and available integrations. Every skill should:
   - Use YAML frontmatter with name and description
   - Reference the user's actual folder paths (not methodology typical_paths)
   - Include only integrations that are actually connected
   - Gracefully skip unavailable integrations (check, skip silently)
   - Reflect the role adaptation from methodology.roles

2. **Append CLAUDE.md section** — add a brief section describing the workflow, when to use each command, and any behavioral guidance

3. **Create folders** if needed

4. **Create templates** if needed

5. **Set up hooks** for approved automatic behaviors — create hook scripts in `.claude/hooks/` and register in `.claude/settings.json`

---

### Phase 6: Log the Adoption

Create `.dex/adoptions/[diff-id].json`:

```json
{
  "diff_id": "[id from manifest]",
  "diff_name": "[name from manifest]",
  "adopted_at": "[ISO 8601 timestamp]",
  "source": "[URL or local path]",
  "role": "[user's role]",
  "files_created": [
    "[every file path created]"
  ],
  "folders_created": [
    "[every folder created]"
  ],
  "claude_md_sections": [
    "[section titles added to CLAUDE.md]"
  ],
  "hooks_created": [
    "[hook file paths and settings.json entries]"
  ],
  "skipped": [
    "[anything skipped and why]"
  ],
  "integrations_available": [
    "[integrations that were connected at adoption time]"
  ],
  "integrations_missing": [
    "[integrations that could enhance this later]"
  ]
}
```

Create `.dex/adoptions/` if it doesn't exist.

---

### Phase 7: Walk Through First Use

Don't just confirm — teach the user how to use what was just created. Give them a concrete next action.

```
All set! Here's how your new workflow works:

[For each command created:]
  /[command] — [when to use it, in one sentence]
  Example: /[command] [realistic example for their role]

THE COMPOUND EFFECT
[Explain how the workflow gets better over time — e.g. "Each meeting
builds context for the next one. After a month, your prep briefs
will surface patterns you'd never notice manually."]

WHAT'S NEXT
Try it now:
  /[first command] [suggestion based on their calendar or recent activity]

LATER
  To see what's installed: /diff-list
  To remove this workflow: /diff-remove [diff-id]
  To enhance with more integrations: /integrate-mcp

[If there are missing integrations that would add value:]
TIP: Connect [integration] to unlock [specific value].
Run /integrate-mcp [name] when you're ready.
```

---

## Edge Cases

**Already adopted:** If `.dex/adoptions/[diff-id].json` exists:
```
[name] is already installed (adopted [date]).
Would you like to reinstall it? This will regenerate all skills from
the methodology — useful if you've changed your role or connected new tools.
Your data (meeting notes, people pages, etc.) won't be touched.
```

**Conflicting skill names:** If a skill exists but wasn't created by DexDiff:
```
You already have /[name] — it looks like [brief description of what it does].
  [Enhance it] — I'll add the new capabilities to your existing skill
  [Create separate] — I'll create /[name]-v2 alongside it
  [Skip] — keep your existing one, don't create this
```

**No matching folders:** New or empty vault — propose creating the full structure from methodology.vault_structure.typical_path values. Frame it positively: "Fresh start! I'll set up a clean folder structure for you."

**No role found:** If user-profile.yaml doesn't exist and the methodology has roles, ask. If the methodology has no roles section, skip role adaptation and generate a general-purpose implementation.

---

## Important Rules

- **Never install foreign code.** Everything is generated by the adopter's own AI. The methodology is a specification, not executable content.
- **Never overwrite existing files** without explicit confirmation.
- **Always preview before creating.** The user approves the plan before any files are written.
- **Adapt to the vault.** Use existing folder names and conventions.
- **Adapt to the role.** Use methodology.roles to tailor generated skills.
- **Be educational.** Explain what each component does in plain language. The user should understand their system better after adoption than before.
- **Log everything.** The adoption log is the contract for `/diff-remove`.
- **Suggest next steps.** Always end with a concrete action the user can take right now.
