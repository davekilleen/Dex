"""Phase 1: planned-content recovery reads must request exact bytes.

``_target_matches_planned_content`` is recovery evidence. On POSIX it must
open with ``binary_read_flags`` so a Ctrl-Z byte cannot truncate the probe.
On Windows, ``os.O_NOFOLLOW`` is absent: Phase 1 refuses the shortcut (and
logs once) until the Phase 4 handle-verified open lands.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import pytest

from core.tests.lifecycle_test_helpers import (
    CTRL_Z_BLOB_SIZE,
    CTRL_Z_OFFSET,
    ctrl_z_binary_blob,
)
from core.transaction import engine as engine_module
from core.transaction.engine import Transaction

WINDOWS_O_BINARY = 0x8000

pytestmark = pytest.mark.windows_supported


@pytest.fixture(autouse=True)
def _reset_windows_shortcut_log() -> None:
    engine_module._WINDOWS_PLANNED_CONTENT_SHORTCUT_LOGGED = False
    yield
    engine_module._WINDOWS_PLANNED_CONTENT_SHORTCUT_LOGGED = False


def test_planned_content_probe_matches_exact_bytes_including_ctrl_z(
    tmp_path: Path,
) -> None:
    blob = ctrl_z_binary_blob()
    target = tmp_path / "planned.bin"
    target.write_bytes(blob)

    assert Transaction._target_matches_planned_content(
        target,
        planned_sha256=hashlib.sha256(blob).hexdigest(),
        planned_size=len(blob),
    )
    assert target.read_bytes()[CTRL_Z_OFFSET] == 0x1A
    assert target.stat().st_size == CTRL_Z_BLOB_SIZE


def test_planned_content_probe_uses_binary_read_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "O_BINARY", WINDOWS_O_BINARY, raising=False)
    seen_flags: list[int] = []
    real_open = os.open

    def tracking_open(path, flags, mode=0o777, **kwargs):
        seen_flags.append(flags)
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", tracking_open)
    planned = b'{"ok": true}\n'
    target = tmp_path / "planned.json"
    target.write_bytes(planned)

    assert Transaction._target_matches_planned_content(
        target,
        planned_sha256=hashlib.sha256(planned).hexdigest(),
        planned_size=len(planned),
    )
    assert seen_flags
    assert all(flags & WINDOWS_O_BINARY for flags in seen_flags)


def test_planned_content_probe_refuses_windows_shortcut_and_logs_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(os, "name", "nt")
    planned = b"# Migrated\n"
    target = tmp_path / "planned.md"
    target.write_bytes(planned)
    digest = hashlib.sha256(planned).hexdigest()

    with caplog.at_level(logging.DEBUG, logger=engine_module.__name__):
        first = Transaction._target_matches_planned_content(
            target, planned_sha256=digest, planned_size=len(planned)
        )
        second = Transaction._target_matches_planned_content(
            target, planned_sha256=digest, planned_size=len(planned)
        )

    assert first is False
    assert second is False
    messages = [
        record.getMessage()
        for record in caplog.records
        if "planned-content probe refuses the no-follow shortcut" in record.getMessage()
    ]
    assert len(messages) == 1
