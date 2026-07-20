#!/bin/bash
# Build the self-contained release-shaped vault tree consumed by Dex Desktop.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="${1:-$REPO_ROOT/dist}"
DISTIGNORE="$REPO_ROOT/.distignore"

if [ ! -f "$DISTIGNORE" ]; then
  echo "Error: .distignore not found at $DISTIGNORE" >&2
  exit 1
fi

# Reject unsafe source inputs before staging or running npm.
python3 "$REPO_ROOT/scripts/check-tau-removal.py" --source-root "$REPO_ROOT"

VERSION="$(node -p "require('$REPO_ROOT/package.json').version")"
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
TARBALL="$OUTPUT_DIR/dex-vault-bundle-v$VERSION.tar.gz"
CHECKSUM="$TARBALL.sha256"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/dex-vault-bundle.XXXXXX")"
ALL_FILES="$(mktemp "${TMPDIR:-/tmp}/dex-vault-all.XXXXXX")"
EXCLUDED_FILES="$(mktemp "${TMPDIR:-/tmp}/dex-vault-excluded.XXXXXX")"
INCLUDED_FILES="$(mktemp "${TMPDIR:-/tmp}/dex-vault-included.XXXXXX")"
trap 'rm -rf "$STAGING_DIR" "$ALL_FILES" "$EXCLUDED_FILES" "$INCLUDED_FILES"' EXIT

cd "$REPO_ROOT"

# Match build-release.sh's .distignore removals without copying ignored local
# files such as .env. Include untracked, non-ignored files so the script is
# testable before a lane is committed.
git ls-files --cached --others --exclude-standard | while IFS= read -r file; do
  [ -e "$file" ] && printf '%s\n' "$file"
done | LC_ALL=C sort -u > "$ALL_FILES"

sh "$REPO_ROOT/scripts/resolve-distignore-files.sh" \
  "$DISTIGNORE" "$ALL_FILES" "$EXCLUDED_FILES" "$INCLUDED_FILES"

rsync -a --files-from="$INCLUDED_FILES" ./ "$STAGING_DIR/"

# Keep package metadata identical to the release branch transformation.
node - "$STAGING_DIR/package.json" <<'NODE'
const fs = require('node:fs');
const packagePath = process.argv[2];
const pkg = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
delete pkg.devDependencies;
if (pkg.scripts) delete pkg.scripts['test:hooks'];
if (pkg.scripts) delete pkg.scripts['test:scripts'];
fs.writeFileSync(packagePath, `${JSON.stringify(pkg, null, 2)}\n`);
NODE

python3 "$REPO_ROOT/core/utils/update_verifier.py" \
  --write-legacy-profile "$STAGING_DIR/System/.release-evidence-profile.json" \
  --release-version "$VERSION"

# The release manifest describes caller-owned shipped content. Production
# node_modules is deliberately an artifact addition, not update-managed vault
# content, so it is excluded from the manifest just as on the release branch.
mkdir -p "$STAGING_DIR/System"
(
  cd "$STAGING_DIR"
  # Ignore macOS metadata junk (AppleDouble ._* forks, .DS_Store) so the manifest
  # stays in agreement with the archive, which is likewise stripped of it below.
  find . \( -type f -o -type l \) ! -name '._*' ! -name '.DS_Store'
) | sed 's|^\./||' | grep -v '^System/\.installed-files\.manifest$' | LC_ALL=C sort \
  > "$STAGING_DIR/System/.installed-files.manifest"
printf '%s\n' 'System/.installed-files.manifest' >> "$STAGING_DIR/System/.installed-files.manifest"
LC_ALL=C sort -u -o "$STAGING_DIR/System/.installed-files.manifest" \
  "$STAGING_DIR/System/.installed-files.manifest"

# The staged tree is the release input. Check it before npm can execute or
# access a registry.
python3 "$REPO_ROOT/scripts/check-tau-removal.py" --tree "$STAGING_DIR"

(
  cd "$STAGING_DIR"
  npm ci --omit=dev --ignore-scripts
)
# npm creates command shims as symlinks. Dex does not execute dependency CLIs
# from the vault bundle, so remove them rather than weakening the no-symlink
# distribution contract.
rm -rf "$STAGING_DIR/node_modules/.bin"

rm -f "$TARBALL" "$CHECKSUM"
(
  cd "$STAGING_DIR"
  # COPYFILE_DISABLE=1 stops macOS bsdtar from synthesizing AppleDouble ._*
  # entries from extended attributes (they are not real files on disk, so the
  # find-based manifest above never lists them). The --exclude flags are
  # belt-and-braces for any stray on-disk macOS metadata, matching the manifest.
  COPYFILE_DISABLE=1 tar --exclude='._*' --exclude='.DS_Store' -czf "$TARBALL" .
)
python3 "$REPO_ROOT/scripts/check-tau-removal.py" --archive "$TARBALL"
(
  cd "$OUTPUT_DIR"
  shasum -a 256 "$(basename "$TARBALL")" > "$(basename "$CHECKSUM")"
)

echo "Built $TARBALL"
echo "Checksum $CHECKSUM"
