#!/usr/bin/env bash
# Prove the installer hash file is uv's current output, not a reused hash.
#
# uv keeps a hash that is already in --output-file. Compiling over the
# committed file therefore cannot catch a bad hash. This check compiles
# into an empty temp file, pins versions with -c (hashes stripped so uv
# cannot reuse them), then diffs that against the committed file.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMMITTED="${1:-$ROOT/core/mcp/requirements.hash.txt}"
REQUIREMENTS="$ROOT/core/mcp/requirements.txt"
DOCUMENTED_COMMAND='uv pip compile --python-version 3.11 --universal --generate-hashes --output-file=core/mcp/requirements.hash.txt core/mcp/requirements.txt'

if [[ ! -f "$COMMITTED" ]]; then
  echo "missing hash file: $COMMITTED" >&2
  exit 1
fi
if [[ ! -f "$REQUIREMENTS" ]]; then
  echo "missing requirements: $REQUIREMENTS" >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to refresh hashed Python pins" >&2
  exit 1
fi

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

# Version-only constraints: keep pins, drop hashes, so uv cannot copy a
# corrupted sha256 out of the committed file.
python3 - "$COMMITTED" "$WORKDIR/constraints.txt" <<'PY'
import re
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf-8")
pins: list[str] = []
for line in source.splitlines():
    match = re.match(r"^([A-Za-z0-9_.-]+==[^\s;\\]+)", line)
    if match:
        pins.append(match.group(1))
if not pins:
    raise SystemExit("no version pins found in hash file")
Path(sys.argv[2]).write_text("\n".join(pins) + "\n", encoding="utf-8")
PY

OUTPUT="$WORKDIR/requirements.hash.txt"
: > "$OUTPUT"

export UV_CUSTOM_COMPILE_COMMAND="$DOCUMENTED_COMMAND"
uv pip compile \
  --python-version 3.11 \
  --universal \
  --generate-hashes \
  --constraint "$WORKDIR/constraints.txt" \
  --output-file="$OUTPUT" \
  "$REQUIREMENTS"

python3 - "$COMMITTED" "$OUTPUT" <<'PY'
"""Diff pins and hashes only. `-c` adds `# via -c ...` comments that are not a pin change."""
from pathlib import Path
import sys


def significant(text: str) -> str:
    kept: list[str] = []
    for index, line in enumerate(text.splitlines()):
        if index >= 2 and line.lstrip().startswith("#"):
            continue
        kept.append(line.rstrip())
    return "\n".join(kept) + "\n"


committed = Path(sys.argv[1]).read_text(encoding="utf-8")
fresh = Path(sys.argv[2]).read_text(encoding="utf-8")
left = significant(committed)
right = significant(fresh)
if left != right:
    import difflib
    sys.stderr.writelines(
        difflib.unified_diff(
            left.splitlines(keepends=True),
            right.splitlines(keepends=True),
            fromfile="committed",
            tofile="clean-empty-compile",
        )
    )
    raise SystemExit("hashed Python pins drifted from a clean uv compile into an empty file")
PY

python3 - "$COMMITTED" <<'PY'
"""Every committed hash must be a sha256 PyPI published for that version."""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

HASH_RE = re.compile(r"--hash=sha256:([0-9a-f]{64})")
PACKAGE_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")


def published_sha256s(name: str, version: str) -> set[str]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "dex-hashed-python-requirements"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(f"PyPI lookup failed for {name}=={version}: HTTP {error.code}") from error
    found: set[str] = set()
    for item in payload.get("urls") or []:
        digest = (item.get("digests") or {}).get("sha256")
        if digest:
            found.add(digest)
    return found


source = Path(sys.argv[1]).read_text(encoding="utf-8")
by_package: dict[tuple[str, str], set[str]] = defaultdict(set)
current: tuple[str, str] | None = None
for line in source.splitlines():
    package = PACKAGE_RE.match(line)
    if package:
        current = (package.group(1), package.group(2))
        continue
    if current is None:
        continue
    for digest in HASH_RE.findall(line):
        by_package[current].add(digest)

if not by_package:
    raise SystemExit("no hashes found in hash file")

unknown: list[str] = []
for (name, version), digests in sorted(by_package.items()):
    published = published_sha256s(name, version)
    missing = sorted(digest for digest in digests if digest not in published)
    if missing:
        unknown.append(f"{name}=={version}: " + ", ".join(missing))

if unknown:
    print("hashes not published by PyPI:", file=sys.stderr)
    for item in unknown:
        print(f"  {item}", file=sys.stderr)
    raise SystemExit(1)

print(f"hashed Python pins match a clean uv compile and {sum(len(v) for v in by_package.values())} PyPI sha256s")
PY
