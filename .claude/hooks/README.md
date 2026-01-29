# Hooks

**Purpose:** User-defined shell commands that execute at various points in Claude Code's lifecycle.

**Status:** ⚠️ **Claude Code Only** - Hooks currently only work in Claude Code desktop/CLI, not in Cursor.

**Documentation:** [Claude Code Hooks Guide](https://code.claude.com/docs/en/hooks-guide)

---

## Important: Claude Code vs Cursor

**How sessions end:**

| Environment | How Sessions End | Hooks That Work |
|-------------|------------------|-----------------|
| **Claude Code** | Graceful shutdown via `exit` command or proper quit | All hooks including SessionStart/SessionEnd |
| **Cursor** | Closing window terminates process immediately | None - no hook system currently |

**Key difference:** When you close Cursor's window, the process terminates instantly with no opportunity for cleanup code to run. SessionEnd and SessionStart hooks require a proper shutdown sequence that only exists in Claude Code.

**For Cursor users:** Use explicit commands like `/daily-review` before closing, or wait for potential future hook support.

---

## What Are Hooks?

**Hooks** are automatic scripts that run when specific events happen in Claude Code. Think of them as "if this happens, then do that" rules.

**Simple example:**
- **Event:** You finish a conversation with Claude
- **Hook:** Automatically save what you learned to your learnings file

Instead of asking Claude to remember to do something (which it might forget), hooks make it happen automatically every time.

**Technical note:** Hooks are shell scripts (bash, Python, etc.) that execute at lifecycle events, providing deterministic behavior rather than relying on LLM decisions.

### Complete List of Hook Events

| Hook Event | When It Fires | Can Block? |
|-----------|---------------|------------|
| **PreToolUse** | Before Claude calls any tool (Read, Edit, Shell, etc.) | Yes - can prevent tool execution |
| **PostToolUse** | After a tool call completes | No |
| **PermissionRequest** | When a permission dialog is shown to user | Yes - can auto-allow or auto-deny |
| **UserPromptSubmit** | When user submits a prompt, before Claude processes it | No |
| **Notification** | When Claude Code sends a notification (needs input, etc.) | No |
| **Stop** | When Claude Code finishes responding | No |
| **SubagentStop** | When a subagent task completes | No |
| **PreCompact** | Before Claude Code compacts conversation context | No |
| **SessionStart** | When Claude Code starts a new or resumed session | No |
| **SessionEnd** | When Claude Code session ends | No |
| **Setup** | When invoked with `--init`, `--init-only`, or `--maintenance` | No |

### Real Examples: Traditional vs Hooks

#### Example 1: Automatic Learning Capture

**Traditional workflow (manual):**
1. You finish your work session
2. You forget to capture what you learned
3. Tomorrow you make the same mistakes
4. Insights are lost forever

**With SessionEnd hook in Claude Code (automatic):**
1. You exit Claude Code gracefully (via `exit` command or proper shutdown)
2. SessionEnd hook fires automatically before process terminates
3. Hook extracts session learnings and saves them
4. Learnings written to `Session_Learnings/YYYY-MM-DD.md`
5. Next week, `/week-review` pulls these for synthesis

**Note for Cursor users:** SessionEnd hooks don't work in Cursor because closing the window terminates the process immediately. Instead, use the `/daily-review` command before closing, or use the Stop hook (fires when Claude finishes responding).

#### Example 2: Never Forget to Review Your Day

**Traditional workflow (manual):**
1. End of day arrives
2. You're tired and skip your daily review
3. You forget what you accomplished
4. Your weekly planning has no data to work with

**With Stop hook (automatic):**
1. Claude finishes responding to your last request
2. If it's after 6pm and no review exists today
3. Hook reminds you: "🌅 End of day - run `/daily-review`?"
4. You either review now or consciously skip it
5. Never accidentally forget

#### Example 3: Desktop Notifications When You're Needed

**Traditional workflow (manual):**
1. You ask Claude to process 20 meeting notes
2. You switch to Slack to work
3. Claude finishes but you don't notice for 15 minutes
4. You check back repeatedly (wasted attention)

**With Notification hook (automatic):**
1. You ask Claude to process meetings
2. You switch to other work confidently
3. Processing completes
4. Desktop notification: "✅ Dex finished - 20 meetings processed"
5. You return exactly when needed

#### Example 4: Protected System Files

**Traditional workflow (manual):**
1. You tell Claude "don't edit 03-Tasks/Tasks.md directly, use the Work MCP"
2. During a complex workflow, Claude accidentally edits 03-Tasks/Tasks.md
3. The file format breaks
4. You have to manually fix it

**With PreToolUse hook (automatic):**
1. Claude tries to edit `03-Tasks/Tasks.md` directly
2. PreToolUse hook fires before the edit
3. Hook blocks the operation: "Use Work MCP tools instead"
4. Claude sees the message and uses proper tool
5. Your task system stays consistent

### Hooks vs Skills vs Agents

| Aspect | Hooks | Skills | Agents |
|--------|-------|--------|--------|
| **Trigger** | Automatic event-driven shell commands | Manual `/command` invocation | Claude delegates complex tasks |
| **Visibility** | Silent background operation | Explicit user action | Returns summary |
| **Environment** | Claude Code only | Cursor + Claude Code | Cursor + Claude Code |
| **Language** | Bash, Python, any shell script | Markdown instructions | Markdown instructions |
| **Use case** | Enforce rules (format, validate, block) | User workflows | Multi-step analysis |
| **Example** | Auto-format code after edits | `/daily-plan` command | `project-health` scan |

---

## Configuration

Hooks are configured in `~/.claude/settings.json` or `.claude/settings.json` (project-level).

**Basic structure:**

```json
{
  "hooks": {
    "EventName": [
      {
        "matcher": "ToolName",
        "hooks": [
          {
            "type": "command",
            "command": "your-shell-command-here"
          }
        ]
      }
    ]
  }
}
```

**Matchers:**
- Use exact tool name: `"Bash"`, `"Edit"`, `"Write"`
- Use multiple: `"Edit|Write"`
- Match all tools: `"*"`
- Empty string for event hooks without tools (SessionStart, Notification, etc.)

**Hook receives JSON input via stdin:**

```json
{
  "tool_use": { "name": "Bash", "id": "..." },
  "tool_input": { "command": "ls -la", "description": "List files" },
  "tool_result": { ... }  // Only in PostToolUse
}
```

**Exit codes:**
- `0` - Success, continue
- `1` - Failure (logged)
- `2` - Block the operation (PreToolUse only)

---

## Practical Examples for Dex

### 1. End-of-Day Reminder (Stop Hook)

Reminds you to run your daily review if it's evening and you haven't done it yet. Uses **Stop** hook which fires when Claude finishes responding (works in both Claude Code and potentially future Cursor support).

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/review-reminder.sh"
          }
        ]
      }
    ]
  }
}
```

`review-reminder.sh`:
```bash
#!/bin/bash
# Remind to review if it's evening and no review exists
hour=$(date +%H)
today=$(date +%Y-%m-%d)

