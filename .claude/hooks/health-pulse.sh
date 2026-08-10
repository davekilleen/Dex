#!/bin/bash
# Mid-session health pulse — runs on every user message, so bad health news
# does not wait for the next fresh session (the v1.84.0 field incident hid a
# dead background sync for six days inside one long-lived session).
#
# Hard rules:
#   - Never compute health. Read the answer Proactive Health already wrote:
#     the latest-snapshot pointer and that snapshot's overall status. Two
#     small local file reads, parsed with bash builtins (no sed/grep forks on
#     the everyday silent path).
#   - Interject at most once per UTC day for staleness and once per snapshot
#     for a critical status — and only after the dedup marker provably
#     persisted, so an unwritable vault degrades to silence, never to a nag
#     on every message.
#   - Any failure is silent. exit 0 always.
#
# Staleness threshold matches core/utils/health_session.py's
# STALE_AFTER_SECONDS (24 h) so session start and the pulse agree on "stale".

{
    CLAUDE_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
    HEALTH_DIR="$CLAUDE_DIR/System/.dex/health"
    POINTER="$HEALTH_DIR/latest.json"
    DEDUP_FILE="${DEX_HEALTH_PULSE_DEDUP_FILE:-$CLAUDE_DIR/System/.dex/health-pulse-dedup}"
    STALE_AFTER_SECONDS=86400

    # Quiet before onboarding and before the first complete snapshot.
    [[ -f "$CLAUDE_DIR/System/.onboarding-complete" ]] || exit 0
    [[ -f "$POINTER" ]] || exit 0

    POINTER_JSON="$(<"$POINTER")"
    [[ "$POINTER_JSON" =~ \"published_at\"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]] || exit 0
    PUBLISHED_AT="${BASH_REMATCH[1]}"
    [[ "$POINTER_JSON" =~ \"snapshot_id\"[[:space:]]*:[[:space:]]*\"([^\"]+)\" ]] || exit 0
    SNAPSHOT_ID="${BASH_REMATCH[1]}"

    NOW=$(date +%s)
    # BSD date needs the bare seconds; strip fraction, Z, and ±HH:MM offsets.
    # GNU date receives the raw stamp (it parses offsets correctly itself).
    TS="${PUBLISHED_AT%%.*}"; TS="${TS%Z}"; TS="${TS%[+-]??:??}"
    PUBLISHED_EPOCH=$(date -u -j -f "%Y-%m-%dT%H:%M:%S" "$TS" +%s 2>/dev/null \
        || date -u -d "$PUBLISHED_AT" +%s 2>/dev/null || true)
    [[ "$PUBLISHED_EPOCH" =~ ^[0-9]+$ && "$NOW" =~ ^[0-9]+$ ]] || exit 0

    AGE=$(( NOW - PUBLISHED_EPOCH ))

    # Speak only after the marker provably persisted (fail-quiet, never fail-nag).
    record_marker() {
        mkdir -p "$(dirname "$DEDUP_FILE")" 2>/dev/null
        echo "$1" >> "$DEDUP_FILE" 2>/dev/null
        grep -qxF "$1" "$DEDUP_FILE" 2>/dev/null
    }

    if (( AGE > STALE_AFTER_SECONDS )); then
        DAY=$(( NOW / 86400 ))
        if ! grep -qxF "stale:$DAY" "$DEDUP_FILE" 2>/dev/null; then
            if (( AGE >= 86400 )); then
                AGE_TEXT="$(( AGE / 86400 )) day(s)"
            else
                AGE_TEXT="$(( AGE / 3600 )) hours"
            fi
            if record_marker "stale:$DAY"; then
                echo "🩺 Dex's health checks haven't completed in $AGE_TEXT — the background checkup may not be running. Run /dex-doctor when convenient."
            fi
        fi
        exit 0
    fi

    SNAPSHOT="$HEALTH_DIR/snapshots/$SNAPSHOT_ID.json"
    [[ -f "$SNAPSHOT" ]] || exit 0
    # Snapshots are canonical JSON with sorted keys, so the top-level
    # "overall_status" precedes the nested reporter envelope ("report") in
    # document order; the first match is the authoritative one.
    SNAPSHOT_JSON="$(<"$SNAPSHOT")"
    [[ "$SNAPSHOT_JSON" =~ \"overall_status\"[[:space:]]*:[[:space:]]*\"([a-z_-]+)\" ]] || exit 0
    STATUS="${BASH_REMATCH[1]}"
    if [[ "$STATUS" == "critical" ]]; then
        if ! grep -qxF "critical:$SNAPSHOT_ID" "$DEDUP_FILE" 2>/dev/null; then
            if record_marker "critical:$SNAPSHOT_ID"; then
                echo "🩺 Dex's latest self-check found a problem — run /dex-doctor for the details and the fix."
            fi
        fi
    fi
    exit 0
} 2>/dev/null || exit 0
