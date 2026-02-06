#!/bin/bash
# Dex PKM - Installation Script
# This script sets up your development environment

set -e

echo "🚀 Setting up Dex..."
echo ""

# Check for Command Line Tools on macOS (required for git)
if [[ "$OSTYPE" == "darwin"* ]]; then
    if ! xcode-select -p &> /dev/null; then
        echo "⚠️  Command Line Developer Tools not found"
        echo ""
        echo "macOS will now prompt you to install them - this is required for git."
        echo "Click 'Install' when the dialog appears (takes 2-3 minutes)."
        echo ""
        echo "Press Enter to continue..."
        read -r
        
        # Trigger the install prompt
        xcode-select --install 2>/dev/null || true
        
        echo ""
        echo "⏳ Waiting for Command Line Tools installation..."
        echo "   (This window will continue once installation completes)"
        echo ""
        
        # Wait for installation to complete
        until xcode-select -p &> /dev/null; do
            sleep 5
        done
        
        echo "✅ Command Line Tools installed!"
        echo ""
    fi
fi

# Silently fix git remote to avoid Claude Desktop confusion
if git remote -v 2>/dev/null | grep -q "davekilleen/[Dd]ex"; then
    git remote rename origin upstream 2>/dev/null || true
fi

# Check Git first (required for repo operations)
if ! command -v git &> /dev/null; then
    echo "❌ Git is not installed"
    echo ""
    echo "Git is required to clone the repository and manage updates."
    echo ""
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        echo "Download Git for Windows from: https://git-scm.com/download/win"
        echo "After installing, restart your terminal and run ./install.sh again"
    else
        echo "Download Git from: https://git-scm.com"
        echo "After installing, restart your terminal and run ./install.sh again"
    fi
    exit 1
fi
echo "✅ Git $(git --version | cut -d' ' -f3)"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed"
    echo "   Please install Node.js 18+ from https://nodejs.org/"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "❌ Node.js version must be 18 or higher (found v$NODE_VERSION)"
    echo "   Please upgrade from https://nodejs.org/"
    exit 1
fi
echo "✅ Node.js $(node -v)"

# Check Python (required for Work MCP - task sync)
# Windows often uses 'python' instead of 'python3'
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    # Verify it's Python 3, not Python 2
    PYTHON_VERSION=$(python --version 2>&1 | grep "Python 3")
    if [ -n "$PYTHON_VERSION" ]; then
        PYTHON_CMD="python"
    fi
fi

if [ -n "$PYTHON_CMD" ]; then
    PYTHON_VERSION=$($PYTHON_CMD --version | cut -d' ' -f2)
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
    
    # Check if Python 3.10+
    if [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]; then
        echo "❌ Python $PYTHON_VERSION found (too old)"
        echo ""
        echo "MCP SDK requires Python 3.10 or newer."
        echo "You have Python $PYTHON_VERSION which is too old."
        echo ""
        echo "Install Python 3.10+:"
        echo "  Download the latest version from https://www.python.org/downloads/"
        echo "  After installing, restart your terminal and run ./install.sh again"
        exit 1
    fi
    
    echo "✅ Python $PYTHON_VERSION"
else
    echo "❌ Python 3 not found"
    echo ""
    echo "Python 3.10+ is required for MCP servers (task sync across all files)."
    echo "Without it, tasks won't sync between meeting notes, person pages, and Tasks.md."
    echo ""
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        echo "Install Python 3.10+:"
        echo "  1. Download from https://www.python.org/downloads/"
        echo "  2. Run the installer"
        echo "  3. ⚠️  IMPORTANT: Check 'Add Python to PATH' during installation"
        echo "  4. Restart your terminal"
        echo "  5. Run ./install.sh again"
    else
        echo "Install Python 3.10+:"
        echo "  Mac: Download from https://www.python.org/downloads/"
        echo "  Or use Homebrew: brew install python3"
        echo ""
        echo "After installing, run ./install.sh again"
    fi
    exit 1
fi

# Install Node dependencies
echo ""
echo "📦 Installing dependencies..."
if command -v pnpm &> /dev/null; then
    pnpm install
elif command -v npm &> /dev/null; then
    npm install
else
    echo "❌ Neither npm nor pnpm found"
    exit 1
fi

# Skip .env creation - it's created during /setup if needed
# (Most users don't need API keys - everything works through Cursor)

