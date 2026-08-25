#!/usr/bin/env python3
"""Build unreleased installable artifacts from Dex's canonical plugin sources."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-agent-plugin"
GEMINI_SOURCE = REPO_ROOT / "packages" / "dex-gemini-extension"
DESKTOP_SOURCE = REPO_ROOT / "packages" / "dex-claude-desktop"
MCPB_CLI = REPO_ROOT / "node_modules" / ".bin" / ("mcpb.cmd" if os.name == "nt" else "mcpb")

SHARED_DIRECTORIES = ("bin", "metadata", "runtime")
SHARED_FILES = ("README.md", "hook.py", "server.py")


def _remove_existing(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def _copy_shared_runtime(target: Path, *, include_skills: bool) -> None:
    target.mkdir(parents=True, exist_ok=True)
    directories = (*SHARED_DIRECTORIES, "skills") if include_skills else SHARED_DIRECTORIES
    for name in directories:
        _copy_tree(PLUGIN_ROOT / name, target / name)
    for name in SHARED_FILES:
        shutil.copy2(PLUGIN_ROOT / name, target / name)


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _write_deterministic_tar(source: Path, target: Path) -> None:
    with target.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                archive.add(source, arcname=source.name, filter=_tar_filter)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    gemini = output_dir / "dex-gemini-extension"
    desktop = output_dir / "dex-claude-desktop"
    gemini_archive = output_dir / "dex-gemini-extension.tar.gz"
    desktop_archive = output_dir / "dex-claude-desktop.mcpb"
    index = output_dir / "artifacts.json"
    for path in (gemini, desktop, gemini_archive, desktop_archive, index):
        _remove_existing(path)

    _copy_shared_runtime(gemini, include_skills=True)
    shutil.copy2(GEMINI_SOURCE / "gemini-extension.json", gemini / "gemini-extension.json")
    shutil.copy2(GEMINI_SOURCE / "README.md", gemini / "README.md")
    _copy_tree(GEMINI_SOURCE / "hooks", gemini / "hooks")
    _write_deterministic_tar(gemini, gemini_archive)

    _copy_shared_runtime(desktop, include_skills=False)
    shutil.copy2(DESKTOP_SOURCE / "manifest.json", desktop / "manifest.json")
    shutil.copy2(DESKTOP_SOURCE / "README.md", desktop / "README.md")
    if not MCPB_CLI.is_file():
        raise RuntimeError("MCPB builder is missing; run npm ci before building artifacts")
    subprocess.run([str(MCPB_CLI), "validate", str(desktop / "manifest.json")], check=True)
    subprocess.run([str(MCPB_CLI), "pack", str(desktop), str(desktop_archive)], check=True)

    artifacts = [desktop_archive, gemini_archive]
    payload = {
        "schema_version": "1.0.0",
        "release_status": "unreleased",
        "artifacts": [
            {
                "name": path.name,
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(artifacts, key=lambda row: row.name)
        ],
    }
    index.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    artifacts = build(output)
    for artifact in artifacts:
        print(f"Built {artifact.name}: {_sha256(artifact)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
