#!/bin/bash
# Claude Code SessionEnd Hook
# Logs session end timestamp for tracking
# For Dex personal knowledge system
#
# ⚠️ IMPORTANT: This only works in Claude Code desktop/CLI
# - Requires graceful shutdown (via `exit` command or proper quit)
# - Does NOT work in Cursor (closing window terminates process immediately)
# - For Cursor: Use /daily-review command manually before closing
#
# NOTE: This hook only logs timestamps. Actual learning extraction happens
# via /daily-review command, which intelligently scans for patterns and improvements.

CLAUDE_DIR="$CLAUDE_PROJECT_DIR"
SESSION_LEARNINGS_DIR="$CLAUDE_DIR/System/Session_Learnings"
TRANSCRIPT_PATH="$1"  # Passed as argument by Claude Code

# Ensure session learnings directory exists
mkdir -p "$SESSION_LEARNINGS_DIR"

# Get today's date for the learning file
TODAY=$(date +%Y-%m-%d)
LEARNING_FILE="$SESSION_LEARNINGS_DIR/$TODAY.md"

# Create or append to today's learning file
if [[ ! -f "$LEARNING_FILE" ]]; then
    cat > "$LEARNING_FILE" <<EOF
# Session Learnings - $TODAY

Automatically captured from Claude Code sessions.

---

EOF
fi

# Log session end time with transcript reference
# Actual learning extraction happens via /daily-review command
if [[ -n "$TRANSCRIPT_PATH" ]] && [[ -f "$TRANSCRIPT_PATH" ]]; then
    echo "## $(date +%H:%M) - Session completed" >> "$LEARNING_FILE"
    echo "" >> "$LEARNING_FILE"
    echo "**Session ended**" >> "$LEARNING_FILE"
    echo "**Transcript:** \`$TRANSCRIPT_PATH\`" >> "$LEARNING_FILE"
    echo "" >> "$LEARNING_FILE"
    echo "_Note: Run /daily-review to extract learnings from this session._" >> "$LEARNING_FILE"
    echo "" >> "$LEARNING_FILE"
    echo "---" >> "$LEARNING_FILE"
    echo "" >> "$LEARNING_FILE"
fi

exit 0
