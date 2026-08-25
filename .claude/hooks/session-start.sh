#!/bin/bash
# Claude Code SessionStart Hook
# Injects strategic hierarchy and tactical context
# For Dex personal knowledge system

# Prevent duplicate injection (symlinked working directories)
DEDUP_FILE="${DEX_SESSION_CONTEXT_DEDUP_FILE:-/tmp/dex-session-context-dedup}"
NOW=$(date +%s)
if [[ -f "$DEDUP_FILE" ]]; then
    LAST=$(cat "$DEDUP_FILE" 2>/dev/null || echo "0")
    if (( NOW - LAST < 5 )); then
        exit 0
    fi
fi
echo "$NOW" > "$DEDUP_FILE"

CLAUDE_DIR="$CLAUDE_PROJECT_DIR"
LEARNINGS_DIR="$CLAUDE_DIR/06-Resources/Learnings"
MISTAKES_FILE="$LEARNINGS_DIR/Mistake_Patterns.md"
PREFERENCES_FILE="$LEARNINGS_DIR/Working_Preferences.md"
ONBOARDING_MARKER="$CLAUDE_DIR/System/.onboarding-complete"

echo "=== Dex Session Context ==="
echo ""
echo "📅 Today: $(date '+%A, %B %d, %Y')"
echo ""

# Detect launch agents that still point to this vault's former location.
# Doctor owns the repair; session start remains read-only for these machine
# files. Detection is delegated to core/utils/launch_agents.py — the exact
# module Doctor uses — so the hook can never warn about something Doctor
# refuses to see (breadcrumb guards, symlink normalization, plist parsing,
# and path-boundary matching all come from that one implementation).
if [[ -f "$ONBOARDING_MARKER" && -f "$CLAUDE_DIR/core/utils/launch_agents.py" ]]; then
    STALE_JOB_PYTHON="python3"
    if [[ -f "$CLAUDE_DIR/.venv/bin/python" ]]; then
        STALE_JOB_PYTHON="$CLAUDE_DIR/.venv/bin/python"
    fi
    STALE_JOB_STATUS=$( (cd "$CLAUDE_DIR" && "$STALE_JOB_PYTHON" -m core.utils.launch_agents --stale-check --vault "$CLAUDE_DIR") 2>/dev/null || true )
    if [[ "$STALE_JOB_STATUS" == "stale-job-found" ]]; then
        echo "Dex found a background job that still points to this vault's old location — run /dex-doctor to fix this safely."
    fi
fi

# First-time setup must use the completion marker, not a seeded folder: fresh
# vaults already contain the standard folder structure. Make the canonical MCP
# onboarding flow explicit at session start so even a first message of "hi"
# cannot bypass it. A completed vault stays silent and continues normally.
if [[ ! -f "$ONBOARDING_MARKER" ]]; then
    echo "🚨 FIRST-TIME SETUP REQUIRED — THIS VAULT HAS NEVER BEEN SET UP"
    if [[ -f "$CLAUDE_DIR/System/.onboarding-session.json" ]]; then
        echo "Onboarding was started earlier but never finished. Whatever the user's first message says — even just 'hi' — resume setup NOW: call start_onboarding_session() from onboarding-mcp (it restores their progress) and continue the flow in .claude/flows/onboarding.md."
    else
        echo "Whatever the user's first message says — even just 'hi' — begin onboarding NOW: call start_onboarding_session() from onboarding-mcp and follow the flow in .claude/flows/onboarding.md. Do not ask what they are working on; setup comes first."
    fi
    echo "(Background checks stay disabled until setup completes.)"
    echo ""
fi

