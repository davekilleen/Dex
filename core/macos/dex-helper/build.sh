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
REQUIRE_UNIVERSAL="${DEX_HELPER_REQUIRE_UNIVERSAL:-1}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Skipping Dex Helper build (macOS only)."
  exit 0
fi

rm -rf "$APP"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
cp "$ROOT/Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"

cd "$ROOT"
swift build -c release --arch arm64 --product DexHelper

ARM_BIN=""
for candidate in \
  "$ROOT/.build/arm64-apple-macosx/release/DexHelper" \
  "$ROOT/.build/release/DexHelper"
do
  if [[ -x "$candidate" ]]; then
    ARM_BIN="$candidate"
    break
  fi
done
[[ -n "$ARM_BIN" ]] || { echo "error: arm64 DexHelper binary was not built" >&2; exit 1; }

X86_BIN=""
if swift build -c release --arch x86_64 --product DexHelper; then
  for candidate in \
    "$ROOT/.build/x86_64-apple-macosx/release/DexHelper" \
    "$ROOT/.build/release/DexHelper"
  do
    if [[ -x "$candidate" && "$candidate" != "$ARM_BIN" ]]; then
      X86_BIN="$candidate"
      break
    fi
  done
  if [[ -z "$X86_BIN" && -x "$ROOT/.build/x86_64-apple-macosx/release/DexHelper" ]]; then
    X86_BIN="$ROOT/.build/x86_64-apple-macosx/release/DexHelper"
  fi
fi

if [[ -n "$X86_BIN" && -x "$X86_BIN" && "$X86_BIN" != "$ARM_BIN" ]]; then
  lipo -create "$ARM_BIN" "$X86_BIN" -output "$MACOS_DIR/DexHelper"
elif [[ "$REQUIRE_UNIVERSAL" == "1" ]]; then
  echo "error: could not build a universal DexHelper (arm64 + x86_64)" >&2
  exit 1
else
  cp "$ARM_BIN" "$MACOS_DIR/DexHelper"
fi
chmod 755 "$MACOS_DIR/DexHelper"

# Ad-hoc sign so LaunchServices will open the app. Not Developer ID.
# Equivalent to `codesign -s -`. Rebuilding this app resets Calendar
# and Reminders permission.
if command -v codesign >/dev/null 2>&1; then
  codesign --force --sign - --entitlements "$ROOT/DexHelper.entitlements" "$MACOS_DIR/DexHelper"
  codesign --force --sign - --entitlements "$ROOT/DexHelper.entitlements" "$APP"
  echo "Ad-hoc signed helper at $APP (rebuilding resets the grant)."
else
  echo "Built helper at $APP without codesign (codesign not found)."
fi
