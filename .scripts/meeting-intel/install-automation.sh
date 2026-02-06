#!/bin/bash

# Dex Meeting Intel - Background Automation Installer
#
# This script sets up a macOS Launch Agent to automatically sync meetings
# from Granola every 30 minutes. No terminal commands visible during /process-meetings.
#
# Usage:
#   ./install-automation.sh          # Install and start
#   ./install-automation.sh --status # Check status
#   ./install-automation.sh --stop   # Stop and uninstall

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_PATH="$(cd "$SCRIPT_DIR/../.." && pwd)"
PLIST_NAME="com.dex.meeting-intel"
PLIST_TEMPLATE="$SCRIPT_DIR/$PLIST_NAME.plist.template"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$VAULT_PATH/.scripts/logs"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║   Dex Meeting Intel - Background Sync      ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Find Node.js path
find_node() {
    if command -v node &> /dev/null; then
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

# Check status
if [ "$1" = "--status" ]; then
    echo "Checking status..."
    echo ""

    if [ -f "$PLIST_DEST" ]; then
        echo -e "${GREEN}✓${NC} Launch Agent installed at: $PLIST_DEST"
    else
        echo -e "${YELLOW}○${NC} Launch Agent not installed"
    fi

    if launchctl list | grep -q "$PLIST_NAME"; then
        echo -e "${GREEN}✓${NC} Launch Agent is running"
        echo ""
        echo "Recent activity (last 10 lines):"
        tail -10 "$LOG_DIR/meeting-intel.stdout.log" 2>/dev/null || echo "  No logs yet"
    else
        echo -e "${YELLOW}○${NC} Launch Agent is not running"
    fi

    echo ""
    exit 0
fi

# Stop and uninstall
if [ "$1" = "--stop" ] || [ "$1" = "--uninstall" ]; then
    echo "Stopping and uninstalling..."

    if launchctl list | grep -q "$PLIST_NAME"; then
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
        echo -e "${GREEN}✓${NC} Stopped Launch Agent"
    fi

    if [ -f "$PLIST_DEST" ]; then
        rm "$PLIST_DEST"
        echo -e "${GREEN}✓${NC} Removed Launch Agent"
    fi

    echo -e "${GREEN}Done!${NC} Background sync disabled."
    echo ""
    exit 0
fi

# Installation
echo "Installing background sync..."
echo ""

# Check prerequisites
echo "Checking prerequisites..."

if [ -z "$NODE_PATH" ]; then
    echo -e "${RED}✗${NC} Node.js not found. Please install Node.js first."
    exit 1
fi
echo -e "${GREEN}✓${NC} Node.js found at: $NODE_PATH"

if [ ! -f "$VAULT_PATH/.env" ]; then
    echo -e "${YELLOW}!${NC} Warning: .env file not found. Make sure GEMINI_API_KEY (or another LLM key) is set."
fi

# Check for Granola
GRANOLA_CACHE="$HOME/Library/Application Support/Granola/cache-v3.json"
if [ -f "$GRANOLA_CACHE" ]; then
    echo -e "${GREEN}✓${NC} Granola cache found"
else
    echo -e "${YELLOW}!${NC} Granola cache not found. Install Granola and record a meeting first."
fi

# Create logs directory
mkdir -p "$LOG_DIR"
echo -e "${GREEN}✓${NC} Log directory ready"

# Create LaunchAgents directory if needed
mkdir -p "$HOME/Library/LaunchAgents"

# Generate plist from template
echo ""
echo "Generating Launch Agent configuration..."

if [ ! -f "$PLIST_TEMPLATE" ]; then
    echo -e "${RED}✗${NC} Template not found: $PLIST_TEMPLATE"
    exit 1
fi

# Replace placeholders
sed -e "s|__NODE_PATH__|$NODE_PATH|g" \
    -e "s|__VAULT_PATH__|$VAULT_PATH|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DEST"

echo -e "${GREEN}✓${NC} Created: $PLIST_DEST"

# Unload if already loaded (to pick up changes)
if launchctl list | grep -q "$PLIST_NAME"; then
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi

# Load the Launch Agent
launchctl load "$PLIST_DEST"
echo -e "${GREEN}✓${NC} Launch Agent started"

# Verify it's running
sleep 1
if launchctl list | grep -q "$PLIST_NAME"; then
    echo -e "${GREEN}✓${NC} Verified: Launch Agent is running"
else
    echo -e "${RED}✗${NC} Launch Agent failed to start. Check logs at:"
    echo "    $LOG_DIR/meeting-intel.stderr.log"
    exit 1
fi

echo ""
echo "════════════════════════════════════════════"
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "What happens now:"
echo "  • Meetings sync automatically every 30 minutes"
echo "  • Also syncs when you log in or wake your laptop"
echo "  • /process-meetings now reads synced files (no terminal output)"
echo ""
echo "Commands:"
echo "  ./install-automation.sh --status    Check if running"
echo "  ./install-automation.sh --stop      Disable background sync"
echo ""
echo "Logs:"
echo "  $LOG_DIR/meeting-intel.stdout.log"
echo "════════════════════════════════════════════"
echo ""