# SELF-LEARNING: Run background checks inline (fallback if Launch Agents not installed)
# These are fast checks with interval throttling - only run when needed
if [[ -f "$ONBOARDING_MARKER" ]]; then

    # This records only the built-in session_started event and the analytics
    # helper owns consent, delivery, and the safe local receipt. Keep the
    # result long enough to show a fixed, non-sensitive receipt failure; never
    # print helper output or retry the delivery. A first-run vault emits none.
    if [[ -f "$CLAUDE_DIR/core/mcp/analytics_helper.py" ]]; then
        ANALYTICS_PYTHON="python3"
        if [[ -f "$CLAUDE_DIR/.venv/bin/python" ]]; then
            ANALYTICS_PYTHON="$CLAUDE_DIR/.venv/bin/python"
        fi
        ANALYTICS_TOTAL_TIMEOUT_SECONDS=3
        # macOS has no GNU timeout command. This standard-library wrapper
        # bounds the whole helper process (startup, imports, receipt work, and
        # request), not just requests.post, and kills its process group on a
        # timeout so a stalled descendant cannot outlive session start.
        ANALYTICS_RESULT=$(
            cd "$CLAUDE_DIR" && VAULT_PATH="$CLAUDE_DIR" \
                "$ANALYTICS_PYTHON" - "$ANALYTICS_PYTHON" \
                    core/mcp/analytics_helper.py --event session_started \
                    --request-timeout-seconds 2 "$ANALYTICS_TOTAL_TIMEOUT_SECONDS" \
                    2>/dev/null <<'PY'
import os
import signal
import subprocess
import sys

command = sys.argv[1:-1]
timeout_seconds = float(sys.argv[-1])
process = subprocess.Popen(
    command,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
    start_new_session=True,
)
try:
    output, _ = process.communicate(timeout=timeout_seconds)
except subprocess.TimeoutExpired:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.communicate()
    raise SystemExit(124)
sys.stdout.write(output)
raise SystemExit(process.returncode)
PY
        )
        ANALYTICS_STATUS=$?
        if [[ "$ANALYTICS_STATUS" -ne 0 || "$ANALYTICS_RESULT" == *receipt_write_failed* ]]; then
            echo "Dex could not save the local analytics receipt. No usage event was retried."
        fi
    fi

    # Claude Code changelog is now checked in daily plan Step 0.5 via fetch-changelog.cjs
    # Background checker removed (was never installed as LaunchAgent, redundant)

    # Check for pending learnings (if not checked today)
    if [[ -x "$CLAUDE_DIR/.scripts/learning-review-prompt.sh" ]]; then
        LAST_LEARNING_CHECK="$CLAUDE_DIR/System/.last-learning-check"
        TODAY=$(date +%Y-%m-%d)
        
        if [[ ! -f "$LAST_LEARNING_CHECK" ]] || [[ "$(cat "$LAST_LEARNING_CHECK")" != "$TODAY" ]]; then
            bash "$CLAUDE_DIR/.scripts/learning-review-prompt.sh" 2>/dev/null &
            echo "$TODAY" > "$LAST_LEARNING_CHECK"
        fi
    fi

    # Wait briefly for checks to complete (but don't block session start)
    sleep 0.1
fi

echo ""

# STRATEGIC HIERARCHY + urgent tasks — same payload as Work MCP boot_today.
# The hook stays a thin wrapper so Cursor/ChatGPT/Codex calling the tool get
# the same facts Claude Code injects here. Do not re-extract these in bash.
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION_BOOT_PY="$HOOK_DIR/../../core/context/session_boot.py"
if [[ -f "$SESSION_BOOT_PY" ]]; then
    BOOT_PYTHON="python3"
    if [[ -f "$CLAUDE_DIR/.venv/bin/python" ]]; then
        BOOT_PYTHON="$CLAUDE_DIR/.venv/bin/python"
    elif [[ -f "$HOOK_DIR/../../.venv/bin/python" ]]; then
        BOOT_PYTHON="$HOOK_DIR/../../.venv/bin/python"
    fi
    BOOT_OUTPUT=$("$BOOT_PYTHON" "$SESSION_BOOT_PY" --vault "$CLAUDE_DIR" --format hook-text 2>/dev/null || true)
    if [[ -n "$BOOT_OUTPUT" ]]; then
        echo "$BOOT_OUTPUT"
        echo ""
    fi
