#!/usr/bin/env bash
# Release automation for Dex
# Usage: bash scripts/release.sh [patch|minor|major]
#
# Steps:
#   1. Check the last release reached the public releases page
#   2. Bump version in package.json
#   3. Insert dated CHANGELOG header for the new version
#   4. Commit, tag, and push

set -euo pipefail

trap 'echo "Release cut stopped before completion; inspect git status and tags before retrying." >&2' ERR

# --- Defaults & validation ---------------------------------------------------

BUMP_TYPE="${1:-patch}"
case "$BUMP_TYPE" in
  patch|minor|major) ;;
  *) echo "Usage: $0 [patch|minor|major]" >&2; exit 1 ;;
esac

# Must run from repo root
if [ ! -f package.json ] || [ ! -f CHANGELOG.md ]; then
  echo "Error: run from the repository root (package.json + CHANGELOG.md required)" >&2
  exit 1
fi

# Working tree must be clean
if [ -n "$(git status --porcelain)" ]; then
  echo "Error: working tree is dirty — commit or stash changes first" >&2
  exit 1
fi

# --- Read current version -----------------------------------------------------

CURRENT_VERSION=$(grep '"version"' package.json | head -1 | sed 's/.*"\([0-9][0-9.]*\)".*/\1/')
IFS='.' read -r V_MAJOR V_MINOR V_PATCH <<< "$CURRENT_VERSION"

case "$BUMP_TYPE" in
  patch) V_PATCH=$((V_PATCH + 1)) ;;
  minor) V_MINOR=$((V_MINOR + 1)); V_PATCH=0 ;;
  major) V_MAJOR=$((V_MAJOR + 1)); V_MINOR=0; V_PATCH=0 ;;
esac

NEW_VERSION="${V_MAJOR}.${V_MINOR}.${V_PATCH}"
TAG="v${NEW_VERSION}"
TODAY=$(date +%Y-%m-%d)

echo "Releasing: ${CURRENT_VERSION} -> ${NEW_VERSION} (${BUMP_TYPE})"

# --- Check previous release reached the public page ---------------------------

if ! command -v curl >/dev/null 2>&1; then
  echo "Releases page check could not run (curl is unavailable); continuing."
else
  FETCH_RESULT=$(
    if curl -fsS --connect-timeout 5 --max-time 15 \
      "https://heydex.ai/releases/releases.md" 2>/dev/null; then
      printf '\n__DEX_RELEASES_FETCH_OK__\n'
    else
      printf '\n__DEX_RELEASES_FETCH_FAILED__\n'
    fi
  )
  if [[ "$FETCH_RESULT" == *$'\n__DEX_RELEASES_FETCH_OK__' ]]; then
    PUBLISHED_CHANGELOG=${FETCH_RESULT%$'\n__DEX_RELEASES_FETCH_OK__'}
    PUBLISHED_VERSION=$(
      if printf '%s\n' "$PUBLISHED_CHANGELOG" \
        | grep -m 1 -E '^## \[[0-9]+\.[0-9]+\.[0-9]+\]' \
        | sed -E 's/^## \[([0-9]+\.[0-9]+\.[0-9]+)\].*/\1/'; then
        :
      fi
    )
    if [ -n "$PUBLISHED_VERSION" ]; then
      IFS='.' read -r C_MAJOR C_MINOR C_PATCH <<< "$CURRENT_VERSION"
      IFS='.' read -r P_MAJOR P_MINOR P_PATCH <<< "$PUBLISHED_VERSION"
      if [ "$PUBLISHED_VERSION" = "$CURRENT_VERSION" ]; then
        echo "Releases page check: ${CURRENT_VERSION} is published."
      elif (( P_MAJOR < C_MAJOR
        || (P_MAJOR == C_MAJOR && P_MINOR < C_MINOR)
        || (P_MAJOR == C_MAJOR && P_MINOR == C_MINOR && P_PATCH < C_PATCH) )); then
        echo ""
        echo "WARNING: The last release has not reached heydex.ai/releases yet."
        echo "  Published version: ${PUBLISHED_VERSION}"
        echo "  Last release:      ${CURRENT_VERSION}"
        echo "  Publish now: run ./deploy-releases.sh in the heydex-website repo."
        echo "  If the hourly timer is dead: run ops/releases-republish/install.sh there."
        echo ""
      fi
    else
      echo "Releases page check could not run (no release version found); continuing."
    fi
  else
    echo "Releases page check could not run (heydex.ai was unavailable); continuing."
  fi
fi

# --- Bump package.json --------------------------------------------------------

sed -i.bak "s/\"version\": \"${CURRENT_VERSION}\"/\"version\": \"${NEW_VERSION}\"/" package.json
rm -f package.json.bak

# Keep package-lock.json in sync (if it exists)
if [ -f package-lock.json ]; then
  sed -i.bak "0,/\"version\": \"${CURRENT_VERSION}\"/s/\"version\": \"${CURRENT_VERSION}\"/\"version\": \"${NEW_VERSION}\"/" package-lock.json
  rm -f package-lock.json.bak
fi

# --- Insert CHANGELOG header --------------------------------------------------

# Insert a new section right after the first "---" separator (after the preamble)
# The CHANGELOG format is:  ## [X.Y.Z] — Title (YYYY-MM-DD)
sed -i.bak "0,/^---$/s/^---$/---\n\n## [${NEW_VERSION}] — (${TODAY})\n/" CHANGELOG.md
rm -f CHANGELOG.md.bak

# --- Generate installed-files manifest -----------------------------------------

python3 core/utils/update_verifier.py \
  --write-legacy-profile System/.release-evidence-profile.json \
  --release-version "$NEW_VERSION"
VAULT_PATH="$PWD" python3 -m core.migrations.preserve_local_only_paths stamp-transition \
  --repo "$PWD"
bash scripts/generate-manifest.sh

# --- Commit, tag, push --------------------------------------------------------

git add package.json package-lock.json CHANGELOG.md \
  System/.release-evidence-profile.json \
  System/.local-only-preservation-transition.json \
  System/.installed-files.manifest
git commit -m "release: v${NEW_VERSION}"
git tag -a "$TAG" -m "Release ${TAG}"
trap - ERR

echo ""
echo "Created commit and tag ${TAG}."
echo ""
echo "To publish:"
echo "  git push origin main --follow-tags"
