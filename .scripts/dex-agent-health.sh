#!/bin/bash
# Dex Agent Health Check
#
# Validates all Dex launch agents have correct paths.
# Run this after moving your vault, or as a periodic check.
#
# Usage:
#   .scripts/dex-agent-health.sh           # Check all agents
#   .scripts/dex-agent-health.sh --fix     # Fix stale paths automatically

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT_PATH="$(cd "$SCRIPT_DIR/.." && pwd)"
BREADCRUMB="$HOME/.config/dex/vault-path"
FIX_MODE=false

if [ "$1" = "--fix" ]; then
    FIX_MODE=true
fi

echo ""
echo "Dex Agent Health Check"
echo "======================"
echo "Current vault: $VAULT_PATH"
echo ""

# Check breadcrumb
if [ -f "$BREADCRUMB" ]; then
    STORED_PATH="$(cat "$BREADCRUMB" | tr -d '[:space:]')"
    if [ "$STORED_PATH" = "$VAULT_PATH" ]; then
        echo -e "${GREEN}✓${NC} Vault path breadcrumb matches"
    else
        echo -e "${RED}✗${NC} Vault path mismatch!"
        echo "  Breadcrumb: $STORED_PATH"
        echo "  Actual:     $VAULT_PATH"
        if $FIX_MODE; then
            echo "$VAULT_PATH" > "$BREADCRUMB"
            echo -e "  ${GREEN}Fixed${NC} breadcrumb updated"
        else
            echo "  Run with --fix to update"
        fi
    fi
else
    echo -e "${YELLOW}○${NC} No breadcrumb file found"
    if $FIX_MODE; then
        mkdir -p "$(dirname "$BREADCRUMB")"
        echo "$VAULT_PATH" > "$BREADCRUMB"
        echo -e "  ${GREEN}Fixed${NC} breadcrumb created"
    else
        echo "  Run with --fix to create"
    fi
fi

echo ""

# Check each launch agent
STALE_COUNT=0
AGENTS_DIR="$HOME/Library/LaunchAgents"

for plist in "$AGENTS_DIR"/com.dex.*.plist "$AGENTS_DIR"/com.claudesidian.*.plist; do
    [ -f "$plist" ] || continue

    NAME="$(basename "$plist" .plist)"

    # Extract all paths from the plist
    PATHS_IN_PLIST=$(grep '<string>' "$plist" | sed 's/.*<string>//;s/<\/string>.*//' | grep "^/" | sort -u)

    STALE=false
    STALE_PATH=""
    for p in $PATHS_IN_PLIST; do
        # Skip system paths
        case "$p" in
            /usr/*|/bin/*|/opt/*) continue ;;
        esac
        # Check if this path exists
        if [ ! -e "$p" ] && [ ! -e "$(dirname "$p")" ]; then
            STALE=true
            STALE_PATH="$p"
            break
        fi
    done

    if $STALE; then
        echo -e "${RED}✗${NC} $NAME"
        echo "    Stale path: $STALE_PATH"
        STALE_COUNT=$((STALE_COUNT + 1))

        if $FIX_MODE; then
            # Try to detect what the old vault path was
            OLD_VAULT=$(echo "$STALE_PATH" | sed "s|/.scripts/.*||;s|/.env||")
            if [ -n "$OLD_VAULT" ] && [ "$OLD_VAULT" != "$STALE_PATH" ]; then
                if [[ "$OSTYPE" == "darwin"* ]]; then
                    sed -i '' "s|$OLD_VAULT|$VAULT_PATH|g" "$plist"
                else
                    sed -i "s|$OLD_VAULT|$VAULT_PATH|g" "$plist"
                fi
                # Reload the agent
                launchctl unload "$plist" 2>/dev/null || true
                launchctl load "$plist" 2>/dev/null || true
                echo -e "    ${GREEN}Fixed${NC} $OLD_VAULT -> $VAULT_PATH (reloaded)"
            else
                echo -e "    ${YELLOW}!${NC} Could not auto-fix — reinstall this agent manually"
            fi
        fi
    else
        # Check if agent is actually running
        if launchctl list 2>/dev/null | grep -q "$NAME"; then
            EXIT_CODE=$(launchctl list "$NAME" 2>/dev/null | grep LastExitStatus | awk '{print $NF}' | tr -d '";')
            if [ "$EXIT_CODE" = "0" ] || [ -z "$EXIT_CODE" ]; then
                echo -e "${GREEN}✓${NC} $NAME"
            else
                echo -e "${YELLOW}!${NC} $NAME (exit code: $EXIT_CODE)"
            fi
        else
            echo -e "${YELLOW}○${NC} $NAME (not running)"
        fi
    fi
done

echo ""
if [ $STALE_COUNT -gt 0 ]; then
    if $FIX_MODE; then
        echo -e "${GREEN}Fixed $STALE_COUNT stale agent(s)${NC}"
    else
        echo -e "${RED}$STALE_COUNT agent(s) have stale paths${NC}"
        echo "Run: .scripts/dex-agent-health.sh --fix"
    fi
else
    echo -e "${GREEN}All agents healthy${NC}"
fi
echo ""
