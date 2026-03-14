#!/usr/bin/env bash
# Generate an installed-files manifest for the current Dex version.
# Output: System/.installed-files.manifest
#
# The manifest lists every tracked file with its SHA-256 hash so that
# /dex-rollback can detect files added by an update and clean them up.

set -euo pipefail

MANIFEST="System/.installed-files.manifest"
VERSION=$(grep '"version"' package.json | head -1 | sed 's/.*"\([0-9][0-9.]*\)".*/\1/')

{
  echo "# Dex installed-files manifest"
  echo "# Version: ${VERSION}"
  echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "#"
  echo "# Format: <sha256>  <path>"
  git ls-files -z | xargs -0 shasum -a 256
} > "$MANIFEST"

echo "Wrote ${MANIFEST} ($(wc -l < "$MANIFEST" | tr -d ' ') entries, v${VERSION})"
