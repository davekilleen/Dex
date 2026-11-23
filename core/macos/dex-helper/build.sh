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
ARM_BIN_COPY=""

cleanup() {
  if [[ -n "$ARM_BIN_COPY" && -e "$ARM_BIN_COPY" ]]; then
    rm -f "$ARM_BIN_COPY"
  fi
}
trap cleanup EXIT

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

ARM_DIR="$(swift build -c release --arch arm64 --show-bin-path)"
ARM_SRC="${ARM_DIR%/}/DexHelper"
[[ -x "$ARM_SRC" ]] || {
  echo "error: arm64 DexHelper binary was not built" >&2
  exit 1
}

# Swift 6.4+ writes every --arch build into the same Products/Release
# directory, so the x86_64 compile would overwrite the arm64 binary.
# Keep a copy, then ask Swift for each arch's path instead of guessing.
ARM_BIN_COPY="$(mktemp "${TMPDIR:-/tmp}/dex-helper-arm64.XXXXXX")"
cp "$ARM_SRC" "$ARM_BIN_COPY"
chmod 755 "$ARM_BIN_COPY"
ARM_BIN="$ARM_BIN_COPY"

X86_BIN=""
if swift build -c release --arch x86_64 --product DexHelper; then
  if X86_DIR="$(swift build -c release --arch x86_64 --show-bin-path)"; then
    X86_SRC="${X86_DIR%/}/DexHelper"
    if [[ -x "$X86_SRC" && "$X86_SRC" != "$ARM_BIN" ]]; then
      X86_BIN="$X86_SRC"
    fi
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
