"""The one Windows-aware fsync used by every durable writer.

POSIX directory-entry durability needs an explicit fsync of the parent
directory after creating, renaming, or unlinking a file. Windows offers no
user-space equivalent: ``os.open`` cannot open a directory there at all
(CreateFile requires FILE_FLAG_BACKUP_SEMANTICS, which os.open never
passes), so the POSIX pattern raises PermissionError — *after* the write it
was meant to make durable, which is how issue #257 orphaned a freshly
created mutation lock. On Windows the directory fsync is therefore skipped
and entry durability is the filesystem's, exactly like every other Windows
write.

File durability has a second Windows wrinkle: ``os.fsync`` on a handle
opened ``O_RDONLY`` fails (ERROR_ACCESS_DENIED). Open ``O_RDWR`` there.
On POSIX, ``O_RDONLY`` is enough and stays the safer default.

Every Python copy of this pattern must route through these helpers; do not
re-inline ``os.open(..., os.O_RDONLY)`` + ``os.fsync`` at call sites.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

__all__ = ["fsync_directory", "fsync_file"]

_LOG = logging.getLogger(__name__)


def fsync_directory(directory: Path | str) -> None:
    """Fsync one directory's entries on POSIX; no-op on Windows."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    except OSError:
        _LOG.debug("fsync_directory failed path=%s", directory, exc_info=True)
        raise
    finally:
        os.close(descriptor)


def fsync_file(path: Path | str) -> None:
    """Fsync one regular file. ``O_RDWR`` on Windows; ``O_RDONLY`` on POSIX.

    Windows refuses ``fsync`` on a read-only handle. POSIX does not, and
    opening writeable is unnecessary there — keep the established
    read-only open so a file we only need to flush is never opened for
    write on macOS/Linux.
    """
    flags = os.O_RDWR if os.name == "nt" else os.O_RDONLY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    except OSError:
        _LOG.debug(
            "fsync_file failed path=%s flags=%s", path, flags, exc_info=True
        )
        raise
    finally:
        os.close(descriptor)