fi

# 5. Working Preferences
if [[ -f "$PREFERENCES_FILE" ]]; then
    PREF_COUNT=$(grep -c "^### " "$PREFERENCES_FILE" 2>/dev/null || echo "0")
    if [[ "$PREF_COUNT" -gt 0 ]]; then
        echo "--- Working Preferences ---"
        grep -A1 "^### " "$PREFERENCES_FILE" | grep -v "^--$" | head -10
        echo "---"
        echo ""
    fi
fi

# 6. Active Mistake Patterns
if [[ -f "$MISTAKES_FILE" ]]; then
    PATTERN_COUNT=$(grep -c "^### " "$MISTAKES_FILE" 2>/dev/null || echo "0")
    if [[ "$PATTERN_COUNT" -gt 0 ]]; then
        echo "--- Active Mistake Patterns ($PATTERN_COUNT) ---"
        awk '/^## Active Patterns/,/^## Resolved/' "$MISTAKES_FILE" | grep -A2 "^### " | grep -v "^--$" | head -15
        echo "---"
        echo ""
    fi
fi

# 7. Recent Learnings — removed from startup (redundant with Pending Learnings nudge)
# Available on-demand via /dex-whats-new --learnings

# 8. Pending Claude Code Updates
CHANGELOG_PENDING="$CLAUDE_DIR/System/changelog-updates-pending.md"
if [[ -f "$CHANGELOG_PENDING" ]]; then
    echo "--- 🆕 Claude Code Updates Detected ---"
    echo "New features or capabilities available!"
    echo "Run: /dex-whats-new"
    echo "---"
    echo ""
fi

# 9. Pending Learning Reviews
LEARNING_PENDING="$CLAUDE_DIR/System/learning-review-pending.md"
if [[ -f "$LEARNING_PENDING" ]]; then
    # Extract count from the file
    LEARNING_COUNT=$(grep "^\*\*Count:\*\*" "$LEARNING_PENDING" 2>/dev/null | sed 's/.*Count:\*\* \([0-9]*\).*/\1/')
    if [[ -n "$LEARNING_COUNT" ]]; then
        echo "--- 📚 Pending Learnings Review ($LEARNING_COUNT) ---"
        echo "Session learnings ready for review"
        echo "Run: /dex-whats-new --learnings"
        echo "---"
        echo ""
    fi
fi

# 10. New Vault Welcome (if < 7 days old and Phase 2 not completed)
ONBOARDING_MARKER="$CLAUDE_DIR/System/.onboarding-complete"
if [[ -f "$ONBOARDING_MARKER" ]]; then
    # Check if marker is less than 7 days old
    AGE_CHECK=$(find "$ONBOARDING_MARKER" -mtime -7 2>/dev/null)
    if [[ -n "$AGE_CHECK" ]]; then
        # Check if phase2_completed is false
        PHASE2_DONE=$(grep '"phase2_completed": true' "$ONBOARDING_MARKER" 2>/dev/null)
        if [[ -z "$PHASE2_DONE" ]]; then
            echo "--- 👋 Welcome! ---"
            echo "You're probably wondering what to do next..."
            echo "Try: /getting-started"
            echo "---"
            echo ""
        fi
    fi
fi

# 11. QMD Index Refresh (if stale > 12 hours)
QMD_TIMESTAMP="$CLAUDE_DIR/System/.last-qmd-update"
QMD_BIN="${QMD_BIN:-$(which qmd 2>/dev/null || echo '')}"
if [[ -x "$QMD_BIN" && -f "$ONBOARDING_MARKER" ]]; then
    NEEDS_UPDATE=false
    if [[ ! -f "$QMD_TIMESTAMP" ]]; then
        NEEDS_UPDATE=true
    else
        # Check if last update was > 1 hour ago (incremental update is fast, <2 seconds)
        LAST_UPDATE=$(cat "$QMD_TIMESTAMP" 2>/dev/null || echo "0")
        NOW=$(date +%s)
        AGE=$(( NOW - LAST_UPDATE ))
        if [[ $AGE -gt 3600 ]]; then
            NEEDS_UPDATE=true
        fi
    fi

    if [[ "$NEEDS_UPDATE" == "true" ]]; then
        # Run silently — no need to inject into context
        "$QMD_BIN" update >/dev/null 2>&1 &
        date +%s > "$QMD_TIMESTAMP"
    fi
