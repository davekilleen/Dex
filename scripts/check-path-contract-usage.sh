#!/bin/bash
set -euo pipefail

BASE_REF="${GITHUB_BASE_REF:-main}"
# Plain fetch, never --depth=1: the base ref must carry enough ancestry for the
# `git merge-base` below. A --depth=1 fetch grafts the ref with no parents, so
# merge-base can't find the common ancestor and this gate fails with the exact
# "no common ancestor" error it prints. CI checks out at fetch-depth:0, so a
# full fetch of one ref is cheap.
git fetch origin "$BASE_REF" >/dev/null 2>&1 || true
if ! MERGE_BASE="$(git merge-base HEAD "origin/$BASE_REF")"; then
  echo "❌ check-path-contract-usage.sh: cannot find a common ancestor between HEAD and origin/$BASE_REF. Your local history may be shallow — run: git fetch --unshallow origin — then retry." >&2
  exit 1
fi
# --diff-filter=ACMR drops deleted (D) files so we never grep a path that no
# longer exists, and never punish a PR for removing code.
CHANGED_FILES="$(git diff --name-only --diff-filter=ACMR "$MERGE_BASE...HEAD")"

if [ -z "$CHANGED_FILES" ]; then
  echo "No changed files detected."
  exit 0
fi

CODE_FILES="$(printf "%s\n" "$CHANGED_FILES" | grep -E '\.(py|ts|js|cjs|sh)$' | grep -Ev '(^|/)(__tests__|tests?)/' || true)"
if [ -z "$CODE_FILES" ]; then
  echo "No changed code files for path-contract policy."
  exit 0
fi

PATTERN="00-Inbox|01-Quarter_Goals|02-Week_Priorities|03-Tasks|04-Projects|05-Areas|06-Resources|07-Archives"
# Bash hooks (*.sh) cannot import core.paths (Python) or paths.cjs (CJS), so the
# path-contract is enforced only on Python/CJS/TS/JS code. Shell scripts are
# allowlisted alongside the contract-source files and migrations.
# .claude/skills/*/scripts/ are STANDALONE-BY-DESIGN: they ship inside a skill
# and run in end users' vaults where dex-core (and core.paths) is not
# installed, so they cannot import the contract. Their literals are checked
# instead by the skills' own tests against the contract JSON.
ALLOWLIST='^(core/paths\.py|\.claude/hooks/paths\.cjs|\.claude/hooks/(company-context-injector|person-context-injector)\.cjs|scripts/check-path-consistency\.sh|scripts/verify-distribution\.sh|scripts/check-path-contract-usage\.sh|core/migrations/|.*\.sh$|\.claude/skills/[a-z-]+/scripts/)'

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
