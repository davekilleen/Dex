#!/bin/bash
# Capture corrections when they happen, not at the end of the day.
#
# The most reusable signal about how an assistant fails is the moment its user
# tells it so. Today that signal reaches nothing: extraction happens in
# /daily-review, which is manual, end-of-day, and competes with everything else.
# On the vault this was written for, a day containing nine distinct corrections
# ended with an empty learning file, because the review never ran.
#
# What this records is the USER'S OWN WORDS, verbatim. Not the assistant's
# summary of its own failure, which is a worse source: an assistant that
# misunderstood the correction will summarise it wrongly, and the summary is
# what survives.
#
# Two-stage, matching the idiom in claude-composition-refresh.sh:
#
#   - The everyday path is one grep against stdin. No interpreter start, no
#     JSON parse, nothing to notice. Almost every prompt exits here.
#   - Python starts only when the prompt looks like a correction, which is rare
#     even on a bad day.
#
# Accuracy, measured against nine real corrections and eight ordinary prompts
# from a single session: eight of nine corrections caught, one false positive
# ("I have no preference, pick one"). The miss is "what day do you think it
# is?" -- Socratic corrections do not look like corrections. Good on blunt,
# blind on oblique. A false positive costs one line in a file and a real miss
# costs the signal, so the patterns lean inclusive on purpose.
#
# Any failure is silent. exit 0 always: a vault that cannot record a correction
# is no worse off than before this existed, and a prompt must never be blocked
# by note-taking.

{
    CLAUDE_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
    [ -d "$CLAUDE_DIR/System" ] || exit 0

    PAYLOAD=""
    [ -t 0 ] || PAYLOAD="$(cat 2>/dev/null || true)"
    [ -n "$PAYLOAD" ] || exit 0

    # Cheap gate. Matched against the RAW JSON payload, not a parsed prompt:
    # this only decides whether starting Python is worth it. Note the word
    # boundaries are [^[:alnum:]] rather than whitespace, because in JSON a
    # leading word is preceded by a quote -- {"prompt":"STOP"} has no space
    # before STOP, and a whitespace-anchored pattern silently never fires.
    printf '%s' "$PAYLOAD" | grep -qiE \
        "(^|[^[:alnum:]])(no|nope|stop|wrong|incorrect)([^[:alnum:]]|\$)|don'?t |you did ?n'?t|you'?re not|that'?s not|thats not|not what|why (did|are|didn'?t) you|again[,.]|i (told|said) you|keep (doing|writing|failing)|stupid|come on|actually," \
        || exit 0

    PY="$CLAUDE_DIR/.claude/hooks/correction-capture.py"
    [ -f "$PY" ] || exit 0
    printf '%s' "$PAYLOAD" | python3 "$PY" >/dev/null 2>&1 || true
    exit 0
} 2>/dev/null || exit 0
