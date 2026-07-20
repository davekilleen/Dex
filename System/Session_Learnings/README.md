# Session Learnings

> Note: this directory is gitignored (see `.gitignore`) except for this README — it's
> grandfathered in from before that rule was added, and intentionally kept as the canonical
> schema reference below. Don't delete it as part of a gitignore cleanup.

System improvements discovered during work sessions.

## What Goes Here

Meta-feedback about Dex itself, captured automatically or during `/review`/`/daily-review`:

- **Mistakes or corrections** — Things that went wrong and how to fix them
- **Preferences mentioned** — Workflow preferences you shared
- **Documentation gaps** — Places where docs were unclear or missing
- **Workflow inefficiencies** — Friction points discovered

## Format (exact — other tools parse this)

`mcp__dex-improvements-mcp__synthesize_learnings` parses entries by this literal markdown
shape (`## HH:MM - Title`, `**Field:**` labels, a `**Status:** pending` value, blocks
separated by `\n---\n`). Entries that don't match this exactly are silently skipped by that
tool — so match it precisely:

```markdown
## HH:MM - [Short title]

**What happened:** [Specific situation]
**Why it matters:** [Impact on system/workflow]
**Suggested fix:** [Specific action, with file paths if applicable]
**Status:** pending

---
```

## Naming Convention

`YYYY-MM-DD.md` (one file per day)

## Workflow

1. **Capture** — Automatic: `.claude/hooks/learning-heartbeat.cjs` (a `Stop` hook) briefly
   pauses substantive sessions, once per session per day, and has Claude reflect and write
   conforming entries. Opt-out: `System/user-profile.yaml` -> `learning_heartbeat.enabled:
   false`. `/review` and `/daily-review` still work as manual triggers too.
2. **Review** — Periodically check pending learnings via `/dex-whats-new`
3. **Implement** — Fix documentation gaps or system issues
4. **Update status** — Mark as implemented when done

## vs. Dex Backlog

**Session Learnings** = specific bugs or doc gaps discovered  
**Dex Backlog** = feature ideas and improvements (in `System/Dex_Backlog.md`)

Both feed into system improvements, but learnings are reactive (fixing issues) while the backlog is proactive (new capabilities).

## Integration

- `/dex-whats-new` checks for pending learnings
- Weekly reviews surface unaddressed learnings
- Helps Dex evolve based on actual usage patterns

This enables Dex to learn from your usage and improve over time.
