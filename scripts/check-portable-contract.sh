#!/bin/bash
set -euo pipefail

PYTHON=""
for candidate in /usr/bin/python3 /bin/python3; do
  if [ -x "$candidate" ]; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "❌ Portable-vault contract gate failed closed: trusted Python is unavailable." >&2
  exit 1
fi

if ! "$PYTHON" -I scripts/check-portable-contract.py; then
  echo "❌ Portable-vault contract gate failed." >&2
  exit 1
fi
