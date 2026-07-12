#!/bin/bash
set -euo pipefail

BASE_REF="${GITHUB_BASE_REF:-main}"
if [ -n "${GITHUB_ACTIONS:-}" ]; then
  git fetch origin "$BASE_REF" --depth=1 >/dev/null 2>&1 || true
else
  git fetch origin "$BASE_REF" >/dev/null 2>&1 || true
fi
if ! MERGE_BASE="$(git merge-base HEAD "origin/$BASE_REF")"; then
  echo "❌ check-doc-drift.sh: cannot find a common ancestor between HEAD and origin/$BASE_REF. Your local history may be shallow — run: git fetch --unshallow origin — then retry." >&2
  exit 1
fi
# --diff-filter=ACMR drops deleted (D) files: removing code should not require
# a doc change.
CHANGED_FILES="$(git diff --name-only --diff-filter=ACMR "$MERGE_BASE...HEAD")"

if [ -z "$CHANGED_FILES" ]; then
  echo "No changed files detected."
  exit 0
fi

SOURCE_CHANGED="$(printf "%s\n" "$CHANGED_FILES" | \
  grep -E '^(core/.*\.py|\.claude/hooks/.*\.(js|cjs))$' | \
  grep -Ev '^(core/tests/|core/mcp/tests/)' || true)"

DOC_CHANGED="$(printf "%s\n" "$CHANGED_FILES" | \
  grep -E '^(docs/|System/PRDs/)|^(README\.md|CHANGELOG\.md|CONTRIBUTING\.md)$' || true)"

if [ -z "$SOURCE_CHANGED" ]; then
  echo "No production-source delta requiring docs review."
  exit 0
fi

if [ -n "$DOC_CHANGED" ]; then
  echo "Doc drift check passed."
  exit 0
fi

# Advisory only: warn, never block. Quality relies on reviewer judgment.
echo "::warning::Source changed without doc updates (advisory). Consider updating docs/, System/PRDs/, README, CHANGELOG, or CONTRIBUTING."
echo "Changed source files:"
printf "%s\n" "$SOURCE_CHANGED"
exit 0
