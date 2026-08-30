"""Filesystem path-safety checks shared by inventory and mutation engines."""

from __future__ import annotations

import stat
from pathlib import Path, PurePosixPath


def unsafe_existing_parent(vault_root: Path, relative: str) -> str | None:
    """Describe the first symlink/non-directory parent, without following it.

    Missing parents are safe evidence: a sanctioned writer may create them.
    Every parent that already exists must be a real directory.
    """
    candidate = PurePosixPath(relative)
    if (
        not relative
        or candidate.is_absolute()
        or candidate.as_posix() != relative
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        return f"unsafe relative path {relative!r}"

    root = Path(vault_root)
    try:
        root_metadata = root.lstat()
    except OSError as error:
        return f"vault root metadata is unavailable ({error.__class__.__name__})"
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        return "vault root is not a real directory"

    current = root
    traversed: list[str] = []
    for part in candidate.parts[:-1]:
        current /= part
        traversed.append(part)
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            return None
        except OSError as error:
            return f"parent {'/'.join(traversed)} is unavailable ({error.__class__.__name__})"
        if stat.S_ISLNK(metadata.st_mode):
            return f"symlinked parent {'/'.join(traversed)}"
        if not stat.S_ISDIR(metadata.st_mode):
            return f"non-directory parent {'/'.join(traversed)}"
    return None


__all__ = ["unsafe_existing_parent"]
