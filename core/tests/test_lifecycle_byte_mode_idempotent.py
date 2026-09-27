"""Phase 2: a second apply writes nothing."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.lifecycle.byte_mode import MARKER_RELATIVE, apply
from core.tests.byte_mode_helpers import crlf_variant, receipt_bytes, write_receipt

pytestmark = pytest.mark.windows_supported


def test_second_apply_writes_nothing(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    path = write_receipt(vault, crlf_variant(receipt_bytes()))

    first = apply(vault)
    assert first["actions"]
    marker = vault / MARKER_RELATIVE
    receipt_mtime = path.stat().st_mtime_ns
    receipt_bytes_after = path.read_bytes()
    marker_mtime = marker.stat().st_mtime_ns
    marker_bytes = marker.read_bytes()

    second = apply(vault)

    assert second["actions"] == []
    assert path.read_bytes() == receipt_bytes_after
    assert path.stat().st_mtime_ns == receipt_mtime
    assert marker.read_bytes() == marker_bytes
    assert marker.stat().st_mtime_ns == marker_mtime
