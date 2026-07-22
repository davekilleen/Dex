#!/bin/bash

if [[ ! -f "${CLAUDE_PROJECT_DIR:-$PWD}/scripts/generate-architecture-inventory.py" ]]; then
    exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
DEDUP_FILE="${DEX_CORE_ORIENTATION_DEDUP_FILE:-/tmp/dex-core-orientation-dedup}"
NOW=$(date +%s)
if [[ -f "$DEDUP_FILE" ]]; then
    LAST=$(cat "$DEDUP_FILE" 2>/dev/null || echo "0")
    if (( NOW - LAST < 5 )); then
        exit 0
    fi
fi
echo "$NOW" > "$DEDUP_FILE" 2>/dev/null || true

OUTPUT=$(python3 - "$PROJECT_DIR/scripts/dex_state.py" "${DEX_CORE_ORIENTATION_TIMEOUT_SECONDS:-5}" <<'PY' 2>/dev/null
import subprocess
import sys

try:
    timeout = float(sys.argv[2])
    if timeout <= 0:
        timeout = 5.0
    result = subprocess.run(
        [sys.executable, sys.argv[1], "--digest"],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
except (OSError, ValueError, subprocess.TimeoutExpired):
    raise SystemExit(0)

if result.returncode == 0:
    sys.stdout.write(result.stdout)
PY
) || true

if [[ -n "$OUTPUT" ]]; then
    printf '%s\n' "$OUTPUT"
fi

exit 0
