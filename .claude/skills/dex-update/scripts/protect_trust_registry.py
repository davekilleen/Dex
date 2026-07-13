#!/usr/bin/env python3
"""Preserve user-owned MCP consent across a Dex release merge."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

REGISTRY_RELATIVE = Path("System/trusted-mcps.yaml")
MANIFEST_NAME = "manifest.json"
BACKUP_NAME = "trusted-mcps.yaml"


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/usr/bin/git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(repo),
            *arguments,
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def capture_registry(repo: Path, state: Path) -> None:
    """Capture the pre-merge user registry, including its absence."""
    state.mkdir(mode=0o700, parents=True, exist_ok=False)
    registry = repo / REGISTRY_RELATIVE
    existed = registry.exists() or registry.is_symlink()
    mode: int | None = None
    if existed:
        registry_stat = registry.lstat()
        if not stat.S_ISREG(registry_stat.st_mode):
            raise ValueError("System/trusted-mcps.yaml must be a regular file before update")
        mode = stat.S_IMODE(registry_stat.st_mode)
        backup = state / BACKUP_NAME
        backup.write_bytes(registry.read_bytes())
        backup.chmod(0o600)
    (state / MANIFEST_NAME).write_text(
        json.dumps({"present": existed, "mode": mode}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (state / MANIFEST_NAME).chmod(0o600)


def restore_registry(repo: Path, state: Path) -> bool:
    """Remove an upstream-tracked registry and restore only pre-merge user bytes."""
    manifest = json.loads((state / MANIFEST_NAME).read_text(encoding="utf-8"))
    tracked = _git(repo, "ls-files", "--error-unmatch", "--", REGISTRY_RELATIVE.as_posix())
    if tracked.returncode != 0:
        print("trusted MCP registry remained user-owned")
        return False

    removed = _git(repo, "update-index", "--force-remove", "--", REGISTRY_RELATIVE.as_posix())
    if removed.returncode != 0:
        raise RuntimeError(removed.stderr.strip() or "could not remove upstream registry from index")

    registry = repo / REGISTRY_RELATIVE
    if manifest.get("present") is True:
        backup = state / BACKUP_NAME
        temporary = registry.with_name(f".{registry.name}.dex-update-{os.getpid()}")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            data = backup.read_bytes()
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
            os.fchmod(descriptor, int(manifest["mode"]))
        finally:
            os.close(descriptor)
        os.replace(temporary, registry)
    else:
        registry.unlink(missing_ok=True)

    print(
        "WARNING: rejected git-tracked System/trusted-mcps.yaml from the merged release; "
        "upstream files cannot grant consent"
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("capture", "restore"):
        command = subparsers.add_parser(action)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument("--state", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "capture":
            capture_registry(args.repo.resolve(), args.state.resolve())
        else:
            restore_registry(args.repo.resolve(), args.state.resolve())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"trusted MCP registry update guard failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
