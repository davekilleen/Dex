#!/usr/bin/env bash
# Generate the deterministic installed-files manifest from a Git tree-ish.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TREEISH="${1:-HEAD}"

# Validate the exact requested tree before the manifest writer can touch output.
python3 "$REPO_ROOT/scripts/check-tau-removal.py" \
  --repo-root "$REPO_ROOT" \
  --git-source "$TREEISH"

exec python3 "$REPO_ROOT/core/utils/manifest.py" \
  "$TREEISH" \
  --repo-root "$REPO_ROOT" \
  --output "$REPO_ROOT/System/.installed-files.manifest"
