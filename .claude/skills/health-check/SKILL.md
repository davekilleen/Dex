---
name: health-check
description: Diagnose and fix Dex system health issues — MCP servers, config, recent errors
---

## Purpose

Diagnose what's working, what's broken, and fix what can be fixed. This is Dex's self-repair system. It reads health data from pre-flight checks and error logs, translates technical failures into plain language, and offers specific fixes.

## When to Run

- User types `/health-check`
- User says "fix health issues" or "something's broken"
- User says "check health" or "system status"
- After session start shows pre-flight warnings
- When an MCP tool fails and user wants to investigate

---

## Execution

### Step 1: Gather Health Data

Read both health files silently. Don't show raw JSON to the user.

**A. Pre-flight results:**

```
Read: .logs/mcp-health.json
```

This file contains cached results from the last pre-flight check. Each server entry has:
- `status`: "ok" or "error"
- `error`: technical error message (for your diagnosis)
- `humanError`: plain-language message (for the user)
- `checkedAt`: when it was last checked

**B. Error queue:**

```
Read: .logs/error-queue.json
```

This file contains recent errors from MCP tool calls. Each entry has:
- `source`: which MCP server (e.g., "mcp:work-mcp")
- `severity`: "error" or "warning"
- `message`: technical error (for your diagnosis)
- `humanMessage`: plain-language message (for the user)
- `context.tool`: which tool was called
- `timestamp`: when it happened
- `count`: how many times (deduped within 5-minute windows)
- `acknowledged`: whether user has been told about it

**C. If either file is missing:**

If `.logs/mcp-health.json` doesn't exist, the pre-flight checker hasn't run yet. Note this and offer to run one.

If `.logs/error-queue.json` doesn't exist, there are no logged errors. This is good news.

If the `.logs/` directory doesn't exist at all, the health system hasn't been set up yet. Tell the user:

```
The health monitoring system isn't set up yet. This is normal if you just updated Dex.

Want me to check your MCP servers manually? I can verify each one is working.
```

Then skip to Step 5 (manual check).

---

### Step 2: Display Health Summary

Present results in plain language, grouped by severity. **Never show raw JSON or stack traces.**

**If everything is healthy and no unacknowledged errors:**

```
All systems are running fine. Nothing to fix.

Last checked: [relative time, e.g., "2 hours ago"]
MCP servers: [X]/[Y] operational
Recent errors: None
```

Stop here. Don't pad with unnecessary detail.

---

**If there are issues, show them grouped by severity:**

```
Dex Health Report
━━━━━━━━━━━━━━━━

ERRORS (need attention)

  1. [Server name] — [humanMessage or humanError]
     When: [relative time]  |  Occurrences: [count]
     Tool affected: [tool name, if from error queue]

  2. [Server name] — [humanMessage or humanError]
     When: [relative time]  |  Occurrences: [count]

WARNINGS (worth knowing)

  3. [Server name] — [humanMessage or humanError]
     When: [relative time]

━━━━━━━━━━━━━━━━
[X] issues found  |  [Y] can be auto-fixed
```

**Formatting rules:**
- Show errors first, then warnings
- Use the `humanMessage` or `humanError` field — never the technical `message` or `error`
- Show relative timestamps ("2 hours ago", "yesterday at 3pm") not ISO timestamps
- If `count` > 1, show it — "Occurrences: 5" tells the user this is a persistent problem
- Combine pre-flight failures and error queue entries for the same server into one item
- Cap display at 10 issues. If more: "...and [N] more. Want to see all?"

---

### Step 3: Diagnose and Propose Fixes

For each issue, analyze the technical `message`/`error` field (not shown to user) and propose a specific fix. Use this mapping:

**Module/Package Issues:**

