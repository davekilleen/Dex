#!/bin/bash
set -euo pipefail

BASE_REF="${GITHUB_BASE_REF:-main}"
git fetch origin "$BASE_REF" --depth=1 >/dev/null 2>&1 || true
MERGE_BASE="$(git merge-base HEAD "origin/$BASE_REF")"
CHANGED_FILES="$(git diff --name-only "$MERGE_BASE...HEAD")"

if [ -z "$CHANGED_FILES" ]; then
  echo "No changed files detected."
  exit 0
fi

CODE_FILES="$(printf "%s\n" "$CHANGED_FILES" | grep -E '\.(py|ts|js|cjs|sh)$' | grep -Ev '(^|/)tests?/' || true)"
if [ -z "$CODE_FILES" ]; then
  echo "No changed code files for path-contract policy."
  exit 0
fi

PATTERN="00-Inbox|01-Quarter_Goals|02-Week_Priorities|03-Tasks|04-Projects|05-Areas|06-Resources|07-Archives"
ALLOWLIST='^(core/paths\.py|\.claude/hooks/paths\.cjs|\.claude/hooks/(company-context-injector|person-context-injector)\.cjs|scripts/check-path-consistency\.sh|scripts/verify-distribution\.sh|scripts/check-path-contract-usage\.sh|core/migrations/)'

VIOLATIONS=0
for file in $CODE_FILES; do
  if [[ "$file" =~ $ALLOWLIST ]]; then
    continue
  fi

  matches="$(grep -nE "['\"][^'\"]*($PATTERN)[^'\"]*['\"]" "$file" || true)"
  if [ -n "$matches" ]; then
    echo "Path-contract violation in $file:"
    echo "$matches" | sed 's/^/  /'
    VIOLATIONS=$((VIOLATIONS + 1))
  fi
done

if [ "$VIOLATIONS" -gt 0 ]; then
  echo ""
  echo "Found $VIOLATIONS path-contract usage violation(s)."
  echo "Use constants from core.paths (Python) or .claude/hooks/paths.cjs (CJS) instead of raw PARA literals."
  exit 1
fi

echo "Path-contract usage check passed."
