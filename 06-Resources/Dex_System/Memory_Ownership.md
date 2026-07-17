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
**How it works:** `.claude/hooks/learning-heartbeat.cjs` (a `Stop` hook) blocks once per
session per day, when the session looks substantive (>=3 user turns or >=8 tool calls),
forcing one extra turn where Claude reflects on the session and writes conforming entries
to `System/Session_Learnings/YYYY-MM-DD.md` using the template in that folder's `README.md`.
A hook script can't do the judgment call itself — it forces the live session to do it.
Confirmed safe to run alongside other `Stop` hooks that also use `decision:block` (Claude
Code surfaces every hook's reason rather than dropping one when multiple fire on the same
event). Opt-out:
`System/user-profile.yaml` -> `learning_heartbeat.enabled: false`. `/review` and
`/daily-review` still work as manual triggers too — the hook just removes the dependency on
remembering to run them.
**Dex action:** Filter for operational only (WP-2.1).

## Dex Vault Search (QMD)
**Owns:** Semantic search across all vault content
**Dex action:** Unchanged.

## Dex Proactive Intelligence (Phase 4 — planned)
**Owns:** Anticipation, pre-fetching, pattern prediction across agents
**Dex action:** Future. Enhanced by agent memory providing richer signal.
