#!/bin/bash
# Distribution Safety Check
# Run this before pushing Dex to GitHub to verify no credentials or personal data

set -e

echo "🔍 Dex Distribution Safety Check"
echo "================================="
echo ""

ERRORS=0
WARNINGS=0

# Tau removal is a release invariant, not merely a source cleanup.
if ! python3 scripts/check-tau-removal.py --source-root "$PWD"; then
    ERRORS=$((ERRORS + 1))
fi

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
        echo "     User data folders should remain untracked"
        WARNINGS=$((WARNINGS + 1))
    fi
done
if [ $WARNINGS -eq 0 ]; then
    echo "  ✅ No user data folders tracked"
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

# Check 9: Every top-level MCP server is registered exactly once
echo ""
echo "✓ Verifying MCP server registrations..."
MCP_FILES=$(find core/mcp -maxdepth 1 \( -name '*_server.py' -o -name 'update_checker.py' \) -print | sort)
TEMPLATE_FILES=$(python3 - <<'PY'
import json
from pathlib import Path

config = json.loads(Path("System/.mcp.json.example").read_text(encoding="utf-8"))
prefix = "{{VAULT_PATH}}/"
for server in config.get("mcpServers", {}).values():
    for arg in server.get("args", []):
        if isinstance(arg, str) and arg.startswith(prefix + "core/mcp/"):
            print(arg.removeprefix(prefix))
PY
)
TEMPLATE_FILES=$(printf '%s\n' "$TEMPLATE_FILES" | sort)

if [ "$MCP_FILES" != "$TEMPLATE_FILES" ]; then
    echo "  ❌ ERROR: MCP server files and template registrations differ"
    MISSING_REGISTRATIONS=$(comm -23 <(printf '%s\n' "$MCP_FILES") <(printf '%s\n' "$TEMPLATE_FILES"))
    MISSING_FILES=$(comm -13 <(printf '%s\n' "$MCP_FILES") <(printf '%s\n' "$TEMPLATE_FILES"))
    if [ -n "$MISSING_REGISTRATIONS" ]; then
        echo "     Unregistered server files:"
        echo "$MISSING_REGISTRATIONS" | sed 's/^/       /'
    fi
    if [ -n "$MISSING_FILES" ]; then
        echo "     Missing or duplicate server files referenced by the template:"
        echo "$MISSING_FILES" | sed 's/^/       /'
    fi
    ERRORS=$((ERRORS + 1))
else
    MCP_COUNT=$(printf '%s\n' "$MCP_FILES" | wc -l | tr -d ' ')
    echo "  ✅ All $MCP_COUNT MCP server files match the template exactly"
fi

