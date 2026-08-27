#!/usr/bin/env bash
# Local preview installer for /setup-lab. Does not patch shipped /setup.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-"$HOME/Dex-lab-onboarding"}"

mkdir -p "$TARGET"
if [ ! -d "$TARGET/.git" ] && [ "$TARGET" != "$ROOT" ]; then
  echo "Copying this Dex tree into $TARGET (throwaway preview vault)."
  rsync -a --delete \
    --exclude '.git' \
    --exclude 'System/.onboarding-complete' \
    --exclude 'System/.onboarding-session.json' \
    --exclude 'System/.onboarding-lab' \
    "$ROOT/" "$TARGET/"
fi

if [ -f "$TARGET/CLAUDE.md" ]; then
  python3 - <<'PY' "$TARGET/CLAUDE.md"
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
start = "## USER_EXTENSIONS_START"
end = "## USER_EXTENSIONS_END"
note = (
    "<!-- lab preview -->\n"
    "This is a preview vault. First setup is `/setup-lab`, not `/setup`.\n"
    "Do not follow `.claude/flows/onboarding.md` here.\n"
)
if start in text and end in text and "lab preview" not in text:
    text = text.replace(start, start + "\n" + note, 1)
    path.write_text(text, encoding="utf-8")
PY
fi

echo
echo "Preview vault: $TARGET"
echo "Open that folder in Claude, Codex, or Cursor and type /setup-lab"
echo "Shipped /setup is unchanged."
