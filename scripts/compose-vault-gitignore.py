#!/usr/bin/env python3
"""Make a release's .gitignore safe before any historic updater can write it."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from core.update.apply_update import _compose_gitignore
from core.utils.os_flags import binary_write_flags


def compose_file(path: Path) -> None:
    target = path.resolve()
    if path.is_symlink() or not target.is_file():
        raise RuntimeError(f"release .gitignore is not a regular file: {path}")
    current = target.read_bytes()
    composed = _compose_gitignore(current, target.parent)
    if composed == current:
        return

    mode = target.stat().st_mode & 0o777
    temporary = target.parent / f".{target.name}.compose-{os.getpid()}"
    descriptor = os.open(
        temporary, binary_write_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL), mode
    )
    try:
        written = 0
        while written < len(composed):
            count = os.write(descriptor, composed[written:])
            if count <= 0:
                raise OSError("release .gitignore write made no progress")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    compose_file(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
