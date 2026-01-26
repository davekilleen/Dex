#!/bin/bash

# Install Dex Meeting Intel Automation
# 
# Sets up the macOS Launch Agent to run Granola sync every 30 minutes.
# Run this script once to enable automatic meeting processing.
#
# Usage:
#   ./install-automation.sh          # Install and enable
#   ./install-automation.sh --remove # Uninstall
#   ./install-automation.sh --status # Check status

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_NAME="com.dex.meeting-intel.plist"
PLIST_SOURCE="$SCRIPT_DIR/$PLIST_NAME"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"
VAULT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================================"
echo "Dex Meeting Intel Automation Installer"
echo "================================================"
echo ""

# Check for required files
check_requirements() {
    echo "Checking requirements..."
    
    # Check Node.js
    if ! command -v node &> /dev/null; then
        echo -e "${RED}✗ Node.js not found${NC}"
        echo "  Install with: brew install node"
        exit 1
    fi
    echo -e "${GREEN}✓ Node.js found: $(node --version)${NC}"
    
    # Check Gemini API key
    if [ -f "$VAULT_ROOT/.env" ]; then
        if grep -q "GEMINI_API_KEY" "$VAULT_ROOT/.env"; then
            echo -e "${GREEN}✓ GEMINI_API_KEY found in .env${NC}"
        else
            echo -e "${RED}✗ GEMINI_API_KEY not found in .env${NC}"
            echo "  Add GEMINI_API_KEY=your_key to $VAULT_ROOT/.env"
            exit 1
        fi
    else
        echo -e "${RED}✗ .env file not found${NC}"
        echo "  Create $VAULT_ROOT/.env with GEMINI_API_KEY=your_key"
        exit 1
    fi
    
    # Check Granola
    if [ -f "$HOME/Library/Application Support/Granola/cache-v3.json" ]; then
        echo -e "${GREEN}✓ Granola cache found${NC}"
    else
        echo -e "${YELLOW}⚠ Granola cache not found${NC}"
        echo "  Make sure Granola app is installed and has recorded meetings"
    fi
    
    # Check sync script
    if [ -f "$SCRIPT_DIR/sync-from-granola.cjs" ]; then
        echo -e "${GREEN}✓ Sync script found${NC}"
    else
        echo -e "${RED}✗ sync-from-granola.cjs not found${NC}"
        exit 1
    fi
    
    # Check npm dependencies
    if [ -f "$VAULT_ROOT/node_modules/js-yaml/package.json" ]; then
        echo -e "${GREEN}✓ npm dependencies installed${NC}"
    else
        echo -e "${YELLOW}⚠ npm dependencies not installed${NC}"
        echo "  Run: cd $VAULT_ROOT && npm install"
    fi
    
    # Check plist
    if [ -f "$PLIST_SOURCE" ]; then
        echo -e "${GREEN}✓ Launch Agent plist found${NC}"
    else
        echo -e "${RED}✗ Launch Agent plist not found${NC}"
        exit 1
    fi
    
    echo ""
}

