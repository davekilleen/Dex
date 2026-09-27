"""Phase 1: hash-bearing filesystem reads must request exact bytes.

On Windows, a raw ``os.open`` without ``O_BINARY`` is a CRT text-mode
descriptor: ``os.read`` turns CRLF into LF and stops at the first ``0x1A``
(Ctrl-Z). Inventory hashes, snapshot stores, and release-anchor binding all
go through ``bounded_read``. These tests pin the flags on file opens (and
their absence on directory opens) and the Ctrl-Z truncation case from
Appendix B of the Windows support spec.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.lifecycle.filesystem import bounded_read
from core.tests.lifecycle_test_helpers import (
    CTRL_Z_BLOB_SIZE,
    CTRL_Z_OFFSET,
    ctrl_z_binary_blob,
)
from core.utils.os_flags import binary_read_flags

WINDOWS_O_BINARY = 0x8000

pytestmark = pytest.mark.windows_supported


def _track_open_flags(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    monkeypatch.setattr(os, "O_BINARY", WINDOWS_O_BINARY, raising=False)
    seen_flags: list[int] = []
    real_open = os.open

    def tracking_open(path, flags, mode=0o777, **kwargs):
        seen_flags.append(flags)
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", tracking_open)
    return seen_flags


def _simulate_windows_crt_read(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Treat missing O_BINARY as CRT text mode: stop at Ctrl-Z, CRLF→LF."""
    monkeypatch.setattr(os, "O_BINARY", WINDOWS_O_BINARY, raising=False)
    opened_flags: dict[int, int] = {}
    seen_flags: list[int] = []
    real_open = os.open
    real_read = os.read
    real_close = os.close

    def tracking_open(path, flags, mode=0o777, **kwargs):
        descriptor = real_open(path, flags, mode, **kwargs)
        opened_flags[descriptor] = flags
        seen_flags.append(flags)
        return descriptor

    def translating_read(descriptor, size):
        payload = real_read(descriptor, size)
        if not (opened_flags.get(descriptor, 0) & WINDOWS_O_BINARY):
            cut = payload.find(b"\x1a")
            if cut != -1:
                payload = payload[:cut]
            payload = payload.replace(b"\r\n", b"\n")
        return payload

    def tracking_close(descriptor):
        opened_flags.pop(descriptor, None)
        return real_close(descriptor)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "read", translating_read)
    monkeypatch.setattr(os, "close", tracking_close)
    return seen_flags


def test_binary_read_flags_or_platform_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "O_BINARY", WINDOWS_O_BINARY, raising=False)
    assert binary_read_flags(os.O_RDONLY) == os.O_RDONLY | WINDOWS_O_BINARY


def test_binary_read_flags_noop_when_platform_has_no_obinary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(os, "O_BINARY", raising=False)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    assert binary_read_flags(os.O_RDONLY | nofollow) == os.O_RDONLY | nofollow


def test_file_opens_include_obinary_and_directory_opens_do_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_flags = _track_open_flags(monkeypatch)
    vault = tmp_path / "vault"
    relative = "nested/dir/payload.bin"
    write_target = vault / relative
    write_target.parent.mkdir(parents=True)
    write_target.write_bytes(b"exact-bytes\n")

    assert bounded_read(vault, relative) == b"exact-bytes\n"
    assert seen_flags

    directory_flag = getattr(os, "O_DIRECTORY", 0)
    file_opens = [flags for flags in seen_flags if not (flags & directory_flag)]
    directory_opens = [flags for flags in seen_flags if flags & directory_flag]
    assert file_opens
    assert all(flags & WINDOWS_O_BINARY for flags in file_opens)
    assert directory_opens
    assert all(not (flags & WINDOWS_O_BINARY) for flags in directory_opens)


def test_windows_fallback_file_open_includes_obinary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "supports_dir_fd", set())
    seen_flags = _track_open_flags(monkeypatch)
    vault = tmp_path / "vault"
    relative = "payload.bin"
    (vault / relative).parent.mkdir(parents=True)
    (vault / relative).write_bytes(b"windows-branch\n")

    assert bounded_read(vault, relative) == b"windows-branch\n"
    assert seen_flags
    assert all(flags & WINDOWS_O_BINARY for flags in seen_flags)


def test_bounded_read_keeps_ctrl_z_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen_flags = _simulate_windows_crt_read(monkeypatch)
    vault = tmp_path / "vault"
    relative = "core/ctrl-z.bin"
    blob = ctrl_z_binary_blob()
    target = vault / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(blob)

    recovered = bounded_read(vault, relative)

    assert len(recovered) == CTRL_Z_BLOB_SIZE
    assert recovered[CTRL_Z_OFFSET] == 0x1A
    assert recovered == blob
    assert any(flags & WINDOWS_O_BINARY for flags in seen_flags)


def test_simulated_text_mode_read_without_obinary_truncates_at_ctrl_z(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _simulate_windows_crt_read(monkeypatch)
    path = tmp_path / "text-mode.bin"
    blob = ctrl_z_binary_blob()
    path.write_bytes(blob)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        recovered = os.read(descriptor, len(blob))
    finally:
        os.close(descriptor)
    assert recovered == blob[:CTRL_Z_OFFSET]
    assert b"\x1a" not in recovered