# Create .mcp.json with current path and correct Python command
if [ ! -f .mcp.json ]; then
    echo ""
    echo "📝 Creating .mcp.json with workspace path..."
    CURRENT_PATH="$(pwd)"
    
    # Use the Python command we detected earlier (python3 or python)
    sed "s|{{VAULT_PATH}}|$CURRENT_PATH|g; s|\"python\"|\"$PYTHON_CMD\"|g" System/.mcp.json.example > .mcp.json
    echo "   MCP servers configured for: $CURRENT_PATH"
    echo "   Python command: $PYTHON_CMD"
fi

# Check for Granola (optional)
echo ""
if [ -f "$HOME/Library/Application Support/Granola/cache-v3.json" ]; then
    echo "✅ Granola detected - meeting intelligence available"
else
    echo "ℹ️  Granola not detected - meeting intelligence won't work"
    echo "   Install Granola from https://granola.ai for meeting transcription"
fi

# Install Python dependencies for Work MCP (CRITICAL for task sync)
echo ""
echo "📦 Installing Python dependencies for Work MCP..."

# Determine pip command (pip3 or pip)
PIP_CMD=""
if command -v pip3 &> /dev/null; then
    PIP_CMD="pip3"
elif command -v pip &> /dev/null; then
    PIP_CMD="pip"
fi

if [ -n "$PIP_CMD" ]; then
    # First, try to upgrade pip (silently, many users have old pip versions)
    echo "   Upgrading pip..."
    $PYTHON_CMD -m pip install --upgrade pip --quiet 2>/dev/null || true
    
    # Detect Apple Silicon and set appropriate pip flags
    PIP_FLAGS=""
    if [[ "$OSTYPE" == "darwin"* ]] && [[ $(uname -m) == "arm64" ]]; then
        echo "   Detected Apple Silicon - ensuring native ARM64 packages..."
        # Force reinstall without cache to get native ARM64 binaries
        PIP_FLAGS="--force-reinstall --no-cache-dir"
    fi
    
    # Try standard install first
    if $PIP_CMD install $PIP_FLAGS mcp pyyaml pyobjc-framework-EventKit --quiet 2>/dev/null; then
        echo "✅ MCP dependencies installed (including fast EventKit calendar access)"
    else
        # Try with --user flag (works around permission issues)
        echo "   Trying with --user flag..."
        if $PIP_CMD install --user $PIP_FLAGS mcp pyyaml pyobjc-framework-EventKit --quiet 2>/dev/null; then
            echo "✅ MCP dependencies installed (user mode)"
        else
            echo "❌ Could not install Python dependencies"
            echo ""
            echo "Work MCP is critical - it syncs tasks across all your files."
            echo "Without it, checking off a task in one place won't update others."
            echo ""
            if [[ "$OSTYPE" == "darwin"* ]] && [[ $(uname -m) == "arm64" ]]; then
                echo "On Apple Silicon, sometimes pip installs Intel packages by mistake."
                echo "Try manually with explicit architecture flags:"
                echo "  arch -arm64 $PIP_CMD install --force-reinstall --no-cache-dir mcp pyyaml pyobjc-framework-EventKit"
            else
                echo "Try manually (upgrade pip first):"
                echo "  $PYTHON_CMD -m pip install --upgrade pip"
                echo "  $PIP_CMD install --user mcp pyyaml pyobjc-framework-EventKit"
            fi
            echo ""
            read -p "Press Enter to continue setup (you can fix this later)..."
        fi
    fi
else
    echo "❌ pip not found (usually comes with Python)"
    echo ""
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
        echo "This usually means Python wasn't added to PATH during installation."
        echo ""
        echo "Fix:"
        echo "  1. Reinstall Python from https://www.python.org/downloads/"
        echo "  2. Check 'Add Python to PATH' during installation"
        echo "  3. Restart your terminal and run ./install.sh again"
    else
        echo "This is unusual - Python is installed but pip is missing."
        echo "Try reinstalling Python from https://www.python.org/downloads/"
    fi
    echo ""
    read -p "Press Enter to continue setup (Work MCP won't work until fixed)..."
fi

# Verify Work MCP setup
echo ""
echo "🔍 Verifying Work MCP setup..."
if [ -n "$PYTHON_CMD" ]; then
    if $PYTHON_CMD -c "import mcp, yaml" 2>/dev/null; then
        echo "✅ Work MCP verified - task sync will work"
        WORK_MCP_STATUS="✅ Working"
    else
        echo "⚠️  Work MCP not working - task sync won't function"
        WORK_MCP_STATUS="⚠️  Needs attention"
    fi
