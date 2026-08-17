#!/bin/bash
set -euo pipefail

if ! REMOTE_TAGS="$(
  git ls-remote --tags origin 'refs/tags/dist/release/v*'
)"; then
  echo "❌ Release-tag uniqueness gate failed: could not read dist/release tags from origin; git ls-remote failed." >&2
  exit 1
fi
if [ -z "$REMOTE_TAGS" ]; then
  echo "❌ Release-tag uniqueness gate failed: origin returned no readable dist/release tags, so uniqueness cannot be verified." >&2
  exit 1
fi

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

# dist/archive tags are the historic fleet's starting points. Discovery
# (scripts/release_fleet.py ARCHIVE_RELEASE_TAG) accepts a 7-64 hex suffix, but
# the executor (scripts/release_fleet_executor.py _ARCHIVE_RELEASE_TAG) requires
# exactly 7 and raises "starting release identity is malformed" per journey,
# hours into the 4.5h historic-fleet-darwin run. Catch it here in seconds.
#
# Discovery de-duplicates journeys by tree, so a non-canonical tag that has a
# canonical twin at the same commit is already shadowed and can never be picked
# as a starting point. Fail only on a lone non-canonical tag.
if ! ARCHIVE_TAGS="$(
  git ls-remote --tags origin 'refs/tags/dist/archive/v*'
)"; then
  echo "❌ Release-tag uniqueness gate failed: could not read dist/archive tags from origin; git ls-remote failed." >&2
  exit 1
fi

UNTWINNED_ARCHIVE_TAGS="$(
  printf '%s\n' "$ARCHIVE_TAGS" |
    awk '
      # An annotated tags peeled ^{} ref carries the commit the tag resolves
      # to; the bare ref carries the tag object. Prefer the peeled value so
      # twins pointing at one commit compare equal.
      {
        ref = $2
        peeled = (ref ~ /\^\{\}$/)
        sub(/\^\{\}$/, "", ref)
        if (ref !~ /^refs\/tags\/dist\/archive\/v[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]+$/) {
          next
        }
        if (peeled || !(ref in commit)) {
          commit[ref] = $1
        }
      }
      END {
        for (ref in commit) {
          if (ref ~ /^refs\/tags\/dist\/archive\/v[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{7}$/) {
            canonical[commit[ref]] = 1
          }
        }
        for (ref in commit) {
          if (ref ~ /^refs\/tags\/dist\/archive\/v[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{7}$/) {
            continue
          }
          if (commit[ref] in canonical) {
            continue
          }
          tag = ref
          sub(/^refs\/tags\//, "", tag)
          print tag, commit[ref]
        }
      }
    ' |
    sort
)"

ARCHIVE_FAILED=0
while read -r TAG COMMIT; do
  [ -n "${TAG:-}" ] || continue
  ARCHIVE_VERSION="${TAG#dist/archive/v}"
  ARCHIVE_VERSION="${ARCHIVE_VERSION%%-*}"
  CANONICAL_SHORT="$(printf '%s' "$COMMIT" | cut -c1-7)"
  echo "❌ $TAG (commit $COMMIT) is a non-canonical dist/archive tag with no canonical twin at that commit." >&2
  echo "The fleet executor requires exactly 7 hex characters in a dist/archive tag, so this start fails hours into historic-fleet-darwin." >&2
  echo "Remedy: create dist/archive/v$ARCHIVE_VERSION-$CANONICAL_SHORT at $COMMIT. Delete nothing — the existing tag stays, and discovery's tree de-duplication will shadow it." >&2
  ARCHIVE_FAILED=1
done <<EOF
$UNTWINNED_ARCHIVE_TAGS
EOF

if [ "$ARCHIVE_FAILED" -ne 0 ]; then
  echo "❌ Release-tag uniqueness gate failed: one or more dist/archive tags are non-canonical with no canonical twin." >&2
  exit 1
fi

echo "Release-tag uniqueness gate passed."