| Technical pattern | What to tell the user | Suggested fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'X'` | [Server] can't start — missing Python package | "Run `pip install -e dex-core` from your vault folder to reinstall packages." |
| `ImportError: cannot import name 'X'` | [Server] has a code compatibility issue | "This usually fixes itself with an update. Run `/dex-update` to get the latest version." |
| `No module named 'core.mcp.X'` | [Server] can't find its code | "The server file may be missing. Want me to check if the file exists?" |

**Config Issues:**

| Technical pattern | What to tell the user | Suggested fix |
|---|---|---|
| `VAULT_PATH not set` or `KeyError: 'VAULT_PATH'` | [Server] doesn't know where your vault is | "Your MCP config may need the vault path. Want me to check `.mcp.json`?" |
| `JSONDecodeError` | [Server] got corrupted data | "A config or data file has invalid formatting. Want me to find and fix it?" |
| `FileNotFoundError: .mcp.json` | MCP configuration file is missing | "Your `.mcp.json` file is missing. Want me to regenerate it from the example?" |

**File/Permission Issues:**

| Technical pattern | What to tell the user | Suggested fix |
|---|---|---|
| `FileNotFoundError: Tasks.md` | Task file not found | "Your task file is missing — the vault may need setup. Want me to create it?" |
| `FileNotFoundError` (other) | [Server] can't find a required file | "The file `[path]` is missing. Want me to check if it should exist?" |
| `PermissionError` | Can't write to [file] | "Check file permissions on `[path]`. On Mac, try: `chmod 644 [path]`" |

**Connection Issues:**

| Technical pattern | What to tell the user | Suggested fix |
|---|---|---|
| `ECONNREFUSED` | [Server] isn't responding | "The server process may have stopped. Restarting your editor usually fixes this." |
| `TimeoutError` or `timed out` | [Server] took too long to respond | "This could be a one-off. If it keeps happening, restart your editor." |
| `ANTHROPIC_API_KEY not set` | API key is missing | "Run `/ai-setup` to configure your API key." |

**Catch-all:**

| Technical pattern | What to tell the user | Suggested fix |
|---|---|---|
| Anything else | [Server] hit an unexpected error | "This is unusual. Want me to look at the server code to investigate?" |

**Present fixes as a numbered list tied to each issue:**

```
Recommended fixes:

  1. Granola MCP — missing package
     → Run: pip install -e dex-core
     [Auto-fixable]

  2. Work MCP — task file not found
     → Want me to check if 03-Tasks/Tasks.md exists?
     [Needs investigation]

  3. Career MCP — permission error on evidence file
     → Run: chmod 644 05-Areas/Career/Evidence/2026-Q1.md
     [Manual fix]
