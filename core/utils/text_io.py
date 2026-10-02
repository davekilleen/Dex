"""UTF-8 vault I/O that stays safe on Windows locale codecs.

Python's default text codec on native Windows is often cp1252. Leaving
``encoding`` unset makes ordinary vault characters raise, and
``Path.write_text`` / ``open(path, "w")`` truncate the target *before*
encoding. A failed encode then leaves an empty or half-written user file.

This module encodes first, writes the bytes to a same-directory temp, then
replaces. Encode failures and write failures leave the original file intact.
Reads always decode UTF-8 (BOM tolerated) so Windows never uses the locale
decoder.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from core.transaction.fsync import fsync_directory

UTF8 = "utf-8"
UTF8_SIG = "utf-8-sig"


def _as_path(path: Path | str) -> Path:
    """Keep an existing Path flavour. Re-wrapping under a patched ``os.name``
    would reinterpret a POSIX path as a Windows path and miss the file."""
    return path if isinstance(path, Path) else Path(path)


def read_text(path: Path | str, *, encoding: str = UTF8_SIG, errors: str = "strict") -> str:
    """Read a text file as UTF-8. A leading BOM is stripped when present."""
    return _as_path(path).read_bytes().decode(encoding, errors)


def write_text(
    path: Path | str,
    data: str,
    *,
    encoding: str = UTF8,
    errors: str = "strict",
    newline: str | None = None,
) -> int:
    """Write ``data`` as UTF-8 without truncating ``path`` on failure.

    ``newline`` matches ``Path.write_text``: ``None`` and ``""`` write the
    string's existing line endings as-is (no ``os.linesep`` translation).
    Any other value replaces ``\\n`` with that ending before encoding.
    """
    if not isinstance(data, str):
        raise TypeError(f"write_text() argument must be str, not {type(data).__name__}")
    payload = _encode_text(data, encoding=encoding, errors=errors, newline=newline)
    write_bytes_atomic(path, payload)
    return len(data)


def write_bytes_atomic(path: Path | str, payload: bytes) -> None:
    """Replace ``path`` with ``payload`` after the bytes are fully on disk."""
    target = _as_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
        fsync_directory(target.parent)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _encode_text(
    data: str,
    *,
    encoding: str,
    errors: str,
    newline: str | None,
) -> bytes:
    if newline not in (None, ""):
        data = data.replace("\n", newline)
    return data.encode(encoding, errors)
