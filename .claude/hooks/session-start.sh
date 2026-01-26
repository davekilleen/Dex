#!/bin/bash
# Claude Code SessionStart Hook
# Injects compound learnings, mistake patterns, preferences, and context
# For Dex personal knowledge system

CLAUDE_DIR="$CLAUDE_PROJECT_DIR"
LEARNINGS_DIR="$CLAUDE_DIR/Resources/Learnings"
MISTAKES_FILE="$LEARNINGS_DIR/Mistake_Patterns.md"
PREFERENCES_FILE="$LEARNINGS_DIR/Working_Preferences.md"
TASKS_FILE="$CLAUDE_DIR/Tasks.md"
WEEK_PRIORITIES="$CLAUDE_DIR/Inbox/Week Priorities.md"

echo "=== Dex Session Context ==="
echo ""

# 1. Inject active mistake patterns
if [[ -f "$MISTAKES_FILE" ]]; then
    PATTERN_COUNT=$(grep -c "^### " "$MISTAKES_FILE" 2>/dev/null || echo "0")
    if [[ "$PATTERN_COUNT" -gt 0 ]]; then
        echo "--- Active Mistake Patterns ($PATTERN_COUNT) ---"
        awk '/^## Active Patterns/,/^## Resolved/' "$MISTAKES_FILE" | grep -A3 "^### " | head -20
        echo "---"
        echo ""
    fi
fi

# 2. Inject working preferences
if [[ -f "$PREFERENCES_FILE" ]]; then
    # Count actual preferences (headers with content, not section headers)
    PREF_COUNT=$(grep -c "^### " "$PREFERENCES_FILE" 2>/dev/null || echo "0")
    if [[ "$PREF_COUNT" -gt 0 ]]; then
        echo "--- Working Preferences ---"
        grep -A2 "^### " "$PREFERENCES_FILE" | head -15
        echo "---"
        echo ""
    fi
fi

# 3. Inject recent learnings from any learning files
if [[ -d "$LEARNINGS_DIR" ]]; then
    FOUND_LEARNINGS=0
    for file in "$LEARNINGS_DIR"/*.md; do
        if [[ -f "$file" ]]; then
            filename=$(basename "$file" .md)
            recent=$(grep -E "## .* — 202[0-9]-[0-9]{2}-[0-9]{2}" "$file" 2>/dev/null | tail -3)
            if [[ -n "$recent" ]]; then
                if [[ $FOUND_LEARNINGS -eq 0 ]]; then
                    echo "--- Recent Learnings ---"
                    FOUND_LEARNINGS=1
                fi
                echo "[$filename]"
                echo "$recent"
            fi
        fi
    done
    if [[ $FOUND_LEARNINGS -eq 1 ]]; then
        echo "---"
        echo ""
    fi
fi

# 4. Surface overdue/urgent items from Tasks.md
if [[ -f "$TASKS_FILE" ]]; then
    URGENT=$(grep -i "P0\|urgent\|today\|overdue" "$TASKS_FILE" 2>/dev/null | grep "^\- \[ \]" | head -3)
    if [[ -n "$URGENT" ]]; then
        echo "--- Urgent Items ---"
        echo "$URGENT"
        echo "---"
        echo ""
    fi
fi

# 5. Show current week's focus
if [[ -f "$WEEK_PRIORITIES" ]]; then
    PRIORITIES=$(grep "^\- \[ \]" "$WEEK_PRIORITIES" 2>/dev/null | head -5)
    if [[ -n "$PRIORITIES" ]]; then
        echo "--- This Week's Focus ---"
        echo "$PRIORITIES"
        echo "---"
        echo ""
    fi
fi

echo "=== End Session Context ==="
