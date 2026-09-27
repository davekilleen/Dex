#!/bin/bash
# Install Obsidian sync daemon as macOS LaunchAgent

set -e  # Exit on error

VAULT_PATH="${VAULT_PATH:-$(pwd)}"
LABEL="com.dex.obsidian-sync"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
PINNED_PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"

# Never point machine-wide background jobs at a temporary checkout. A git
# worktree marks .git as a file; a real clone or plain vault does not.
if [[ -f "$VAULT_PATH/.git" || "$VAULT_PATH" == */worktrees/* ]]; then
    echo "Error: $VAULT_PATH looks like a temporary working copy (a git worktree), not your real Dex vault."
    echo "Run this installer from your real vault."
    exit 1
fi

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

# launchd does not inherit the user's shell PATH. Pin the same supported
# interpreter for dependency setup and the background job.
PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "$PYTHON_BIN" ]] || ! "$PYTHON_BIN" -c "import sys; raise SystemExit(sys.version_info < (3, 11))" 2>/dev/null; then
    echo "Error: Obsidian sync requires Python 3.11 or newer."
    echo "Install a current Python, then run this installer again."
    exit 1
fi

# Check if watchdog is installed for the exact interpreter launchd will run.
if ! "$PYTHON_BIN" -c "import watchdog" 2>/dev/null; then
    echo "Installing watchdog package..."
    "$PYTHON_BIN" -m pip install watchdog
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
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$VAULT_PATH/core/obsidian/sync_daemon.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>VAULT_PATH</key>
        <string>$VAULT_PATH</string>
        <key>PATH</key>
        <string>$PINNED_PATH</string>
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
if launchctl list | grep -q "$LABEL"; then
    echo "Stopping existing daemon..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
fi

# Load the agent
echo "Starting daemon..."
launchctl load "$PLIST_PATH"

# Wait a moment and check whether it stayed running. A crash-looping launchd
# job still appears in `launchctl list`, but its last exit status is non-zero.
sleep 2
DAEMON_STATUS="$(launchctl list | awk -v label="$LABEL" '$3 == label { print $2; exit }')"
if [[ "$DAEMON_STATUS" == "0" ]]; then
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
    if [[ -n "$DAEMON_STATUS" ]]; then
        echo "⚠️  Daemon exited with exit status $DAEMON_STATUS."
    else
        echo "⚠️  Daemon may not have started successfully."
    fi
    echo "Check the error log: $VAULT_PATH/System/obsidian-sync-error.log"
    exit 1
fi
