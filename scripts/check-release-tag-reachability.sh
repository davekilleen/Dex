#!/bin/bash
set -euo pipefail

SENTINEL_VERSIONS=("1.62.0" "1.68.0" "1.74.0")
# An unpublished version may consume one more slot in this CI run. A version
# already present on origin cannot: build-release's exact-version guard skips it.
PREPUBLICATION_MARGIN=31
SHIPPED_TAG_BOUND=32

if ! REMOTE_TAGS="$(
  git ls-remote --tags origin 'refs/tags/dist/release/v*'
)"; then
  echo "❌ Release-tag reachability gate failed: could not read dist/release tags from origin; git ls-remote failed." >&2
  exit 1
fi

# Annotated tags also produce a peeled ^{} ref; count only the tag ref itself.
RELEASE_VERSIONS="$(
  printf '%s\n' "$REMOTE_TAGS" |
    awk '
      $2 !~ /\^\{\}$/ &&
      $2 ~ /^refs\/tags\/dist\/release\/v[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]+$/ {
        version = $2
        sub(/^refs\/tags\/dist\/release\/v/, "", version)
        sub(/-[0-9a-f]+$/, "", version)
        print version
      }
    '
)"

if [ -z "$RELEASE_VERSIONS" ]; then
  echo "❌ Release-tag reachability gate failed: origin returned no readable dist/release tags, so old-version reachability cannot be verified." >&2
  exit 1
fi

if ! CURRENT_VERSION="$(
  python3 -c 'import json; print(json.load(open("package.json"))["version"])'
)"; then
  echo "❌ Release-tag reachability gate failed: could not read the current package version." >&2
  exit 1
fi

# Keep prerelease recognition aligned with build-release-beta: that lane writes
# dist/release-beta/* and cannot consume a stable dist/release/* slot.
CURRENT_VERSION_KIND=""
if [[ "$CURRENT_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  CURRENT_VERSION_KIND="stable"
elif [[ "$CURRENT_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+-[0-9A-Za-z.]+$ ]]; then
  CURRENT_VERSION_KIND="prerelease"
else
  echo "❌ Release-tag reachability gate failed: current package version '$CURRENT_VERSION' is not a supported stable or prerelease semantic version." >&2
  exit 1
fi

CURRENT_VERSION_PUBLISHED=0
if [ "$CURRENT_VERSION_KIND" = "stable" ] && printf '%s\n' "$RELEASE_VERSIONS" | grep -Fxq "$CURRENT_VERSION"; then
  CURRENT_VERSION_PUBLISHED=1
fi

FAILED=0
for SENTINEL in "${SENTINEL_VERSIONS[@]}"; do
  NEWER_COUNT="$(
    printf '%s\n' "$RELEASE_VERSIONS" |
      awk -F. -v sentinel="$SENTINEL" '
        BEGIN {
          split(sentinel, sentinel_parts, ".")
        }
        ($1 + 0) > (sentinel_parts[1] + 0) ||
        (($1 + 0) == (sentinel_parts[1] + 0) &&
          ($2 + 0) > (sentinel_parts[2] + 0)) ||
        (($1 + 0) == (sentinel_parts[1] + 0) &&
          ($2 + 0) == (sentinel_parts[2] + 0) &&
          ($3 + 0) > (sentinel_parts[3] + 0)) {
            count++
        }
        END {
          print count + 0
        }
      '
  )"

  if [ "$NEWER_COUNT" -ge "$SHIPPED_TAG_BOUND" ]; then
    echo "❌ v$SENTINEL has $NEWER_COUNT newer dist/release tags; the shipped verifier bound is $SHIPPED_TAG_BOUND." >&2
    echo "Do not move immutable release labels blindly; use the verified bridge-and-archive procedure before old installs go silent." >&2
    FAILED=1
  elif [ "$NEWER_COUNT" -ge "$PREPUBLICATION_MARGIN" ] && [ "$CURRENT_VERSION_KIND" = "stable" ] && [ "$CURRENT_VERSION_PUBLISHED" -ne 1 ]; then
    echo "❌ v$SENTINEL has $NEWER_COUNT newer dist/release tags and current package version v$CURRENT_VERSION is not published; the pre-publication safety margin is $PREPUBLICATION_MARGIN." >&2
    echo "This CI run may publish one more tag, so use the verified bridge-and-archive procedure before old installs go silent." >&2
    FAILED=1
  fi
done

if [ "$FAILED" -ne 0 ]; then
  echo "❌ Release-tag reachability gate failed." >&2
  exit 1
fi

echo "Release-tag reachability gate passed."
