# Claude Code hooks

These hooks provide deterministic lifecycle behavior for Claude Code. Cursor does not run Claude Code hooks.

The wiring sources of truth are:

- Repository-wide hooks: [`.claude/settings.json`](../settings.json)
- Skill-scoped hooks: each skill's `hooks` frontmatter
- Direct callers: the scripts and workflows named below

Claude Code sends hook-event JSON on standard input. Any `.cjs` hook that consumes that payload must parse stdin file descriptor 0 and fail open when the payload is absent or invalid. The contract is enforced by `tests/input-contract.test.cjs`; `CLAUDE_HOOK_*` environment variables are not hook-payload inputs.

## Repository-wide wiring

These commands are wired in `.claude/settings.json` and run independently of any skill.

| Event | Matcher | Command | Purpose |
|---|---|---|---|
| `SessionStart` | all | `bash .claude/hooks/session-start.sh` | Inject the current Dex session context and run the bounded smoke fallback when no clean check completed on the current local day. |
| `SessionStart` | all | `python3 "$CLAUDE_PROJECT_DIR/core/utils/update_verifier.py" --vault "$CLAUDE_PROJECT_DIR" --session-start` | Perform the bounded release-evidence check. |
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
| `/daily-plan` | `Stop` | all | `daily-plan-quick-ref.cjs` | Generate `00-Inbox/Daily_Prep/YYYY-MM-DD-quickref.md` from the daily plan. |
| `/career-coach` | `PostToolUse` | `Write` | `career-evidence-capture.cjs` | Append metric- or outcome-bearing career evidence to the Career Evidence Log. |

`post-meeting-person-update.cjs` and `career-evidence-capture.cjs` are not global `PostToolUse` hooks.

## Direct and script callers

These files are not registered as repository-wide lifecycle hooks.

| File | Caller | Purpose |
|---|---|---|
| `meeting-cache-builder.cjs` | Work MCP meeting-cache workflow | Build `System/Memory/meeting-cache.json`. Work MCP exposes `rebuild_meeting_cache`; its missing-cache guidance also names the standalone Node command. |
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
