#!/bin/bash
set -euo pipefail

# Every release at or below this version was published before this uniqueness
# guard existed, so duplicate tags there are history rather than a CI failure.
HISTORICAL_VERSION_THRESHOLD="1.77.1"

REMOTE_TAGS="$(
  git ls-remote --tags origin 'refs/tags/dist/release/v*'
)"

version_is_at_or_below_threshold() {
  local version="$1"
  local threshold="$2"
  local version_major version_minor version_patch
  local threshold_major threshold_minor threshold_patch

  IFS=. read -r version_major version_minor version_patch <<<"$version"
  IFS=. read -r threshold_major threshold_minor threshold_patch <<<"$threshold"

  if ((version_major != threshold_major)); then
    ((version_major < threshold_major))
    return
  fi
  if ((version_minor != threshold_minor)); then
    ((version_minor < threshold_minor))
    return
  fi
  ((version_patch <= threshold_patch))
}

# Annotated tags also produce a peeled ^{} ref; count only the tag ref itself.
DUPLICATE_VERSIONS="$(
  printf '%s\n' "$REMOTE_TAGS" |
    awk '
      $2 !~ /\^\{\}$/ &&
      $2 ~ /^refs\/tags\/dist\/release\/v[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]+$/ {
        version = $2
        sub(/^refs\/tags\/dist\/release\/v/, "", version)
        sub(/-[0-9a-f]+$/, "", version)
        counts[version]++
      }
      END {
        for (version in counts) {
          if (counts[version] > 1) {
            print version, counts[version]
          }
        }
      }
    ' |
    sort
)"

FAILED=0
while read -r VERSION COUNT; do
  [ -n "${VERSION:-}" ] || continue
  if version_is_at_or_below_threshold "$VERSION" "$HISTORICAL_VERSION_THRESHOLD"; then
    echo "Historical exception: v$VERSION has $COUNT release tags; it is at or below v$HISTORICAL_VERSION_THRESHOLD and predates the uniqueness guard."
  else
    echo "❌ v$VERSION has $COUNT dist/release tags; each version may publish exactly one artifact." >&2
    FAILED=1
  fi
done <<EOF
$DUPLICATE_VERSIONS
EOF

if [ "$FAILED" -ne 0 ]; then
  echo "❌ Release-tag uniqueness gate failed. Bump the version before publishing another artifact." >&2
  exit 1
fi

echo "Release-tag uniqueness gate passed."
