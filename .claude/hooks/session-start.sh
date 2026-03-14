#!/bin/bash
# Claude Code SessionStart Hook
# Injects strategic hierarchy and tactical context
# For Dex personal knowledge system

# Prevent duplicate injection (symlinked working directories)
DEDUP_FILE="/tmp/dex-session-context-dedup"
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

# Demo Mode Check
DEMO_STATE="$CLAUDE_DIR/System/.demo-mode-state.json"
if [[ -f "$DEMO_STATE" ]]; then
    DEMO_ACTIVE=$(python3 -c "import json; d=json.load(open('$DEMO_STATE')); print(d.get('active', False))" 2>/dev/null)
    if [[ "$DEMO_ACTIVE" == "True" ]]; then
        TERM_COUNT=$(python3 -c "
import sys; sys.path.insert(0, '$CLAUDE_DIR')
from importlib import import_module
m = import_module('dex-core.core.mcp.demo_mode_server')
import os; os.environ['VAULT_PATH'] = '$CLAUDE_DIR'
state = m.load_state()
print(len(m.get_all_terms(state)))
" 2>/dev/null || echo "?")
        echo "🔒 DEMO MODE ACTIVE — $TERM_COUNT terms redacted"
        echo "   Call get_demo_status() from demo-mode MCP at session start."
        echo "   ALL output (files, chat, MCP params) must be redacted via redact_text()."
        echo "   PTY wrapper is the safety net. You are the primary filter."
        echo ""
    fi
fi

# Silent self-healing: ensure vault-path breadcrumb and launch agents stay in sync
VAULT_BREADCRUMB="$HOME/.config/dex/vault-path"
if [[ -f "$ONBOARDING_MARKER" ]]; then
    STORED_VAULT=""
    if [[ -f "$VAULT_BREADCRUMB" ]]; then
        STORED_VAULT=$(tr -d '[:space:]' < "$VAULT_BREADCRUMB")
    fi
    if [[ "$STORED_VAULT" != "$CLAUDE_DIR" ]]; then
        # Vault has moved — update breadcrumb and fix all launch agents
        mkdir -p "$HOME/.config/dex"
        echo "$CLAUDE_DIR" > "$VAULT_BREADCRUMB"
        if [[ -n "$STORED_VAULT" ]]; then
            for plist in "$HOME/Library/LaunchAgents"/com.dex.*.plist "$HOME/Library/LaunchAgents"/com.claudesidian.*.plist; do
                [[ -f "$plist" ]] || continue
                if grep -q "$STORED_VAULT" "$plist" 2>/dev/null; then
                    AGENT_NAME=$(basename "$plist" .plist)
                    launchctl unload "$plist" 2>/dev/null || true
                    sed -i '' "s|$STORED_VAULT|$CLAUDE_DIR|g" "$plist"
                    launchctl load "$plist" 2>/dev/null || true
                fi
            done
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

# 12. Innovation Engine - Run daily scan (once per day) and check for discoveries
INNOVATION_STATE="$CLAUDE_DIR/System/Innovation_Research/.state.json"
INNOVATION_SCAN="$CLAUDE_DIR/System/Innovation_Research/daily-research-scan.cjs"
INNOVATION_CHECKER="$CLAUDE_DIR/.claude/hooks/innovation-engine-checker.cjs"
if [[ -f "$INNOVATION_SCAN" && -f "$ONBOARDING_MARKER" ]]; then
    TODAY=$(date +%Y-%m-%d)
    LAST_SCAN_DATE=""
    if [[ -f "$INNOVATION_STATE" ]]; then
        LAST_SCAN_DATE=$(python3 -c "
import json
try:
    with open('$INNOVATION_STATE') as f:
        s = json.load(f)
    ts = s.get('last_scan_completed', '')
    print(ts[:10] if ts else '')
except:
    print('')
" 2>/dev/null)
    fi

    if [[ "$LAST_SCAN_DATE" != "$TODAY" && -n "$GITHUB_TOKEN" ]]; then
        # Run silently — no need to inject into context
        node "$INNOVATION_SCAN" > "$CLAUDE_DIR/System/Innovation_Research/logs/pipeline-stdout.log" 2> "$CLAUDE_DIR/System/Innovation_Research/logs/pipeline-stderr.log" &
    elif [[ -z "$GITHUB_TOKEN" ]]; then
        : # Silent — no token, no scan
    fi

    # Check for discoveries from previous scans
    if [[ -f "$INNOVATION_CHECKER" ]]; then
        node "$INNOVATION_CHECKER" 2>/dev/null
    fi
fi

# 14. Intel Pipeline Refresh (YouTube, Newsletter, Twitter)
# Checks if today's digests exist. If not, fires pipelines in background.
# Also resumes any pipelines that started but didn't complete.
INTEL_REFRESH="$CLAUDE_DIR/.claude/hooks/intel-pipeline-refresh.cjs"
if [[ -f "$INTEL_REFRESH" && -f "$ONBOARDING_MARKER" ]]; then
    INTEL_OUTPUT=$(node "$INTEL_REFRESH" 2>/dev/null)
    if [[ -n "$INTEL_OUTPUT" ]]; then
        echo "--- 📡 Intel Pipeline Status ---"
        echo "$INTEL_OUTPUT"
        echo "---"
        echo ""
    fi
fi

# 15. Product Context — strategy one-liner only (insights load on-demand)
PRODUCT_CONTEXT="$CLAUDE_DIR/System/product-context.md"
if [[ -f "$PRODUCT_CONTEXT" && -f "$ONBOARDING_MARKER" ]]; then
    STRATEGY=$(grep -F "**The One-Sentence Strategy:**" "$PRODUCT_CONTEXT" 2>/dev/null | head -1 | sed 's/.*Strategy:\*\* //')
    if [[ -n "$STRATEGY" ]]; then
        echo "--- 🎯 Product Strategy ---"
        echo "$STRATEGY"
        echo "Details: System/product-context.md"
        echo "---"
        echo ""
    fi
fi

# 15. Top Backlog Ideas — removed from startup (available via /dex-improve)

# 16. Hot Research Repos — removed from startup (available via /repo-radar)

# 17. Pendo Partnership — removed from startup (loaded contextually when relevant)

# 19. Critical Decisions Memory (cross-session awareness)
CRITICAL_DECISIONS="$CLAUDE_DIR/System/Memory/critical-decisions.md"
if [[ -f "$CRITICAL_DECISIONS" && -f "$ONBOARDING_MARKER" ]]; then
    # Count recent decisions (last 7 days)
    WEEK_AGO=$(date -v-7d +%Y-%m-%d 2>/dev/null || date -d "7 days ago" +%Y-%m-%d 2>/dev/null)
    if [[ -n "$WEEK_AGO" ]]; then
        RECENT_DECISIONS=$(awk -v cutoff="$WEEK_AGO" '/^### [0-9]{4}-[0-9]{2}-[0-9]{2}/{date=substr($2,1,10); if(date>=cutoff) show=1; else show=0} show && !/^---$/' "$CRITICAL_DECISIONS" 2>/dev/null | head -10)
        if [[ -n "$RECENT_DECISIONS" ]]; then
            echo "--- 🧠 Recent Critical Decisions ---"
            echo "$RECENT_DECISIONS"
            echo "---"
            echo ""
        fi
    fi
fi

# 20. Session Memory Context (cross-session awareness)
SESSION_MEMORY_PRIMER="$CLAUDE_DIR/.claude/hooks/session-memory-primer.cjs"
if [[ -f "$SESSION_MEMORY_PRIMER" && -f "$ONBOARDING_MARKER" ]]; then
    SESSION_MEMORY_OUTPUT=$(node "$SESSION_MEMORY_PRIMER" 2>/dev/null)
    if [[ -n "$SESSION_MEMORY_OUTPUT" ]]; then
        echo "$SESSION_MEMORY_OUTPUT"
        echo ""
    fi
fi

# 21. Slack Token Health Check (once per day)
SLACK_CHECKER="$CLAUDE_DIR/.claude/hooks/slack-token-checker.cjs"
if [[ -f "$SLACK_CHECKER" && -f "$ONBOARDING_MARKER" ]]; then
    SLACK_CHECK_OUTPUT=$(node "$SLACK_CHECKER" 2>/dev/null)
    if [[ -n "$SLACK_CHECK_OUTPUT" ]]; then
        echo "$SLACK_CHECK_OUTPUT"
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
    DEX_CORE_DIR="$CLAUDE_DIR/dex-core"
    if [[ -f "$DEX_CORE_DIR/core/utils/preflight.py" ]]; then
        HEALTH_OUTPUT=$(cd "$DEX_CORE_DIR" && python3 -c "
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
" 2>/dev/null)
        if [[ -n "$HEALTH_OUTPUT" ]]; then
            echo "$HEALTH_OUTPUT"
        fi
    fi
fi

echo "=== End Session Context ==="
