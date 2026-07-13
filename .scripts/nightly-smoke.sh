#!/bin/bash

set -e

VAULT_PATH=""
BREADCRUMB="$HOME/.config/dex/vault-path"
if [ -f "$BREADCRUMB" ]; then
    VAULT_PATH="$(tr -d '[:space:]' < "$BREADCRUMB")"
fi

if [ -z "$VAULT_PATH" ] || [ ! -d "$VAULT_PATH" ]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    VAULT_PATH="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

if [ -x "$VAULT_PATH/.venv/bin/python" ]; then
    PYTHON="$VAULT_PATH/.venv/bin/python"
else
    PYTHON="python3"
fi

cd "$VAULT_PATH"
set +e
VAULT_PATH="$VAULT_PATH" "$PYTHON" core/utils/smoke.py --json --ledger
SMOKE_STATUS=$?
set -e

if [ -f "System/.smoke-last-run.json" ]; then
    "$PYTHON" core/utils/health_telemetry.py \
        --report "System/.smoke-last-run.json" \
        --vault "$VAULT_PATH" \
        --repo "$VAULT_PATH" \
        --channel "stable" >/dev/null 2>&1 || true
fi

if [ "$SMOKE_STATUS" -ne 0 ]; then
    exit "$SMOKE_STATUS"
fi

mkdir -p .scripts/logs
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] nightly smoke completed" >> .scripts/logs/smoke-nightly.log
