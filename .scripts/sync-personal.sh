#!/bin/bash
# sync-personal.sh
# Push personal content to personal GitHub repo (tlives/dex-personal)
#
# Personal = portable across employers:
#   .claude/, core/, .scripts/, System/, CLAUDE.md
#   06-Resources/Wiki/, 06-Resources/Learnings/
#   05-Areas/Career/, 04-Projects/Personal/
#   03-Tasks/Personal_Tasks.md, 01-Quarter_Goals/
#
# Work-sensitive (excluded):
#   00-Inbox/Meetings/, 04-Projects/Work/, 03-Tasks/Work_Tasks.md
#   05-Areas/People/, 05-Areas/Companies/

set -euo pipefail

VAULT="/Users/taralivesey/projects/Dex"
PERSONAL_REMOTE="https://github.com/tlives/dex-personal.git"
TEMP=$(mktemp -d)
trap "rm -rf $TEMP" EXIT

echo "🔄 Syncing personal content to personal repo..."

# Clone personal repo (or init fresh if first run)
if git clone "$PERSONAL_REMOTE" "$TEMP" 2>/dev/null; then
    echo "  Cloned existing personal repo"
else
    echo "  Initialising personal repo..."
    cd "$TEMP" && git init && git remote add origin "$PERSONAL_REMOTE"
fi

cd "$TEMP"

# Copy personal content
PERSONAL_ITEMS=(
    ".claude"
    "core"
    ".scripts"
    "System"
    "06-Resources/Wiki"
    "06-Resources/Learnings"
    "06-Resources/Dex_System"
    "05-Areas/Career"
    "04-Projects/Personal"
    "01-Quarter_Goals"
    "02-Week_Priorities"
    "00-Inbox/Ideas"
    "00-Inbox/Research"
    "CLAUDE.md"
    ".gitignore"
    "requirements.txt"
    "package.json"
    ".env.example"
)

for item in "${PERSONAL_ITEMS[@]}"; do
    src="$VAULT/$item"
    [ -e "$src" ] || continue
    mkdir -p "$(dirname "$TEMP/$item")"
    cp -r "$src" "$TEMP/$item"
done

# Personal tasks (single file, not whole Tasks dir)
mkdir -p "$TEMP/03-Tasks"
[ -f "$VAULT/03-Tasks/Personal_Tasks.md" ] && \
    cp "$VAULT/03-Tasks/Personal_Tasks.md" "$TEMP/03-Tasks/Personal_Tasks.md"

# Commit and push
git add -A
if git diff --cached --quiet; then
    echo "✅ Personal repo already up to date — nothing to sync"
else
    COMMIT_MSG="sync: $(date '+%Y-%m-%d %H:%M')"
    git commit -m "$COMMIT_MSG"
    git push origin main --force-with-lease 2>/dev/null || git push origin main
    echo "✅ Personal repo synced: $COMMIT_MSG"
fi
