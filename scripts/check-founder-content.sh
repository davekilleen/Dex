#!/bin/bash
set -euo pipefail

echo "🧹 Founder-content gate"
echo "======================="

PYTHON=""
for candidate in /usr/bin/python3 /bin/python3; do
  if [ -x "$candidate" ]; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "❌ Founder-content scan failed closed: trusted Python is unavailable." >&2
  exit 1
fi

ALLOWLIST_FILE="scripts/founder-content-allowlist.txt"

if ! "$PYTHON" -I scripts/check-founder-content.py "$ALLOWLIST_FILE"; then
  echo "❌ Founder-content gate failed." >&2
  exit 1
fi
echo "✅ No un-allowlisted founder-personal content in the tracked tree."
