#!/bin/bash
# Dex Customer Intelligence — Monthly Report Automation
#
# Installs a macOS Launch Agent that auto-generates a customer intelligence
# report on the 1st of every month at 8 AM. Report saved to Inbox/Reports/.
#
# Usage:
#   ./install-automation.sh           # Install and activate
#   ./install-automation.sh --status  # Check status
#   ./install-automation.sh --run     # Run report now (test)
#   ./install-automation.sh --stop    # Uninstall

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_PATH="$(cd "$SCRIPT_DIR/../.." && pwd)"
PLIST_NAME="com.dex.customer-intel"
PLIST_TEMPLATE="$SCRIPT_DIR/$PLIST_NAME.plist.template"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$VAULT_PATH/.scripts/logs"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║   Dex Customer Intelligence — Automation   ║"
echo "╚════════════════════════════════════════════╝"
echo ""

find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" &>/dev/null; then
            echo "$(command -v "$candidate")"
            return
        fi
    done
    echo ""
}

PYTHON_PATH=$(find_python)

# ── Status ────────────────────────────────────────────────────────────────────

if [ "$1" = "--status" ]; then
    echo "Status check..."
    echo ""

    if [ -f "$PLIST_DEST" ]; then
        echo -e "${GREEN}✓${NC} Launch Agent installed: $PLIST_DEST"
    else
        echo -e "${YELLOW}○${NC} Launch Agent not installed"
    fi

    if launchctl list 2>/dev/null | grep -q "$PLIST_NAME"; then
        echo -e "${GREEN}✓${NC} Agent is running"
    else
        echo -e "${YELLOW}○${NC} Agent not loaded"
    fi

    REPORTS_DIR="$VAULT_PATH/Inbox/Reports"
    if ls "$REPORTS_DIR"/Customer_Intel_*.md 2>/dev/null | head -1 | grep -q .; then
        LATEST=$(ls -t "$REPORTS_DIR"/Customer_Intel_*.md | head -1)
        echo -e "${GREEN}✓${NC} Latest report: $LATEST"
    else
        echo -e "${YELLOW}○${NC} No reports generated yet"
    fi

    if [ -f "$LOG_DIR/customer-intel.stderr.log" ]; then
        echo ""
        echo "Last log lines:"
        tail -5 "$LOG_DIR/customer-intel.stderr.log" 2>/dev/null || true
    fi

    echo ""
    echo "Next scheduled run: 1st of next month at 8:00 AM"
    exit 0
fi

# ── Stop / Uninstall ──────────────────────────────────────────────────────────

if [ "$1" = "--stop" ]; then
    echo "Stopping automation..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
    rm -f "$PLIST_DEST"
    echo -e "${GREEN}✓${NC} Automation stopped and uninstalled."
    exit 0
fi

# ── Run now (test) ────────────────────────────────────────────────────────────

if [ "$1" = "--run" ]; then
    echo "Running report now..."
    echo ""

    if [ -z "$PYTHON_PATH" ]; then
        echo -e "${RED}✗${NC} Python not found. Install Python 3.10+."
        exit 1
    fi

    mkdir -p "$LOG_DIR"
    export VAULT_PATH="$VAULT_PATH"

    OUTPUT=$("$PYTHON_PATH" "$SCRIPT_DIR/generate-report.py" 2>&1 >/dev/null && \
             "$PYTHON_PATH" "$SCRIPT_DIR/generate-report.py" 2>/dev/null || true)

    # Run for real and capture output path
    REPORT_PATH=$("$PYTHON_PATH" "$SCRIPT_DIR/generate-report.py" 2>"$LOG_DIR/customer-intel.stderr.log")

    if [ -n "$REPORT_PATH" ] && [ -f "$REPORT_PATH" ]; then
        echo -e "${GREEN}✓${NC} Report generated: $REPORT_PATH"
        echo ""
        echo "Open it in Dex or run: cat '$REPORT_PATH'"
    else
        echo -e "${RED}✗${NC} Report generation failed. Check log:"
        cat "$LOG_DIR/customer-intel.stderr.log"
        exit 1
    fi
    exit 0
fi

# ── Install ───────────────────────────────────────────────────────────────────

echo "Installing monthly Customer Intelligence automation..."
echo ""

# Validate prerequisites
if [ -z "$PYTHON_PATH" ]; then
    echo -e "${RED}✗${NC} Python not found. Install Python 3.10+."
    exit 1
fi
echo -e "${GREEN}✓${NC} Python found: $PYTHON_PATH"

# Check SF tokens exist
SF_TOKENS="$HOME/.claude/sf_tokens.json"
if [ ! -f "$SF_TOKENS" ]; then
    echo -e "${RED}✗${NC} Salesforce not authenticated."
    echo "   Run sf_authenticate from Dex first, then re-run this installer."
    exit 1
fi
echo -e "${GREEN}✓${NC} Salesforce tokens found"

# Create log directory
mkdir -p "$LOG_DIR"
echo -e "${GREEN}✓${NC} Log directory: $LOG_DIR"

# Read SF credentials (from .mcp.json or environment)
SF_CLIENT_ID="${SF_CLIENT_ID:-}"
SF_CLIENT_SECRET="${SF_CLIENT_SECRET:-}"

# Try to read from .mcp.json if not set
if [ -z "$SF_CLIENT_ID" ] && [ -f "$VAULT_PATH/.mcp.json" ]; then
    SF_CLIENT_ID=$(python3 -c "
import json, sys
try:
    data = json.load(open('$VAULT_PATH/.mcp.json'))
    servers = data.get('mcpServers', {})
    sf = servers.get('salesforce', {})
    env = sf.get('env', {})
    print(env.get('SF_CLIENT_ID', ''))
except: pass
" 2>/dev/null || echo "")
    SF_CLIENT_SECRET=$(python3 -c "
import json, sys
try:
    data = json.load(open('$VAULT_PATH/.mcp.json'))
    servers = data.get('mcpServers', {})
    sf = servers.get('salesforce', {})
    env = sf.get('env', {})
    print(env.get('SF_CLIENT_SECRET', ''))
except: pass
" 2>/dev/null || echo "")
fi

# Save vault path breadcrumb (used by dex-launcher.sh)
mkdir -p "$HOME/.config/dex"
echo "$VAULT_PATH" > "$HOME/.config/dex/vault-path"

# Build plist from template
mkdir -p "$HOME/Library/LaunchAgents"
sed \
    -e "s|__VAULT_PATH__|$VAULT_PATH|g" \
    -e "s|__SF_CLIENT_ID__|$SF_CLIENT_ID|g" \
    -e "s|__SF_CLIENT_SECRET__|$SF_CLIENT_SECRET|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DEST"
echo -e "${GREEN}✓${NC} Launch Agent installed: $PLIST_DEST"

# Load the agent
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

if launchctl list 2>/dev/null | grep -q "$PLIST_NAME"; then
    echo -e "${GREEN}✓${NC} Agent loaded and running"
else
    echo -e "${YELLOW}⚠${NC}  Agent installed but may not be active yet"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  ✓ Customer Intelligence automation installed!                 ║"
echo "║                                                                ║"
echo "║  Monthly reports auto-save to: Inbox/Reports/                 ║"
echo "║  Schedule: 1st of every month at 8:00 AM                      ║"
echo "║                                                                ║"
echo "║  Test it now:  ./install-automation.sh --run                  ║"
echo "║  Check status: ./install-automation.sh --status               ║"
echo "║  In Dex:       /customer-intel report                         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
