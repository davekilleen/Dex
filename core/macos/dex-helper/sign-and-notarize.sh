#!/bin/bash
# Sign, notarise, staple, and verify Dex Helper on the Mac that holds the certificate.
#
# This is the local Developer ID path. It is not CI, does not publish,
# does not tag, and never reads Apple secrets from the repo. The notary
# password lives in the keychain profile named `dex-notary`.
#
# Repo path assumptions — run from the Dex checkout root, or from this
# directory. Examples (replace the checkout path with yours):
#
#   cd ~/Dex
#   bash core/macos/dex-helper/sign-and-notarize.sh
#
#   cd ~/Dex/core/macos/dex-helper
#   bash sign-and-notarize.sh
#
# One-time prerequisites on this Mac:
#   1. Xcode command-line tools (`xcode-select --install` if needed)
#   2. Certificate "Developer ID Application: DAVID EDWARD KILLEEN (6WVLPMNTL5)"
#      in the login keychain
#   3. notarytool profile stored once:
#        xcrun notarytool store-credentials dex-notary
set -euo pipefail

IDENTITY="Developer ID Application: DAVID EDWARD KILLEEN (6WVLPMNTL5)"
NOTARY_PROFILE="dex-notary"
ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$ROOT/../../.." && pwd)"
OUT="${DEX_HELPER_BUILD_DIR:-$ROOT/build}"
APP="$OUT/Dex Helper.app"
ZIP="$OUT/DexHelper.zip"
ENTITLEMENTS="$ROOT/DexHelper.entitlements"
BUILD_SCRIPT="$ROOT/build.sh"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
VERSIONED_ZIP="$OUT/DexHelper-v${VERSION}.zip"
CHECKSUM="$OUT/DexHelper-v${VERSION}.zip.sha256"

fail() {
  echo "error: $*" >&2
  exit 1
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "sign-and-notarize.sh must run on a Mac. Current OS is $(uname -s)."
fi

command -v codesign >/dev/null 2>&1 || fail "codesign is not on PATH."
command -v ditto >/dev/null 2>&1 || fail "ditto is not on PATH."
command -v spctl >/dev/null 2>&1 || fail "spctl is not on PATH."
xcrun --find notarytool >/dev/null 2>&1 || fail "xcrun notarytool is not available."
xcrun --find stapler >/dev/null 2>&1 || fail "xcrun stapler is not available."
[[ -f "$BUILD_SCRIPT" ]] || fail "missing $BUILD_SCRIPT"
[[ -f "$ENTITLEMENTS" ]] || fail "missing $ENTITLEMENTS"

if ! security find-identity -v -p codesigning 2>/dev/null | grep -F -q "$IDENTITY"; then
  fail "signing identity not found in the keychain: $IDENTITY"
fi

echo "==> 1. Build Dex Helper"
DEX_HELPER_REQUIRE_UNIVERSAL=1 bash "$BUILD_SCRIPT"
[[ -d "$APP" ]] || fail "build did not produce $APP"

echo "==> 2. codesign with hardened runtime and Calendar/Reminders entitlements"
codesign --force --options runtime --timestamp \
  --entitlements "$ENTITLEMENTS" \
  --sign "$IDENTITY" \
  "$APP/Contents/MacOS/DexHelper"
codesign --force --options runtime --timestamp \
  --entitlements "$ENTITLEMENTS" \
  --sign "$IDENTITY" \
  "$APP"

echo "==> 3. Zip and notarise (keychain profile: $NOTARY_PROFILE)"
rm -f "$ZIP" "$VERSIONED_ZIP" "$CHECKSUM"
ditto -c -k --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" --keychain-profile dex-notary --wait

echo "==> 4. Staple"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

echo "==> 5. Zip the stapled app and write checksum"
ditto -c -k --keepParent "$APP" "$ZIP"
cp "$ZIP" "$VERSIONED_ZIP"
shasum -a 256 "$VERSIONED_ZIP" | awk '{print $1 "  DexHelper-v'"$VERSION"'.zip"}' > "$CHECKSUM"

echo "==> 6. Verify"
codesign --verify --deep --strict --verbose=2 "$APP"
spctl --assess --type execute -vv "$APP"

echo
echo "Signed, notarised, stapled helper:"
echo "  app: $APP"
echo "  zip: $ZIP"
echo "  versioned zip: $VERSIONED_ZIP"
echo "  sha256: $(cut -d ' ' -f1 "$CHECKSUM") ($CHECKSUM)"
echo "  identity: $IDENTITY"
echo "  bundle id: ai.heydex.DexHelper"
echo "This script does not publish, tag, or create a GitHub release."
echo "Repo root used: $REPO_ROOT"
