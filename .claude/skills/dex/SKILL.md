---
name: dex
description: Show the full catalog of Dex skills grouped by category — your menu of everything Dex can do
model_hint: fast
---

Show the user everything Dex can do. This is the "what are my options" command — a scannable menu when you don't remember the exact skill name to type.

## Process

1. Read `.claude/skills/CATALOG.md` (auto-generated, always current).
2. Present it to the user as-is — it's already grouped by category with descriptions.
3. If `CATALOG.md` does not exist, run `node .scripts/sync-skill-commands.cjs` first to generate it, then present it.

## Arguments

$ARGUMENTS: Optional filter.

- `/dex` — show the full catalog
- `/dex meetings` — show only the matching category (or skills whose name/description match the term)
- `/dex sales` — same, filtered

If a filter is given, show only the matching category section(s) or skills, then mention the user can run `/dex` with no argument to see everything.

## After Showing

End with a short, non-pushy nudge tailored to what's likely useful right now:
- If it's morning and no daily plan exists today → "Start with `/daily-plan`?"
- If they just asked about meetings → point to `/log-meeting` or `/meeting-prep`
- Otherwise → "Just type `/` in the chat box to fuzzy-search any of these, or tell me what you're trying to do."

Keep it to one line. Don't list everything again.
