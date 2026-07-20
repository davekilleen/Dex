#!/bin/bash
set -euo pipefail

echo "🔐 Security Gate"
echo "================"

PYTHON=""
for candidate in /usr/bin/python3 /bin/python3; do
  if [ -x "$candidate" ]; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  echo "❌ Tracked-file security scan failed closed: trusted Python is unavailable." >&2
  exit 1
fi

ALLOWLIST_FILE="scripts/security-allowlist.txt"
STRICT_AUDIT="${SECURITY_STRICT_AUDIT:-0}"

if ! "$PYTHON" -I scripts/security-scan.py "$ALLOWLIST_FILE"; then
  echo "❌ Tracked-file security scan failed." >&2
  exit 1
fi
echo "✅ No high-risk secret patterns detected."

if [ "$STRICT_AUDIT" = "1" ]; then
  echo ""
  echo "Running strict dependency audits..."
  if ! "$PYTHON" -I -m pip_audit --progress-spinner off; then
    echo "❌ SECURITY_STRICT_AUDIT=1 but pip-audit is unavailable."
    exit 1
  fi

  if [ -f package-lock.json ]; then
    if [ ! -x /usr/bin/npm ]; then
      echo "❌ SECURITY_STRICT_AUDIT=1 but trusted npm is unavailable."
      exit 1
    fi
    /usr/bin/npm audit --omit=dev --audit-level=high
  fi
else
  echo ""
  echo "Dependency audit checks are in advisory mode (set SECURITY_STRICT_AUDIT=1 for strict mode)."
fi

echo "Security gate passed."
