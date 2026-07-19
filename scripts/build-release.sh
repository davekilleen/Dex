#!/bin/bash
# Build a clean release branch for user distribution.
#
# Usage:
#   ./scripts/build-release.sh          # Build from current main HEAD
#   ./scripts/build-release.sh --dry-run # Show what would be removed
#   ./scripts/build-release.sh --source beta --target release-beta
#
# This reads .distignore and produces a 'release' branch with dev-only
# files stripped out. Users pull from this branch via /dex-update.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Fail before constructing a release if removed Tau code, loaders, dependencies,
# LAN exposure, or unsupported authentication claims return to source inputs.
python3 scripts/check-tau-removal.py --source-root "$REPO_ROOT"

SOURCE_BRANCH="${DEX_RELEASE_SOURCE:-main}"
RELEASE_BRANCH="${DEX_RELEASE_TARGET:-release}"
DRY_RUN=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --source)
            if [ "$#" -lt 2 ] || [ -z "$2" ]; then
                echo "Error: --source requires a branch name." >&2
                exit 1
            fi
            SOURCE_BRANCH="$2"
            shift 2
            ;;
        --target)
            if [ "$#" -lt 2 ] || [ -z "$2" ]; then
                echo "Error: --target requires a branch name." >&2
                exit 1
            fi
            RELEASE_BRANCH="$2"
            shift 2
            ;;
        *)
            echo "Error: unknown argument '$1'." >&2
            exit 1
            ;;
    esac
done

# --- Validate state ---

DISTIGNORE="$REPO_ROOT/.distignore"
if [ ! -f "$DISTIGNORE" ]; then
    echo "Error: .distignore not found at $DISTIGNORE" >&2
    exit 1
fi

# Ensure we're working from a clean state
if [ -n "$(git status --porcelain)" ]; then
    echo "Error: working tree is dirty. Commit or stash changes first." >&2
    exit 1
fi

if [ "$SOURCE_BRANCH" = "$RELEASE_BRANCH" ]; then
    echo "Error: source and target branches must differ ('$SOURCE_BRANCH')." >&2
    exit 1
fi

# Ensure source branch exists
if ! git show-ref --verify --quiet "refs/heads/$SOURCE_BRANCH"; then
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
        # Keep path boundaries intact for spaces and other special characters.
        while IFS= read -r -d '' match; do
            printf '  %s\n' "$match"
        done < <(git ls-files -z -- "$pattern")
    done
    echo ""
    echo "Source: $SOURCE_BRANCH ($(git rev-parse --short $SOURCE_BRANCH))"
    echo "Target: $RELEASE_BRANCH"
    exit 0
fi

# --- Build release branch ---

SOURCE_SHA=$(git rev-parse "$SOURCE_BRANCH")
PKG_VERSION=$(grep '"version"' package.json | head -1 | sed 's/.*"version": *"\([^"]*\)".*/\1/')
TAU_CHECKER=$(mktemp)
cp scripts/check-tau-removal.py "$TAU_CHECKER"
trap 'rm -f "$TAU_CHECKER"' EXIT

echo "Building release branch..."
echo "  Source: $SOURCE_BRANCH ($SOURCE_SHA)"
echo "  Version: v$PKG_VERSION"
echo ""

# Create or reset release branch to match the selected source
git checkout -B "$RELEASE_BRANCH" "$SOURCE_BRANCH" --quiet

# Remove dev-only files
REMOVED=0
MATCHES_FILE=$(mktemp)
trap 'rm -f "$MATCHES_FILE" "$TAU_CHECKER"' EXIT
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

Clean distribution from $SOURCE_BRANCH (${SOURCE_SHA:0:7}).
Dev-only files removed per .distignore ($REMOVED files stripped).
EOF
)" --quiet

# Verify the exact committed release tree and generated legacy manifest before
# creating its immutable tag.
python3 "$TAU_CHECKER" --repo-root "$REPO_ROOT" --git-tree "$RELEASE_BRANCH"

RELEASE_SHA=$(git rev-parse --short HEAD)
# Immutable rollback identity: every distribution commit gets an annotated tag
# scoped by target branch, dist/<target>/v<version>-<release-short-sha>.
RELEASE_TAG="dist/$RELEASE_BRANCH/v$PKG_VERSION-$RELEASE_SHA"
if git show-ref --verify --quiet "refs/tags/$RELEASE_TAG"; then
    echo "Error: immutable release tag '$RELEASE_TAG' already exists." >&2
    exit 1
fi
git tag -a "$RELEASE_TAG" -m "Dex $RELEASE_BRANCH v$PKG_VERSION ($RELEASE_SHA)"

echo "Done! Release branch built:"
echo "  Branch: $RELEASE_BRANCH ($RELEASE_SHA)"
echo "  Tag: $RELEASE_TAG"
echo "  Removed: $REMOVED dev-only files"
echo ""
echo "To publish: git push origin $RELEASE_BRANCH && git push origin $RELEASE_TAG"

# Return to previous branch
git checkout - --quiet