if [ $hour -ge 17 ] && [ ! -f "00-Inbox/Daily_Reviews/${today}.md" ]; then
  echo "🌅 End of day - consider running /review to capture today's wins"
fi
```

**Why Stop instead of SessionEnd?** Stop hooks fire when Claude finishes any response, so they work during active sessions. SessionEnd only fires during graceful shutdown of Claude Code (not when closing Cursor window).

### 2. Desktop Notifications

Get notified when Claude Code needs your input, so you can work elsewhere.

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "osascript -e 'display notification \"Dex needs your input\" with title \"Dex\"'"
          }
        ]
      }
    ]
  }
}
```

### 3. Protect Your Core System Files

Prevents accidental edits to critical files that should only be modified through specific tools.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/protect-files.sh"
          }
        ]
      }
    ]
  }
}
```

`protect-files.sh`:
```bash
#!/bin/bash
# Block direct edits to files that should use MCP tools
file_path=$(jq -r '.tool_input.file_path // ""' | cat)

if [[ "$file_path" == *"03-Tasks/Tasks.md"* ]]; then
  echo "❌ Use Work MCP tools to modify 03-Tasks/Tasks.md (keeps task IDs in sync)"
  exit 2  # Exit code 2 blocks the operation
fi

exit 0  # Allow other files
```

### 4. Session End Logging (SessionEnd Hook - Claude Code Only)

**⚠️ Claude Code Only** - This example only works in Claude Code desktop/CLI with proper shutdown.

Logs session end timestamp when you exit Claude Code gracefully (via `exit` command or proper shutdown sequence). Does NOT work when closing Cursor window because the process terminates immediately.

**Note:** This hook only logs timestamps. Actual learning extraction happens via `/daily-review` command, which intelligently scans the session for patterns, mistakes, and improvements.

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/session-end.sh"
          }
        ]
      }
    ]
  }
}
```

`session-end.sh`:
```bash
#!/bin/bash
# Log session end time - runs during graceful Claude Code shutdown
date=$(date +%Y-%m-%d)
time=$(date +%H:%M)
mkdir -p "00-Inbox/Session_Learnings"
echo "Session ended at ${time}" >> "00-Inbox/Session_Learnings/${date}.md"
```

**For Cursor users:** Use `/daily-review` command manually before closing, or use Stop hooks (Example 1) which fire when Claude finishes responding.

### 5. Morning Greeting (SessionStart Hook - Claude Code Only)

**⚠️ Claude Code Only** - Welcomes you when starting a new Claude Code session. Does not work in Cursor (no SessionStart event).

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/morning-greeting.sh"
          }
        ]
      }
    ]
  }
}
```

`morning-greeting.sh`:
```bash
#!/bin/bash
# Friendly morning greeting with planning reminder
hour=$(date +%H)
today=$(date +%Y-%m-%d)

if [ $hour -lt 12 ] && [ ! -f "00-Inbox/Daily_Plans/${today}.md" ]; then
  echo "☀️ Good morning! Run /daily-plan when you're ready to start your day"
fi
```

**For Cursor users:** No direct equivalent - you'll need to remember to run `/daily-plan` manually when starting your day.

---

## Security Warning

⚠️ **Hooks run automatically with your current environment credentials.** Always review hook code before adding it. Malicious hooks can exfiltrate data.

See [Security Considerations](https://code.claude.com/docs/en/hooks#security-considerations) in official docs.

## Related

- **MCP** (`.claude/mcp/`) - External tool integrations
- **Agents** (`.claude/agents/`) - Multi-step autonomous tasks
- **Scripts** (`.scripts/`) - Standalone automation tools
