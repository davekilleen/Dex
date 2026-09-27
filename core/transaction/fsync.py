"""The one Windows-aware directory-fsync used by every durable writer.

POSIX directory-entry durability needs an explicit fsync of the parent
directory after creating, renaming, or unlinking a file. Windows offers no
user-space equivalent: ``os.open`` cannot open a directory there at all
(CreateFile requires FILE_FLAG_BACKUP_SEMANTICS, which os.open never
passes), so the POSIX pattern raises PermissionError — *after* the write it
was meant to make durable, which is how issue #257 orphaned a freshly
created mutation lock. On Windows the fsync is therefore skipped and entry
durability is the filesystem's, exactly like every other Windows write.

Every Python copy of this pattern must route through this helper; do not
re-inline ``os.open(directory, os.O_RDONLY)`` + ``os.fsync`` at call sites.

File contents use ``fsync_file``. Windows CRT ``_commit`` (``os.fsync``)
returns EBADF on a read-only handle, which is why
``test_transaction_core`` failed on windows-latest with
``os.open(..., os.O_RDONLY)`` then ``os.fsync``.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["fsync_directory", "fsync_file"]


def fsync_directory(directory: Path | str) -> None:
    """Fsync one directory's entries on POSIX; no-op on Windows."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_file(path: Path | str) -> None:
    """Fsync one file's contents.

    POSIX can fsync an ``O_RDONLY`` descriptor. Windows cannot: open
    ``O_RDWR`` there, with ``O_BINARY`` so the handle stays byte-exact.
    """
    flags = os.O_RDWR if os.name == "nt" else os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
