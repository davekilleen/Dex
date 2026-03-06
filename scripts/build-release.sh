#!/bin/bash
# Build a clean release branch for user distribution.
#
# Usage:
#   ./scripts/build-release.sh          # Build from current main HEAD
#   ./scripts/build-release.sh --dry-run # Show what would be removed
#
# This reads .distignore and produces a 'release' branch with dev-only
# files stripped out. Users pull from this branch via /dex-update.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
fi

# --- Validate state ---

DISTIGNORE="$REPO_ROOT/.distignore"
if [ ! -f "$DISTIGNORE" ]; then
    echo "Error: .distignore not found at $DISTIGNORE" >&2
    exit 1
fi

SOURCE_BRANCH="main"
RELEASE_BRANCH="release"

# Ensure we're working from a clean state
if [ -n "$(git status --porcelain)" ]; then
    echo "Error: working tree is dirty. Commit or stash changes first." >&2
    exit 1
fi

# Ensure source branch exists
if ! git rev-parse --verify "$SOURCE_BRANCH" >/dev/null 2>&1; then
    echo "Error: branch '$SOURCE_BRANCH' not found." >&2
    exit 1
fi

# --- Parse .distignore ---

# Read patterns, skip comments and blank lines
PATTERNS=()
while IFS= read -r line; do
    line="${line%%#*}"       # strip inline comments
    line="${line%"${line##*[! ]}"}"  # trim trailing whitespace
    line="${line#"${line%%[! ]*}"}"  # trim leading whitespace
    [ -z "$line" ] && continue
    PATTERNS+=("$line")
done < "$DISTIGNORE"

if [ ${#PATTERNS[@]} -eq 0 ]; then
    echo "Error: no patterns found in .distignore" >&2
    exit 1
fi

# --- Dry run: show what would be removed ---

if [ "$DRY_RUN" = true ]; then
    echo "Dry run — files that would be removed from release branch:"
    echo ""
    for pattern in "${PATTERNS[@]}"; do
        # Use git ls-files to match tracked files
        matches=$(git ls-files -- "$pattern" 2>/dev/null || true)
        if [ -n "$matches" ]; then
            echo "$matches" | sed 's/^/  /'
        fi
    done
    echo ""
    echo "Source: $SOURCE_BRANCH ($(git rev-parse --short $SOURCE_BRANCH))"
    echo "Target: $RELEASE_BRANCH"
    exit 0
fi

# --- Build release branch ---

SOURCE_SHA=$(git rev-parse "$SOURCE_BRANCH")
PKG_VERSION=$(grep '"version"' package.json | head -1 | sed 's/.*"version": *"\([^"]*\)".*/\1/')

echo "Building release branch..."
echo "  Source: $SOURCE_BRANCH ($SOURCE_SHA)"
echo "  Version: v$PKG_VERSION"
echo ""

# Create or reset release branch to match main
git checkout -B "$RELEASE_BRANCH" "$SOURCE_BRANCH" --quiet

# Remove dev-only files
REMOVED=0
for pattern in "${PATTERNS[@]}"; do
    matches=$(git ls-files -- "$pattern" 2>/dev/null || true)
    if [ -n "$matches" ]; then
        echo "$matches" | xargs git rm -rf --quiet 2>/dev/null || true
        count=$(echo "$matches" | wc -l | tr -d ' ')
        REMOVED=$((REMOVED + count))
    fi
done

if [ $REMOVED -eq 0 ]; then
    echo "Nothing to remove — release branch matches main."
    git checkout - --quiet
    exit 0
fi

# Remove devDependencies from package.json if present
if grep -q '"devDependencies"' package.json 2>/dev/null; then
    # Use node to strip devDependencies cleanly
    node -e "
        const pkg = require('./package.json');
        delete pkg.devDependencies;
        require('fs').writeFileSync('package.json', JSON.stringify(pkg, null, 2) + '\n');
    "
    git add package.json
fi

# Commit the clean state
git add -A
git commit -m "$(cat <<EOF
release: v$PKG_VERSION

Clean distribution from $SOURCE_BRANCH (${SOURCE_SHA:0:7}).
Dev-only files removed per .distignore ($REMOVED files stripped).
EOF
)" --quiet

RELEASE_SHA=$(git rev-parse --short HEAD)

echo "Done! Release branch built:"
echo "  Branch: $RELEASE_BRANCH ($RELEASE_SHA)"
echo "  Removed: $REMOVED dev-only files"
echo ""
echo "To publish: git push origin $RELEASE_BRANCH"

# Return to previous branch
git checkout - --quiet
