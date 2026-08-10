#!/bin/bash
# Mid-session health pulse — runs on every user message, so bad health news
# does not wait for the next fresh session (the v1.84.0 field incident hid a
# dead background sync for six days inside one long-lived session).
#
# Hard rules:
#   - Never compute health. Read the answer Proactive Health already wrote:
#     the latest-snapshot pointer and that snapshot's overall status. Two
#     small local file reads, nothing else.
#   - Interject at most once per day for staleness and once per snapshot for
#     a critical status; otherwise print nothing (no output = zero cost).
#   - Any failure is silent. exit 0 always.

{
    CLAUDE_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
    HEALTH_DIR="$CLAUDE_DIR/System/.dex/health"
    POINTER="$HEALTH_DIR/latest.json"
    DEDUP_FILE="${DEX_HEALTH_PULSE_DEDUP_FILE:-$CLAUDE_DIR/System/.dex/health-pulse-dedup}"
    STALE_AFTER_SECONDS=93600  # 26 h: one nightly refresh plus sleep slack

    # Quiet before onboarding and before the first complete snapshot.
    [[ -f "$CLAUDE_DIR/System/.onboarding-complete" ]] || exit 0
    [[ -f "$POINTER" ]] || exit 0

    PUBLISHED_AT=$(sed -n 's/.*"published_at"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$POINTER" | head -1)
    SNAPSHOT_ID=$(sed -n 's/.*"snapshot_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$POINTER" | head -1)
    [[ -n "$PUBLISHED_AT" && -n "$SNAPSHOT_ID" ]] || exit 0

    NOW=$(date +%s)
    TS="${PUBLISHED_AT%%.*}"; TS="${TS%Z}"; TS="${TS%%+*}"
    PUBLISHED_EPOCH=$(date -u -j -f "%Y-%m-%dT%H:%M:%S" "$TS" +%s 2>/dev/null \
        || date -u -d "$PUBLISHED_AT" +%s 2>/dev/null || true)
    [[ "$PUBLISHED_EPOCH" =~ ^[0-9]+$ && "$NOW" =~ ^[0-9]+$ ]] || exit 0

    TODAY=$(date -u +%Y-%m-%d)
    AGE=$(( NOW - PUBLISHED_EPOCH ))

    if (( AGE > STALE_AFTER_SECONDS )); then
        if ! grep -qF "stale:$TODAY" "$DEDUP_FILE" 2>/dev/null; then
            AGE_DAYS=$(( AGE / 86400 ))
            if (( AGE_DAYS >= 1 )); then
                AGE_TEXT="$AGE_DAYS day(s)"
            else
                AGE_TEXT="$(( AGE / 3600 )) hours"
            fi
            mkdir -p "$(dirname "$DEDUP_FILE")" 2>/dev/null
            echo "stale:$TODAY" >> "$DEDUP_FILE" 2>/dev/null
            echo "🩺 Dex's health checks haven't completed in $AGE_TEXT — the background checkup may not be running. Run /dex-doctor when convenient."
        fi
        exit 0
    fi

    SNAPSHOT="$HEALTH_DIR/snapshots/$SNAPSHOT_ID.json"
    [[ -f "$SNAPSHOT" ]] || exit 0
    STATUS=$(sed -n 's/.*"overall_status"[[:space:]]*:[[:space:]]*"\([a-z_-]*\)".*/\1/p' "$SNAPSHOT" | head -1)
    if [[ "$STATUS" == "critical" ]]; then
        if ! grep -qF "critical:$SNAPSHOT_ID" "$DEDUP_FILE" 2>/dev/null; then
            mkdir -p "$(dirname "$DEDUP_FILE")" 2>/dev/null
            echo "critical:$SNAPSHOT_ID" >> "$DEDUP_FILE" 2>/dev/null
            echo "🩺 Dex's latest self-check found a problem — run /dex-doctor for the details and the fix."
        fi
    fi
    exit 0
} 2>/dev/null || exit 0
