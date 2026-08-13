# Hook inventory (three buckets)

This is the #506 follow-up inventory. It classifies every file under
`.claude/hooks/` so the next slices know what to move, what to wrap, and
what to leave. **Do not mass-migrate hooks.**

The harness is not the product. Claude Code hooks stay the best path for
automatic in-chat behaviour (**Tier 3 Full**). The *guarantee* that other
clients need from the gates bucket — refuse a destructive command or an
unsafe path — now lives in `core/gates/` and is exposed as the Work MCP
tool `check_safety_gate` (**Tier 1 Core**). Claude Code still auto-fires
the same function via the hook below.

Capability contract: [`HARNESS-CAPABILITY.md`](./HARNESS-CAPABILITY.md).

## 1. Scheduled (OS / launchd already)

These are not Claude Code hooks. They already run on a clock from `.scripts/`
and are **Tier 1 Core** today. Listed here so they are not confused with
in-turn files that happen to live next to hooks.

| Job | Cadence | What it does |
| --- | --- | --- |
| `com.dex.meeting-intel` | every 30 minutes | Sync meetings into the vault |
| `com.dex.smoke-nightly` | nightly | Local health smoke |
| `com.dex.changelog-checker` | every 6 hours | Watch Anthropic’s changelog |
| `com.dex.learning-review` | weekly | Prompt review of pending learnings |
| `com.dex.obsidian-sync` | daemon | Optional Obsidian live sync |

Hook-adjacent scripts that are **not** lifecycle hooks (direct callers):

| File | Caller |
| --- | --- |
| `meeting-cache-builder.cjs` | Work MCP meeting-cache workflow |
| `integration-concierge.cjs` | Onboarding / `/getting-started` / `/dex-level-up` |
| `maintenance.cjs` | Manual maintenance scan |
| `paths.cjs`, `adapters/` | Shared support code |

## 2. In-turn inject

These stuff facts into the current turn. An OS timer cannot substitute
without a harness that can still show the user the notice. **This slice
does not migrate inject hooks.** Session boot and person inject-on-read
are a separate slice.

| File | Event | Payload |
| --- | --- | --- |
| `session-start.sh` | `SessionStart` | Pillars, quarter goals, week priorities, urgent tasks, plus remaining notices (onboarding, health, meeting queue) |
| `person-context-injector.cjs` | `PreToolUse` / Read | Person page inject-on-read |
| `company-context-injector.cjs` | `PreToolUse` / Read | Company page inject-on-read |
| `health-pulse.sh` | `UserPromptSubmit` | Mid-session stale-health nudge |
| `connection-health-checker.cjs` | `SessionStart` | Integration health glance |
| `dex-core-orientation.sh` | `SessionStart` | Contributor orientation (this repo) |
| `update_verifier.py --session-start` | `SessionStart` | Bounded daily release-evidence check (`core/utils/`, not this folder) |
| `feedback_sweep.py` / `release_notes_sweep.py` | `SessionStart` | Once-daily inbox / what’s-new (`core/utils/`) |
| `meeting-queue-check.cjs` | called from `session-start.sh` | Unprocessed-meeting notice |
| `career-evidence-capture.cjs` | `PostToolUse` Write/Edit | Surfaces a sourced evidence candidate |
| `daily-plan-quick-ref.cjs` | skill-scoped `Stop` | Writes the daily quickref |

## 3. Gates

These block or redirect a call **before** it runs. Reimplementing the
Claude-only matchers on another harness means that harness growing an
equivalent hook model. The interceptors (destructive commands, unsafe
paths, a live migration lock) are **Tier 1 Core**.

| File | Event | Why it is a gate |
| --- | --- | --- |
| `dex-safety-guard.sh` | `PreToolUse` / Bash and MCP | **Now a thin wrapper** around `core/gates/safety.py` for destructive commands and unsafe paths. The Claude-only scraper matcher (Firecrawl / RAG-browser) stays in the hook. |
| `ensure-mcp-user-scope.cjs` | `PreToolUse` / Bash | Requires an explicit scope for `claude mcp add`. Matcher; not this slice. |
| `install-learnings.sh` | `Stop` | Blocks Stop once per day when unused learnings have piled up. Not this slice. |
| `soft-promise-detector.py` | `UserPromptSubmit` | Offers to capture a commitment in the message just sent. Not this slice. |

## Out of these three buckets (not this slice)

Session-end writers are neither inject nor gates nor scheduled work:

| File | Event | Notes |
| --- | --- | --- |
| `session-end.sh` | `SessionEnd` | Session marker / transcript reference |
| `vault-autocommit.cjs` | `SessionEnd` | Optional local Git checkpoint |
| `memory_mirror.py` | `SessionEnd` | Copy Claude Code project notes into the vault (`core/utils/`) |
| `post-meeting-person-update.cjs` | skill-scoped `PostToolUse` | Updates person pages after a meeting note write |

Tests live in `tests/`. The observation layer is intentionally absent.

## MCP tools any harness can call

| Tool | Server | When to call | Claude Code |
| --- | --- | --- | --- |
| `check_safety_gate` | `dex-work-mcp` | Before a destructive command or unsafe path | `dex-safety-guard.sh` auto-fires the same function |

Shared implementation: `core/gates/safety.py`.
