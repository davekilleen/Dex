#!/bin/bash
# Daily upstream check — fetches davekilleen/Dex and reports new commits.
# Does NOT auto-merge. Writes a summary to .scripts/upstream-check.log
# so you can review and decide whether to pull changes.

set -euo pipefail

REPO="/Users/taralivesey/projects/Dex"
LOG="$REPO/.scripts/upstream-check.log"

cd "$REPO"

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }

echo "" >> "$LOG"
echo "$(timestamp) [upstream-check] Fetching upstream (davekilleen/Dex)..." >> "$LOG"

if ! git fetch upstream >> "$LOG" 2>&1; then
    echo "$(timestamp) [upstream-check] ERROR: Could not fetch upstream." >> "$LOG"
    exit 1
fi

# Count commits on upstream/main not yet in our main
NEW_COMMITS=$(git log main..upstream/main --oneline 2>/dev/null)

if [ -z "$NEW_COMMITS" ]; then
    echo "$(timestamp) [upstream-check] Up to date with upstream. No action needed." >> "$LOG"
    exit 0
fi

COUNT=$(echo "$NEW_COMMITS" | wc -l | tr -d ' ')
echo "$(timestamp) [upstream-check] $COUNT new commit(s) available from upstream:" >> "$LOG"
echo "$NEW_COMMITS" | sed 's/^/  /' >> "$LOG"
echo "" >> "$LOG"
echo "  To review the diff:  git diff main..upstream/main" >> "$LOG"
echo "  To merge:            git merge upstream/main" >> "$LOG"
echo "" >> "$LOG"
