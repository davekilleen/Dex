#!/bin/bash
# Path Consistency Checker
# Ensures all code uses numbered PARA prefixes (00-Inbox, 05-Areas, etc.)
# instead of bare folder names (Inbox, Areas, etc.)
#
# Source of truth: core/paths.py

set -e

echo "🔍 Path Consistency Check"
echo "========================="
echo ""

VIOLATIONS=0

# Get all tracked code files, excluding:
#   - core/paths.py (source of truth)
#   - test files
#   - this script itself
#   - verify-distribution.sh (contains /Users/ in its own checks)
FILES=$(git ls-files -- '*.py' '*.ts' '*.cjs' '*.sh' | \
    grep -v 'core/paths\.py' | \
    grep -v 'core/tests/' | \
    grep -v 'scripts/check-path-consistency\.sh' | \
    grep -v 'scripts/verify-distribution\.sh' || true)

if [ -z "$FILES" ]; then
    echo "⚠️  No code files to check"
    exit 0
fi

# Helper: count and display violations
check_pattern() {
    local label="$1"
    local matches="$2"
    if [ -n "$matches" ]; then
        local count
        count=$(echo "$matches" | wc -l | tr -d ' ')
        echo "  ❌ Found bare '$label' references:"
        echo "$matches" | sed 's/^/     /'
        VIOLATIONS=$((VIOLATIONS + count))
    fi
}

# Check 1: Bare 'Inbox/' at top level (should be '00-Inbox/')
echo "✓ Checking for bare 'Inbox/' (should be '00-Inbox/')..."
MATCHES=$(echo "$FILES" | xargs grep -n '['\''"/]Inbox/' 2>/dev/null | \
    grep -v '00-Inbox' | \
    grep -v '#.*Inbox' | \
    grep -v '//.*Inbox' || true)
check_pattern "Inbox" "$MATCHES"

# Check 2: Bare 'Active/' as top-level path (should use PARA prefix)
# Matches: 'Active/', "Active/", /Active/ — i.e. used as a directory path
echo "✓ Checking for bare 'Active/' paths..."
MATCHES=$(echo "$FILES" | xargs grep -n '['\''"/]Active/' 2>/dev/null | \
    grep -v '04-Projects\|05-Areas' | \
    grep -v '#.*Active' | \
    grep -v '//.*Active' || true)
# Also catch .startswith('Active/') patterns
MATCHES2=$(echo "$FILES" | xargs grep -n "startswith('Active/" 2>/dev/null || true)
MATCHES=$(printf '%s\n%s' "$MATCHES" "$MATCHES2" | grep -v '^$' | sort -u || true)
check_pattern "Active" "$MATCHES"

# Check 3: Bare 'Resources/' at top level (should be '06-Resources/')
echo "✓ Checking for bare 'Resources/' (should be '06-Resources/')..."
MATCHES=$(echo "$FILES" | xargs grep -n '['\''"/]Resources/' 2>/dev/null | \
    grep -v '06-Resources' | \
    grep -v '#.*Resources' | \
    grep -v '//.*Resources' || true)
check_pattern "Resources" "$MATCHES"

# Check 4: Hardcoded /Users/ paths
echo "✓ Checking for hardcoded /Users/ paths..."
MATCHES=$(echo "$FILES" | xargs grep -n '/Users/' 2>/dev/null | \
    grep -v '#.*/Users/' | \
    grep -v '//.*/Users/' || true)
check_pattern "/Users/" "$MATCHES"

# Check 5: '02-Areas' typo (should be '05-Areas')
echo "✓ Checking for '02-Areas' typo..."
MATCHES=$(echo "$FILES" | xargs grep -n '02-Areas' 2>/dev/null || true)
check_pattern "02-Areas" "$MATCHES"

# Check 6: '01-Daily_Plan' typo (Daily Plans are under 00-Inbox)
echo "✓ Checking for '01-Daily_Plan' typo..."
MATCHES=$(echo "$FILES" | xargs grep -n '01-Daily_Plan' 2>/dev/null || true)
check_pattern "01-Daily_Plan" "$MATCHES"

# Summary
echo ""
echo "========================="
if [ $VIOLATIONS -gt 0 ]; then
    echo "❌ Found $VIOLATIONS path consistency violation(s)"
    echo "   All paths should use numbered PARA prefixes from core/paths.py"
    exit 1
else
    echo "✅ Path consistency check PASSED — all paths use correct prefixes"
    exit 0
fi
