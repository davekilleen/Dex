#!/bin/bash
set -euo pipefail

SENTINEL_VERSIONS=("1.62.0" "1.68.0" "1.74.0")
# The shipped verifier accepts at most 32 newer candidates. Stop while two
# slots remain: the current CI run may publish one release, leaving one final
# recovery slot rather than forcing a risky early label move.
SAFETY_MARGIN=31
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

  if [ "$NEWER_COUNT" -ge "$SAFETY_MARGIN" ]; then
    echo "❌ v$SENTINEL has $NEWER_COUNT newer dist/release tags; the safety margin is $SAFETY_MARGIN before the shipped $SHIPPED_TAG_BOUND-tag bound." >&2
    echo "Do not move immutable release labels blindly; use the verified bridge-and-archive procedure before old installs go silent." >&2
    FAILED=1
  fi
done

if [ "$FAILED" -ne 0 ]; then
  echo "❌ Release-tag reachability gate failed." >&2
  exit 1
fi

echo "Release-tag reachability gate passed."
