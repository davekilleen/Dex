#!/bin/bash
# Dex Safety Guard — PreToolUse hook.
# The shared Python gate owns destructive-command and path decisions. The only
# Claude-specific rule left here is the configured scraper preference.
# Exit 0 = allow, exit 2 = block.

INPUT=$(cat)

# === CLAUDE-ONLY MATCHER (not a shared interceptor) ===
TOOL_LOWER=$(printf '%s' "$INPUT" | python3 -c '
import json
import sys
try:
    data = json.loads(sys.stdin.read())
    print(str(data.get("tool_name", "")).lower())
except Exception:
    print("")
' 2>/dev/null)

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

# A missing helper or interpreter is a hook failure, not a shared gate result;
# preserve the existing fail-open behavior while still enforcing real blocks.
if [[ ! -f "$SAFETY_PY" ]]; then
    exit 0
fi

SAFETY_ARGS=(--hook)
if [[ -n "$CLAUDE_PROJECT_DIR" ]]; then
    SAFETY_ARGS+=(--vault "$CLAUDE_PROJECT_DIR")
fi
printf '%s' "$INPUT" | "$PYTHON" "$SAFETY_PY" "${SAFETY_ARGS[@]}"
STATUS=$?
if [[ "$STATUS" -eq 2 ]]; then
    exit 2
fi
exit 0
