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
**How it works:** Captured at session Stop, stored in System/Session_Learnings/
**Dex action:** Filter for operational only (WP-2.1).

## Dex Vault Search (QMD)
**Owns:** Semantic search across all vault content
**Dex action:** Unchanged.

## Dex Proactive Intelligence (Phase 4 — planned)
**Owns:** Anticipation, pre-fetching, pattern prediction across agents
**Dex action:** Future. Enhanced by agent memory providing richer signal.
