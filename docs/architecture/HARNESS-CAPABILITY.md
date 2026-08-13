# Harness capability contract

Dex is a vault plus a set of tools. The assistant that sits in front of it
(Claude Code, Cursor, Codex, Gemini CLI, or something else) is a **harness**.
Which language model that harness uses is a separate question. This document
is the contract for the first axis. It is not a multi-model router, and it
does not revive `/ai-setup`.

| Axis | What it is | Cost |
| --- | --- | --- |
| **Harness agnosticism** | Packaging: skills, hooks, MCP config | Mostly a packaging problem |
| **Model agnosticism** | Which LLM does the reasoning | Quality / instruction adherence. Not solved by a config flag. |

Claude Code is the **Tier 3 reference implementation**. That is a stated
position: the full hook / injector / self-learning surface may stay
Claude-only. Other harnesses get a documented, tested slice — not a silent
subset, and not a promise of parity.

## Capability tiers

| Tier | Name | What it is | Who can run it |
| --- | --- | --- | --- |
| **Tier 0 Vault** | Markdown + PARA | Notes, people, projects, tasks as files. No agent required. | Any editor |
| **Tier 1 Core** | MCP + scheduled jobs | Tasks, people index, meeting sync, search. Background jobs already run on a schedule. | Any MCP-capable harness |
| **Tier 2 Skills** | Agent Skills + journeys | Named `/commands` generated into `.agents/skills/` from canonical `.claude/skills/`. | Any harness that reads Agent Skills / `AGENTS.md` |
| **Tier 3 Full** | Hooks, injectors, self-learning | Session context, inject-on-read, pre-tool-use gates, mid-session health, session-end snapshot. | Claude Code today |

Layers 1–2 of the repo (`core/`, MCP servers, `.scripts/`, including
`.scripts/lib/llm-client.cjs`) already qualify as Tier 1. Do not rewrite them
to “become” harness-neutral; they already are.

Conformance tests live in `core/tests/test_harness_capability_contract.py`.
They fail CI when:

- the README loses the tier table
- a live doc claims cross-harness support without naming a tier
- a generated `.agents/` adapter is missing or still carries Claude-only frontmatter
- a Tier ≤2 code surface imports Claude hooks or opens `.claude/settings.json` at import time

## Skill adapters (Tier 2)

Canonical skills live under `.claude/skills/`. `.agents/skills/` is generated
by `scripts/generate-agents-skills.py`. It strips `hooks:`, `context:`, and
`model_routing:` frontmatter. User-authored `*-custom/` directories are never
touched.

This is generation, not a hand-maintained mirror. Run the generator after
adding or editing a canonical skill; CI’s `--check` mode refuses drift.

## Hooks split: in-turn vs scheduled

Hooks are the reason Tier 3 is Claude-only today. Cursor, Codex, and Gemini
CLI do not run `.claude/settings.json` hooks. The question that decides
whether Tier 2 is a real product or a consolation prize is: **which of those
hooks are actually hooks, and which are scheduled work wearing a hook’s
clothes?**

### Already OS-scheduled (Tier 1 — harness-neutral today)

These run on launchd (macOS) from `.scripts/`, not from a chat event. They
are the existence proof that “hook-shaped” work can live outside Claude.
Meeting sync lives in `.scripts/meeting-intel/` and is installed by
`.scripts/meeting-intel/install-automation.sh`.

| Job | Cadence | What it does |
| --- | --- | --- |
| `com.dex.meeting-intel` | every 30 minutes (freshness promise 48h) | Sync meetings into the vault |
| `com.dex.smoke-nightly` | nightly | Local health smoke |
| `com.dex.changelog-checker` | every 6 hours (freshness promise 7d) | Watch Anthropic’s changelog |
| `com.dex.learning-review` | weekly | Prompt review of pending learnings |
| `com.dex.obsidian-sync` | daemon | Optional Obsidian live sync |

None of these need a harness hook. They already do not have one.

### Synchronous in-turn (Tier 3 — stays on Claude)

These must run **during a turn**, on a specific tool call or prompt. An
OS timer cannot substitute without changing the product.

