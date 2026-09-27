"""Portable OS open-flag helpers.

Windows and Cygwin open files in CRT text mode unless ``O_BINARY`` is set.
That mode translates ``\\n`` to ``\\r\\n`` even for ``os.write`` of bytes,
which corrupts JSON, hashes, journals, and other verbatim payloads. POSIX
does not define ``O_BINARY``; ``getattr`` keeps these helpers a no-op there.
"""

from __future__ import annotations

import os


def binary_write_flags(base_flags: int) -> int:
    """Return *base_flags* with ``O_BINARY`` set when the platform defines it."""
    return base_flags | getattr(os, "O_BINARY", 0)
