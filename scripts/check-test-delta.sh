#!/bin/bash
set -euo pipefail

BASE_REF="${GITHUB_BASE_REF:-main}"
git fetch origin "$BASE_REF" --depth=1 >/dev/null 2>&1 || true
MERGE_BASE="$(git merge-base HEAD "origin/$BASE_REF")"
# --diff-filter=ACMR drops deleted (D) files: removing dead code should not
# require adding a test.
CHANGED_FILES="$(git diff --name-only --diff-filter=ACMR "$MERGE_BASE...HEAD")"

if [ -z "$CHANGED_FILES" ]; then
  echo "No changed files detected."
  exit 0
fi

SOURCE_CHANGED="$(printf "%s\n" "$CHANGED_FILES" | \
  grep -E '^(core/.*\.py|pi-extensions/.*\.(js|cjs|ts)|\.claude/hooks/.*\.(js|cjs))$' | \
  grep -Ev '^(core/tests/|core/mcp/tests/)|(^|/)test_.*\.py$|(^|/).+_test\.py$' || true)"

TEST_CHANGED="$(printf "%s\n" "$CHANGED_FILES" | \
  grep -E '^(core/tests/|core/mcp/tests/)|(^|/)test_.*\.py$|(^|/).+_test\.py$' || true)"

if [ -z "$SOURCE_CHANGED" ]; then
  echo "No production-source delta requiring test changes."
  exit 0
fi

if [ -n "$TEST_CHANGED" ]; then
  echo "Test delta check passed."
  exit 0
fi

# Advisory only: warn, never block. Quality relies on reviewer judgment.
echo "::warning::Source changed without test updates (advisory). Consider adding or updating tests."
echo "Changed source files:"
printf "%s\n" "$SOURCE_CHANGED"
exit 0
