#!/bin/bash
set -euo pipefail

REMOTE_TAGS="$(
  git ls-remote --tags origin 'refs/tags/dist/release/v*'
)"

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
  echo "❌ v$VERSION has $COUNT dist/release tags; each version may publish exactly one artifact." >&2
  FAILED=1
done <<EOF
$DUPLICATE_VERSIONS
EOF

if [ "$FAILED" -ne 0 ]; then
  echo "❌ Release-tag uniqueness gate failed: one or more versions have duplicate dist/release tags." >&2
  echo "Archive the duplicates under dist/archive/*. The likely cause is a git push --tags from a clone holding stale local tags." >&2
  exit 1
fi

echo "Release-tag uniqueness gate passed."
