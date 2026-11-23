"""Dex Helper universal build must not reuse one binary path for both arches."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "core/macos/dex-helper/build.sh"
SIGN_SCRIPT = REPO_ROOT / "core/macos/dex-helper/sign-and-notarize.sh"


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_build_script_asks_swift_for_each_arch_path_and_copies_arm64_first() -> None:
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    arm_marker = 'swift build -c release --arch arm64 --show-bin-path'
    x86_marker = 'swift build -c release --arch x86_64 --show-bin-path'
    x86_build = "swift build -c release --arch x86_64 --product DexHelper"
    assert arm_marker in text
    assert x86_marker in text
    assert "mktemp" in text
    arm_copy_at = text.index("ARM_BIN_COPY")
    x86_build_at = text.index(x86_build)
    assert arm_copy_at < x86_build_at
    guessed_x86 = '"$ROOT/.build/x86_64-apple-macosx/release/DexHelper"'
    guessed_release = '"$ROOT/.build/release/DexHelper"'
    assert guessed_x86 not in text
    assert guessed_release not in text
    assert "DEX_HELPER_REQUIRE_UNIVERSAL=1" in SIGN_SCRIPT.read_text(encoding="utf-8")


def test_build_script_lipo_does_not_reuse_one_path_when_swift_overwrites_shared_bin(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    shared_dir = tmp_path / "shared-bin"
    shared_dir.mkdir()
    lipo_log = tmp_path / "lipo.log"
    out_dir = tmp_path / "out"

    _write_executable(
        fake_bin / "uname",
        """#!/bin/sh
if [ "$1" = "-s" ]; then
  echo Darwin
  exit 0
fi
exec /usr/bin/uname "$@"
""",
    )
    _write_executable(
        fake_bin / "swift",
        f"""#!/bin/sh
set -e
arch=""
show=""
product=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--arch" ]; then
    arch="$arg"
  elif [ "$prev" = "--product" ]; then
    product="$arg"
  elif [ "$arg" = "--show-bin-path" ]; then
    show="1"
  fi
  prev="$arg"
done
shared="{shared_dir}"
if [ -n "$show" ]; then
  printf '%s\\n' "$shared"
  exit 0
fi
mkdir -p "$shared"
if [ "$arch" = "arm64" ]; then
  printf 'arm64-body' > "$shared/DexHelper"
elif [ "$arch" = "x86_64" ]; then
  printf 'x86_64-body' > "$shared/DexHelper"
else
  echo "unexpected arch: $arch" >&2
  exit 1
fi
chmod 755 "$shared/DexHelper"
exit 0
""",
    )
    _write_executable(
        fake_bin / "lipo",
        f"""#!/bin/sh
log="{lipo_log}"
: > "$log"
output=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-output" ]; then
    output="$arg"
  elif [ "$arg" != "-create" ] && [ "$arg" != "-output" ] && [ "$prev" != "-output" ]; then
    printf '%s\\t' "$arg" >> "$log"
    if [ -f "$arg" ]; then
      cat "$arg" >> "$log"
    fi
    printf '\\n' >> "$log"
  fi
  prev="$arg"
done
if [ -z "$output" ]; then
  echo "lipo: missing -output" >&2
  exit 1
fi
first="$(sed -n '1p' "$log" | cut -f1)"
second="$(sed -n '2p' "$log" | cut -f1)"
if [ "$first" = "$second" ]; then
  echo "lipo received the same path for both inputs: $first" >&2
  exit 1
fi
cat "$first" "$second" > "$output"
""",
    )
    _write_executable(
        fake_bin / "codesign",
        """#!/bin/sh
exit 0
""",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
    env["DEX_HELPER_BUILD_DIR"] = str(out_dir)
    env["DEX_HELPER_REQUIRE_UNIVERSAL"] = "1"
    env["TMPDIR"] = str(tmp_path / "tmp")
    (tmp_path / "tmp").mkdir()

    completed = subprocess.run(
        ["bash", str(BUILD_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    built = out_dir / "Dex Helper.app" / "Contents" / "MacOS" / "DexHelper"
    assert built.is_file()
    assert built.read_text(encoding="utf-8") == "arm64-bodyx86_64-body"
    log_text = lipo_log.read_text(encoding="utf-8")
    lines = [line for line in log_text.splitlines() if line]
    assert len(lines) == 2, log_text
    first_path, first_body = lines[0].split("\t", 1)
    second_path, second_body = lines[1].split("\t", 1)
    assert first_path != second_path, log_text
    assert {first_body, second_body} == {"arm64-body", "x86_64-body"}
