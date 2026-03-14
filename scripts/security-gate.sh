#!/bin/bash
set -euo pipefail

echo "🔐 Security Gate"
echo "================"

SECRET_PATTERNS='(lin_api_[A-Za-z0-9]{20,}|sk-ant-api[0-9A-Za-z_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY-----)'
ALLOWLIST_FILE="scripts/security-allowlist.txt"
STRICT_AUDIT="${SECURITY_STRICT_AUDIT:-0}"

MATCHES=$(git ls-files | xargs grep -nE "$SECRET_PATTERNS" 2>/dev/null || true)
if [ -n "$MATCHES" ] && [ -f "$ALLOWLIST_FILE" ]; then
  while IFS= read -r rule; do
    [ -z "$rule" ] && continue
    [[ "$rule" =~ ^# ]] && continue
    MATCHES=$(printf "%s\n" "$MATCHES" | grep -Ev "$rule" || true)
  done < "$ALLOWLIST_FILE"
fi

if [ -n "$MATCHES" ]; then
  echo "❌ Potential secret leakage detected:"
  printf "%s\n" "$MATCHES" | sed 's/^/  /'
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
