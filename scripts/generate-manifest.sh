#!/usr/bin/env bash
# Generate the deterministic installed-files manifest from a Git tree-ish.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TREEISH="${1:-HEAD}"

exec python3 "$REPO_ROOT/core/utils/manifest.py" \
  "$TREEISH" \
  --repo-root "$REPO_ROOT" \
  --output "$REPO_ROOT/System/.installed-files.manifest"
