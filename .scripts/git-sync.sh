#!/bin/bash
# Auto-sync local changes to origin (tara-magentic/Dex)
# Runs on a cron schedule — commits and pushes any uncommitted changes.

set -euo pipefail

REPO="/Users/taralivesey/projects/Dex"
LOG="$REPO/.scripts/git-sync.log"
MAX_LOG_LINES=500

cd "$REPO"

# Rotate log if it gets large
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt "$MAX_LOG_LINES" ]; then
    tail -n 250 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }

# Nothing to do if working tree is clean
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    echo "$(timestamp) [sync] No changes." >> "$LOG"
    exit 0
fi

echo "$(timestamp) [sync] Changes detected — committing..." >> "$LOG"

git add -A
git commit -m "auto-sync: $(date '+%Y-%m-%d %H:%M')" >> "$LOG" 2>&1

if git push origin main >> "$LOG" 2>&1; then
    echo "$(timestamp) [sync] Pushed to origin/main." >> "$LOG"
else
    echo "$(timestamp) [sync] ERROR: Push failed." >> "$LOG"
    exit 1
fi
