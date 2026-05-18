# ADR-003: Invocation mode — explicit `/librarian "<query>"` for v1

- **Status**: accepted
- **Date**: 2026-05-16
- **Implemented**: 2026-05-18 (commit 9d2e28c on `feat/proactive-librarian-hardening`)
- **Deciders**: David Orban
- **Tags**: librarian, ux, invocation, scope

## Context

The Librarian could surface relevant research in two fundamentally different modes:

1. **Explicit** — David runs `/librarian "<query>"` when he wants suggestions. Slash-command UX.
2. **Ambient** — A PostToolUse hook on `Edit`/`Write` events detects when David is drafting a deliverable, extracts the topic from the current paragraph/section, and silently injects suggestions into context (similar to the existing person-/company-context-injector hooks).

Ambient is technically buildable — the injector hook pattern is well-proven in this vault — but it doubles the design surface (when to fire / when to suppress / how to format / how to avoid noise / how to handle false positives) and introduces a constant background side-effect on editing.

David explicitly stated: "OK with explicit now."

## Decision

**v1 ships explicit-only.** Invocation is `/librarian "<query>"` — a Dex skill that takes a query string, returns the top 5 results with citations, and exits.

Ambient injection is **deliberately deferred to v2** as a separate decision, not built speculatively. A future v2 ADR will revisit after v1 has accumulated usage data ("did David actually find this useful enough that he wants it ambient?").

## Consequences

### Positive
- Minimal scope. v1 ships fast.
- No risk of unwanted background context injection that bloats prompts or surfaces irrelevant results.
- Usage is observable — each `/librarian` invocation is a deliberate signal, useful for measuring whether v2 ambient is worth building.
- David retains full control over when retrieval happens.

### Negative
- Misses the "I didn't know to ask" use case. Some of the highest-leverage moments for citation come when David doesn't realise relevant research exists. Ambient would catch those; explicit won't.
- Friction: typing `/librarian "..."` is non-zero cognitive overhead vs. background magic.

### Neutral
- Trivially reversible. Adding a hook later is non-destructive — the skill UX stays identical; the hook just becomes an additional caller.
- v1 explicit-only mode also serves as the safest baseline for the v2 ambient design: ambient mode can call the same skill internally, so all retrieval logic stays in one place.

## Links

- Plan: [`plans/dex-improvement-proactive-librarian.md`](../../plans/dex-improvement-proactive-librarian.md) (Phase 4 v2 explicitly out-of-scope)
- Related pattern: person-context-injector / company-context-injector hooks (ambient injection model that v2 would mirror)
- Related ADRs: [ADR-005](ADR-005-dex-skill-plus-qmd-collection-no-new-mcp.md) (stack placement makes v2 hook trivial to add later)
