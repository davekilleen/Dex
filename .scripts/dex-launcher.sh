#!/bin/bash
# Dex Launcher - Resilient wrapper for background launch agents
#
# Instead of hardcoding vault paths in plists, agents call this wrapper
# which resolves the vault path at runtime and validates it exists.
#
# Usage (in plist ProgramArguments):
#   dex-launcher.sh <script-relative-path> [args...]
#
# Example:
#   dex-launcher.sh .scripts/meeting-intel/sync-from-granola.cjs
#
# Path resolution (in order):
#   1. ~/.config/dex/vault-path (written at install time)
#   2. Derive from this script's own location (fallback)

set -e

SCRIPT_NAME="$1"
shift

# --- Resolve vault path ---

VAULT_PATH=""

# Method 1: Breadcrumb file (primary)
BREADCRUMB="$HOME/.config/dex/vault-path"
if [ -f "$BREADCRUMB" ]; then
    VAULT_PATH="$(cat "$BREADCRUMB" | tr -d '[:space:]')"
fi

# Method 2: Derive from this script's location (fallback)
if [ -z "$VAULT_PATH" ] || [ ! -d "$VAULT_PATH" ]; then
    SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
    # This script lives at <vault>/.scripts/dex-launcher.sh
    VAULT_PATH="$(cd "$SELF_DIR/.." && pwd)"
fi

# --- Validate ---

TARGET="$VAULT_PATH/$SCRIPT_NAME"

if [ ! -d "$VAULT_PATH" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Vault path does not exist: $VAULT_PATH" >&2
    echo "  Update $BREADCRUMB with the correct path, or re-run install-automation.sh" >&2
    exit 1
fi

if [ ! -f "$TARGET" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Script not found: $TARGET" >&2
    echo "  Vault path: $VAULT_PATH" >&2
    echo "  Script: $SCRIPT_NAME" >&2
    exit 1
fi

# --- Find Node.js ---

NODE_PATH=""
if command -v node &> /dev/null; then
    NODE_PATH="$(command -v node)"
elif [ -x "/opt/homebrew/bin/node" ]; then
    NODE_PATH="/opt/homebrew/bin/node"
elif [ -x "/usr/local/bin/node" ]; then
    NODE_PATH="/usr/local/bin/node"
fi

if [ -z "$NODE_PATH" ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: Node.js not found" >&2
    exit 1
fi

# --- Run ---

cd "$VAULT_PATH"
exec "$NODE_PATH" "$TARGET" "$@"
