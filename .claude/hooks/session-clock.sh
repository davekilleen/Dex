#!/bin/bash
# Re-state the current time on every prompt.
#
# A session's context carries no freshness. Everything in it presents with equal
# authority whether it was observed a minute ago or yesterday, so a date read
# once at session start sits there unchanged and unqualified for as long as the
# session lasts. In a short session that is harmless. In a long one it is the
# cause of a specific failure: a stale clock is used confidently because it is
# right there and looks current.
#
# Observed on a real vault: SessionStart printed Tuesday's date, the session ran
# overnight, and on Wednesday morning a full daily plan was built, presented and
# defended as "today's" using Tuesday. Nothing in context contradicted it.
#
# Two deliberate choices:
#
#   - **Unconditional.** It would be cheaper to emit only when something changed,
#     but every conditional hook in this tree is a place where a branch can
#     quietly not fire, and this file exists because of exactly that class of
#     bug. One `date` call per prompt is not worth the risk of being clever.
#
#   - **The day-change line is the point.** Crossing midnight mid-session is when
#     context becomes actively wrong rather than merely old, so that transition
#     is called out once rather than left for the reader to notice.
#
# Any failure is silent and exits 0. A vault that cannot read a clock is no worse
# off than before this hook existed.

{
    CLAUDE_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
    STATE_DIR="$CLAUDE_DIR/System/.dex"
    STATE_FILE="${DEX_SESSION_CLOCK_STATE:-$STATE_DIR/session-clock-day}"

    NOW="$(date '+%Y-%m-%d %H:%M %Z (%A)')" || exit 0
    TODAY="$(date '+%Y-%m-%d')" || exit 0

    printf '🕐 %s\n' "$NOW"

    # Only meaningful once the vault exists; a missing state dir is not a fault.
    if [ -d "$STATE_DIR" ]; then
        LAST=""
        [ -f "$STATE_FILE" ] && LAST="$(tr -d '[:space:]' < "$STATE_FILE" 2>/dev/null)"
        if [ -n "$LAST" ] && [ "$LAST" != "$TODAY" ]; then
            printf 'The date has changed since this session last checked (was %s). Anything computed from the earlier date is stale.\n' "$LAST"
        fi
        printf '%s\n' "$TODAY" > "$STATE_FILE" 2>/dev/null || true
    fi
    exit 0
} 2>/dev/null || exit 0
