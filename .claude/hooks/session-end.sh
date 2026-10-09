#!/bin/bash
# Claude Code SessionEnd Hook
# Records that a session ended, then extracts obvious candidate lessons
# from the recorded transcript so the day's learning file is never only a marker.
#
# ⚠️ Requires graceful shutdown (via `exit` or a proper quit). Closing a Cursor
# window terminates the process immediately and no SessionEnd hook runs at all.
# Corrections said during the session were still captured as they were typed
# by correction-capture.sh.
#
# Extraction is local, bounded, and fail-open: no network, a short deadline
# inside the Python helper, and any helper failure still leaves the session
# marker. /daily-review remains the careful pass that confirms these
# candidates and catches what the heuristic missed.
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
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd 2>/dev/null || true)"

# Payload arrives as JSON on stdin. Read it only when stdin is not a terminal,
# so direct invocation from a shell cannot hang waiting for input.
PAYLOAD=""
if [ ! -t 0 ]; then
    PAYLOAD="$(cat 2>/dev/null || true)"
fi

TRANSCRIPT_PATH=""
SESSION_ID=""
if [ -n "$PAYLOAD" ]; then
    # Deliberately not a JSON parser: bash has none, and adding an interpreter
    # start to a shutdown path to read one string is not worth it.
    if [[ "$PAYLOAD" =~ \"transcript_path\"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]]; then
        TRANSCRIPT_PATH="${BASH_REMATCH[1]}"
    fi
    if [[ "$PAYLOAD" =~ \"session_id\"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]]; then
        SESSION_ID="${BASH_REMATCH[1]}"
    fi
fi
# Fallback for direct invocation (the hook harness passes it as an argument).
[ -z "$TRANSCRIPT_PATH" ] && TRANSCRIPT_PATH="${1:-}"

mkdir -p "$SESSION_LEARNINGS_DIR" 2>/dev/null || exit 0

TODAY=$(date +%Y-%m-%d)
LEARNING_FILE="$SESSION_LEARNINGS_DIR/$TODAY.md"

# Marker + extract go through one locked Python write so two session-end
# hooks finishing together cannot interleave or duplicate the same session.
# If the helper cannot run, the bash fallback below still records that a
# session ended — the valuable part — without extracting lessons.
EXTRACTOR=""
if [[ -f "$CLAUDE_DIR/core/utils/session_lesson_extract.py" ]]; then
    EXTRACTOR="$CLAUDE_DIR/core/utils/session_lesson_extract.py"
elif [[ -n "$HOOK_DIR" && -f "$HOOK_DIR/../../core/utils/session_lesson_extract.py" ]]; then
    EXTRACTOR="$HOOK_DIR/../../core/utils/session_lesson_extract.py"
fi

PYTHON_CMD=()
if [[ -n "${DEX_PYTHON:-}" && -x "${DEX_PYTHON}" ]]; then
    PYTHON_CMD=("$DEX_PYTHON")
elif [[ -x "$CLAUDE_DIR/.venv/bin/python" ]]; then
    PYTHON_CMD=("$CLAUDE_DIR/.venv/bin/python")
elif [[ -x "$CLAUDE_DIR/.venv/Scripts/python.exe" ]]; then
    PYTHON_CMD=("$CLAUDE_DIR/.venv/Scripts/python.exe")
elif command -v py >/dev/null 2>&1 && py -3 -c "raise SystemExit(0)" >/dev/null 2>&1; then
    PYTHON_CMD=(py -3)
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD=(python)
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD=(python3)
fi

if [[ -n "$EXTRACTOR" && ${#PYTHON_CMD[@]} -gt 0 ]]; then
    RECORD_ARGS=(--record-session --learning-file "$LEARNING_FILE")
    [[ -n "$TRANSCRIPT_PATH" ]] && RECORD_ARGS+=(--transcript "$TRANSCRIPT_PATH")
    [[ -n "$SESSION_ID" ]] && RECORD_ARGS+=(--session-id "$SESSION_ID")
    if "${PYTHON_CMD[@]}" "$EXTRACTOR" "${RECORD_ARGS[@]}" >/dev/null 2>&1; then
        exit 0
    fi
fi

# Fallback when Python cannot record. A mkdir lock keeps two fallbacks from
# interleaving; it does not coordinate with the Python path above.
LOCKDIR="$SESSION_LEARNINGS_DIR/.session-end.lock"
lock_held=0
if mkdir "$LOCKDIR" 2>/dev/null; then
    lock_held=1
    trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT
fi

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
    if [[ -n "$SESSION_ID" ]]; then
        echo "**Session:** \`$SESSION_ID\`"
    fi
    if [[ -n "$TRANSCRIPT_PATH" ]] && [[ -f "$TRANSCRIPT_PATH" ]]; then
        echo "**Transcript:** \`$TRANSCRIPT_PATH\`"
        echo ""
        echo "_Note: Obvious corrections and preferences from this session are captured automatically when they can be spotted, marked pending. Run /daily-review to confirm them and catch anything the automatic pass missed._"
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

if [[ "$lock_held" -eq 1 ]]; then
    rmdir "$LOCKDIR" 2>/dev/null || true
    trap - EXIT
fi

exit 0
