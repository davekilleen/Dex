#!/bin/bash
set -euo pipefail

BASE_REF="${GITHUB_BASE_REF:-main}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Match the other PR diff gates: fetch the complete base history, then compare
# the PR head with the true merge base. A shallow base ref breaks merge-base.
git fetch origin "$BASE_REF" >/dev/null 2>&1 || true
if ! MERGE_BASE="$(git merge-base HEAD "origin/$BASE_REF")"; then
  echo "❌ check-pii.sh: cannot find a common ancestor between HEAD and origin/$BASE_REF. Your local history may be shallow — run: git fetch --unshallow origin — then retry." >&2
  exit 1
fi

PYTHONPATH="$SCRIPT_DIR/.." VAULT_PATH="$PWD" python3 "$SCRIPT_DIR/pii_gate.py" "$MERGE_BASE"
