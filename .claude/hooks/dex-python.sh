#!/usr/bin/env bash
# Run a Dex Python hook with the interpreter that has Dex's dependencies.
#
# install.sh puts PyYAML and the rest of Dex's Python packages into the vault's
# private .venv. A bare `python3` is whatever comes first on PATH, and a system
# Python upgrade (for example Homebrew moving to a new minor version) drops
# those packages, which silently disabled update detection (DEX-242).
#
# Order: $DEX_PYTHON, the vault .venv (macOS/Linux, then Windows), then the
# system python3 / python / py -3 so a vault without a .venv keeps working.

VAULT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

if [[ -n "${DEX_PYTHON:-}" && -x "${DEX_PYTHON}" ]]; then
    exec "$DEX_PYTHON" "$@"
fi
if [[ -x "$VAULT_DIR/.venv/bin/python" ]]; then
    exec "$VAULT_DIR/.venv/bin/python" "$@"
fi
if [[ -x "$VAULT_DIR/.venv/Scripts/python.exe" ]]; then
    exec "$VAULT_DIR/.venv/Scripts/python.exe" "$@"
fi
if command -v python3 >/dev/null 2>&1; then
    exec python3 "$@"
fi
if command -v python >/dev/null 2>&1; then
    exec python "$@"
fi
if command -v py >/dev/null 2>&1; then
    exec py -3 "$@"
fi
echo "Dex: no Python interpreter found (looked for .venv, python3, python, py)." >&2
exit 127
