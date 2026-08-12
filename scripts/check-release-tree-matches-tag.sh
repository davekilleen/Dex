#!/bin/bash
# Refuse to build release assets from a tree that is not the tree of the tag
# whose version they will be labelled with.
#
# Why this exists: build-release triggers on pushes to main and builds from
# whatever main HEAD is at execution time, while taking the release identity
# from package.json. If the run at the release commit does not reach the build
# step — a flaky test is enough — a later run builds the assets from a newer
# tree and still labels them with the old version. On 2026-08-12 that shipped a
# v1.95.0 bundle containing core/customization_migration/inventory.py from two
# commits later; only an unrelated TLS failure in the read-back step stopped it
# going public.
#
# The existing read-back check cannot catch this: it compares what was ATTACHED
# against what was BUILT, and both sides are the later tree, so it agrees with
# itself. Nothing compared the TAG against the BUILT tree. This does.
#
# Trees, not commits: a later commit whose tree is identical (a revert pair, an
# empty commit) ships byte-identical content and is safe. Content drift is the
# thing to refuse.
set -euo pipefail

VERSION="$(python3 -c 'import json; print(json.load(open("package.json"))["version"])')"
TAG="v${VERSION}"
REF="refs/tags/${TAG}"

# release.sh pushes main first and the tag immediately after, so a run that
# starts between the two would see no tag yet. Wait briefly rather than fail a
# legitimate release on a few seconds of ordering.
ATTEMPTS="${RELEASE_TAG_WAIT_ATTEMPTS:-12}"
SLEEP_SECONDS="${RELEASE_TAG_WAIT_SECONDS:-5}"
FOUND=""
for _ in $(seq 1 "$ATTEMPTS"); do
  if [ -n "$(git ls-remote --tags origin "$REF" 2>/dev/null)" ]; then
    FOUND=1
    break
  fi
  sleep "$SLEEP_SECONDS"
done

if [ -z "$FOUND" ]; then
  echo "❌ Release-tree gate failed: package.json says $VERSION but no $TAG exists on origin." >&2
  echo "Assets labelled $VERSION would have no tag to be checked against, so they cannot be trusted to name their own contents." >&2
  echo "Push the release tag, or bump the version in a release commit that carries one." >&2
  exit 1
fi

git fetch --quiet origin "$REF:$REF" 2>/dev/null || true

if ! TAG_TREE="$(git rev-parse --verify --quiet "${TAG}^{tree}")"; then
  echo "❌ Release-tree gate failed: $TAG exists on origin but could not be resolved locally." >&2
  echo "Refusing to build rather than guess which tree $VERSION names." >&2
  exit 1
fi
HEAD_TREE="$(git rev-parse "HEAD^{tree}")"

if [ "$TAG_TREE" != "$HEAD_TREE" ]; then
  TAG_COMMIT="$(git rev-parse "${TAG}^{commit}")"
  HEAD_COMMIT="$(git rev-parse HEAD)"
  echo "❌ Release-tree gate failed: this build would label a different tree as $VERSION." >&2
  echo "  $TAG names commit $TAG_COMMIT (tree $TAG_TREE)" >&2
  echo "  this build is running on $HEAD_COMMIT (tree $HEAD_TREE)" >&2
  echo "" >&2
  echo "Files that differ between them:" >&2
  git diff --name-only "$TAG_TREE" "$HEAD_TREE" 2>/dev/null | sed 's/^/  /' >&2 || true
  echo "" >&2
  echo "Publishing now would produce assets whose contents are not the contents of $TAG." >&2
  echo "Re-run the build on the release commit itself, or cut a fresh version for the current tree." >&2
  exit 1
fi

echo "Release-tree gate passed: $TAG and this build share tree $TAG_TREE."