else
    WORK_MCP_STATUS="⚠️  Needs attention"
fi

# Cursor/Claude Code compatibility
echo ""
echo "🔄 Checking AI editor compatibility..."

# Detect which editor is likely being used
EDITOR_DETECTED=""
CURSOR_VERSION=""

if [ -d "$HOME/.cursor" ]; then
    EDITOR_DETECTED="Cursor"
    
    # Try to detect Cursor version from the app bundle (macOS)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        CURSOR_PLIST="/Applications/Cursor.app/Contents/Info.plist"
        if [ -f "$CURSOR_PLIST" ]; then
            CURSOR_VERSION=$(/usr/libexec/PlistBuddy -c "Print CFBundleShortVersionString" "$CURSOR_PLIST" 2>/dev/null || echo "")
        fi
    fi
fi

# Skills in .claude/skills/ work natively in BOTH editors:
# - Claude Code (Claude Desktop) - always
# - Cursor 2.4+ - has .claude/skills/ compatibility built-in (Agent Skills standard)
#
# NO SYNC NEEDED - both editors read from the same location!

if [ "$EDITOR_DETECTED" == "Cursor" ]; then
    echo "   Detected Cursor installation"
    
    if [ -n "$CURSOR_VERSION" ]; then
        echo "   Cursor version: $CURSOR_VERSION"
        
        # Extract major.minor version for comparison
        CURSOR_MAJOR=$(echo "$CURSOR_VERSION" | cut -d'.' -f1)
        CURSOR_MINOR=$(echo "$CURSOR_VERSION" | cut -d'.' -f2)
        
        # Check if version is 2.4 or higher
        if [ "$CURSOR_MAJOR" -lt 2 ] || ([ "$CURSOR_MAJOR" -eq 2 ] && [ "$CURSOR_MINOR" -lt 4 ]); then
            echo ""
            echo "   ⚠️  WARNING: Cursor $CURSOR_VERSION detected (skills require 2.4+)"
            echo ""
            echo "   Dex skills won't work until you upgrade Cursor!"
            echo "   Skills like /setup, /daily-plan, etc. require Cursor 2.4 or later."
            echo ""
            echo "   To upgrade: Cursor menu → Check for Updates"
            echo "   Or download latest from: https://cursor.com"
            echo ""
            echo "   After upgrading, skills in .claude/skills/ will work automatically."
            echo ""
            read -p "Press Enter to continue (upgrade Cursor later)..."
        else
            echo ""
            echo "   ✅ Cursor $CURSOR_VERSION supports skills natively"
            echo "   Skills work in both Cursor AND Claude Code from .claude/skills/"
        fi
    else
        echo ""
        echo "   ℹ️  Could not detect Cursor version automatically."
        echo "   Skills require Cursor 2.4+ to work."
        echo ""
        echo "   Check your version: Cursor menu → About Cursor"
        echo "   If < 2.4, upgrade via: Cursor menu → Check for Updates"
    fi
    echo ""
    echo "✅ Cursor compatibility check complete"
else
    echo "✅ Claude Code / Claude Desktop detected (or no editor found)"
    echo "   Skills in .claude/skills/ will work natively"
fi

# Success
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Dex installation complete!"
echo ""
echo "Status:"
echo "  • Node.js: ✅ Working"
echo "  • Work MCP: $WORK_MCP_STATUS"
echo "  • Editor: ${EDITOR_DETECTED:-Claude Code}"
if [[ "$WORK_MCP_STATUS" == *"Needs"* ]]; then
    echo ""
    echo "⚠️  IMPORTANT: Work MCP enables task sync across all files."
    echo "   Without it, Dex works but tasks won't sync automatically."
    echo "   See troubleshooting above to fix."
fi
echo ""
echo "Next steps:"
if [ "$EDITOR_DETECTED" == "Cursor" ]; then
    echo "  1. Make sure you're on Cursor 2.4+ for best experience"
    echo "  2. In Cursor chat, type: /setup"
    echo "  3. Answer the setup questions (~5 minutes)"
    echo "  4. Start using Dex!"
else
    echo "  1. In chat, type: /setup"
    echo "  2. Answer the setup questions (~5 minutes)"
    echo "  3. Start using Dex!"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
