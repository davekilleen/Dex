# Memory Ownership Boundaries

## Claude Auto-Memory (native)
**Owns:** Preferences, style, communication patterns, formatting choices
**Examples:** "User prefers bullet points", "Use neutral mermaid theme", "Direct communication style"
**How it works:** Automatically captured by Claude. Persists across all sessions and harnesses.
**Dex action:** Don't duplicate. Don't capture preferences in learning-heartbeat.

## Agent Memory (frontmatter, `memory: project`)
**Owns:** Per-agent operational state across sessions
**Examples:** "deal-attention flagged Acme Corp 3 times", "cracks-detector: pricing follow-up resolved"
**How it works:** Each agent reads/writes its own memory. Scoped to that agent.
**Dex action:** Configured in Phase 1, WP-1.1.

## Dex Session Memory (learning-heartbeat)
**Owns:** Operational decisions, commitments, work patterns, system learnings
**Examples:** "Agreed to deliver DACH deck by Friday", "Meeting-prep skill needs more account context"
**How it works today:** Not yet automatic. `SessionEnd` only logs a timestamp/transcript
pointer to `System/Session_Learnings/`; actual extraction (mistakes, preferences, doc gaps)
runs as an LLM-reasoning step inside `/review` and `/daily-review`, and only fires when one
of those is run to completion. A hook alone can't do the judgment call — see
`Background_Processing_Guide.md` for the planned Stop-hook automation that would close this
gap and make "learning-heartbeat" live up to its name.
**Dex action:** Filter for operational only (WP-2.1).

## Dex Vault Search (QMD)
**Owns:** Semantic search across all vault content
**Dex action:** Unchanged.

## Dex Proactive Intelligence (Phase 4 — planned)
**Owns:** Anticipation, pre-fetching, pattern prediction across agents
**Dex action:** Future. Enhanced by agent memory providing richer signal.
