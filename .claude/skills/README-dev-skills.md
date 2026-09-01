# Dev skills — provenance

These build-agent skills were ported on 2026-09-01 from **pstack**, a Cursor
plugin (github.com/cursor/plugins, MIT license, author Lauren Tan / poteto).
They are development tooling for agents working on this repo (arrived via
the same port made for dex-bb-plugin). In this repository the surrounding
`.claude/skills/` directory IS the shipped product, so every directory
listed below is excluded from user distribution via `.distignore` — a
founder ruling (2026-09-01): build tooling is available only to the
founder, never to users. Adding a dev skill here means adding its
`.distignore` entry in the same change.

## What was ported

- **Verbatim-class skills** (`skills/<name>/SKILL.md` in pstack, references
  and scripts included): create-verification-skill, maintain-verification-skill,
  blast-radius, unslop, technical-writing, figure-it-out, tdd,
  show-me-your-work, and all 21 `principle-*` skills.
- **Playbooks promoted to standalone skills**: pstack kept these as plain
  markdown under `skills/poteto-mode/playbooks/`; here each is a skill named
  `playbook-<name>` with new frontmatter (the description is the only authored
  prose). Ported: investigation, bug-fix, feature, refactoring, prototype,
  shipping, session-pickup, pause-safely, opening-a-pr, eval, hillclimb,
  babysit, orchestrate, autonomous-run, multi-phase-plan.

## What was adapted (mechanical edits only)

- **Paths**: Cursor's project-local skills directory became
  `.claude/skills/`; Cursor agent transcript locations became
  `~/.claude/projects/<slug>/` (Claude Code session transcripts, same JSONL
  idea); references to a Cursor-side model defaults file were removed or
  replaced with "the repo's model defaults".
- **Tool names**: Cursor's ask-the-user tool name became
  `AskUserQuestion`; Cursor Task-tool
  parameter blocks (`environment: "cloud"`, `readonly`, explicit model slugs)
  were rephrased to Claude Code's Agent tool — background subagents
  (`run_in_background: true`) where the source said cloud, read-only
  exploration agents where it said readonly, and neutral role wording
  ("a fast model" / "a judgment model") in place of model slugs.
- **Cursor built-ins**: `/deslop` became `/unslop`; the built-in babysit
  became playbook-babysit; `/loop` stays (this harness has `/loop`).
- **Verification surfaces**: pstack's `control-ui`/`control-cli` (from a
  Cursor team kit) became "the project's UI/CLI verification skill" — build
  one with create-verification-skill.
- **Cross-references**: links into `poteto-mode/playbooks/` now point at the
  `playbook-*` skills. pstack skills that were not ported (how, why,
  architect, interrogate, arena, swarm, no-comments, recall, autopilot-full,
  autopilot-stack, the orch and watch-pr scripts, check-plan.mjs, the
  bugbot-triage rubric) are kept as plain-text names where the prose depends
  on them, with a bracketed note at load-bearing spots.
- **Graphite**: `gt` stack steps are kept as written; where a playbook step
  requires Graphite, its first such step carries a bracketed line noting the
  plain git/gh equivalent applies.

Everything else is verbatim. The source prose is the asset.
