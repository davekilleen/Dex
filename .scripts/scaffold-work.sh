#!/bin/bash
# scaffold-work.sh
# Recreate the work layer of your vault at a new organisation.
# Run this after cloning your personal repo at a new job.
#
# Usage:
#   .scripts/scaffold-work.sh <new-work-git-remote-url> <org-name>
#
# Example:
#   .scripts/scaffold-work.sh https://github.com/new-org/Dex.git "Acme Corp"

set -euo pipefail

NEW_REMOTE="${1:?Usage: scaffold-work.sh <new-work-git-remote-url> <org-name>}"
ORG_NAME="${2:?Usage: scaffold-work.sh <new-work-git-remote-url> <org-name>}"

VAULT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$VAULT"

echo ""
echo "🏗  Scaffolding work layer for: $ORG_NAME"
echo "   Vault: $VAULT"
echo "   Remote: $NEW_REMOTE"
echo ""

# Create work folder structure
mkdir -p \
    "00-Inbox/Meetings" \
    "03-Tasks" \
    "04-Projects/Work" \
    "05-Areas/People/Internal" \
    "05-Areas/People/External" \
    "05-Areas/Companies" \
    "07-Archives/Projects" \
    "07-Archives/Plans" \
    "07-Archives/Reviews"

# Create empty work tasks file if it doesn't exist
if [ ! -f "03-Tasks/Work_Tasks.md" ]; then
cat > "03-Tasks/Work_Tasks.md" << 'EOF'
# Work Tasks

## P0 - Urgent (max 3)

## P1 - Important (max 5)

## P2 - Normal (max 10)

## P3 - Backlog

---

## Task Format

```
- [ ] **Task title** — Context or notes #pillar
- [s] Started
- [b] Blocked (note blocker)
- [x] Completed ✅ YYYY-MM-DD
```
EOF
fi

# Set up work remote
if git remote get-url work &>/dev/null; then
    git remote set-url work "$NEW_REMOTE"
    echo "  Updated 'work' remote → $NEW_REMOTE"
else
    git remote add work "$NEW_REMOTE"
    echo "  Added 'work' remote → $NEW_REMOTE"
fi

# Initial push to work remote
echo ""
echo "  Pushing to work remote..."
git push work main 2>/dev/null || git push work main --set-upstream

echo ""
echo "✅ Work layer scaffolded for $ORG_NAME"
echo ""
echo "Next steps:"
echo "  1. Run /setup in Dex to update your profile (name, role, company, pillars)"
echo "  2. Your personal content (wiki, learnings, career, skills) is already here"
echo "  3. Run .scripts/sync-personal.sh to keep personal repo in sync"
echo ""
