# ADR-005: Stack placement — Dex skill + QMD collection, no new MCP server

- **Status**: accepted
- **Date**: 2026-05-16
- **Implemented**: 2026-05-18 (commit 9d2e28c on `feat/proactive-librarian-hardening`)
- **Deciders**: David Orban
- **Tags**: librarian, architecture, stack-placement

## Context

The Librarian's logic could live in three places:

1. **New MCP server** — `librarian-mcp` exposing `search_research(query)`, `cite_passage(file, page)`, `ingest()` tools. Clean separation, callable by any MCP client.
2. **Dex skill + QMD collection** — `/librarian` slash command in `.claude/skills/librarian/`. Ingest is a script under `scripts/`; retrieval is a script that calls the existing `mcp__qmd-mcp__query` tool. No new MCP.
3. **QMD collection extension only** — no skill at all; David runs `mcp__qmd-mcp__query` directly with `collection=research`. Lightest weight; no orchestration layer.

Option 3 misses the "format citations as `file.pdf:p.N`" step and forces David to remember collection names and merge lex+vec results manually — too primitive for the use case.

Option 1 adds a new long-running process to the MCP ecosystem with its own lifecycle, logs, and failure modes for a use case that doesn't justify it. Right now the Librarian is one user (David), one machine (his laptop), one invocation surface (Claude Code).

Option 2 is the smallest thing that resolves the use case and matches every other recently-built Dex skill (`/expense-report`, `/triage`, `/process-meetings`) in shape.

## Decision

**Dex skill + QMD collection.**

- Skill at `.claude/skills/librarian/SKILL.md`.
- Scripts under `.claude/skills/librarian/scripts/{ingest.py, query.py, _categories.py}`.
- Retrieval calls the existing `mcp__qmd-mcp__query` tool. No new MCP server, no new background process.
- Source: `06-Resources/Research/`. Cache: `06-Resources/Research/.derived/`. Both gitignored (see ADR-004).

## Consequences

### Positive
- Mirrors `/expense-report` skill shape — same scaffolding, same shared-library pattern, same pre-flight conventions. Trivial cognitive overhead.
- No new lifecycle: no MCP process to install, configure, restart, or debug.
- All retrieval logic stays in one place (the skill's `query.py`). A future v2 ambient hook (see ADR-003) imports the same module.
- Easy to commit — skill files go to `davidorban/Dex` via the standard PR workflow.

### Negative
- Not directly callable by other MCP clients (Claude Desktop, etc.) without exposing the skill via slash command. Unlikely to matter for the personal-tool use case.
- Skill scripts run in the same process as Claude Code's tooling — heavy ingest can compete for resources during a session. Ingest is intended to be run from a terminal outside an active Claude session.

### Neutral
- Reversible: if a future need for an MCP server emerges (e.g., the Librarian becomes useful enough to expose to other tools), the existing `query.py` becomes the implementation behind an MCP server's `search_research` tool — no rework, just additional wrapping.

## Links

- Plan: [`plans/dex-improvement-proactive-librarian.md`](../../plans/dex-improvement-proactive-librarian.md)
- Pattern reference: `.claude/skills/expense-report/` (same skill + scripts + SKILL.md shape)
- Related ADRs: [ADR-001](ADR-001-storage-substrate-qmd-for-proactive-librarian.md), [ADR-003](ADR-003-explicit-invocation-via-librarian-slash-command.md), [ADR-004](ADR-004-pdf-canonical-derived-markdown-cache.md)
