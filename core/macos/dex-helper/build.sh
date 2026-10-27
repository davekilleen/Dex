#!/bin/bash
# Build an unsigned Dex Helper.app for local use and tests.
# Signing and notarizing are a separate release step. This script must never
# call codesign, notarytool, or stapler, and must never read signing secrets.
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

if ! command -v swiftc >/dev/null 2>&1; then
  echo "swiftc not found; skipping unsigned helper build."
  exit 0
fi

rm -rf "$APP"
mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
cp "$ROOT/Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"

# Unsigned on purpose. Do not add codesign here.
ARCH="$(uname -m)"
swiftc \
  -O \
  -target "${ARCH}-apple-macos14.0" \
  -sdk "$(xcrun --show-sdk-path --sdk macosx)" \
  -framework EventKit \
  -framework Foundation \
  -o "$MACOS_DIR/DexHelper" \
  "$ROOT/Sources/main.swift"

chmod 755 "$MACOS_DIR/DexHelper"
echo "Built unsigned helper at $APP"
