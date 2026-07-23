"""Reusable E5 observed-write assertions for vault-mutating tests.

The snapshot is content-addressed, ignores timestamps, and never follows a
symlink.  That makes a before/after diff an exact statement about persistent
vault mutations rather than incidental filesystem activity.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class ObservedPath:
    """Stable identity for one node beneath a vault root."""

    kind: str
    mode: int
    size: int | None = None
    sha256: str | None = None
    link_target: str | None = None


VaultSnapshot = dict[str, ObservedPath]


def _file_sha256(descriptor: int) -> str:
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 1 << 20):
        digest.update(chunk)
    return digest.hexdigest()


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_mode,
        left.st_size,
        left.st_mtime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_mode,
        right.st_size,
        right.st_mtime_ns,
    )


def snapshot_vault(vault_root: Path) -> VaultSnapshot:
    """Hash every vault node without following directory or file symlinks."""
    root = Path(vault_root)
    root_metadata = root.lstat()
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
        raise ValueError("vault root must be a real directory")

    directory_flag = getattr(os, "O_DIRECTORY", 0)
    nofollow_flag = getattr(os, "O_NOFOLLOW", 0)
    root_descriptor = os.open(root, os.O_RDONLY | directory_flag | nofollow_flag)
    observed: VaultSnapshot = {}
    pending: list[tuple[int, str]] = [(root_descriptor, "")]
    try:
        while pending:
            directory_descriptor, prefix = pending.pop()
            try:
                with os.scandir(directory_descriptor) as iterator:
                    children = sorted(iterator, key=lambda child: child.name)
                for child in children:
                    relative = f"{prefix}/{child.name}" if prefix else child.name
                    metadata = child.stat(follow_symlinks=False)
                    mode = stat.S_IMODE(metadata.st_mode)
                    if stat.S_ISLNK(metadata.st_mode):
                        observed[relative] = ObservedPath(
                            "symlink",
                            mode,
                            link_target=os.readlink(
                                child.name, dir_fd=directory_descriptor
                            ),
                        )
                    elif stat.S_ISDIR(metadata.st_mode):
                        child_descriptor = os.open(
                            child.name,
                            os.O_RDONLY | directory_flag | nofollow_flag,
                            dir_fd=directory_descriptor,
                        )
                        opened = os.fstat(child_descriptor)
                        if not _same_identity(metadata, opened):
                            os.close(child_descriptor)
                            raise RuntimeError(
                                f"vault path changed during snapshot: {relative}"
                            )
                        observed[relative] = ObservedPath("directory", mode)
                        pending.append((child_descriptor, relative))
                    elif stat.S_ISREG(metadata.st_mode):
                        descriptor = os.open(
                            child.name,
                            os.O_RDONLY | nofollow_flag,
                            dir_fd=directory_descriptor,
                        )
                        try:
                            opened = os.fstat(descriptor)
                            if not _same_identity(metadata, opened):
                                raise RuntimeError(
                                    f"vault path changed during snapshot: {relative}"
                                )
                            digest = _file_sha256(descriptor)
                            if not _same_identity(opened, os.fstat(descriptor)):
                                raise RuntimeError(
                                    f"vault file changed while hashing: {relative}"
                                )
                        finally:
                            os.close(descriptor)
                        observed[relative] = ObservedPath(
                            "file", mode, metadata.st_size, digest
                        )
                    else:
                        observed[relative] = ObservedPath(
                            "special", mode, metadata.st_size
                        )
            finally:
                os.close(directory_descriptor)
    finally:
        for descriptor, _prefix in pending:
            os.close(descriptor)
    return dict(sorted(observed.items()))


def changed_vault_paths(
    before: Mapping[str, ObservedPath],
    after: Mapping[str, ObservedPath],
) -> frozenset[str]:
    """Return every created, deleted, content-changed, type-changed, or mode-changed path."""
    return frozenset(
        path
        for path in before.keys() | after.keys()
        if before.get(path) != after.get(path)
    )


def assert_observed_writes(
    before: Mapping[str, ObservedPath],
    after: Mapping[str, ObservedPath],
    declared_paths: set[str] | frozenset[str],
) -> frozenset[str]:
    """Assert that the full vault diff equals the caller's declared mutation set."""
    changed = changed_vault_paths(before, after)
    expected = frozenset(declared_paths)
    assert changed == expected, {
        "unexplained": sorted(changed - expected),
        "declared_but_unchanged": sorted(expected - changed),
    }
    return changed


__all__ = [
    "ObservedPath",
    "VaultSnapshot",
    "assert_observed_writes",
    "changed_vault_paths",
    "snapshot_vault",
]
