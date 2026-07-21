"""Read-only, bounded filesystem primitives for lifecycle inventory.

The inventory must be safe to run against a live, user-owned vault.  These
helpers never follow symlinks, never mutate the tree, bound both entry counts
and file reads, and report case-fold collisions instead of choosing a winner.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from core import portable_contract

DEFAULT_MAX_ENTRIES = 200_000
DEFAULT_MAX_READ_BYTES = 8 * 1024 * 1024


class FilesystemInspectionError(RuntimeError):
    """A filesystem fact could not be established without guessing."""


@dataclass(frozen=True)
class WalkEntry:
    path: str
    kind: str
    size: int | None
    denied: bool


@dataclass(frozen=True)
class WalkReport:
    entries: tuple[WalkEntry, ...]
    case_collisions: tuple[tuple[str, ...], ...]
    errors: tuple[str, ...]
    truncated: bool


def detect_case_collisions(paths: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Group distinct paths that collide on a case-insensitive filesystem."""
    folded: dict[str, list[str]] = {}
    for path in paths:
        folded.setdefault(path.casefold(), []).append(path)
    return tuple(
        tuple(sorted(candidates))
        for _, candidates in sorted(folded.items())
        if len(candidates) > 1
    )


def normalize_relative_path(path: str) -> str:
    """Return one canonical vault-relative POSIX path or fail closed."""
    raw = str(path)
    if not raw or "\\" in raw or "\x00" in raw:
        raise FilesystemInspectionError(f"unsafe relative path: {raw!r}")
    candidate = PurePosixPath(raw)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != raw
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise FilesystemInspectionError(f"unsafe relative path: {raw!r}")
    return candidate.as_posix()


def _entry_kind(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "special"


def walk_read_only(root: Path, *, max_entries: int = DEFAULT_MAX_ENTRIES) -> WalkReport:
    """Walk ``root`` without following symlinks or reading file contents."""
    vault = Path(root)
    errors: list[str] = []
    entries: list[WalkEntry] = []
    truncated = False

    try:
        root_stat = vault.lstat()
    except OSError as error:
        raise FilesystemInspectionError(f"cannot inspect vault root: {error}") from error
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise FilesystemInspectionError("vault root must be a real directory, not a symlink")
    if max_entries <= 0:
        raise ValueError("max_entries must be positive")

    pending: list[tuple[Path, str]] = [(vault, "")]
    while pending:
        directory, prefix = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: (item.name.casefold(), item.name))
        except OSError as error:
            errors.append(f"{prefix or '.'}: directory unreadable: {error.__class__.__name__}")
            continue
        child_directories: list[tuple[Path, str]] = []
        for child in children:
            relative = f"{prefix}/{child.name}" if prefix else child.name
            try:
                normalized = normalize_relative_path(relative)
                metadata = child.stat(follow_symlinks=False)
            except (OSError, FilesystemInspectionError) as error:
                errors.append(f"{relative}: metadata unavailable: {error.__class__.__name__}")
                continue
            denied = portable_contract.is_denied(normalized)
            kind = _entry_kind(metadata.st_mode)
            size = metadata.st_size if kind == "file" and not denied else None
            entries.append(WalkEntry(normalized, kind, size, denied))
            if len(entries) >= max_entries:
                truncated = True
                pending.clear()
                break
            if kind == "directory" and not denied:
                child_directories.append((Path(child.path), normalized))
        pending.extend(reversed(child_directories))

    collisions = detect_case_collisions(tuple(entry.path for entry in entries))
    return WalkReport(
        tuple(sorted(entries, key=lambda entry: entry.path)),
        collisions,
        tuple(sorted(set(errors))),
        truncated,
    )


def _open_beneath(root: Path, relative: str) -> int:
    """Open a regular file beneath ``root`` with no symlink traversal."""
    normalized = normalize_relative_path(relative)
    if portable_contract.is_denied(normalized):
        raise FilesystemInspectionError(f"refusing to read hard-denied path: {normalized}")
    try:
        root_metadata = root.lstat()
    except OSError as error:
        raise FilesystemInspectionError(f"cannot inspect vault root: {error.__class__.__name__}") from error
    if not stat.S_ISDIR(root_metadata.st_mode) or stat.S_ISLNK(root_metadata.st_mode):
        raise FilesystemInspectionError("vault root must be a real directory, not a symlink")
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    nofollow_flag = getattr(os, "O_NOFOLLOW", 0)
    if os.open not in os.supports_dir_fd:
        # Windows lacks descriptor-relative open.  Inventory remains read-only:
        # reject every observed symlink, prove the resolved target stays beneath
        # the real root, then open the checked regular file.
        target = root
        for part in normalized.split("/"):
            target /= part
            try:
                metadata = target.lstat()
            except OSError as error:
                raise FilesystemInspectionError(
                    f"cannot safely open {normalized}: {error.__class__.__name__}"
                ) from error
            if stat.S_ISLNK(metadata.st_mode):
                raise FilesystemInspectionError(f"refusing to follow symlink: {normalized}")
        try:
            resolved_root = root.resolve(strict=True)
            resolved_target = target.resolve(strict=True)
            if not resolved_target.is_relative_to(resolved_root) or not resolved_target.is_file():
                raise FilesystemInspectionError(f"path is not a regular file beneath the vault: {normalized}")
            return os.open(resolved_target, os.O_RDONLY | nofollow_flag)
        except OSError as error:
            raise FilesystemInspectionError(
                f"cannot safely open {normalized}: {error.__class__.__name__}"
            ) from error

    directory_fd = os.open(root, os.O_RDONLY | directory_flag)
    opened: list[int] = [directory_fd]
    try:
        parts = normalized.split("/")
        for part in parts[:-1]:
            directory_fd = os.open(
                part,
                os.O_RDONLY | directory_flag | nofollow_flag,
                dir_fd=directory_fd,
            )
            opened.append(directory_fd)
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY | nofollow_flag,
            dir_fd=directory_fd,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(descriptor)
            raise FilesystemInspectionError(f"path is not a regular file: {normalized}")
        return descriptor
    except OSError as error:
        raise FilesystemInspectionError(f"cannot safely open {normalized}: {error.__class__.__name__}") from error
    finally:
        for opened_fd in reversed(opened):
            os.close(opened_fd)


def bounded_read(root: Path, relative: str, *, max_bytes: int = DEFAULT_MAX_READ_BYTES) -> bytes:
    """Read a non-denied regular file through a descriptor, with a hard cap."""
    if max_bytes < 0:
        raise ValueError("max_bytes cannot be negative")
    descriptor = _open_beneath(Path(root), relative)
    try:
        size = os.fstat(descriptor).st_size
        if size > max_bytes:
            raise FilesystemInspectionError(f"bounded read exceeded for {relative}: {size} > {max_bytes}")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks)
        if len(value) > max_bytes:
            raise FilesystemInspectionError(f"bounded read exceeded for {relative}")
        return value
    finally:
        os.close(descriptor)


def sha256_file(root: Path, relative: str, *, max_bytes: int = DEFAULT_MAX_READ_BYTES) -> str:
    """Hash one safe, bounded, non-denied regular file."""
    return hashlib.sha256(bounded_read(root, relative, max_bytes=max_bytes)).hexdigest()


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_READ_BYTES",
    "FilesystemInspectionError",
    "WalkEntry",
    "WalkReport",
    "bounded_read",
    "detect_case_collisions",
    "normalize_relative_path",
    "sha256_file",
    "walk_read_only",
]
