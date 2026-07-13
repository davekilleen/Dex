#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_PATH="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_NAME="com.dex.smoke-nightly"
PLIST_TEMPLATE="$SCRIPT_DIR/$PLIST_NAME.plist.template"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

launchctl_list() { launchctl list; }
launchctl_load() { launchctl load "$1"; }
launchctl_unload() { launchctl unload "$1"; }
is_loaded() { launchctl_list 2>/dev/null | grep -q "$PLIST_NAME"; }

if [ "${1:-}" = "--status" ]; then
    if [ -f "$PLIST_DEST" ]; then
        echo "Nightly smoke automation is installed."
    else
        echo "Nightly smoke automation is not installed."
    fi
    if is_loaded; then
        echo "Launch Agent is loaded."
    else
        echo "Launch Agent is not loaded."
    fi
    exit 0
fi

if [ "${1:-}" = "--uninstall" ]; then
    if is_loaded; then
        launchctl_unload "$PLIST_DEST" 2>/dev/null || true
    fi
    if [ -f "$PLIST_DEST" ]; then
        rm "$PLIST_DEST"
    fi
    echo "Nightly smoke automation uninstalled."
    exit 0
fi

if [ "${1:-}" != "" ]; then
    echo "Usage: $0 [--status|--uninstall]" >&2
    exit 2
fi

mkdir -p "$HOME/.config/dex" "$HOME/Library/LaunchAgents" "$VAULT_PATH/.scripts/logs"
echo "$VAULT_PATH" > "$HOME/.config/dex/vault-path"
chmod +x "$VAULT_PATH/.scripts/nightly-smoke.sh"
sed "s|__VAULT_PATH__|$VAULT_PATH|g" "$PLIST_TEMPLATE" > "$PLIST_DEST"

if is_loaded; then
    launchctl_unload "$PLIST_DEST" 2>/dev/null || true
fi
launchctl_load "$PLIST_DEST"
echo "Nightly smoke automation installed."
