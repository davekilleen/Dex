#!/usr/bin/env bash
# Practice-folder starter for /setup-lab. Does not patch shipped /setup.
# Finishes the behind-the-scenes setup so the first chat can say hello.
#
# Two ways to run it:
#   scripts/lab-onboarding.sh [target-folder]
#       Copies the Dex folder this script lives in into a practice folder.
#   scripts/lab-onboarding.sh --from-github[=branch] [target-folder]
#       Downloads a fresh copy of Dex from GitHub instead — nothing on this
#       computer is used as the source. This is the mode to give a tester who
#       already has their own Dex folder: the practice copy is brand new and
#       their real folder is never read or written. The branch defaults to main.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || pwd)"
GITHUB_REPO="davekilleen/Dex"

REMOTE_REF=""
TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from-github)
      REMOTE_REF="main"
      ;;
    --from-github=*)
      REMOTE_REF="${1#--from-github=}"
      ;;
    --help|-h)
      sed -n '2,14p' "${BASH_SOURCE[0]:-$0}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      TARGET="$1"
      ;;
  esac
  shift
done
TARGET="${TARGET:-"$HOME/Dex-lab-onboarding"}"

plain_fail() {
  echo
  echo "$1"
  echo "Nothing is wrong with your real Dex folder. Send Dave the last few lines if you want a hand."
  exit 1
}

is_practice_copy() {
  [ -f "$1/System/.onboarding-lab" ]
}

looks_like_a_real_vault() {
  # A folder someone actually finished setting up, or wrote notes into.
  [ -f "$1/System/.onboarding-complete" ] && grep -q '"user_name"' "$1/System/.onboarding-complete" 2>/dev/null && return 0
  [ -f "$1/System/user-profile.yaml" ] && ! is_practice_copy "$1" && return 0
  return 1
}

is_empty_dir() {
  [ -d "$1" ] && [ -z "$(ls -A "$1" 2>/dev/null)" ]
}

# Refuse before a single byte is written anywhere.
guard_target() {
  if looks_like_a_real_vault "$TARGET"; then
    plain_fail "That folder looks like a real Dex folder someone already uses: $TARGET
The practice starter never writes into a real Dex folder. Pick a new, empty folder
(or just run the starter with no folder name) and your real folder stays exactly as it is."
  fi
  if [ -e "$TARGET" ] && [ ! -d "$TARGET" ]; then
    plain_fail "That name already belongs to a file, not a folder: $TARGET
Pick a folder name that does not exist yet. Nothing was changed."
  fi
  if [ -d "$TARGET" ] && ! is_empty_dir "$TARGET" && ! is_practice_copy "$TARGET"; then
    if [ -n "$REMOTE_REF" ] || [ "$TARGET" != "$ROOT" ]; then
      plain_fail "That folder already has things in it: $TARGET
The practice starter only writes into a brand-new folder, or a practice folder it
made earlier. Pick a new name and everything you have stays exactly as it is."
    fi
  fi
}

download_fresh_copy() {
  command -v curl >/dev/null 2>&1 || plain_fail "This Mac needs curl before the practice folder can download."
  command -v tar >/dev/null 2>&1 || plain_fail "This Mac needs tar before the practice folder can download."
  STAGE="$(mktemp -d "${TMPDIR:-/tmp}/dex-lab-starter.XXXXXX")"
  trap 'rm -rf "$STAGE"' EXIT
  echo "Downloading a fresh copy of Dex ($REMOTE_REF)..."
  curl -fsSL "https://github.com/$GITHUB_REPO/archive/refs/heads/$REMOTE_REF.tar.gz" -o "$STAGE/dex.tar.gz" || \
    curl -fsSL "https://github.com/$GITHUB_REPO/archive/refs/tags/$REMOTE_REF.tar.gz" -o "$STAGE/dex.tar.gz" || \
    plain_fail "Could not download Dex from GitHub. Check the internet connection and try again."
  tar -xzf "$STAGE/dex.tar.gz" -C "$STAGE" || plain_fail "Could not unpack the downloaded copy. Try again."
  SOURCE="$(find "$STAGE" -mindepth 1 -maxdepth 1 -type d | head -1)"
  [ -n "$SOURCE" ] && [ -f "$SOURCE/core/provision.cjs" ] || \
    plain_fail "The downloaded copy is missing pieces. Try again, or send Dave the last few lines."
}

copy_practice_tree() {
  local source="$1"
  mkdir -p "$TARGET"
  if [ "$TARGET" = "$source" ]; then
    return 0
  fi
  local delete_flag=""
  if is_practice_copy "$TARGET"; then
    # Refreshing a practice copy the starter made earlier is the only time
    # anything in the target may be replaced.
    delete_flag="--delete"
  fi
  command -v rsync >/dev/null 2>&1 || \
    plain_fail "This computer needs rsync before the practice folder can be made. It comes with macOS; on Linux install it with your package manager."
  echo "Making a practice copy in $TARGET."
  rsync -a $delete_flag \
    --exclude '.git' \
    --exclude 'node_modules' \
    --exclude '.venv' \
    --exclude 'System/.onboarding-complete' \
    --exclude 'System/.onboarding-session.json' \
    --exclude 'System/.onboarding-lab' \
    "$source/" "$TARGET/"
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
  [ -d "$TARGET/node_modules/js-yaml" ] || return 1
  [ -d "$TARGET/05-Areas/People" ] || return 1
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
    if command -v npm >/dev/null 2>&1; then
      npm install --silent
    else
      plain_fail "This Mac needs npm (it usually arrives with Node.js) before the practice folder can start."
    fi

    local venv_python=".venv/bin/python"
    local venv_pip=".venv/bin/pip"
    if [ ! -x "$venv_python" ]; then
      "$python_cmd" -m venv .venv || plain_fail "Could not create the small Python folder Dex uses. Try again, or send Dave the last few lines."
    fi
    "$venv_pip" install -r core/mcp/requirements.txt --quiet || \
      plain_fail "Could not install what Dex needs. Try again, or send Dave the last few lines."

    DEX_PYTHON="$TARGET/.venv/bin/python" \
    DEX_LIFECYCLE_PYTHON="$TARGET/.venv/bin/python" \
    node core/provision.cjs --path "$TARGET" --json >/dev/null || \
      plain_fail "Could not finish a fresh Dex copy in this folder. Try again, or send Dave the last few lines."

    # Full provision writes a completion marker with no person on it. Remove
    # that skeleton so /setup-lab can still run the hour. Keep a finished
    # hour's marker (it names the person).
    if [ -f "$TARGET/System/.onboarding-complete" ] && \
       ! grep -q '"user_name"' "$TARGET/System/.onboarding-complete"; then
      rm -f "$TARGET/System/.onboarding-complete"
    fi
  )

  practice_ready || plain_fail "The practice folder is still not ready. Try the starter once more, or send Dave the last few lines."
}

guard_target

SOURCE="$ROOT"
if [ -n "$REMOTE_REF" ]; then
  download_fresh_copy
fi

copy_practice_tree "$SOURCE"
mark_first_command
mkdir -p "$TARGET/System"
if [ ! -f "$TARGET/System/.onboarding-lab" ]; then
  printf '%s\n' '{"lab": true}' > "$TARGET/System/.onboarding-lab"
fi
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
