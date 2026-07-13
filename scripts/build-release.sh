#!/bin/bash
# Build a clean release branch for user distribution.
#
# Usage:
#   ./scripts/build-release.sh           # Build and tag the distributed commit
#   ./scripts/build-release.sh --dry-run # Show what would be removed
#   ./scripts/build-release.sh --no-tag  # Build only (CI validation)
#
# This reads .distignore and produces a 'release' branch with dev-only
# files stripped out. Users pull from this branch via /dex-update.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=false
TAG_RELEASE=true
for argument in "$@"; do
    case "$argument" in
        --dry-run) DRY_RUN=true ;;
        --no-tag) TAG_RELEASE=false ;;
        *) echo "Usage: $0 [--dry-run] [--no-tag]" >&2; exit 2 ;;
    esac
done

# --- Validate state ---

DISTIGNORE="$REPO_ROOT/.distignore"
if [ ! -f "$DISTIGNORE" ]; then
    echo "Error: .distignore not found at $DISTIGNORE" >&2
    exit 1
fi

SOURCE_REF="${DEX_RELEASE_SOURCE:-main}"
RELEASE_BRANCH="release"

# Ensure we're working from a clean state
if [ -n "$(git status --porcelain)" ]; then
    echo "Error: working tree is dirty. Commit or stash changes first." >&2
    exit 1
fi

# Ensure source branch exists
if ! git rev-parse --verify "$SOURCE_REF^{commit}" >/dev/null 2>&1; then
    echo "Error: release source '$SOURCE_REF' not found." >&2
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
        # Keep path boundaries intact for spaces and other special characters.
        while IFS= read -r -d '' match; do
            printf '  %s\n' "$match"
        done < <(git ls-files -z -- "$pattern")
    done
    echo ""
    echo "Source: $SOURCE_REF ($(git rev-parse --short "$SOURCE_REF"))"
    echo "Target: $RELEASE_BRANCH"
    exit 0
fi

# --- Build release branch ---

SOURCE_SHA=$(git rev-parse "$SOURCE_REF^{commit}")
PKG_VERSION=$(grep '"version"' package.json | head -1 | sed 's/.*"version": *"\([^"]*\)".*/\1/')
DIST_TAG="dist-v$PKG_VERSION"
ORIGINAL_REF=$(git symbolic-ref --quiet --short HEAD || git rev-parse HEAD)

echo "Building release branch..."
echo "  Source: $SOURCE_REF ($SOURCE_SHA)"
echo "  Version: v$PKG_VERSION"
echo ""

# Create or reset release branch to match main
git checkout -B "$RELEASE_BRANCH" "$SOURCE_SHA" --quiet

# Remove dev-only files
REMOVED=0
MATCHES_FILE=$(mktemp)
trap 'rm -f "$MATCHES_FILE"' EXIT
for pattern in "${PATTERNS[@]}"; do
    git ls-files -z -- "$pattern" > "$MATCHES_FILE"
    if [ -s "$MATCHES_FILE" ]; then
        count=0
        while IFS= read -r -d '' _match; do
            count=$((count + 1))
        done < "$MATCHES_FILE"
        xargs -0 git rm -rf --quiet -- < "$MATCHES_FILE"
        REMOVED=$((REMOVED + count))
    fi
done

# Remove development-only package metadata that points at stripped files.
node -e "
    const fs = require('fs');
    const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
    delete pkg.devDependencies;
    if (pkg.scripts) delete pkg.scripts['test'];
    if (pkg.scripts) delete pkg.scripts['test:hooks'];
    if (pkg.scripts) delete pkg.scripts['test:scripts'];
    fs.writeFileSync('package.json', JSON.stringify(pkg, null, 2) + '\n');
"
git add -- package.json

# Generate the installed-files manifest from the exact release index. Stage an
# empty manifest first so the manifest truthfully includes its own shipped path;
# replacing its contents does not change the set of paths in the tree.
MANIFEST="System/.installed-files.manifest"
mkdir -p "$(dirname "$MANIFEST")"
: > "$MANIFEST"
git add -- "$MANIFEST"
MANIFEST_TREE=$(git write-tree)
python3 core/utils/manifest.py "$MANIFEST_TREE" --repo-root "$REPO_ROOT" --output "$MANIFEST"
git add -- "$MANIFEST"

if git diff --cached --quiet; then
    echo "Nothing to remove — release branch matches main."
    git checkout - --quiet
    exit 0
fi

# Commit the clean state and its installed-files manifest
git commit -m "$(cat <<EOF
release: v$PKG_VERSION

Clean distribution from $SOURCE_REF (${SOURCE_SHA:0:7}).
Dev-only files removed per .distignore ($REMOVED files stripped).
EOF
)" --quiet

RELEASE_COMMIT=$(git rev-parse HEAD)
if [ "$TAG_RELEASE" = true ]; then
    if EXISTING_DIST_COMMIT=$(git rev-parse --verify "$DIST_TAG^{commit}" 2>/dev/null); then
        if [ "$EXISTING_DIST_COMMIT" != "$RELEASE_COMMIT" ]; then
            EXISTING_TREE=$(git rev-parse "$EXISTING_DIST_COMMIT^{tree}")
            RELEASE_TREE=$(git rev-parse "$RELEASE_COMMIT^{tree}")
            git checkout "$ORIGINAL_REF" --quiet
            git branch -f "$RELEASE_BRANCH" "$EXISTING_DIST_COMMIT" >/dev/null
            if [ "$EXISTING_TREE" != "$RELEASE_TREE" ]; then
                echo "Error: $DIST_TAG is immutable and already points at different distributed bytes. Bump the package version before building another release." >&2
                exit 1
            fi
            RELEASE_COMMIT="$EXISTING_DIST_COMMIT"
        fi
    else
        git tag -a "$DIST_TAG" "$RELEASE_COMMIT" -m "Distributed release v$PKG_VERSION"
    fi
fi

RELEASE_SHA=$(git rev-parse --short "$RELEASE_COMMIT")

echo "Done! Release branch built:"
echo "  Branch: $RELEASE_BRANCH ($RELEASE_SHA)"
echo "  Removed: $REMOVED dev-only files"
if [ "$TAG_RELEASE" = true ]; then
    echo "  Tag: $DIST_TAG ($RELEASE_SHA)"
fi
echo ""
echo "To publish: git push origin $RELEASE_BRANCH"

# Return to previous branch
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "$ORIGINAL_REF^{commit}")" ] \
    || [ "$(git symbolic-ref --quiet --short HEAD || true)" != "$ORIGINAL_REF" ]; then
    git checkout "$ORIGINAL_REF" --quiet
fi
