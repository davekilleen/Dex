#!/bin/bash
# Dex Safety Guard — PreToolUse hook
# Thin wrapper: Claude-only scraper matcher stays here. Destructive commands
# and unsafe paths are refused by core/gates/safety.py — the same module Work
# MCP check_safety_gate calls. Exit 0 = allow, Exit 2 = block.

INPUT=$(cat)

# Extract tool name for the Claude-only scraper matcher. Interceptors do not
# live in this file; do not reimplement rm / git / path checks here.
TOOL_LOWER=$(printf '%s' "$INPUT" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    print(str(data.get('tool_name', '')).lower())
except Exception:
    print('')
" 2>/dev/null)

# === CLAUDE-ONLY MATCHER (not an interceptor; not in core/gates) ===
# Scrapling is the preferred configured scraper. Block unsafe scraper MCPs while
# leaving native WebFetch available as the fallback when Scrapling is absent.

case "$TOOL_LOWER" in
    mcp__firecrawl__*|mcp__rag-web-browser__*|mcp__rag_web_browser__*)
        echo "WRONG SCRAPER: Scrapling is the configured default. Use scrapling get/fetch/stealthy_fetch instead of $TOOL_LOWER."
        exit 2
        ;;
esac

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAFETY_PY="$HOOK_DIR/../../core/gates/safety.py"
PYTHON="python3"
if [[ -n "$CLAUDE_PROJECT_DIR" && -f "$CLAUDE_PROJECT_DIR/.venv/bin/python" ]]; then
    PYTHON="$CLAUDE_PROJECT_DIR/.venv/bin/python"
elif [[ -f "$HOOK_DIR/../../.venv/bin/python" ]]; then
    PYTHON="$HOOK_DIR/../../.venv/bin/python"
fi

if [[ ! -f "$SAFETY_PY" ]]; then
    exit 0
fi

printf '%s' "$INPUT" | "$PYTHON" "$SAFETY_PY" --hook
STATUS=$?
# Exit 2 is a refusal from the shared gate. Any other failure (missing
# interpreter, import error) fails open, matching other Claude Code hooks.
if [[ "$STATUS" -eq 2 ]]; then
    exit 2
fi
exit 0
