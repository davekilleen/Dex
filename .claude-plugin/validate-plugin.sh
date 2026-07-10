#!/bin/bash

# Dex Plugin Validation Script
# Run this before publishing to catch common issues

set -e  # Exit on error

echo "🔍 Validating Dex Plugin..."
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# Function to print errors
error() {
    echo -e "${RED}❌ ERROR: $1${NC}"
    ERRORS=$((ERRORS + 1))
}

# Function to print warnings
warn() {
    echo -e "${YELLOW}⚠️  WARNING: $1${NC}"
    WARNINGS=$((WARNINGS + 1))
}

# Function to print success
success() {
    echo -e "${GREEN}✅ $1${NC}"
}

echo "1️⃣  Checking plugin.json..."

if [ ! -f ".claude-plugin/plugin.json" ]; then
    error ".claude-plugin/plugin.json not found"
else
    success "plugin.json exists"

    # Check for placeholder GitHub URL
    if grep -q "YOUR-USERNAME" .claude-plugin/plugin.json; then
        error "GitHub URL still has placeholder YOUR-USERNAME - update it!"
    else
        success "GitHub URL is configured"
    fi

    # Validate JSON syntax
    if ! python3 -m json.tool .claude-plugin/plugin.json > /dev/null 2>&1; then
        error "plugin.json has invalid JSON syntax"
    else
        success "plugin.json is valid JSON"
    fi
fi

echo ""
echo "2️⃣  Checking Python requirements..."

if [ ! -f "requirements.txt" ]; then
    error "requirements.txt not found"
else
    success "requirements.txt exists"
fi

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    error "python3 not found - required for MCP servers"
else
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    success "Python $PYTHON_VERSION found"

    # Check Python version (need 3.10+)
    MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

    if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]); then
        error "Python 3.10+ required, found $PYTHON_VERSION"
    else
        success "Python version is compatible"
    fi
fi

echo ""
echo "3️⃣  Checking MCP servers..."

if ! PLUGIN_MCP_ENTRIES=$(python3 - <<'PY'
import json
from pathlib import Path

manifest = json.loads(Path(".claude-plugin/plugin.json").read_text(encoding="utf-8"))
expected = {
    "work": "core.mcp.work_server",
    "calendar": "core.mcp.calendar_server",
    "career": "core.mcp.career_server",
    "resume": "core.mcp.resume_server",
    "onboarding": "core.mcp.onboarding_server",
    "dex-improvements": "core.mcp.dex_improvements_server",
    "granola": "core.mcp.granola_server",
}
servers = manifest.get("mcpServers", {})

for name in sorted(expected.keys() - servers.keys()):
    print(f"INVALID\t{name}\tMissing required plugin MCP registration")
for name in sorted(servers.keys() - expected.keys()):
    print(f"INVALID\t{name}\tUnexpected plugin MCP registration")

for name, server in servers.items():
    if name not in expected:
        continue
    args = server.get("args", [])
    if len(args) < 2 or args[0] != "-m" or not isinstance(args[1], str) or not args[1].startswith("core.mcp."):
        print(f"INVALID\t{name}\tExpected Python module args: -m core.mcp.<server>")
        continue
    if args[1] != expected[name]:
        print(f"INVALID\t{name}\tExpected module {expected[name]}, found {args[1]}")
        continue
    server_path = args[1].replace(".", "/") + ".py"
    print(f"SERVER\t{name}\t{server_path}")
PY
); then
    error "Unable to read MCP registrations from plugin.json"
else
    PLUGIN_MCP_PATHS=""
    while IFS=$'\t' read -r entry_type server_name server_path; do
        [ -z "$entry_type" ] && continue
        if [ "$entry_type" = "INVALID" ]; then
            error "Invalid MCP registration '$server_name': $server_path"
        elif [ ! -f "$server_path" ]; then
            error "MCP server not found for '$server_name': $server_path"
        else
            success "$(basename "$server_path")"
            PLUGIN_MCP_PATHS="${PLUGIN_MCP_PATHS}${server_path}"$'\n'
        fi
    done <<< "$PLUGIN_MCP_ENTRIES"

    DUPLICATE_MCP_PATHS=$(printf '%s' "$PLUGIN_MCP_PATHS" | sed '/^$/d' | sort | uniq -d)
    if [ -n "$DUPLICATE_MCP_PATHS" ]; then
        error "Multiple plugin registrations target the same MCP server: $(echo "$DUPLICATE_MCP_PATHS" | tr '\n' ' ')"
    fi
fi

echo ""
echo "4️⃣  Checking .gitignore..."

if [ ! -f ".gitignore" ]; then
    warn ".gitignore not found - personal data may be committed!"
else
    success ".gitignore exists"

    # Check for critical patterns
    CRITICAL_PATTERNS=(
        "00-Inbox/"
        "System/user-profile.yaml"
        "System/pillars.yaml"
        "__pycache__/"
        "*.pyc"
    )

    for pattern in "${CRITICAL_PATTERNS[@]}"; do
        if ! grep -q "$pattern" .gitignore; then
            warn ".gitignore missing pattern: $pattern"
        fi
    done

    if [ $WARNINGS -eq 0 ]; then
        success ".gitignore has all critical patterns"
    fi
fi

echo ""
echo "5️⃣  Checking documentation..."

DOCS=(
    "README.md"
    "LICENSE"
    "CHANGELOG.md"
    ".claude-plugin/PLUGIN_README.md"
    ".claude-plugin/DISTRIBUTION_GUIDE.md"
    ".claude-plugin/INSTALLATION_QUICK_START.md"
)

for doc in "${DOCS[@]}"; do
    if [ ! -f "$doc" ]; then
        error "Documentation missing: $doc"
    else
        success "$(basename $doc)"
    fi
done

echo ""
echo "6️⃣  Checking skills..."

if [ ! -d ".claude/skills" ]; then
    error ".claude/skills directory not found"
else
    SKILL_COUNT=$(find .claude/skills -name "SKILL.md" | wc -l)
    success "Found $SKILL_COUNT skills"

    if [ "$SKILL_COUNT" -lt 10 ]; then
        warn "Less than 10 skills found - expected 60+"
    fi
fi

echo ""
echo "7️⃣  Running claude plugin validate..."

if command -v claude &> /dev/null; then
    if claude plugin validate . > /dev/null 2>&1; then
        success "Claude plugin validation passed"
    else
        error "Claude plugin validation failed"
        echo "Run manually to see errors: claude plugin validate ."
    fi
else
    warn "claude CLI not found - skipping validation"
    echo "Install Claude Code to run: claude plugin validate ."
fi

echo ""
echo "8️⃣  Checking for personal data leaks..."

PERSONAL_FILES=(
    "System/user-profile.yaml"
    "System/pillars.yaml"
    "00-Inbox/"
    "01-Quarter_Goals/"
    "05-Areas/People/"
)

for file in "${PERSONAL_FILES[@]}"; do
    if [ -e "$file" ]; then
        warn "Personal data exists: $file (should be gitignored)"
    fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}🎉 All checks passed! Plugin is ready to publish.${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Create GitHub repository"
    echo "2. Push to GitHub"
    echo "3. Test installation: claude plugin install <your-github-url>"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  $WARNINGS warnings found. Review and fix if needed.${NC}"
    echo ""
    echo "Plugin should still work, but review warnings above."
    exit 0
else
    echo -e "${RED}❌ $ERRORS errors found. Fix these before publishing.${NC}"
    echo ""
    echo "Review errors above and fix before distribution."
    exit 1
fi
