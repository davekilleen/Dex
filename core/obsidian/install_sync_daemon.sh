#!/bin/bash
# Install Obsidian sync daemon as macOS LaunchAgent

set -e  # Exit on error

VAULT_PATH="${VAULT_PATH:-$(pwd)}"
PLIST_PATH="$HOME/Library/LaunchAgents/com.dex.obsidian-sync.plist"

echo "Dex Obsidian Sync Daemon Installer"
echo "===================================="
echo ""

# Check if on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "Error: This installer is for macOS only."
    echo "For other platforms, run the sync daemon manually:"
    echo "  python3 core/obsidian/sync_daemon.py"
    exit 1
fi

# Check if watchdog is installed
if ! python3 -c "import watchdog" 2>/dev/null; then
    echo "Installing watchdog package..."
    pip3 install watchdog
fi

echo "Installing Dex Obsidian Sync Daemon..."
echo "  Vault path: $VAULT_PATH"
echo "  LaunchAgent: $PLIST_PATH"
echo ""

# Create LaunchAgent plist
cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.dex.obsidian-sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>python3</string>
        <string>$VAULT_PATH/core/obsidian/sync_daemon.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>VAULT_PATH</key>
        <string>$VAULT_PATH</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>$VAULT_PATH/System/obsidian-sync-error.log</string>
    <key>StandardOutPath</key>
    <string>$VAULT_PATH/System/obsidian-sync.log</string>
</dict>
</plist>
EOF

# Unload existing agent if running
if launchctl list | grep -q "com.dex.obsidian-sync"; then
    echo "Stopping existing daemon..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi

# Load the agent
echo "Starting daemon..."
launchctl load "$PLIST_PATH"

# Wait a moment and check if it started
sleep 2
if launchctl list | grep -q "com.dex.obsidian-sync"; then
    echo ""
    echo "✅ Sync daemon installed and started successfully!"
    echo ""
    echo "Logs:"
    echo "  - Output: $VAULT_PATH/System/obsidian-sync.log"
    echo "  - Errors: $VAULT_PATH/System/obsidian-sync-error.log"
    echo ""
    echo "Management commands:"
    echo "  - Stop:  launchctl unload $PLIST_PATH"
    echo "  - Start: launchctl load $PLIST_PATH"
    echo "  - Status: launchctl list | grep com.dex.obsidian-sync"
    echo ""
    echo "The daemon will automatically start on login."
else
    echo ""
    echo "⚠️  Daemon may not have started successfully."
    echo "Check the error log: $VAULT_PATH/System/obsidian-sync-error.log"
    exit 1
fi
