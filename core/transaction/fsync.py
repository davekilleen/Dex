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
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["fsync_directory"]


def fsync_directory(directory: Path | str) -> None:
    """Fsync one directory's entries on POSIX; no-op on Windows."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
