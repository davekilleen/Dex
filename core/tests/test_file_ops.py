"""Tests for safe file operations."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from core.utils.file_ops import atomic_write_json, file_lock


def test_atomic_write_json_roundtrip(tmp_path: Path):
    target = tmp_path / "queue.json"
    payload = {"version": 1, "items": [{"id": "x"}]}
    atomic_write_json(target, payload)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == payload


def test_file_lock_timeout(tmp_path: Path):
    lock_path = tmp_path / "queue.lock"
    started = threading.Event()
    release = threading.Event()

    def holder():
        with file_lock(lock_path, timeout_seconds=1):
            started.set()
            release.wait(timeout=2)

    t = threading.Thread(target=holder, daemon=True)
    t.start()
    assert started.wait(timeout=1), "Lock holder did not start"

    with pytest.raises(TimeoutError):
        with file_lock(lock_path, timeout_seconds=0.1):
            pass

    release.set()
    t.join(timeout=1)


def test_atomic_write_json_stays_parseable_with_concurrent_writes(tmp_path: Path):
    target = tmp_path / "queue.json"
    lock_path = tmp_path / "queue.lock"

    def writer(idx: int):
        for n in range(10):
            payload = {"writer": idx, "counter": n}
            with file_lock(lock_path, timeout_seconds=2):
                atomic_write_json(target, payload)
            time.sleep(0.001)

    threads = [threading.Thread(target=writer, args=(i,), daemon=True) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    data = json.loads(target.read_text(encoding="utf-8"))
    assert "writer" in data
    assert "counter" in data