```

---

### Step 4: Offer to Fix

After showing the diagnosis, offer to take action:

```
Want me to try fixing these? Here's what I can do:

  Auto-fix (I'll handle it):
  • Reinstall Python packages
  • Regenerate missing config from example
  • Create missing vault files (Tasks.md, etc.)
  • Validate and repair .mcp.json

  Manual (you'll need to do this):
  • File permission changes
  • Editor restart
  • API key configuration (/ai-setup)

[Fix what you can] / [Show me details first] / [Skip for now]
```

**If user says "fix what you can":**

Execute auto-fixable items in order:

1. **Missing packages:** Run `pip install -e dex-core` from the dex-core directory
2. **Missing .mcp.json:** Copy from `.mcp.json.example`, substitute VAULT_PATH
3. **Invalid .mcp.json:** Read it, validate JSON, identify the issue, offer to rewrite
4. **Missing vault files:** Create with minimal valid content (e.g., empty Tasks.md with headers)
5. **Corrupted JSON data files:** Read the file, identify the corruption, offer to reset or repair

After each fix, report:
```
✓ Reinstalled Python packages
✓ Created missing 03-Tasks/Tasks.md
✗ Couldn't fix permission on Evidence file — you'll need to run:
  chmod 644 05-Areas/Career/Evidence/2026-Q1.md
```

**If user says "show me details first":**

For each issue, show the full technical context (this is the one time you show technical detail):

```
Issue #1: Granola MCP — missing package

  Technical error: ModuleNotFoundError: No module named 'granola_server'
  Server config: dex-granola-mcp in .mcp.json
  Last working: 2 days ago

  Fix: pip install -e dex-core

  This reinstalls all MCP server packages. It takes about 10 seconds.
```

---

### Step 5: Acknowledge Errors

After addressing issues (whether auto-fixed or explained):

**Update the error queue:**

Read `.logs/error-queue.json`, set `acknowledged: true` on every entry that was shown to the user. Write the file back.

This prevents the same errors from resurfacing at the next session start.

**Note:** If the error queue file doesn't exist or is empty, skip this step.

---

### Step 6: Fresh Re-Check (Optional)

At the end, offer a fresh check:

```
Want me to run a fresh pre-flight check to verify everything?
```

**If yes:**

1. Delete `.logs/mcp-health.json` (forces re-check)
2. Run the pre-flight checker:
   ```bash
   python3 "$VAULT_PATH/dex-core/core/utils/preflight.py" 2>/dev/null || python3 "core/utils/preflight.py" 2>/dev/null
   ```
3. Read the newly generated `.logs/mcp-health.json`
4. Report results:
   ```
   Fresh check complete:

   ✓ work-mcp — OK
   ✓ calendar-mcp — OK
   ✓ career-mcp — OK
   ✗ granola-mcp — still failing (missing package)
   ✓ dex-improvements-mcp — OK
   ...

   [X]/[Y] MCP servers operational
   ```

**If the pre-flight script doesn't exist yet** (health system not fully built):

Fall back to manual checks:

```python
# For each server in .mcp.json, try importing the module
python3 -c "import core.mcp.work_server" 2>&1
python3 -c "import core.mcp.calendar_server" 2>&1
# etc.
```

Report which imports succeed and which fail.

---

### Step 7: Track Usage (Silent)

Update `System/usage_log.md` to mark health check as used.

**Analytics (Silent):**

Call `track_event` with event_name `health_check_completed` and properties:
- `errors_found`: number of errors found
- `warnings_found`: number of warnings found
- `auto_fixed`: number of issues auto-fixed

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".

---

## Edge Cases

### No Health Files Exist

The health system hasn't been set up yet. This is expected for new or recently updated Dex installations.

Offer to do a manual check of MCP servers by testing imports, then report what's working.

### Error Queue is Very Large

If error-queue.json has more than 20 unacknowledged entries:

```
There are [N] unacknowledged errors in the queue. Here are the most recent 10:

[Show top 10 by timestamp]

The older errors are likely symptoms of the same issues. Want me to acknowledge them all after we fix the root causes?
```

### Same Server Appears in Both Files

If a server has both a pre-flight failure AND error queue entries, combine them:

```
Granola MCP — can't start (missing package)
  Pre-flight: Failed to import at [time]
  Also: 3 tool errors since [time] (task creation, task update, etc.)
  Root cause: Missing Python package — fixing the import will resolve the tool errors too
```

### All Servers Healthy but Errors Exist

This means servers started fine but tools failed during use. Focus on the error queue:

```
All MCP servers are starting correctly, but some tools had errors recently:

  1. Work MCP — task creation failed (3 times, yesterday)
     This might be a data issue rather than a server problem.
     Want me to investigate the task file?
```

### User Just Wants Quick Status

If user says "is everything working?" or "quick health check":

Give the short version only:

```
MCP Servers: [X]/[Y] operational
Recent errors: [N] (or "None")
[One-liner about any critical issue, or "Nothing needs attention."]
```

Don't go into fix mode unless asked.

---

### Granola Mobile Recording Check

As part of the health check, also check for Granola migration status:

1. Run: `node .scripts/meeting-intel/check-granola-migration.cjs 2>/dev/null || echo '{"status":"not_applicable"}'`
2. If status is `migration_available`, add to the health report under a "Recommended" section:
   ```
   RECOMMENDED

   Granola mobile recordings — not yet enabled
     Your phone call recordings aren't syncing to Dex yet.
     To enable: say "enable mobile recordings" or run /process-meetings
   ```
3. If status is `token_expired`, add under WARNINGS:
   ```
   Granola sign-in expired — mobile recordings paused
     Desktop meetings still sync, but phone recordings need a refresh.
     Say "refresh Granola" to fix.
   ```
4. If `authenticated` or `not_applicable`: don't mention it.

---

## Related Commands

- `/ai-status` — Check AI model configuration specifically
- `/ai-setup` — Configure API keys and model preferences
- `/dex-update` — Update Dex (often fixes package issues)
- `/xray` — Understand how Dex's architecture works under the hood