fi

# 13. Recent Errors (from web app, server, or CLI)
ERROR_QUEUE="$CLAUDE_DIR/.logs/error-queue.json"
if [[ -f "$ERROR_QUEUE" ]]; then
    # Count unacknowledged errors using python (available on macOS)
    UNACK_COUNT=$(python3 -c "
import json
try:
    with open('$ERROR_QUEUE') as f:
        q = json.load(f)
    unack = [e for e in q if not e.get('acknowledged', False)]
    print(len(unack))
except:
    print(0)
" 2>/dev/null)

    if [[ "$UNACK_COUNT" -gt 0 ]]; then
        echo "--- ⚠️ Recent Errors ($UNACK_COUNT) ---"
        # Show the most recent 3 unacknowledged errors
        python3 -c "
import json
with open('$ERROR_QUEUE') as f:
    q = json.load(f)
unack = [e for e in q if not e.get('acknowledged', False)]
for e in unack[-3:]:
    src = e.get('source', '?')
    msg = e.get('message', 'Unknown')[:120]
    ts = e.get('timestamp', '')[:16]
    print(f'  [{src}] {ts} — {msg}')
" 2>/dev/null
        echo ""
        echo "These errors were captured from the Dex web app or server."
        echo "Ask: 'Show me the recent errors' or 'Fix the recent errors'"
        echo "---"
        echo ""
    fi
fi

# 18. Dex Health System — Pre-flight checks and error queue
# Runs preflight health checks (MCP servers, config files, etc.) and displays
# any queued errors. Silent when everything is healthy (no output = no display).
if [[ -f "$ONBOARDING_MARKER" ]]; then
    DEX_CORE_DIR="$CLAUDE_DIR"
    if [[ -f "$DEX_CORE_DIR/core/utils/preflight.py" ]]; then
        HEALTH_PYTHON="python3"
        if [[ -f "$CLAUDE_DIR/.venv/bin/python" ]]; then
            HEALTH_PYTHON="$CLAUDE_DIR/.venv/bin/python"
        fi
        if ! HEALTH_OUTPUT=$(cd "$DEX_CORE_DIR" && "$HEALTH_PYTHON" -c "
import sys
sys.path.insert(0, '.')
from core.utils.preflight import run_preflight, format_output, format_errors
health = run_preflight()
preflight = format_output(health)
errors = format_errors()
if preflight:
    print(preflight)
if errors:
    print(errors)
" 2>/dev/null); then
            echo "⚠️ Dex health check failed to run (see .claude/hooks/session-start.sh)"
        elif [[ -n "$HEALTH_OUTPUT" ]]; then
            echo "$HEALTH_OUTPUT"
        fi
    fi
fi

# 19. Daily self-check fallback.
# The 03:15 Launch Agent remains the normal trigger. If the Mac was asleep or
# off, the first Dex session of the local day runs the same bounded smoke check.
# A clean report suppresses later session starts; broken, inconclusive, or
# interrupted checks remain eligible for retry. The Python runner owns the
# process-safe lock so overlapping sessions cannot launch duplicate checks.
if [[ -f "$ONBOARDING_MARKER" && -f "$CLAUDE_DIR/core/utils/session_health.py" ]]; then
    HEALTH_PYTHON="python3"
    if [[ -f "$CLAUDE_DIR/.venv/bin/python" ]]; then
        HEALTH_PYTHON="$CLAUDE_DIR/.venv/bin/python"
    fi
    "$HEALTH_PYTHON" "$CLAUDE_DIR/core/utils/session_health.py" \
        --vault "$CLAUDE_DIR" \
        --repo "$CLAUDE_DIR" >/dev/null 2>&1
    DAILY_HEALTH_STATUS=$?
    if [[ "$DAILY_HEALTH_STATUS" -ne 0 \
        && "$DAILY_HEALTH_STATUS" -ne 1 \
        && "$DAILY_HEALTH_STATUS" -ne 3 ]]; then
        echo "⚠️ Dex's daily self-check could not finish — it will try again next session."
        echo ""
    elif [[ "$DAILY_HEALTH_STATUS" -eq 3 ]]; then
        echo "⚠️ Dex's daily self-check was inconclusive — it will try again next session."
        echo ""
    fi
fi

# 20. Latest smoke result — surface only actionable broken journeys.
SMOKE_LAST_RUN="$CLAUDE_DIR/System/.smoke-last-run.json"
if [[ -f "$ONBOARDING_MARKER" && -f "$SMOKE_LAST_RUN" ]]; then
    SMOKE_ALERT=$(python3 -c "
import json
try:
    with open('$SMOKE_LAST_RUN') as handle:
        report = json.load(handle)
    if report.get('summary', {}).get('broken', 0) > 0:
        print('--- 🚨 Overnight check found a problem ---')
        for journey in report.get('journeys', []):
            if journey.get('verdict') == 'BROKEN':
                detail = ' '.join(str(journey.get('detail', 'Unknown problem')).split())[:140]
                print(f\"{journey.get('id', '?')} — {detail}\")
        print('Run /dex-doctor for diagnosis and the fix.')
except Exception:
    pass
" 2>/dev/null)
    if [[ -n "$SMOKE_ALERT" ]]; then
        echo "$SMOKE_ALERT"
        echo ""
    fi
fi

# 21. Unprocessed synced meetings — detect only; processing happens via /process-meetings.
if [[ -f "$ONBOARDING_MARKER" ]]; then
    MEETING_QUEUE_OUTPUT=$(node "$CLAUDE_DIR/.claude/hooks/meeting-queue-check.cjs" "$CLAUDE_DIR" 2>/dev/null || true)
    if [[ -n "$MEETING_QUEUE_OUTPUT" ]]; then
        echo "$MEETING_QUEUE_OUTPUT"
        echo ""
    fi
fi

# Background job staleness — keep in sync with the health promise register
# (core/health/promises.py), which Doctor and Proactive Health audit.
{
    DEX_LAUNCH_AGENTS_DIR="${DEX_LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
    AUTOMATION_OWNER_PYTHON="python3"
    if [[ -f "$CLAUDE_DIR/.venv/bin/python" ]]; then
        AUTOMATION_OWNER_PYTHON="$CLAUDE_DIR/.venv/bin/python"
    fi
    while IFS='|' read -r JOB_NAME JOB_LOG_RELATIVE_PATH JOB_MAX_AGE_SECONDS JOB_EXPECTED_CADENCE JOB_LABEL JOB_MODE; do
        [[ -f "$DEX_LAUNCH_AGENTS_DIR/$JOB_NAME.plist" ]] || continue
        if [[ -f "$CLAUDE_DIR/core/utils/launch_agents.py" ]] && (
            cd "$CLAUDE_DIR" && "$AUTOMATION_OWNER_PYTHON" -m core.utils.launch_agents \
                --offloaded-check --vault "$CLAUDE_DIR" \
                --plist-relative "Library/LaunchAgents/$JOB_NAME.plist"
        ) >/dev/null 2>&1; then
            continue
        fi

        JOB_LOG="$CLAUDE_DIR/$JOB_LOG_RELATIVE_PATH"
        if [[ ! -f "$JOB_LOG" ]]; then
            echo "⏰ $JOB_LABEL is installed but has never run — run /dex-doctor to investigate."
            continue
        fi

        if [[ "$JOB_MODE" == json:* ]]; then
            # A completed run is the only writer of the receipt key; the log
            # keeps updating even when every run fails, so log age proves nothing.
            JOB_KEY="${JOB_MODE#json:}"
            JOB_TS=$(sed -n 's/.*"'"$JOB_KEY"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$JOB_LOG" | head -1)
            if [[ -z "$JOB_TS" ]]; then
                echo "⏰ $JOB_LABEL is installed but has never completed a successful run — run /dex-doctor to investigate."
                continue
            fi
            # BSD date needs bare seconds (strip fraction, Z, and ±HH:MM);
            # GNU date parses the raw stamp, offsets included.
            JOB_TS_SECONDS="${JOB_TS%%.*}"; JOB_TS_SECONDS="${JOB_TS_SECONDS%Z}"; JOB_TS_SECONDS="${JOB_TS_SECONDS%[+-]??:??}"
            JOB_MTIME=$(date -u -j -f "%Y-%m-%dT%H:%M:%S" "$JOB_TS_SECONDS" +%s 2>/dev/null || date -u -d "$JOB_TS" +%s 2>/dev/null || true)
        else
            JOB_MTIME=$(stat -f %m "$JOB_LOG" 2>/dev/null || true)
            if [[ ! "$JOB_MTIME" =~ ^[0-9]+$ ]]; then
                JOB_MTIME=$(stat -c %Y "$JOB_LOG" 2>/dev/null || true)
            fi
        fi
        [[ "$JOB_MTIME" =~ ^[0-9]+$ && "$NOW" =~ ^[0-9]+$ ]] || continue

        JOB_AGE_SECONDS=$(( NOW - JOB_MTIME ))
        if (( JOB_AGE_SECONDS > JOB_MAX_AGE_SECONDS )); then
            if (( JOB_AGE_SECONDS < 86400 )); then
                JOB_AGE=$(( JOB_AGE_SECONDS / 3600 ))
                JOB_AGE_UNIT="hours"
            else
                JOB_AGE=$(( JOB_AGE_SECONDS / 86400 ))
                JOB_AGE_UNIT="days"
            fi
            if (( JOB_AGE == 1 )); then
                JOB_AGE_UNIT="${JOB_AGE_UNIT%s}"
            fi
            JOB_VERB="last ran"
            [[ "$JOB_MODE" == json:* || "$JOB_MODE" == "mtime-success" ]] && JOB_VERB="last completed successfully"
            echo "⏰ $JOB_LABEL $JOB_VERB $JOB_AGE $JOB_AGE_UNIT ago (expected every $JOB_EXPECTED_CADENCE) — run /dex-doctor to investigate."
        fi
    done <<'EOF'
com.dex.smoke-nightly|.scripts/logs/smoke-nightly.log|93600|26 hours|Nightly smoke|mtime-success
com.dex.meeting-intel|.scripts/meeting-intel/processed-meetings.json|172800|2 days|Meeting sync|json:lastSync
com.dex.changelog-checker|.scripts/logs/changelog-checker.log|604800|7 days|Claude update watcher|mtime
com.dex.learning-review|.scripts/logs/learning-review.log|604800|7 days|Learning review|mtime
EOF
} || true

# 22. Proactive health status — read the latest complete snapshot only.
# No snapshot is the quiet preparing state. Warnings, staleness, recoveries,
# and repeated critical states do not interrupt the session; only a newly
# critical latest snapshot receives the attention block.
if [[ -f "$CLAUDE_DIR/core/utils/health_session.py" ]]; then
    HEALTH_PYTHON="python3"
    if [[ -f "$CLAUDE_DIR/.venv/bin/python" ]]; then
        HEALTH_PYTHON="$CLAUDE_DIR/.venv/bin/python"
    fi
    (
        cd "$CLAUDE_DIR" || exit 0
        "$HEALTH_PYTHON" -m core.utils.health_session --vault "$CLAUDE_DIR"
    ) 2>/dev/null || true
fi

echo "=== End Session Context ==="