| Hook | Event | Why it is in-turn |
| --- | --- | --- |
| `person-context-injector.cjs` | `PreToolUse` / Read | Injects the matching person page **before that file is read** |
| `company-context-injector.cjs` | `PreToolUse` / Read | Same for company pages |
| `dex-safety-guard.sh` | `PreToolUse` / Bash and MCP | Thin wrapper over `core/gates/safety.py`: blocks unsafe shell **before the call runs**. Claude-only scraper matcher stays in the hook. |
| `ensure-mcp-user-scope.cjs` | `PreToolUse` / Bash | Requires an explicit scope for `claude mcp add` |
| `soft-promise-detector.py` | `UserPromptSubmit` | Offers to capture a commitment **in the message just sent** |
| `health-pulse.sh` | `UserPromptSubmit` | Mid-session stale-health nudge; must interrupt *this* conversation |
| `post-meeting-person-update.cjs` | skill-scoped `PostToolUse` | Updates person pages after a meeting note write |
| `career-evidence-capture.cjs` | skill-scoped `PostToolUse` | Surfaces a sourced evidence candidate after a write |
| `daily-plan-quick-ref.cjs` | skill-scoped `Stop` | Writes the daily quickref when `/daily-plan` finishes |

This is the genuinely un-portable remainder. Reimplementing it on another
harness means that harness growing an equivalent hook model, not Dex
rewriting the jobs as cron.

### Session-bound (tied to chat lifecycle, not a clock)

These run at session start or end. They are **not** a substitute for a
calendar schedule: the user sees them when they sit down, and several of
them inject into the current conversation. They could be *triggered* by a
timer, but the notice still has to land in a turn.

| Hook | Event | Notes |
| --- | --- | --- |
| `session-start.sh` | `SessionStart` | Injects goals, priorities, tasks, meeting-queue notice |
| `update_verifier.py --session-start` | `SessionStart` | Bounded daily release-evidence check |
| `dex-core-orientation.sh` | `SessionStart` | Contributor orientation (this repo) |
| `connection-health-checker.cjs` | `SessionStart` | Integration health glance |
| `feedback_sweep.py` | `SessionStart` | Once-daily feedback inbox |
| `release_notes_sweep.py` | `SessionStart` | Once-daily what’s-new notice |
| `session-end.sh` | `SessionEnd` | Session marker / transcript reference |
| `vault-autocommit.cjs` | `SessionEnd` | Optional local Git checkpoint of vault edits |

`feedback_sweep`, `release_notes_sweep`, and `update_verifier` are already
**once per local day**. A launchd job could write the same receipts. It
could not show the three-line notice in the conversation that just opened.
Moving them off SessionStart without an in-turn injector would hide the
result from the user. That is not an obvious safe move.

The three-bucket inventory (scheduled / in-turn inject / gates), including
session-end writers left out of those buckets, is in
[`HOOK-INVENTORY.md`](./HOOK-INVENTORY.md).

### Gates slice: shared refusal, not a matcher rewrite

Destructive commands and unsafe paths now live in `core/gates/` and are
exposed as a Work MCP tool (**Tier 1 Core**). The Claude Code hook is a
thin wrapper over the same function — no behaviour fork, and no silent
skip on another harness that calls the tool.

| Guarantee | Shared module | MCP tool | Claude Code hook |
| --- | --- | --- | --- |
| Refuse destructive commands and unsafe paths | `core/gates/safety.py` | `check_safety_gate` | `dex-safety-guard.sh` |

Cursor, ChatGPT, and Codex call `check_safety_gate` before a dangerous
action. Claude Code still auto-fires it. Claude-only matchers (preferred
scraper, `claude mcp add` scope) stay in the hook. Nothing else in the
inject bucket is migrated in this slice.

### What this change does not do

Not migrated: no hook is moved to launchd, remaining inject hooks stay
Claude-only, and Claude-only matchers stay in the hook. **Do not mass-migrate hooks.** The scheduled slice is already harness-neutral. The
in-turn inject slice is why Tier 3 stays Claude Code for automatic
behaviour. Session sweeps stay on SessionStart until a harness-neutral
injector exists that can still show the user the notice.

## Non-goals (do not revive)

- Multi-model routing, per-task model selection, or a “bring your own model”
  config surface. That was `/ai-setup`, deleted in #115 because it reported
  success on a harness that could not deliver.
- Claiming Cursor, Codex, or Gemini CLI is “the same Dex”. They are Tier 2
  unless they grow hooks.
- Hand-maintaining a 3-skill `.agents/` mirror. Generation is the contract.

## Related

- User-facing tier table: `README.md`
- Adapter generation: `scripts/generate-agents-skills.py`
- Hook wiring: `.claude/hooks/README.md`, `.claude/settings.json`
- Hook inventory (scheduled / inject / gates): `docs/architecture/HOOK-INVENTORY.md`
- Scheduled job promises: `docs/architecture/HEALTH-PROMISES.md`
- Issue: https://github.com/davekilleen/Dex/issues/506
