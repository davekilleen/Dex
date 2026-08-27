#!/bin/bash
# Re-lock Dex's Python dependencies.
#
# pyproject.toml declares the version ranges Dex wants. This script turns those
# ranges into an exact, cross-platform lock and then writes the two requirements
# files that installers actually read, each pinned to exact versions with
# checksums so an installer can never pull a package that was published after
# the lock was made:
#
#   uv.lock                     the universal lock (macOS, Linux, Windows; 3.10+)
#   core/mcp/requirements.txt   runtime install.sh puts in .venv
#   requirements.txt            the same runtime plus the optional scraping extra
#
# Run this whenever pyproject.toml changes, or to deliberately take newer
# versions (add --upgrade). Commit the three generated files together.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv &> /dev/null; then
  echo "❌ uv is required to lock Python dependencies." >&2
  echo "   Install it with: pip install uv    (or see https://docs.astral.sh/uv/)" >&2
  exit 1
fi

UPGRADE=()
if [ "${1:-}" = "--upgrade" ]; then
  UPGRADE=(--upgrade)
fi

echo "🔒 Resolving pyproject.toml into uv.lock..."
uv lock "${UPGRADE[@]}"

# Prepend the "don't hand-edit this" note uv's own header doesn't carry.
prepend_header() {
  local target="$1"
  local title="$2"
  local tmp
  tmp="$(mktemp)"
  {
    echo "# $title"
    echo "#"
    echo "# GENERATED FILE — DO NOT EDIT BY HAND."
    echo "#"
    echo "# Every package below, direct and transitive, is pinned to one exact"
    echo "# version with checksums, so an install can only ever get this reviewed"
    echo "# set — never a release published after this file was generated."
    echo "#"
    echo "# To change a dependency: edit the version ranges in pyproject.toml, run"
    echo "# ./scripts/lock-python-deps.sh, and commit uv.lock alongside this file."
    cat "$target"
  } > "$tmp"
  mv "$tmp" "$target"
}

# --no-emit-project: Dex is a checkout, not a distribution — never emit `-e .`.
# --no-dev: development and CI packages are not part of a user install.
echo "📝 Writing core/mcp/requirements.txt (runtime)..."
uv export --frozen --no-dev --no-emit-project \
  --format requirements-txt \
  --output-file core/mcp/requirements.txt
prepend_header core/mcp/requirements.txt "Dex MCP server dependencies — what install.sh puts in .venv."

echo "📝 Writing requirements.txt (runtime + scraping)..."
uv export --frozen --no-dev --no-emit-project \
  --extra scraping \
  --format requirements-txt \
  --output-file requirements.txt
prepend_header requirements.txt "Dex dependencies — the MCP runtime plus the optional web-scraping extra."

echo "✅ Locked. Commit uv.lock, core/mcp/requirements.txt and requirements.txt together."
