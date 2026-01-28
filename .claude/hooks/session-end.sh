#!/bin/bash
# Claude Code SessionEnd Hook
# Automatically extracts learnings from session transcript
# For Dex personal knowledge system

CLAUDE_DIR="$CLAUDE_PROJECT_DIR"
SESSION_LEARNINGS_DIR="$CLAUDE_DIR/Inbox/Session_Learnings"
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

# Extract learnings from transcript using Claude
# This requires the transcript path to be available
if [[ -n "$TRANSCRIPT_PATH" ]] && [[ -f "$TRANSCRIPT_PATH" ]]; then
    echo "## $(date +%H:%M) - Session completed" >> "$LEARNING_FILE"
    echo "" >> "$LEARNING_FILE"
    echo "**Session ended**" >> "$LEARNING_FILE"
    echo "**Transcript:** \`$TRANSCRIPT_PATH\`" >> "$LEARNING_FILE"
    echo "" >> "$LEARNING_FILE"
    echo "_Note: Review transcript for learnings to extract manually._" >> "$LEARNING_FILE"
    echo "" >> "$LEARNING_FILE"
    echo "---" >> "$LEARNING_FILE"
    echo "" >> "$LEARNING_FILE"
fi

exit 0
