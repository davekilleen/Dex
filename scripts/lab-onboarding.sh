#!/usr/bin/env bash
# Practice-folder starter for /setup-lab. Does not patch shipped /setup.
# Finishes the behind-the-scenes setup so the first chat can say hello.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-"$HOME/Dex-lab-onboarding"}"

plain_fail() {
  echo
  echo "$1"
  echo "Nothing is wrong with your real Dex folder. Send Dave the last few lines if you want a hand."
  exit 1
}

copy_practice_tree() {
  mkdir -p "$TARGET"
  if [ ! -d "$TARGET/.git" ] && [ "$TARGET" != "$ROOT" ]; then
    echo "Making a practice copy in $TARGET."
    rsync -a --delete \
      --exclude '.git' \
      --exclude 'System/.onboarding-complete' \
      --exclude 'System/.onboarding-session.json' \
      --exclude 'System/.onboarding-lab' \
      "$ROOT/" "$TARGET/"
  fi
}

mark_first_command() {
  if [ -f "$TARGET/CLAUDE.md" ]; then
    python3 - <<'PY' "$TARGET/CLAUDE.md"
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
start = "## USER_EXTENSIONS_START"
note = (
    "<!-- lab preview -->\n"
    "This is a practice folder. First setup is `/setup-lab`, not `/setup`.\n"
    "Do not follow `.claude/flows/onboarding.md` here.\n"
)
if start in text and "## USER_EXTENSIONS_END" in text and "lab preview" not in text:
    path.write_text(text.replace(start, start + "\n" + note, 1), encoding="utf-8")
PY
  fi
}

practice_ready() {
  local python_bin=""
  if [ -x "$TARGET/.venv/bin/python" ]; then
    python_bin="$TARGET/.venv/bin/python"
  elif [ -x "$TARGET/.venv/Scripts/python.exe" ]; then
    python_bin="$TARGET/.venv/Scripts/python.exe"
  fi
  [ -n "$python_bin" ] || return 1
  "$python_bin" -c "import mcp, yaml" >/dev/null 2>&1 || return 1
  [ -f "$TARGET/.mcp.json" ] || return 1
  grep -q '"onboarding-mcp"' "$TARGET/.mcp.json" || return 1
  return 0
}

bootstrap_practice_folder() {
  if practice_ready; then
    echo "Practice folder is already ready."
    return 0
  fi

  echo "Finishing the behind-the-scenes setup so the first chat can say hello..."

  if ! command -v node >/dev/null 2>&1; then
    plain_fail "This Mac needs Node.js 18+ from https://nodejs.org/ before the practice folder can start."
  fi

  local python_cmd=""
  if command -v python3 >/dev/null 2>&1; then
    python_cmd="python3"
  elif command -v python >/dev/null 2>&1; then
    python_cmd="python"
  fi
  [ -n "$python_cmd" ] || plain_fail "This Mac needs Python 3.10+ from https://www.python.org/downloads/ before the practice folder can start."

  (
    cd "$TARGET"
    if [ ! -d node_modules/js-yaml ]; then
      if command -v npm >/dev/null 2>&1; then
        npm install --silent
      else
        plain_fail "This Mac needs npm (it usually arrives with Node.js) before the practice folder can start."
      fi
    fi

    local venv_python=".venv/bin/python"
    local venv_pip=".venv/bin/pip"
    if [ ! -x "$venv_python" ]; then
      "$python_cmd" -m venv .venv || plain_fail "Could not create the small Python folder Dex uses. Try again, or send Dave the last few lines."
    fi
    "$venv_pip" install -r core/mcp/requirements.txt --quiet || \
      plain_fail "Could not install what Dex needs. Try again, or send Dave the last few lines."

    node core/provision.cjs --path "$TARGET" --install-config-only --json >/dev/null || \
      plain_fail "Could not point this folder at Dex's helpers. Try again, or send Dave the last few lines."
  )

  practice_ready || plain_fail "The practice folder is still not ready. Try the starter once more, or send Dave the last few lines."
}

copy_practice_tree
mark_first_command
bootstrap_practice_folder

echo
echo "Practice folder is ready: $TARGET"
echo
echo "Next:"
echo "1. Quit Claude if this folder is already open"
echo "2. Open Claude on this folder"
echo "3. Type /setup-lab"
echo
echo "You should hear a hello first. Your real Dex folder is untouched."
