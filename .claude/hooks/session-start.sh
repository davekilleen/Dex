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
PILLARS_FILE="$CLAUDE_DIR/System/pillars.yaml"
QUARTER_GOALS="$CLAUDE_DIR/01-Quarter_Goals/Quarter_Goals.md"
WEEK_PRIORITIES="$CLAUDE_DIR/02-Week_Priorities/Week_Priorities.md"
TASKS_FILE="$CLAUDE_DIR/03-Tasks/Tasks.md"
LEARNINGS_DIR="$CLAUDE_DIR/06-Resources/Learnings"
MISTAKES_FILE="$LEARNINGS_DIR/Mistake_Patterns.md"
PREFERENCES_FILE="$LEARNINGS_DIR/Working_Preferences.md"
ONBOARDING_MARKER="$CLAUDE_DIR/System/.onboarding-complete"

echo "=== Dex Session Context ==="
echo ""
echo "📅 Today: $(date '+%A, %B %d, %Y')"
echo ""

# Detect launch agents that still point to this vault's former location.
# Doctor owns the repair; session start remains read-only for these machine files.
VAULT_BREADCRUMB="$HOME/.config/dex/vault-path"
if [[ -f "$ONBOARDING_MARKER" ]]; then
    STORED_VAULT=""
    if [[ -f "$VAULT_BREADCRUMB" ]]; then
        STORED_VAULT=$(tr -d '[:space:]' < "$VAULT_BREADCRUMB")
    fi
    if [[ "$STORED_VAULT" != "$CLAUDE_DIR" ]]; then
        if [[ -n "$STORED_VAULT" ]]; then
            PLIST_PATH_CONFLICT="false"
            for plist in "$HOME/Library/LaunchAgents"/com.dex.*.plist "$HOME/Library/LaunchAgents"/com.claudesidian.*.plist; do
                [[ -f "$plist" ]] || continue
                if grep -Fq -- "$STORED_VAULT" "$plist" 2>/dev/null; then
                    PLIST_PATH_CONFLICT="true"
                    break
                fi
            done
            if [[ "$PLIST_PATH_CONFLICT" == "true" ]]; then
                echo "Dex found a background job that still points to this vault's old location — run /dex-doctor to fix this safely."
            fi
        fi
    fi
fi

# Skip background checks during onboarding - nothing to check yet!
if [[ ! -f "$ONBOARDING_MARKER" ]]; then
    echo "⏩ Onboarding in progress - background checks disabled"
    echo ""
fi

# SELF-LEARNING: Run background checks inline (fallback if Launch Agents not installed)
# These are fast checks with interval throttling - only run when needed
if [[ -f "$ONBOARDING_MARKER" ]]; then

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

# STRATEGIC HIERARCHY (Top-Down)

# 1. Strategic Pillars
if [[ -f "$PILLARS_FILE" ]]; then
    echo "--- Strategic Pillars ---"
    # Extract pillar names and descriptions
    awk '/^  - id:/{getline; name=$0; getline; desc=$0; gsub(/^[[:space:]]*name: "/, "", name); gsub(/"$/, "", name); gsub(/^[[:space:]]*description: "/, "", desc); gsub(/"$/, "", desc); print "• " name " — " desc}' "$PILLARS_FILE" 2>/dev/null | head -5
    echo "---"
    echo ""
fi

# 2. Quarterly Goals
if [[ -f "$QUARTER_GOALS" ]]; then
    # Check if goals are filled in (not template)
    if ! grep -q "^\[Goal 1 Title\]" "$QUARTER_GOALS" 2>/dev/null; then
        echo "--- Quarter Goals ---"
        # Extract goal titles and progress
        awk '/^### [0-9]\./,/^---$/{if(/^### [0-9]\./) print; if(/^\*\*Progress:\*\*/) print}' "$QUARTER_GOALS" 2>/dev/null | head -10
        echo "---"
        echo ""
    fi
fi

# 3. Weekly Priorities
if [[ -f "$WEEK_PRIORITIES" ]]; then
    # Extract current week's priorities section
    WEEK_PRIORITIES_CONTENT=$(awk '/^## 🎯 This Week|^## This Week/,/^---$/{if(!/^##/ && !/^---/ && NF) print}' "$WEEK_PRIORITIES" 2>/dev/null)
    if [[ -n "$WEEK_PRIORITIES_CONTENT" ]]; then
        echo "--- Weekly Priorities ---"
        echo "$WEEK_PRIORITIES_CONTENT"
        echo "---"
        echo ""
    fi
fi

# TACTICAL CONTEXT

# 4. Urgent Tasks
if [[ -f "$TASKS_FILE" ]]; then
    URGENT=$(grep -i "P0\|urgent\|today\|overdue" "$TASKS_FILE" 2>/dev/null | grep "^\- \[ \]" | head -3)
    if [[ -n "$URGENT" ]]; then
        echo "--- Urgent Tasks ---"
        echo "$URGENT"
        echo "---"
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

# Background job staleness — keep in sync with core/utils/doctor.py's JOB_FRESHNESS table.
{
    DEX_LAUNCH_AGENTS_DIR="${DEX_LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
    while IFS='|' read -r JOB_NAME JOB_LOG_RELATIVE_PATH JOB_MAX_AGE_SECONDS JOB_EXPECTED_CADENCE JOB_LABEL; do
        [[ -f "$DEX_LAUNCH_AGENTS_DIR/$JOB_NAME.plist" ]] || continue

        JOB_LOG="$CLAUDE_DIR/$JOB_LOG_RELATIVE_PATH"
        if [[ ! -f "$JOB_LOG" ]]; then
            echo "⏰ $JOB_LABEL is installed but has never run — run /dex-doctor to investigate."
            continue
        fi

        JOB_MTIME=$(stat -f %m "$JOB_LOG" 2>/dev/null || true)
        if [[ ! "$JOB_MTIME" =~ ^[0-9]+$ ]]; then
            JOB_MTIME=$(stat -c %Y "$JOB_LOG" 2>/dev/null || true)
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
            echo "⏰ $JOB_LABEL last ran $JOB_AGE $JOB_AGE_UNIT ago (expected every $JOB_EXPECTED_CADENCE) — run /dex-doctor to investigate."
        fi
    done <<'EOF'
com.dex.smoke-nightly|.scripts/logs/smoke-nightly.log|93600|26 hours|Nightly smoke
com.dex.meeting-intel|.scripts/logs/meeting-intel.log|172800|2 days|Meeting sync
com.dex.changelog-checker|.scripts/logs/changelog-checker.log|604800|7 days|Claude update watcher
com.dex.learning-review|.scripts/logs/learning-review.log|604800|7 days|Learning review
EOF
} || true

echo "=== End Session Context ==="
