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

# Validate the selected source tree, not whichever branch happens to be checked
# out. This happens before creating/resetting any release ref.
python3 scripts/check-tau-removal.py --repo-root "$REPO_ROOT" --git-source "$SOURCE_BRANCH"

DISTIGNORE=$(mktemp)
TAU_CHECKER=$(mktemp)
CATALOG_GENERATOR=$(mktemp)
CATALOG_COVERAGE_CHECKER=$(mktemp)
MATCHES_FILE=$(mktemp)
trap 'rm -f "$DISTIGNORE" "$TAU_CHECKER" "$CATALOG_GENERATOR" "$CATALOG_COVERAGE_CHECKER" "$MATCHES_FILE"' EXIT
if ! git show "$SOURCE_BRANCH:.distignore" > "$DISTIGNORE"; then
    echo "Error: .distignore not found in selected source '$SOURCE_BRANCH'." >&2
    exit 1
fi
cp scripts/check-tau-removal.py "$TAU_CHECKER"

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
        done < <(git ls-tree -r -z --name-only "$SOURCE_BRANCH" -- "$pattern")
    done
    echo ""
    echo "Source: $SOURCE_BRANCH ($(git rev-parse --short $SOURCE_BRANCH))"
    echo "Target: $RELEASE_BRANCH"
    exit 0
fi

# --- Build release branch ---

SOURCE_SHA=$(git rev-parse "$SOURCE_BRANCH")
git show "$SOURCE_SHA:scripts/generate-release-catalog.py" > "$CATALOG_GENERATOR"
git show "$SOURCE_SHA:scripts/check-catalog-coverage.py" > "$CATALOG_COVERAGE_CHECKER"
SOURCE_PACKAGE_SIZE=$(git cat-file -s "$SOURCE_SHA:package.json" 2>/dev/null || true)
if ! [[ "$SOURCE_PACKAGE_SIZE" =~ ^[0-9]+$ ]] || [ "$SOURCE_PACKAGE_SIZE" -gt 1048576 ]; then
    echo "Error: selected source package.json is missing or exceeds 1 MiB." >&2
    exit 1
fi
if ! PKG_VERSION=$(git show "$SOURCE_SHA:package.json" | python3 -c '
import json, re, sys
def _unique(pairs):
    result = {}
    for key, item in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = item
    return result

raw = sys.stdin.buffer.read(1048577)
if len(raw) > 1048576:
    raise SystemExit("selected package.json exceeds 1 MiB")
try:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=lambda pairs: _unique(pairs))
except Exception as error:
    raise SystemExit(f"selected package.json is invalid: {error}")
version = value.get("version") if isinstance(value, dict) else None
if not isinstance(version, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version) is None:
    raise SystemExit("selected package.json version is not canonical semver")
print(version)
' 2>&1); then
    echo "Error: $PKG_VERSION" >&2
    exit 1
fi

echo "Building release branch..."
echo "  Source: $SOURCE_BRANCH ($SOURCE_SHA)"
echo "  Version: v$PKG_VERSION"
echo ""

# Create or reset release branch to the immutable source identity validated
# above, even if the source branch moves while this build is running.
git checkout -B "$RELEASE_BRANCH" "$SOURCE_SHA" --quiet

# Remove dev-only files
REMOVED=0
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

# Generate SR1's closed legacy declaration from the exact distribution version.
# Later catalog-bearing releases replace it; legacy-v1 never needs a catalog.
PROFILE="System/.release-evidence-profile.json"
python3 core/utils/update_verifier.py \
    --write-legacy-profile "$PROFILE" \
    --release-version "$PKG_VERSION"
git add -- "$PROFILE"

# Generate the installed-files manifest from the exact release index. Stage the
# generated manifest and catalog paths first so the manifest truthfully includes
# both; replacing their contents does not change the set of shipped paths.
MANIFEST="System/.installed-files.manifest"
CATALOG="System/.release-catalog.json"
mkdir -p "$(dirname "$MANIFEST")"
: > "$MANIFEST"
: > "$CATALOG"
git add -- "$MANIFEST" "$CATALOG"
MANIFEST_TREE=$(git write-tree)
python3 core/utils/manifest.py "$MANIFEST_TREE" --repo-root "$REPO_ROOT" --output "$MANIFEST" \
    --require-lifecycle-contracts

# B1 supports stable and beta catalog identities. Custom target names used by
# local verification retain stable catalog semantics.
CATALOG_CHANNEL="release"
if [ "$RELEASE_BRANCH" = "release-beta" ]; then
    CATALOG_CHANNEL="release-beta"
fi
python3 "$CATALOG_GENERATOR" \
    --release-root "$REPO_ROOT" \
    --channel "$CATALOG_CHANNEL" \
    --source-commit "$SOURCE_SHA"
python3 "$CATALOG_COVERAGE_CHECKER" --release-root "$REPO_ROOT"
git add -- "$MANIFEST" "$CATALOG" packages/dex-contracts/dist/release-catalog-v1.schema.json

if git diff --cached --quiet; then
    echo "Nothing to remove — release branch matches main."
    git checkout - --quiet
    exit 0
fi

# Commit the clean state, installed-files manifest, and release catalog.
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
