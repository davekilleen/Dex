# Hook inventory (three buckets)

This is the #506 follow-up inventory. It classifies every file under
`.claude/hooks/` so the next slices know what to move, what to wrap, and
what to leave. **Do not mass-migrate hooks.**

The harness is not the product. Claude Code remains the reference for Dex's
complete automatic in-chat behaviour (**Tier 3 Full**). The shared guarantees
other clients need — session boot context, person context, and destructive-action
decisions — live in `core/context/` and `core/gates/`. They are available both
as Work MCP tools and through the generated portable plugin. Codex and Claude
plugin hosts can run the shared SessionStart and PreToolUse adapters after the
user trusts them; other MCP clients receive an advisory decision only.

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
without a harness that can still show the user the notice.

| File | Event | Payload |
| --- | --- | --- |
| `session-start.sh` | `SessionStart` | **Now a thin wrapper** around `core/context/session_boot.py` for pillars, quarter goals, week priorities, urgent tasks. Remaining notices (onboarding, health, meeting queue) stay in the hook. |
| `person-context-injector.cjs` | `PreToolUse` / Read | **Now a thin wrapper** around `core/context/person_context.py`. |
| `company-context-injector.cjs` | `PreToolUse` / Read | Company page inject-on-read. Not in this slice. |
| `health-pulse.sh` | `UserPromptSubmit` | Mid-session stale-health nudge |
| `connection-health-checker.cjs` | `SessionStart` | Integration health glance |
| `dex-core-orientation.sh` | `SessionStart` | Contributor orientation (this repo) |
| `update_verifier.py --session-start` | `SessionStart` | Bounded daily release-evidence check (`core/utils/`, not this folder) |
| `feedback_sweep.py` / `release_notes_sweep.py` | `SessionStart` | Once-daily inbox / what’s-new (`core/utils/`) |
| `meeting-queue-check.cjs` | called from `session-start.sh` | Unprocessed-meeting notice |
| `career-evidence-capture.cjs` | `PostToolUse` Write/Edit | Surfaces a sourced evidence candidate |
| `daily-plan-quick-ref.cjs` | skill-scoped `Stop` | Writes the daily quickref |

**Portable slice:** `session-start.sh` (strategic payload only) and
`person-context-injector.cjs` share one Python implementation with MCP. The
portable plugin vendors those exact modules and maps SessionStart. Person
context remains on-demand outside Claude's Read interceptor. Nothing else in
this bucket is silently treated as portable.

## 3. Gates

These block or redirect a call **before** it runs. The shared destructive-action
gate is mapped to verified PreToolUse events in the Codex/Claude plugin; every
other gate still needs a host-specific equivalent before Dex can claim it.

| File | Event | Why it is a gate |
| --- | --- | --- |
| `dex-safety-guard.sh` | `PreToolUse` / Bash and MCP | Calls the shared safety gate and blocks unsafe shell / MCP before the call runs |
| `ensure-mcp-user-scope.cjs` | `PreToolUse` / Bash | Requires an explicit scope for `claude mcp add` |
| `install-learnings.sh` | `Stop` | Blocks Stop once per day when unused learnings have piled up |
| `soft-promise-detector.py` | `UserPromptSubmit` | Offers to capture a commitment in the message just sent |

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
| `boot_today` | `dex-work-mcp` | Session start | `session-start.sh` auto-fires the same function |
| `get_person_context` | `dex-work-mcp` | When a person is mentioned | `person-context-injector.cjs` auto-fires the same function |
| `check_safety_gate` | `dex-work-mcp` and portable plugin | Before a risky shell/path action; advisory unless an interceptor enforces it | `dex-safety-guard.sh` and trusted portable PreToolUse hooks enforce the same decision |

Shared implementation: `core/context/session_boot.py`, `core/context/person_context.py`, and `core/gates/safety.py`.
