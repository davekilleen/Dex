#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_PATH="$(cd "$SCRIPT_DIR/.." && pwd)"
PLIST_NAME="com.dex.week-priority-sync"
PLIST_TEMPLATE="$SCRIPT_DIR/$PLIST_NAME.plist.template"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$VAULT_PATH/.scripts/logs"

find_node() {
  if command -v node >/dev/null 2>&1; then
    which node
  elif [ -f "/opt/homebrew/bin/node" ]; then
    echo "/opt/homebrew/bin/node"
  elif [ -f "/usr/local/bin/node" ]; then
    echo "/usr/local/bin/node"
  else
    echo ""
  fi
}

NODE_PATH=$(find_node)
if [ -z "$NODE_PATH" ]; then
  echo "Node.js not found."
  exit 1
fi

if [ "$1" = "--status" ]; then
  if launchctl list | grep -q "$PLIST_NAME"; then
    echo "running"
  else
    echo "not-running"
  fi
  exit 0
fi

if [ "$1" = "--stop" ] || [ "$1" = "--uninstall" ]; then
  launchctl unload "$PLIST_DEST" 2>/dev/null || true
  rm -f "$PLIST_DEST"
  echo "stopped"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

sed -e "s|__NODE_PATH__|$NODE_PATH|g" \
    -e "s|__VAULT_PATH__|$VAULT_PATH|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DEST"

launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"
echo "installed"