# Install the Launch Agent
install() {
    check_requirements
    
    echo "Installing Launch Agent..."
    
    # Create LaunchAgents directory if needed
    mkdir -p "$HOME/Library/LaunchAgents"
    
    # Create logs directory
    mkdir -p "$VAULT_ROOT/.scripts/logs"
    
    # Unload existing agent if present
    if launchctl list | grep -q "com.dex.meeting-intel"; then
        echo "  Unloading existing agent..."
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
    fi
    
    # Copy plist with VAULT_ROOT replaced
    echo "  Copying plist to ~/Library/LaunchAgents/"
    sed "s|VAULT_ROOT|$VAULT_ROOT|g" "$PLIST_SOURCE" > "$PLIST_DEST"
    
    # Set permissions
    chmod 644 "$PLIST_DEST"
    
    # Load the agent
    echo "  Loading Launch Agent..."
    launchctl load "$PLIST_DEST"
    
    # Verify
    if launchctl list | grep -q "com.dex.meeting-intel"; then
        echo ""
        echo -e "${GREEN}✓ Dex Meeting Intel automation installed successfully!${NC}"
        echo ""
        echo "The sync will run:"
        echo "  • Every 30 minutes while your laptop is awake"
        echo "  • Immediately when you log in"
        echo ""
        echo "Logs are written to:"
        echo "  • $VAULT_ROOT/.scripts/logs/meeting-intel.log"
        echo "  • $VAULT_ROOT/.scripts/logs/meeting-intel.stdout.log"
        echo "  • $VAULT_ROOT/.scripts/logs/meeting-intel.stderr.log"
        echo ""
        echo "To manually trigger a sync:"
        echo "  node $SCRIPT_DIR/sync-from-granola.cjs"
        echo ""
        echo "To check status:"
        echo "  ./install-automation.sh --status"
    else
        echo -e "${RED}✗ Failed to load Launch Agent${NC}"
        exit 1
    fi
}

# Remove the Launch Agent
remove() {
    echo "Removing Launch Agent..."
    
    if launchctl list | grep -q "com.dex.meeting-intel"; then
        echo "  Unloading agent..."
        launchctl unload "$PLIST_DEST" 2>/dev/null || true
    fi
    
    if [ -f "$PLIST_DEST" ]; then
        echo "  Removing plist..."
        rm "$PLIST_DEST"
    fi
    
    echo -e "${GREEN}✓ Dex Meeting Intel automation removed${NC}"
}

# Check status
status() {
    echo "Dex Meeting Intel Automation Status"
    echo "------------------------------------"
    
    if [ -f "$PLIST_DEST" ]; then
        echo -e "Plist installed: ${GREEN}Yes${NC}"
    else
        echo -e "Plist installed: ${RED}No${NC}"
    fi
    
    if launchctl list | grep -q "com.dex.meeting-intel"; then
        echo -e "Agent loaded: ${GREEN}Yes${NC}"
        
        # Get last run info from log
        if [ -f "$VAULT_ROOT/.scripts/logs/meeting-intel.log" ]; then
            last_run=$(tail -1 "$VAULT_ROOT/.scripts/logs/meeting-intel.log" | head -c 25)
            echo "Last activity: $last_run"
        fi
    else
        echo -e "Agent loaded: ${RED}No${NC}"
    fi
    
    # Check state file
    if [ -f "$SCRIPT_DIR/processed-meetings.json" ]; then
        count=$(grep -o '"processedMeetings"' "$SCRIPT_DIR/processed-meetings.json" | wc -l)
        last_sync=$(grep '"lastSync"' "$SCRIPT_DIR/processed-meetings.json" | head -1 | sed 's/.*: "\([^"]*\)".*/\1/')
        echo "Last sync: $last_sync"
        meetings_count=$(grep -o '"title"' "$SCRIPT_DIR/processed-meetings.json" | wc -l)
        echo "Meetings processed: $meetings_count"
    fi
    
    echo ""
    echo "Manual commands:"
    echo "  Run now:    node $SCRIPT_DIR/sync-from-granola.cjs"
    echo "  Dry run:    node $SCRIPT_DIR/sync-from-granola.cjs --dry-run"
    echo "  View logs:  tail -f $VAULT_ROOT/.scripts/logs/meeting-intel.log"
}

# Parse arguments
case "${1:-}" in
    --remove|-r)
        remove
        ;;
    --status|-s)
        status
        ;;
    --help|-h)
        echo "Usage: $0 [--remove|--status|--help]"
        echo ""
        echo "Options:"
        echo "  (no args)   Install and enable automation"
        echo "  --remove    Uninstall automation"
        echo "  --status    Check automation status"
        echo "  --help      Show this help"
        ;;
    *)
        install
        ;;
esac
