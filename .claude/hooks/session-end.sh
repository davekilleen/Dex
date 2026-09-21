#!/bin/bash
# Claude Code SessionEnd Hook
# Records that a session ended, so the day's learning file is never silently empty.
#
# ⚠️ Requires graceful shutdown (via `exit` or a proper quit). Closing a Cursor
# window terminates the process immediately and no SessionEnd hook runs at all.
#
# NOTE: this hook records the session boundary. Learning EXTRACTION happens in
# /daily-review, which scans the transcript for patterns worth keeping.
#
# Two faults this file used to have, both silent:
#
#   1. It read the transcript path from "$1", and settings.json passes
#      "$transcript_path" -- a shell variable nothing in the hook environment
#      ever sets, so it expanded to empty on every real invocation. Hooks are
#      given their payload as JSON on stdin (see soft-promise-detector.py).
#      Stdin is now the primary source, with argv kept as a fallback because
#      the test harness invokes the hook directly.
#
#   2. It gated the whole session record on having a transcript path. The
#      valuable part -- that a session ended, and when -- does not depend on
#      that optional detail. Gating the essential on the optional meant a
#      missing path produced a file containing nothing but its own header,
#      which reads as "nothing happened" rather than "this did not work".
#
# Observed before the fix: two consecutive days whose learning files contained
# only the header, while the autocommit hook faithfully committed them and every
# mechanism reported success.

CLAUDE_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
SESSION_LEARNINGS_DIR="$CLAUDE_DIR/System/Session_Learnings"

# Payload arrives as JSON on stdin. Read it only when stdin is not a terminal,
# so direct invocation from a shell cannot hang waiting for input.
PAYLOAD=""
if [ ! -t 0 ]; then
    PAYLOAD="$(cat 2>/dev/null || true)"
fi

TRANSCRIPT_PATH=""
if [ -n "$PAYLOAD" ]; then
    # Deliberately not a JSON parser: bash has none, and adding an interpreter
    # start to a shutdown path to read one string is not worth it.
    if [[ "$PAYLOAD" =~ \"transcript_path\"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]]; then
        TRANSCRIPT_PATH="${BASH_REMATCH[1]}"
    fi
fi
# Fallback for direct invocation (the hook harness passes it as an argument).
[ -z "$TRANSCRIPT_PATH" ] && TRANSCRIPT_PATH="${1:-}"

mkdir -p "$SESSION_LEARNINGS_DIR" 2>/dev/null || exit 0

TODAY=$(date +%Y-%m-%d)
LEARNING_FILE="$SESSION_LEARNINGS_DIR/$TODAY.md"

if [[ ! -f "$LEARNING_FILE" ]]; then
    cat > "$LEARNING_FILE" <<HEADER
# Session Learnings - $TODAY

Automatically captured from Claude Code sessions.

---

HEADER
fi

# The session record is written unconditionally. Whether the transcript could be
# located is reported as part of it, because a learning file that cannot say
# "the transcript was not available" is indistinguishable from a quiet day.
{
    echo "## $(date +%H:%M) - Session completed"
    echo ""
    echo "**Session ended**"
    if [[ -n "$TRANSCRIPT_PATH" ]] && [[ -f "$TRANSCRIPT_PATH" ]]; then
        echo "**Transcript:** \`$TRANSCRIPT_PATH\`"
        echo ""
        echo "_Note: Run /daily-review to extract learnings from this session._"
    elif [[ -n "$TRANSCRIPT_PATH" ]]; then
        echo "**Transcript:** recorded as \`$TRANSCRIPT_PATH\`, but no file exists there."
        echo ""
        echo "_Learnings cannot be extracted automatically. If this session mattered,"
        echo "capture them by hand before the detail is gone._"
    else
        echo "**Transcript:** not supplied to this hook."
        echo ""
        echo "_Learnings cannot be extracted automatically. If this session mattered,"
        echo "capture them by hand before the detail is gone._"
    fi
    echo ""
    echo "---"
    echo ""
} >> "$LEARNING_FILE"

exit 0
