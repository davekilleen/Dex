#!/usr/bin/env bash
# Release automation for Dex
# Usage: bash scripts/release.sh [patch|minor|major]
#
# Steps:
#   1. Bump version in package.json
#   2. Insert dated CHANGELOG header for the new version
#   3. Commit, tag, and push

set -euo pipefail

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

bash scripts/generate-manifest.sh

# --- Commit, tag, push --------------------------------------------------------

git add package.json package-lock.json CHANGELOG.md System/.installed-files.manifest
git commit -m "release: v${NEW_VERSION}"
git tag -a "$TAG" -m "Release ${TAG}"

echo ""
echo "Created commit and tag ${TAG}."
echo ""
echo "To publish:"
echo "  git push origin main --follow-tags"
