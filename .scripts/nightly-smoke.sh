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

# Make node discoverable, the same way PYTHON is resolved above.
#
# smoke.py syntax-checks Dex's .cjs hooks with node, and finds node by looking
# on the inherited PATH. launchd hands a scheduled job a minimal PATH that does
# not include either Homebrew prefix, so on a normal Mac node is invisible here
# even though it works in every terminal. The hooks journey then reports
# UNKNOWN rather than BROKEN, so nightly hook checking can be dead for months
# without anything looking wrong.
#
# Appending is deliberate: anything already on PATH keeps priority, and the
# validated-tool checks in core/utils/release_channel.py still decide what is
# safe to use. This only widens where node may be found, never what is trusted.
if ! command -v node >/dev/null 2>&1; then
    for NODE_DIR in /opt/homebrew/bin /usr/local/bin; do
        if [ -x "$NODE_DIR/node" ]; then
            PATH="$PATH:$NODE_DIR"
            export PATH
            break
        fi
    done
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

# Record completion separately from the report. SessionStart requires both a
# clean report and this post-success marker, so an interrupted/partial run can
# never suppress the next retry.
SUCCESS_MARKER="System/.dex/session-health-success.json"
SUCCESS_TEMP="System/.dex/.session-health-success.$$.json"
trap 'rm -f "$SUCCESS_TEMP"' EXIT
mkdir -p "$(dirname "$SUCCESS_MARKER")"
printf '{"schema_version":1,"local_date":"%s","completed_at":"%s"}\n' \
    "$(date +%Y-%m-%d)" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SUCCESS_TEMP"
mv "$SUCCESS_TEMP" "$SUCCESS_MARKER"
trap - EXIT
