#!/usr/bin/env bash
# Prove the installer hash file resolves to wheels for Intel Mac + CPython 3.14.
#
# cryptography 49+ dropped macOS x86_64/universal2 wheels. This check downloads
# with --only-binary :all: so a missing Intel-Mac wheel fails closed instead of
# falling back to an sdist build. macosx_10_15_x86_64 is the target: CPython
# 3.14 wheels already use 10_15+, and an Intel Mac new enough to run 3.14 is
# well past 10_12.
#
# pip --platform does not re-evaluate PEP 508 environment markers, so a Linux
# runner would otherwise pick cryptography 50.0.1 (no Intel wheel) and fail.
# Filter the hash file to the Intel-Mac + 3.14 marker environment first.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REQUIREMENTS="${1:-$ROOT/core/mcp/requirements.hash.txt}"

if [[ ! -f "$REQUIREMENTS" ]]; then
  echo "missing hash file: $REQUIREMENTS" >&2
  exit 1
fi

DEST="$(mktemp -d)"
FILTERED="$(mktemp)"
trap 'rm -rf "$DEST" "$FILTERED"' EXIT

python3 - "$REQUIREMENTS" "$FILTERED" <<'PY'
from pathlib import Path
import sys

try:
    from pip._vendor.packaging.markers import default_environment
    from pip._vendor.packaging.requirements import Requirement
except ImportError:
    from packaging.markers import default_environment
    from packaging.requirements import Requirement

source = Path(sys.argv[1])
dest = Path(sys.argv[2])
env = default_environment()
env.update(
    {
        "os_name": "posix",
        "sys_platform": "darwin",
        "platform_machine": "x86_64",
        "platform_system": "Darwin",
        "platform_release": "24.0.0",
        "python_version": "3.14",
        "python_full_version": "3.14.0",
        "implementation_name": "cpython",
        "implementation_version": "3.14.0",
        "platform_python_implementation": "CPython",
    }
)

lines = source.read_text(encoding="utf-8").splitlines()
blocks: list[list[str]] = []
index = 0
while index < len(lines):
    stripped = lines[index].strip()
    if not stripped or stripped.startswith("#"):
        index += 1
        continue
    block = [lines[index]]
    index += 1
    while index < len(lines):
        nxt = lines[index]
        nstrip = nxt.strip()
        if not nstrip:
            break
        if nstrip.startswith("#") or nstrip.startswith("--hash=") or nxt.startswith("    "):
            block.append(nxt)
            index += 1
            continue
        break
    blocks.append(block)

kept: list[list[str]] = []
for block in blocks:
    header = block[0].rstrip("\\").strip()
    try:
        req = Requirement(header)
    except Exception as error:
        raise SystemExit(f"could not parse requirement: {header!r}: {error}") from error
    if req.marker is not None and not req.marker.evaluate(env):
        continue
    # pip still evaluates markers against the host, even with --platform.
    # Drop the marker so Linux CI actually downloads the Intel-Mac pin.
    rewritten = [f"{req.name}{req.specifier} \\"]
    rewritten.extend(block[1:])
    kept.append(rewritten)

if not kept:
    raise SystemExit("no requirements matched Intel Mac + 3.14")
if not any(block[0].startswith("cryptography==48.0.1") for block in kept):
    raise SystemExit("Intel Mac + 3.14 filter did not keep cryptography==48.0.1")
if any(block[0].startswith("cryptography==50.0.1") for block in kept):
    raise SystemExit("Intel Mac + 3.14 filter kept cryptography==50.0.1")

out: list[str] = []
for block in kept:
    out.extend(block)
dest.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"filtered {len(kept)} packages for Intel Mac cp314")
PY

python3 -m pip download \
  --quiet \
  --only-binary :all: \
  --python-version 3.14 \
  --platform macosx_10_15_x86_64 \
  --implementation cp \
  --abi cp314 \
  --abi abi3 \
  --abi none \
  --dest "$DEST" \
  -r "$FILTERED"

python3 - "$DEST" <<'PY'
from pathlib import Path
import sys

dest = Path(sys.argv[1])
wheels = sorted(path.name for path in dest.iterdir() if path.suffix == ".whl")
if not wheels:
    raise SystemExit("pip download wrote no wheels")
cryptography = [name for name in wheels if name.startswith("cryptography-")]
if not cryptography:
    raise SystemExit("pip download did not resolve cryptography for Intel Mac + 3.14")
if not any("macosx" in name and ("x86_64" in name or "universal2" in name) for name in cryptography):
    raise SystemExit("cryptography wheel is not an Intel/universal2 macOS wheel: " + ", ".join(cryptography))
if not any(name.startswith("cryptography-48.0.1") for name in cryptography):
    raise SystemExit("expected cryptography 48.0.1 for Intel Mac: " + ", ".join(cryptography))
print(f"Intel Mac cp314 wheels ok ({len(wheels)} files; cryptography={cryptography[0]})")
PY
