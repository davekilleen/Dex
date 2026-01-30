#!/bin/bash
# Dex PKM - Installation Script
# This script sets up your development environment

set -e

echo "🚀 Setting up Dex..."
echo ""

# Silently fix git remote to avoid Claude Desktop confusion
if git remote -v 2>/dev/null | grep -q "davekilleen/[Dd]ex"; then
    git remote rename origin upstream 2>/dev/null || true
fi

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

# Check Python (for Work MCP)
if command -v python3 &> /dev/null; then
    echo "✅ Python $(python3 --version | cut -d' ' -f2)"
else
    echo "⚠️  Python 3 not found - Work MCP server won't work"
    echo "   Install Python 3.8+ for full functionality"
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

# Create .mcp.json with current path
if [ ! -f .mcp.json ]; then
    echo ""
    echo "📝 Creating .mcp.json with workspace path..."
    CURRENT_PATH="$(pwd)"
    sed "s|{{VAULT_PATH}}|$CURRENT_PATH|g" System/.mcp.json.example > .mcp.json
    echo "   MCP servers configured for: $CURRENT_PATH"
fi

# Check for Granola (optional)
echo ""
if [ -f "$HOME/Library/Application Support/Granola/cache-v3.json" ]; then
    echo "✅ Granola detected - meeting intelligence available"
else
    echo "ℹ️  Granola not detected - meeting intelligence won't work"
    echo "   Install Granola from https://granola.ai for meeting transcription"
fi

# Install Python dependencies for MCP (optional)
echo ""
echo "📦 Checking Python dependencies for Work MCP..."
if command -v pip3 &> /dev/null; then
    pip3 install mcp pyyaml --quiet 2>/dev/null || echo "⚠️  Could not install Python deps - Work MCP may not work"
fi

# Success
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Dex is ready!"
echo ""
echo "Next steps:"
echo "  1. Open this folder in Cursor: cursor ."
echo "  2. Start a chat and run: /setup"
echo "  3. Answer the setup questions (~5 minutes)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
