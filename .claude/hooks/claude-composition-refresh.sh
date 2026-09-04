#!/bin/bash
# Keep CLAUDE.md in step with CLAUDE-custom.md — runs on every user message.
#
# Why every message rather than a session boundary: composition previously ran
# only inside the update transaction, so a personal instruction did nothing
# until the next update. Anything tied to a boundary event inherits the user's
# habits — and this is already a bug about inheriting the user's habits. A
# session-end trigger was tried first and rejected: it does not fire once
# during a long working session, which is exactly when people edit their
# instructions.
#
# Hard rules, matching health-pulse.sh:
#   - The everyday path is two stat calls in bash builtins. No forks, no
#     interpreter start, nothing to notice.
#   - Python starts ONLY when CLAUDE-custom.md is genuinely newer. On this
#     machine that was three times in eight hours; an interpreter start costs
#     ~19 ms against a model round-trip measured in hundreds.
#   - Any failure is silent. exit 0 always. A vault that cannot recompose is
#     no worse off than before this hook existed, and /dex-doctor reports it.
#   - Never a partial write: the Python side composes to a temp file and
#     renames, so a half-written instruction file is impossible.
#   - Never a competing write: the Python side takes the vault mutation lock
#     before composing, and gives up quietly if another Dex process holds it.
#     An update composes CLAUDE.md itself, so nothing is lost by waiting, and
#     racing it would overwrite the new file using the old release template.
#   - This path is mtime-gated, so it cannot repair a CLAUDE.md that is newer
#     than the custom block and still wrong. That case is Doctor's, which
#     forces on bytes. Do not point a user here to fix drift.

{
    CLAUDE_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"
    CLAUDE_FILE="$CLAUDE_DIR/CLAUDE.md"
    CUSTOM_FILE="$CLAUDE_DIR/CLAUDE-custom.md"
    HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    DEX_REPO_DIR="$(cd "$HOOK_DIR/../.." && pwd)"

    DEX_PYTHON_CMD=()
    if [[ -n "${DEX_PYTHON:-}" && -x "$DEX_PYTHON" ]]; then
        DEX_PYTHON_CMD=("$DEX_PYTHON")
    elif [[ -x "$CLAUDE_DIR/.venv/bin/python" ]]; then
        DEX_PYTHON_CMD=("$CLAUDE_DIR/.venv/bin/python")
    elif [[ -x "$CLAUDE_DIR/.venv/Scripts/python.exe" ]]; then
        DEX_PYTHON_CMD=("$CLAUDE_DIR/.venv/Scripts/python.exe")
    elif [[ -x "$DEX_REPO_DIR/.venv/bin/python" ]]; then
        DEX_PYTHON_CMD=("$DEX_REPO_DIR/.venv/bin/python")
    elif [[ -x "$DEX_REPO_DIR/.venv/Scripts/python.exe" ]]; then
        DEX_PYTHON_CMD=("$DEX_REPO_DIR/.venv/Scripts/python.exe")
    elif command -v py >/dev/null 2>&1 && py -3 -c "raise SystemExit(0)" >/dev/null 2>&1; then
        DEX_PYTHON_CMD=(py -3)
    elif command -v python >/dev/null 2>&1; then
        DEX_PYTHON_CMD=(python)
    elif command -v python3 >/dev/null 2>&1; then
        DEX_PYTHON_CMD=(python3)
    else
        exit 0
    fi

    # No custom block is a valid state, not drift.
    [ -f "$CUSTOM_FILE" ] || exit 0

    # The cheap gate. If CLAUDE.md is absent the composer should run; otherwise
    # compare modification times only. Deliberately imprecise: a touch with no
    # content change trips it, and the only cost is one recompose that finds
    # the bytes already correct and writes nothing.
    SNAPSHOT_FILE="$CLAUDE_DIR/System/.dex/claude-composed-baseline.md"
    if [ -f "$CLAUDE_FILE" ]; then
        # GNU stat first: on Linux, `stat -f %m` SUCCEEDS with filesystem
        # info (BSD -f means mtime, GNU -f means file system), so trying the
        # BSD form first silently broke this gate on every Linux vault.
        CUSTOM_MTIME=$(stat -c %Y "$CUSTOM_FILE" 2>/dev/null || stat -f %m "$CUSTOM_FILE" 2>/dev/null) || exit 0
        CLAUDE_MTIME=$(stat -c %Y "$CLAUDE_FILE" 2>/dev/null || stat -f %m "$CLAUDE_FILE" 2>/dev/null) || exit 0
        if ! [ "$CUSTOM_MTIME" -gt "$CLAUDE_MTIME" ] 2>/dev/null; then
            # Quiet tick. The direct-edit guard needs a record of what the
            # composer last wrote, and the one safe moment to create it
            # retroactively is while the live file still matches its expected
            # composition — so when that record is missing, start Python once
            # to write it. One extra stat on every later tick; the Python
            # start happens at most once per vault.
            [ -f "$SNAPSHOT_FILE" ] && exit 0
            (cd "$CLAUDE_DIR" && "${DEX_PYTHON_CMD[@]}" -c '
from pathlib import Path
from core.utils.claude_composition import _bootstrap_snapshot
_bootstrap_snapshot(Path("."))
' >/dev/null 2>&1) || true
            exit 0
        fi
    fi

    # Expensive path, reached only when the custom block has actually moved.
    RESULT=$(cd "$CLAUDE_DIR" && "${DEX_PYTHON_CMD[@]}" -c '
import sys
from pathlib import Path
from core.utils.claude_composition import recompose_if_needed
print(recompose_if_needed(Path(".")))
' 2>/dev/null) || exit 0

    # Say something only when the file actually changed. The user asked for a
    # customisation and was told it was made; telling them it is now live
    # closes that loop. Silence on "current" and on any unavailable reason —
    # /dex-doctor owns reporting the broken case, not this hook.
    case "$RESULT" in
        recomposed)
            echo "📝 Your CLAUDE.md customisations have been applied and are now live."
            ;;
    esac
    exit 0
} 2>/dev/null || exit 0
