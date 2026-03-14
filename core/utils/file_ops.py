"""Shared safe file operations for concurrent writers."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def file_lock(lock_path: Path, timeout_seconds: float = 5.0, poll_seconds: float = 0.05) -> Iterator[None]:
    """Acquire an advisory lock for a file path with timeout."""
    import fcntl

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = lock_path.open("a+", encoding="utf-8")
    start = time.monotonic()
    try:
        while True:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - start >= timeout_seconds:
                    raise TimeoutError(f"Could not acquire lock within {timeout_seconds}s: {lock_path}")
                time.sleep(poll_seconds)
        yield
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        finally:
            fd.close()


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    """Atomically write text file by replace-on-rename in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding=encoding) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_name = tmp.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, data: dict) -> None:
    """Atomically persist JSON data."""
    payload = json.dumps(data, indent=2) + "\n"
    atomic_write_text(path, payload)
