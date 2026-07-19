#!/bin/bash
set -euo pipefail

echo "🔐 Security Gate"
echo "================"

ALLOWLIST_FILE="scripts/security-allowlist.txt"
STRICT_AUDIT="${SECURITY_STRICT_AUDIT:-0}"

SCAN_OUTPUT=$(mktemp)
trap 'rm -f "$SCAN_OUTPUT"' EXIT
if ! python3 scripts/security-scan.py "$ALLOWLIST_FILE" >"$SCAN_OUTPUT"; then
  echo "❌ Tracked-file security scan failed:"
  sed 's/^/  /' "$SCAN_OUTPUT"
  exit 1
fi
echo "✅ No high-risk secret patterns detected."

if [ "$STRICT_AUDIT" = "1" ]; then
  echo ""
  echo "Running strict dependency audits..."
  if command -v pip-audit >/dev/null 2>&1; then
    pip-audit --progress-spinner off
  else
    echo "❌ SECURITY_STRICT_AUDIT=1 but pip-audit is unavailable."
    exit 1
  fi

  if command -v npm >/dev/null 2>&1 && [ -f package-lock.json ]; then
    npm audit --omit=dev --audit-level=high
  fi
else
  echo ""
  echo "Dependency audit checks are in advisory mode (set SECURITY_STRICT_AUDIT=1 for strict mode)."
fi

echo "Security gate passed."
