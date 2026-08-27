# Claude Code hooks

These hooks provide deterministic lifecycle behavior for Claude Code (**Tier 3 Full**). Cursor, Codex, and other Agent Skills harnesses do not run Claude Code hooks; they stop at **Tier 2 Skills**. Session boot and person context are also **Tier 1 Core** tools (`boot_today`, `get_person_context`) — Cursor/ChatGPT call them; these hooks auto-fire the same functions. The three-bucket inventory (scheduled / in-turn inject / gates) is in [`docs/architecture/HOOK-INVENTORY.md`](../../docs/architecture/HOOK-INVENTORY.md). Do not mass-migrate hooks.

The wiring sources of truth are:

- Repository-wide hooks: [`.claude/settings.json`](../settings.json)
- Skill-scoped hooks: each skill's `hooks` frontmatter
- Direct callers: the scripts and workflows named below

Claude Code sends hook-event JSON on standard input. Any `.cjs` hook that consumes that payload must parse stdin file descriptor 0 and fail open when the payload is absent or invalid. The contract is enforced by `tests/input-contract.test.cjs`; `CLAUDE_HOOK_*` environment variables are not hook-payload inputs.

## Repository-wide wiring

These commands are wired in `.claude/settings.json` and run independently of any skill.

| Event | Matcher | Command | Purpose |
|---|---|---|---|
| `SessionStart` | all | `bash .claude/hooks/session-start.sh` | Inject the current Dex session context, show the latest complete proactive-health status, and run the bounded smoke fallback when no clean check completed on the current local day. |
| `SessionStart` | all | `python3 "$CLAUDE_PROJECT_DIR/core/utils/update_verifier.py" --vault "$CLAUDE_PROJECT_DIR" --session-start` | Perform the bounded release-evidence check. |
| `SessionStart` | all | `python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/skill-freshness.py" --session-start` | Record which skills were already on disk at startup or resume so a skill that lands mid-session can be injected without waiting for a restart. Compact, clear, and fork keep that baseline and ask the host to re-scan; they do not reset it. |
| `UserPromptSubmit` | all | `python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/skill-freshness.py"` | If an update wrote a new `SKILL.md` after session start, inject it as additional context so it is usable this session even when the host slash list still omits it. |
| `UserPromptSubmit` | all | `python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/soft-promise-detector.py"` | Detect soft commitments in the user's message and offer a one-time capture. |
| `UserPromptSubmit` | all | `bash "$CLAUDE_PROJECT_DIR/.claude/hooks/health-pulse.sh"` | Mid-session health pulse: read the latest proactive-health snapshot's age and status (two file reads, never computes) and interject at most once per day when the checkup is stale or newly critical — so bad health news does not wait for the next fresh session. |
| `UserPromptSubmit` | all | `bash "$CLAUDE_PROJECT_DIR/.claude/hooks/claude-composition-refresh.sh"` | Recompose `CLAUDE.md` when the personal-instructions block has moved. This keeps custom instructions live; it does not refresh the host slash-skill list. |
| `PreToolUse` | `Read` | `node .claude/hooks/person-context-injector.cjs` | Inject matching person context before a file read. |
| `PreToolUse` | `Read` | `node .claude/hooks/company-context-injector.cjs` | Inject matching company context before a file read. |
| `PreToolUse` | `Bash` | `bash .claude/hooks/dex-safety-guard.sh` | Block unsafe shell commands and redirect disallowed MCP usage. |
| `PreToolUse` | `Bash` | `node .claude/hooks/ensure-mcp-user-scope.cjs` | Require an explicit scope for `claude mcp add`. |
| `PreToolUse` | `mcp__.*` | `bash .claude/hooks/dex-safety-guard.sh` | Apply the MCP safety rules before MCP calls. |
| `SessionEnd` | all | `"$CLAUDE_PROJECT_DIR"/.claude/hooks/session-end.sh "$transcript_path"` | Record the session-end marker and transcript reference. |
| `SessionEnd` | all | `node "$CLAUDE_PROJECT_DIR"/.claude/hooks/vault-autocommit.cjs` | Safely checkpoint eligible vault changes when no mutation is active. |

Settings also uses the macOS system ping for `Stop` and permission/elicitation `Notification` events. Those entries do not invoke repository hook files.

## Skill-scoped wiring

These hooks are declared in skill frontmatter and exist only while that skill runs.

| Skill | Event | Matcher | Hook | Purpose |
|---|---|---|---|---|
| `/process-meetings` | `PostToolUse` | `Write` | `post-meeting-person-update.cjs` | Update recent interactions on existing person pages after a meeting note is written. |
| `/daily-plan` | `Stop` | all | `daily-plan-quick-ref.cjs` | Generate `00-Inbox/Daily_Plans/YYYY-MM-DD-quickref.md` from the daily plan. |
| `/career-coach` | `PostToolUse` | `Write` | `career-evidence-capture.cjs` | Detect possible career evidence and return a provenance-bearing, unconfirmed candidate; the hook never writes evidence. |

`post-meeting-person-update.cjs` and `career-evidence-capture.cjs` are not global `PostToolUse` hooks.

## Direct and script callers

These files are not registered as repository-wide lifecycle hooks.

| File | Caller | Purpose |
|---|---|---|
| `meeting-cache-builder.cjs` | Work MCP meeting-cache workflow | Build `System/Memory/meeting-cache.json`. Work MCP exposes `rebuild_meeting_cache`; its missing-cache guidance also names the standalone Node command. |
| `meeting-queue-check.cjs` | `session-start.sh` | Detect unprocessed meetings in the landing zone (synced, manually captured, or queued) and inject a one-block notice so the session processes them in the background. |
| `integration-concierge.cjs` | Onboarding, `/getting-started`, and `/dex-level-up` | Scan the vault for integration signals and return ranked recommendations. |
| `maintenance.cjs` | Manual: `node .claude/hooks/maintenance.cjs` | Report stale inbox files, broken WikiLinks, orphaned person pages, and old agent memory. |

`paths.cjs` and `adapters/` are shared support code, not lifecycle hooks.

## Removed observation layer

The ambient-intelligence observation layer is intentionally removed. There are no observation hook files, settings entries, skill hooks, launchd triggers, or observation state paths in the product tree. Reintroducing it requires a new explicit design and wiring review.

## Testing

Run the hook contract and context-injector tests with:

```bash
node .claude/hooks/tests/input-contract.test.cjs
node .claude/hooks/tests/context-injectors.test.cjs
```

Hooks run with the user's current environment credentials. Review hook code and wiring before adding or changing a registration. See the [Claude Code hooks guide](https://code.claude.com/docs/en/hooks-guide) for the platform contract.
