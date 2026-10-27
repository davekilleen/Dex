#!/bin/bash
# Build Dex Helper.app for local use.
# Dev path: ad-hoc sign with `codesign --sign -`. Rebuilding resets the
# Calendar and Reminders grant. Developer ID + notarization is a later
# release step that needs explicit founder approval and must never read
# signing secrets from this script or the repo.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${DEX_HELPER_BUILD_DIR:-$ROOT/build}"
APP="$OUT/Dex Helper.app"
MACOS_DIR="$APP/Contents/MacOS"
RESOURCES_DIR="$APP/Contents/Resources"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Skipping Dex Helper build (macOS only)."
  exit 0
fi

rm -rf "$APP"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
cp "$ROOT/Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"
cp "$ROOT/DexHelper.py" "$MACOS_DIR/DexHelper"
chmod 755 "$MACOS_DIR/DexHelper"

# Point the installed app at this Dex tree so EventKit ops stay shared.
if [[ -n "${DEX_HELPER_CORE_ROOT:-}" ]]; then
  printf '%s\n' "$DEX_HELPER_CORE_ROOT" > "$RESOURCES_DIR/dex-root.txt"
else
  printf '%s\n' "$(cd "$ROOT/../../.." && pwd)" > "$RESOURCES_DIR/dex-root.txt"
fi

# Ad-hoc sign so LaunchServices will open the app. Not Developer ID.
# Equivalent to `codesign -s -`. Rebuilding this app resets Calendar
# and Reminders permission.
if command -v codesign >/dev/null 2>&1; then
  codesign --force --sign - "$APP"
  echo "Ad-hoc signed helper at $APP (rebuilding resets the grant)."
else
  echo "Built helper at $APP without codesign (codesign not found)."
fi
