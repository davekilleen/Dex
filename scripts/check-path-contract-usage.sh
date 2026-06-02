#!/bin/bash
set -euo pipefail

BASE_REF="${GITHUB_BASE_REF:-main}"
git fetch origin "$BASE_REF" --depth=1 >/dev/null 2>&1 || true
MERGE_BASE="$(git merge-base HEAD "origin/$BASE_REF")"
# --diff-filter=ACMR drops deleted (D) files so we never grep a path that no
# longer exists, and never punish a PR for removing code.
CHANGED_FILES="$(git diff --name-only --diff-filter=ACMR "$MERGE_BASE...HEAD")"

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
# Bash hooks (*.sh) cannot import core.paths (Python) or paths.cjs (CJS), so the
# path-contract is enforced only on Python/CJS/TS/JS code. Shell scripts are
# allowlisted alongside the contract-source files and migrations.
ALLOWLIST='^(core/paths\.py|\.claude/hooks/paths\.cjs|\.claude/hooks/(company-context-injector|person-context-injector)\.cjs|scripts/check-path-consistency\.sh|scripts/verify-distribution\.sh|scripts/check-path-contract-usage\.sh|core/migrations/|.*\.sh$)'

VIOLATIONS=0
for file in $CODE_FILES; do
  if [[ "$file" =~ $ALLOWLIST ]]; then
    continue
  fi

  # Defensive guard in case a rename/edge-case slips a non-existent path through.
  [ -f "$file" ] || continue

  # Diff-aware: only inspect lines this PR ADDS (the '+' side of the unified
  # diff, excluding the '+++' file header). This stops the gate punishing
  # pre-existing PARA literals that already lived in a file the PR merely
  # touched, while still catching any new raw PARA literal the PR introduces.
  added="$(git diff "$MERGE_BASE...HEAD" -- "$file" \
    | grep -E '^\+' | grep -Ev '^\+\+\+' \
    | sed -E 's/^\+//' \
    | grep -nE "['\"][^'\"]*($PATTERN)[^'\"]*['\"]" || true)"
  if [ -n "$added" ]; then
    echo "Path-contract violation in $file (newly added lines):"
    echo "$added" | sed 's/^/  +/'
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
