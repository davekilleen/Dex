#!/bin/bash
# Install Dex Learning Automation Launch Agents
#
# This script installs two background automation jobs:
# 1. Changelog Checker - Runs every 6 hours to check for Claude Code updates
# 2. Learning Review - Runs daily at 5pm to prompt for learning review
#
# Usage:
#   bash .scripts/install-learning-automation.sh           # Install both agents
#   bash .scripts/install-learning-automation.sh --uninstall # Remove both agents

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

CHANGELOG_PLIST="com.dex.changelog-checker.plist"
LEARNING_PLIST="com.dex.learning-review.plist"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=== Dex Learning Automation Installer ==="
echo ""

# Check if uninstall mode
if [[ "$1" == "--uninstall" ]]; then
  echo "Uninstalling Launch Agents..."
  
  # Unload and remove changelog checker
  if launchctl list | grep -q "com.dex.changelog-checker"; then
    launchctl unload "$LAUNCH_AGENTS_DIR/$CHANGELOG_PLIST" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Unloaded changelog checker"
  fi
  
  if [[ -f "$LAUNCH_AGENTS_DIR/$CHANGELOG_PLIST" ]]; then
    rm "$LAUNCH_AGENTS_DIR/$CHANGELOG_PLIST"
    echo -e "${GREEN}✓${NC} Removed changelog checker plist"
  fi
  
  # Unload and remove learning review
  if launchctl list | grep -q "com.dex.learning-review"; then
    launchctl unload "$LAUNCH_AGENTS_DIR/$LEARNING_PLIST" 2>/dev/null || true
    echo -e "${GREEN}✓${NC} Unloaded learning review"
  fi
  
  if [[ -f "$LAUNCH_AGENTS_DIR/$LEARNING_PLIST" ]]; then
    rm "$LAUNCH_AGENTS_DIR/$LEARNING_PLIST"
    echo -e "${GREEN}✓${NC} Removed learning review plist"
  fi
  
  echo ""
  echo -e "${GREEN}Uninstall complete!${NC}"
  exit 0
fi

# Install mode
echo "Installing Launch Agents..."
echo ""

# Get the vault root (parent of .scripts directory)
VAULT_ROOT="$(dirname "$SCRIPT_DIR")"
echo "Vault path: $VAULT_ROOT"
echo ""

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCH_AGENTS_DIR"

# Copy plist files WITH path substitution
sed "s|{{VAULT_PATH}}|$VAULT_ROOT|g" "$SCRIPT_DIR/$CHANGELOG_PLIST" > "$LAUNCH_AGENTS_DIR/$CHANGELOG_PLIST"
sed "s|{{VAULT_PATH}}|$VAULT_ROOT|g" "$SCRIPT_DIR/$LEARNING_PLIST" > "$LAUNCH_AGENTS_DIR/$LEARNING_PLIST"
echo -e "${GREEN}✓${NC} Installed plist files to $LAUNCH_AGENTS_DIR (with your vault path)"

# Load changelog checker
if launchctl list | grep -q "com.dex.changelog-checker"; then
  launchctl unload "$LAUNCH_AGENTS_DIR/$CHANGELOG_PLIST"
fi
launchctl load "$LAUNCH_AGENTS_DIR/$CHANGELOG_PLIST"
echo -e "${GREEN}✓${NC} Loaded changelog checker (runs every 6 hours)"

# Load learning review
if launchctl list | grep -q "com.dex.learning-review"; then
  launchctl unload "$LAUNCH_AGENTS_DIR/$LEARNING_PLIST"
fi
launchctl load "$LAUNCH_AGENTS_DIR/$LEARNING_PLIST"
echo -e "${GREEN}✓${NC} Loaded learning review (runs daily at 5pm)"

echo ""
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "The following background jobs are now active:"
echo "  • Changelog Checker: Checks for Claude Code updates every 6 hours"
echo "  • Learning Review: Prompts for learning review daily at 5pm"
echo ""
echo "Logs will be written to:"
echo "  • .scripts/logs/changelog-checker.log"
echo "  • .scripts/logs/learning-review.log"
echo ""
echo "To test the automation immediately:"
echo "  node .scripts/check-anthropic-changelog.cjs --force"
echo "  bash .scripts/learning-review-prompt.sh"
echo ""
echo "To uninstall:"
echo "  bash .scripts/install-learning-automation.sh --uninstall"
