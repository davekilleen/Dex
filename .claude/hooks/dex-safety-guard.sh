#!/bin/bash
# Dex Safety Guard — PreToolUse hook.
# The shared Python gate owns destructive-command and path decisions. The only
# Claude-specific rule left here is the configured scraper preference.
# Exit 0 = allow, exit 2 = block.

INPUT=$(/bin/cat)

HOOK_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
SAFETY_PY="$HOOK_DIR/../../core/gates/safety.py"
PYTHON_CMD=()
if [[ -n "${DEX_PYTHON:-}" && -x "$DEX_PYTHON" ]]; then
    PYTHON_CMD=("$DEX_PYTHON")
elif [[ -n "$CLAUDE_PROJECT_DIR" && -x "$CLAUDE_PROJECT_DIR/.venv/bin/python" ]]; then
    PYTHON_CMD=("$CLAUDE_PROJECT_DIR/.venv/bin/python")
elif [[ -n "$CLAUDE_PROJECT_DIR" && -x "$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe" ]]; then
    PYTHON_CMD=("$CLAUDE_PROJECT_DIR/.venv/Scripts/python.exe")
elif [[ -x "$HOOK_DIR/../../.venv/bin/python" ]]; then
    PYTHON_CMD=("$HOOK_DIR/../../.venv/bin/python")
elif [[ -x "$HOOK_DIR/../../.venv/Scripts/python.exe" ]]; then
    PYTHON_CMD=("$HOOK_DIR/../../.venv/Scripts/python.exe")
elif command -v py >/dev/null 2>&1 && py -3 -c "raise SystemExit(0)" >/dev/null 2>&1; then
    PYTHON_CMD=(py -3)
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD=(python)
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD=(python3)
fi

# === CLAUDE-ONLY MATCHER (not a shared interceptor) ===
TOOL_LOWER=""
if [[ "${#PYTHON_CMD[@]}" -gt 0 ]]; then
    TOOL_LOWER=$(printf '%s' "$INPUT" | "${PYTHON_CMD[@]}" -c '
import json
import sys
try:
    data = json.loads(sys.stdin.read())
    print(str(data.get("tool_name", "")).lower())
except Exception:
    print("")
' 2>/dev/null)
else
    case "$INPUT" in
        *mcp__firecrawl__*|*mcp__rag-web-browser__*|*mcp__rag_web_browser__*)
            echo "WRONG SCRAPER: Scrapling is the configured default."
            exit 2
            ;;
    esac
fi

case "$TOOL_LOWER" in
    mcp__firecrawl__*|mcp__rag-web-browser__*|mcp__rag_web_browser__*)
        echo "WRONG SCRAPER: Scrapling is the configured default. Use scrapling get/fetch/stealthy_fetch instead of $TOOL_LOWER."
        exit 2
        ;;
esac

# A missing helper or interpreter is a hook failure, not a shared gate result;
# preserve fail-open so this file stays a thin wrapper around the Python gate.
if [[ ! -f "$SAFETY_PY" ]]; then
    exit 0
fi
if [[ "${#PYTHON_CMD[@]}" -eq 0 ]]; then
    exit 0
fi

SAFETY_ARGS=(--hook)
if [[ -n "$CLAUDE_PROJECT_DIR" ]]; then
    SAFETY_ARGS+=(--vault "$CLAUDE_PROJECT_DIR")
fi
printf '%s' "$INPUT" | "${PYTHON_CMD[@]}" "$SAFETY_PY" "${SAFETY_ARGS[@]}"
STATUS=$?
if [[ "$STATUS" -eq 2 ]]; then
    exit 2
fi
exit 0
