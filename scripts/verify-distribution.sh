#!/bin/bash
# Distribution Safety Check
# Run this before pushing Dex to GitHub to verify no credentials or personal data

set -e

echo "🔍 Dex Distribution Safety Check"
echo "================================="
echo ""

ERRORS=0
WARNINGS=0

# Check 1: Verify .mcp.json is not tracked
echo "✓ Checking .mcp.json is gitignored..."
if git ls-files --error-unmatch .mcp.json 2>/dev/null; then
    echo "  ❌ ERROR: .mcp.json is tracked by git!"
    echo "     Run: git rm --cached .mcp.json"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ .mcp.json not tracked"
fi

# Check 2: Verify .env is not tracked
echo ""
echo "✓ Checking .env is gitignored..."
if git ls-files --error-unmatch .env 2>/dev/null; then
    echo "  ❌ ERROR: .env is tracked by git!"
    echo "     Run: git rm --cached .env"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ .env not tracked"
fi

# Check 3: Check for API keys in tracked files
echo ""
echo "✓ Scanning for API keys..."
KEY_MATCHES=$(git ls-files | xargs grep -E '(sk-ant-api|sk-ant-[a-zA-Z0-9]{90,}|sk-proj-[a-zA-Z0-9]{20,}|AIza[a-zA-Z0-9-_]{35})' 2>/dev/null | grep -v 'env.example\|Distribution_Checklist' || true)
if [ -n "$KEY_MATCHES" ]; then
    echo "  ❌ ERROR: Potential API keys found:"
    echo "$KEY_MATCHES" | sed 's/^/     /'
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ No API keys found"
fi

# Check 4: Check for user data folders
echo ""
echo "✓ Checking user data is gitignored..."
USER_FOLDERS=("00-Inbox" "01-Quarter_Goals" "02-Week_Priorities" "03-Tasks" "04-Projects" "05-Areas" "07-Archives")
for folder in "${USER_FOLDERS[@]}"; do
    if git ls-files --error-unmatch "$folder" 2>/dev/null | head -1 >/dev/null; then
        echo "  ⚠️  WARNING: $folder has tracked files"
        echo "     These should be in demo mode only: System/Demo/$folder"
        WARNINGS=$((WARNINGS + 1))
    fi
done
if [ $WARNINGS -eq 0 ]; then
    echo "  ✅ No user data folders tracked (or only System/Demo)"
fi

# Check 5: Check for personal identifiable information
echo ""
echo "✓ Scanning for personal email addresses..."
EMAIL_MATCHES=$(git ls-files | xargs grep -E '[a-z0-9._%+-]+@[a-z0-9.-]+\.(com|net|org|io|ai)' 2>/dev/null | \
    grep -v 'README\|example\|template\|CHANGELOG\|Distribution_Checklist\|\.md:.*https://\|\.md:.*example@' | \
    grep -v 'user@example.com\|name@company.com\|you@domain.com' || true)
if [ -n "$EMAIL_MATCHES" ]; then
    echo "  ⚠️  WARNING: Email addresses found (verify these are examples):"
    echo "$EMAIL_MATCHES" | head -5 | sed 's/^/     /'
    WARNINGS=$((WARNINGS + 1))
else
    echo "  ✅ No personal emails found (or all are examples)"
fi

# Check 6: Verify critical files exist
echo ""
echo "✓ Checking critical distribution files..."
REQUIRED_FILES=("README.md" ".gitignore" "install.sh" "System/.mcp.json.example" "env.example")
for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        echo "  ❌ ERROR: Missing required file: $file"
        ERRORS=$((ERRORS + 1))
    fi
done
if [ $ERRORS -eq 0 ]; then
    echo "  ✅ All critical files present"
fi

# Check 7: Verify install.sh is executable
echo ""
echo "✓ Checking install.sh permissions..."
if [ ! -x "install.sh" ]; then
    echo "  ⚠️  WARNING: install.sh is not executable"
    echo "     Run: chmod +x install.sh"
    WARNINGS=$((WARNINGS + 1))
else
    echo "  ✅ install.sh is executable"
fi

# Check 8: Verify .mcp.json.example uses template placeholders
echo ""
echo "✓ Checking .mcp.json.example uses placeholders..."
if ! grep -q '{{VAULT_PATH}}' System/.mcp.json.example; then
    echo "  ❌ ERROR: .mcp.json.example doesn't use {{VAULT_PATH}} placeholder"
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ Template uses {{VAULT_PATH}} placeholder"
fi

# Check 9: Count MCP servers
echo ""
echo "✓ Verifying MCP server count..."
MCP_COUNT=$(find core/mcp -name '*_server.py' -o -name 'update_checker.py' | wc -l | tr -d ' ')
TEMPLATE_COUNT=$(grep -c '{{VAULT_PATH}}/core/mcp/' System/.mcp.json.example)
if [ "$MCP_COUNT" != "$TEMPLATE_COUNT" ]; then
    echo "  ⚠️  WARNING: MCP mismatch - $MCP_COUNT servers found, $TEMPLATE_COUNT in template"
    WARNINGS=$((WARNINGS + 1))
else
    echo "  ✅ All $MCP_COUNT MCP servers in template"
fi

# Check 10: Personal paths in .mcp.json (if exists)
if [ -f ".mcp.json" ]; then
    echo ""
    echo "✓ Checking local .mcp.json doesn't contain personal paths..."
    if grep -q "/Users/dave" .mcp.json; then
        echo "  ℹ️  INFO: Your local .mcp.json has /Users/dave paths (this is fine - file is gitignored)"
    fi
fi

# Summary
echo ""
echo "================================="
echo "📊 Summary"
echo "================================="
echo "Errors:   $ERRORS"
echo "Warnings: $WARNINGS"
echo ""

if [ $ERRORS -gt 0 ]; then
    echo "❌ Distribution check FAILED - fix errors before pushing to GitHub"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    echo "⚠️  Distribution check passed with warnings - review above"
    exit 0
else
    echo "✅ Distribution check PASSED - safe to push to GitHub!"
    echo ""
    echo "Next steps:"
    echo "  1. Review CHANGELOG.md"
    echo "  2. Update version in package.json"
    echo "  3. Commit and push: git push origin main"
    echo "  4. Create release: git tag -a v1.0.0 -m 'Initial release'"
    exit 0
fi