# Check 10: Tracked integration templates must not enable personal integrations
echo ""
echo "✓ Checking integration templates contain no personal enabled state..."
INTEGRATION_STATE_VIOLATIONS=$(python3 - <<'PY'
import re
import subprocess
from pathlib import Path

tracked = subprocess.run(
    ["git", "ls-files", "--", "System/integrations/*.yaml"],
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines()

for filename in tracked:
    enabled_block_indent = None
    hooks_block_indent = None
    for line_number, raw_line in enumerate(
        Path(filename).read_text(encoding="utf-8").splitlines(), start=1
    ):
        content = raw_line.split("#", 1)[0].rstrip()
        if not content.strip() or ":" not in content:
            continue

        indent = len(content) - len(content.lstrip())
        key, value = content.lstrip().split(":", 1)
        key = key.strip()
        value = value.strip()

        if enabled_block_indent is not None and indent <= enabled_block_indent:
            enabled_block_indent = None
        if hooks_block_indent is not None and indent <= hooks_block_indent:
            hooks_block_indent = None

        normalized = value.strip("'\"").lower()
        is_true = normalized == "true"
        inline_true = bool(re.search(r"(?i)(?<![A-Za-z0-9_])true(?![A-Za-z0-9_])", value))
        enabled_true = bool(
            re.search(
                r"(?i)(?:^|[,{\s])['\"]?enabled['\"]?\s*:\s*true(?![A-Za-z0-9_])",
                content,
            )
        )
        violation = enabled_true or (
            is_true
            and (
                key == "enabled"
                or enabled_block_indent is not None
                or hooks_block_indent is not None
            )
        )
        if key in {"enabled", "hooks"} and value and inline_true:
            violation = True

        if violation:
            print(f"{filename}:{line_number}:{raw_line}")

        if not value and key == "enabled":
            enabled_block_indent = indent
        if not value and key == "hooks":
            hooks_block_indent = indent
PY
)
if [ -n "$INTEGRATION_STATE_VIOLATIONS" ]; then
    echo "  ❌ ERROR: Tracked integration templates contain enabled integrations or hooks:"
    echo "$INTEGRATION_STATE_VIOLATIONS" | sed 's/^/     /'
    echo "     Keep shipped templates off; /integrate-mcp populates each user's local state."
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ Tracked integration templates are safely disabled"
fi

# Check 11: Personal paths in .mcp.json (if exists)
if [ -f ".mcp.json" ]; then
    echo ""
    echo "✓ Checking local .mcp.json doesn't contain personal paths..."
    if grep -q "/Users/dave" .mcp.json; then
        echo "  ℹ️  INFO: Your local .mcp.json has /Users/dave paths (this is fine - file is gitignored)"
    fi
fi

# Check 12: No hardcoded /Users/ paths in tracked code files
echo ""
echo "✓ Checking for hardcoded /Users/ paths in code..."
HARDCODED_PATHS=$(git ls-files -- '*.py' '*.ts' '*.cjs' '*.sh' | \
    xargs grep -n '/Users/' 2>/dev/null | \
    grep -v 'scripts/verify-distribution\.sh' | \
    grep -v 'scripts/check-path-consistency\.sh' | \
    grep -v '#.*/Users/' | \
    grep -v '//.*/Users/' || true)
if [ -n "$HARDCODED_PATHS" ]; then
    echo "  ❌ ERROR: Hardcoded /Users/ paths found in code:"
    echo "$HARDCODED_PATHS" | head -10 | sed 's/^/     /'
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ No hardcoded /Users/ paths in code"
fi

# Check 13: package.json version matches CHANGELOG latest
echo ""
echo "✓ Checking package.json version matches CHANGELOG..."
PKG_VERSION=$(grep '"version"' package.json | head -1 | sed 's/.*"version": *"\([^"]*\)".*/\1/')
CHANGELOG_VERSION=$(grep -m1 '^\#\# \[' CHANGELOG.md | sed 's/.*\[\([0-9][0-9.]*\)\].*/\1/')
if [ "$PKG_VERSION" != "$CHANGELOG_VERSION" ]; then
    echo "  ⚠️  WARNING: package.json ($PKG_VERSION) != CHANGELOG ($CHANGELOG_VERSION)"
    WARNINGS=$((WARNINGS + 1))
else
    echo "  ✅ Versions match: $PKG_VERSION"
fi

# Check 14: All MCP servers in .mcp.json.example exist as files
echo ""
echo "✓ Checking MCP server files exist..."
MCP_MISSING=0
if [ -f "System/.mcp.json.example" ]; then
    for server_path in $(grep -o '{{VAULT_PATH}}/core/mcp/[^"]*' System/.mcp.json.example | sed 's|{{VAULT_PATH}}/||'); do
        if [ ! -f "$server_path" ]; then
            echo "  ❌ ERROR: MCP server missing: $server_path"
            MCP_MISSING=$((MCP_MISSING + 1))
        fi
    done
    if [ $MCP_MISSING -gt 0 ]; then
        ERRORS=$((ERRORS + MCP_MISSING))
    else
        echo "  ✅ All MCP server files exist"
    fi
else
    echo "  ⚠️  WARNING: System/.mcp.json.example not found"
    WARNINGS=$((WARNINGS + 1))
fi

# Check 15: No hardcoded /Users/ paths in docs/config (.md, .yaml, .json)
# These ship to users and either break installs or leak personal paths.
echo ""
echo "✓ Checking for hardcoded /Users/ paths in docs/config..."
DOC_USER_PATHS=$(git ls-files -- '*.md' '*.yaml' '*.yml' '*.json' | \
    xargs grep -n '/Users/' 2>/dev/null | \
    grep -v 'env.example\|Distribution_Checklist\|DISTRIBUTION_READY\|verify-distribution' | \
    grep -vE '/Users/(your-name|your-username|username|testuser|you|name|<|\{)' || true)
if [ -n "$DOC_USER_PATHS" ]; then
    echo "  ❌ ERROR: Hardcoded /Users/ paths found in docs/config:"
    echo "$DOC_USER_PATHS" | head -10 | sed 's/^/     /'
    echo "     Use \$CLAUDE_PROJECT_DIR, ~/your-vault, or a placeholder instead."
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ No hardcoded /Users/ paths in docs/config"
fi

# Check 16: Scripts that docs tell Dex to RUN must exist.
# Catches "instruction shipped, implementation didn't" (e.g. auto-link-people.cjs).
# Only matches runnable invocations (node/bash/sh/python <path>) of Dex-owned
# dirs (.scripts/.claude/core) — prose mentions of a filename are ignored.
echo ""
echo "✓ Checking referenced runnable scripts exist..."
# Keep in sync with core/tests/test_skill_integrity.py MISSING_RUNNABLE_ALLOWLIST.
MISSING_RUNNABLE_ALLOWLIST=(
    ".scripts/improve-prompt.cjs"
    ".scripts/mcp/gmail-mcp.js"
)
MISSING_RUN=$(git grep -hoE '(node|bash|sh|python3?)[[:space:]]+(\./)?(\.scripts|\.claude|core)/[A-Za-z0-9_./-]+\.(cjs|js|sh|py)' -- '*.md' 2>/dev/null \
    | grep -oE '(\.scripts|\.claude|core)/[A-Za-z0-9_./-]+\.(cjs|js|sh|py)' \
    | sort -u | while read -r p; do if [ ! -e "$p" ]; then echo "$p"; fi; done || true)
MISSING_REQUIRED_RUN=""
if [ -n "$MISSING_RUN" ]; then
    while IFS= read -r p; do
        ALLOWLISTED=false
        for allowed in "${MISSING_RUNNABLE_ALLOWLIST[@]}"; do
            if [ "$p" = "$allowed" ]; then
                ALLOWLISTED=true
                break
            fi
        done
        if [ "$ALLOWLISTED" = true ]; then
            echo "  ℹ️  INFO: Optional referenced script is not shipped: $p"
        elif [ -z "$MISSING_REQUIRED_RUN" ]; then
            MISSING_REQUIRED_RUN="$p"
        else
            MISSING_REQUIRED_RUN="${MISSING_REQUIRED_RUN}"$'\n'"$p"
        fi
    done <<< "$MISSING_RUN"
fi
if [ -n "$MISSING_REQUIRED_RUN" ]; then
    echo "  ❌ ERROR: Docs tell Dex to run scripts that don't exist:"
    echo "$MISSING_REQUIRED_RUN" | sed 's/^/     /'
    echo "     Either ship the script or remove the instruction."
    ERRORS=$((ERRORS + 1))
else
    echo "  ✅ All required referenced runnable scripts exist"
fi

# Check 17: A real release build contains no test suites.
echo ""
echo "✓ Verifying release branch strips all test suites..."
RELEASE_CHECK_DIR=$(mktemp -d)
RELEASE_CHECK_REPO="$RELEASE_CHECK_DIR/repo"
if git clone --local --no-hardlinks --quiet "$PWD" "$RELEASE_CHECK_REPO" \
    && git -C "$RELEASE_CHECK_REPO" config user.name "Dex Distribution Check" \
    && git -C "$RELEASE_CHECK_REPO" config user.email "distribution@example.com" \
    && git -C "$RELEASE_CHECK_REPO" checkout -B main HEAD --quiet \
    && bash "$RELEASE_CHECK_REPO/scripts/build-release.sh" >/dev/null; then
    RELEASE_TEST_FILES=$(git -C "$RELEASE_CHECK_REPO" ls-tree -r --name-only release -- \
        core/tests core/mcp/tests core/migrations/tests .claude/hooks/tests)
    if [ -n "$RELEASE_TEST_FILES" ]; then
        echo "  ❌ ERROR: Test files found in generated release branch:"
        echo "$RELEASE_TEST_FILES" | sed 's/^/     /'
        ERRORS=$((ERRORS + 1))
    else
        echo "  ✅ Generated release branch contains no test suites"
    fi
else
    echo "  ❌ ERROR: Could not build a temporary release branch"
    ERRORS=$((ERRORS + 1))
fi
rm -rf "$RELEASE_CHECK_DIR"

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
