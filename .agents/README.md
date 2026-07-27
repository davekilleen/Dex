# .agents/ — cross-harness skill surface

This directory ships a small subset of Dex skills in the harness-neutral
Agent Skills layout, so AI coding harnesses that don't read `.claude/skills/`
can still run the core journeys:

- `skills/getting-started/` — post-onboarding tour
- `skills/process-meetings/` — meeting processing
- `skills/industry-truths/` — strategic context capture

## Relationship to `.claude/skills/`

`.claude/skills/` is the canonical, fully-maintained skill set (74 skills).
The copies here are **adapters**, not a second source of truth: when a skill
that exists in both places changes in `.claude/skills/`, the change should be
mirrored here in the same PR.

> Last synced 2026-07-27 (canonical body verbatim; Claude-Code-only frontmatter
> keys like `hooks:`/`context:` dropped). These files are covered by
> instruction-honesty and configuration-truth tests
> (`core/tests/test_instruction_honesty.py`,
> `core/tests/test_granola_configuration_truth.py`,
> `scripts/check-instructed-tools.py`) — always sync via a reviewed change and
> re-run those, never a blind copy.

This directory is `brain`-classed in the portable ownership contract and is
provisioned into installs (`core/provision-contract.json`); user-authored
variants belong in `.agents/skills/*-custom/`, which updates never touch.
