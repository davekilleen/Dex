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
# Accuracy: blunt corrections ("no, that's not", "stop doing that") are
# caught. Ordinary conversational words ("no", "stop", "actually,") are not.
# Socratic corrections ("what day do you think it is?") still miss.
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

    # Machine-generated text (notifications, reminders, scheduled-task preambles)
    # is NOT screened here. This grep is only a cheap pre-filter on the raw
    # payload, so most prompts exit without starting Python. The Python step
    # strips machine text first and re-tests the same wording against what is
    # left, so a correction that arrives alongside a notification is still
    # recorded, and a notification's own prose never is.

    # Cheap gate. Matched against the RAW JSON payload, not a parsed prompt:
    # this only decides whether starting Python is worth it. Note the word
    # boundaries are [^[:alnum:]] rather than whitespace, because in JSON a
    # leading word is preceded by a quote -- {"prompt":"wrong"} has no space
    # before the word, and a whitespace-anchored pattern silently never fires.
    printf '%s' "$PAYLOAD" | grep -qiE \
        "(^|[^[:alnum:]])(nope|wrong|incorrect)([^[:alnum:]]|$)|(^|[^[:alnum:]])no([[:space:]]*,|[[:space:]]*\\.\\.\\.|[[:space:]]+no[^[:alnum:]])|(^|[^[:alnum:]])stop[[:space:]]+(doing|making|writing|over|inferr|that|this)[^[:alnum:]]|don'?t |you did ?n'?t|you'?re not|that'?s not|thats not|not what|why (did|are|didn'?t) you|again[,.]|i (told|said) you|keep (doing|writing|failing)|stupid|come on" \
        || exit 0

    PY="$CLAUDE_DIR/.claude/hooks/correction-capture.py"
    [ -f "$PY" ] || exit 0
    printf '%s' "$PAYLOAD" | python3 "$PY" >/dev/null 2>&1 || true
    exit 0
} 2>/dev/null || exit 0
