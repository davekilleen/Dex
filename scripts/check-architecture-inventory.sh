#!/bin/bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
INVENTORY_PATH="${ARCHITECTURE_INVENTORY_PATH:-$REPO_ROOT/docs/architecture/INVENTORY.md}"
TEMP_FILE="$(mktemp "${TMPDIR:-/tmp}/dex-architecture-inventory.XXXXXX")"
trap 'rm -f "$TEMP_FILE"' EXIT

cd "$REPO_ROOT"
python3 scripts/generate-architecture-inventory.py --output "$TEMP_FILE" >/dev/null

if [ ! -f "$INVENTORY_PATH" ]; then
  echo "❌ Architecture inventory drift gate failed: $INVENTORY_PATH is missing." >&2
  echo "Run scripts/generate-architecture-inventory.py and commit the result." >&2
  exit 1
fi

if ! diff -u "$INVENTORY_PATH" "$TEMP_FILE"; then
  echo "❌ Architecture inventory drift detected." >&2
  echo "To refresh it, run scripts/generate-architecture-inventory.py and commit the result." >&2
  exit 1
fi

echo "Architecture inventory is current."
