"""POSIX and Windows backends for the shared advisory file lock."""

from __future__ import annotations

import errno
import logging
import os
import sys
import threading
import types
from pathlib import Path

import pytest

from core.utils import file_lock
from core.utils.file_lock import (
    LOCK_EX,
    LOCK_NB,
    LOCK_SH,
    LOCK_UN,
    LOCKFILE_EXCLUSIVE_LOCK,
    LOCKFILE_FAIL_IMMEDIATELY,
    flock,
    locked,
)

LEDGER_AND_SIBLINGS = (
    Path("core/lifecycle/ledger.py"),
    Path("core/health/snapshot.py"),
    Path("core/utils/dex_logger.py"),
    Path("core/utils/history_hygiene.py"),
    Path("core/utils/release_notes_sweep.py"),
    Path("core/utils/session_health.py"),
)


def _open_lockfile(path: Path) -> int:
    path.write_bytes(b"lock")
    return os.open(path, os.O_RDWR)


def _close(*descriptors: int) -> None:
    for descriptor in descriptors:
        if descriptor >= 0:
            os.close(descriptor)


class FakePywinTypesError(Exception):
    def __init__(self, winerror: int, funcname: str, message: str) -> None:
        self.winerror = winerror
        super().__init__(winerror, funcname, message)


class FakeWin32File:
    def __init__(self) -> None:
        self.owners: dict[int, bool] = {}
        self.lock_calls: list[tuple[int, int]] = []
        self.unlock_calls: list[int] = []

    def LockFileEx(
        self,
        handle: int,
        flags: int,
        reserved: int,
        nlow: int,
        nhigh: int,
        overlapped: object,
    ) -> None:
        exclusive = bool(flags & LOCKFILE_EXCLUSIVE_LOCK)
        self.lock_calls.append((handle, flags))
        for owner, owner_exclusive in self.owners.items():
            if owner == handle:
                continue
            if exclusive or owner_exclusive:
                raise FakePywinTypesError(
                    33, "LockFileEx", "The process cannot access the file"
                )
        self.owners[handle] = exclusive

    def UnlockFileEx(
        self,
        handle: int,
        reserved: int,
        nlow: int,
        nhigh: int,
        overlapped: object,
    ) -> None:
        self.unlock_calls.append(handle)
        if handle not in self.owners:
            raise FakePywinTypesError(158, "UnlockFileEx", "not locked")
        del self.owners[handle]


class FakeMsvcrt:
    LK_UNLCK = 0
    LK_LOCK = 1
    LK_NBLCK = 2
    LK_RLCK = 3

    def __init__(self) -> None:
        self.owners: dict[int, int] = {}
        self.calls: list[tuple[int, int, int, int]] = []
        self.handle_calls: list[int] = []
        self.timeout_failures_remaining = 0
        self.hard_error: OSError | None = None

    def get_osfhandle(self, descriptor: int) -> int:
        self.handle_calls.append(descriptor)
        return descriptor

    def locking(self, descriptor: int, mode: int, nbytes: int) -> None:
        position = os.lseek(descriptor, 0, os.SEEK_CUR)
        self.calls.append((descriptor, mode, nbytes, position))
        if self.hard_error is not None:
            raise self.hard_error
        inode = os.fstat(descriptor).st_ino
        if mode == self.LK_UNLCK:
            if self.owners.get(inode) == descriptor:
                del self.owners[inode]
            return
        holder = self.owners.get(inode)
        busy = holder is not None and holder != descriptor
        if self.timeout_failures_remaining > 0:
            self.timeout_failures_remaining -= 1
            raise OSError(errno.EDEADLK, "injected msvcrt lock timeout")
        if busy:
            raise OSError(errno.EACCES, "already locked")
        self.owners[inode] = descriptor


def _install_win32(
    monkeypatch: pytest.MonkeyPatch, *, with_win32: bool = True
) -> tuple[FakeMsvcrt, FakeWin32File | None]:
    fake_msvcrt = FakeMsvcrt()
    fake_win32 = FakeWin32File() if with_win32 else None
    monkeypatch.setattr(file_lock.os, "name", "nt")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    if with_win32:
        pywintypes = types.SimpleNamespace(
            error=FakePywinTypesError,
            OVERLAPPED=type("OVERLAPPED", (), {}),
        )
        win32con = types.SimpleNamespace(
            LOCKFILE_FAIL_IMMEDIATELY=LOCKFILE_FAIL_IMMEDIATELY,
            LOCKFILE_EXCLUSIVE_LOCK=LOCKFILE_EXCLUSIVE_LOCK,
        )
        monkeypatch.setitem(sys.modules, "pywintypes", pywintypes)
        monkeypatch.setitem(sys.modules, "win32con", win32con)
        monkeypatch.setitem(sys.modules, "win32file", fake_win32)
    else:
        for name in ("pywintypes", "win32con", "win32file"):
            monkeypatch.setitem(sys.modules, name, None)
    return fake_msvcrt, fake_win32


def test_ledger_and_siblings_do_not_import_fcntl() -> None:
    for path in LEDGER_AND_SIBLINGS:
        text = path.read_text(encoding="utf-8")
        assert "fcntl" not in text, f"{path} still mentions fcntl"


def test_posix_constants_match_fcntl() -> None:
    import fcntl

    assert file_lock.LOCK_SH == fcntl.LOCK_SH
    assert file_lock.LOCK_EX == fcntl.LOCK_EX
    assert file_lock.LOCK_NB == fcntl.LOCK_NB
    assert file_lock.LOCK_UN == fcntl.LOCK_UN


def test_posix_uses_fcntl_even_when_win32_modules_are_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported: list[str] = []

    def refuse_win32(name: str, *args: object, **kwargs: object):
        imported.append(name)
        raise AssertionError(f"POSIX flock must not import {name}")

    monkeypatch.setattr(file_lock.os, "name", "posix")
    monkeypatch.setitem(sys.modules, "win32file", object())
    first, second = _open_lockfile(tmp_path / "a"), _open_lockfile(tmp_path / "a")
    try:
        flock(first, LOCK_EX)
        flock(first, LOCK_UN)
        monkeypatch.setattr(file_lock, "_win32_api", refuse_win32)
        monkeypatch.setattr(file_lock, "_msvcrt_flock", refuse_win32)
        flock(second, LOCK_EX)
        flock(second, LOCK_UN)
    finally:
        _close(first, second)
    assert imported == []


def test_posix_shared_readers_do_not_block_each_other(tmp_path: Path) -> None:
    first, second = _open_lockfile(tmp_path / "lock"), _open_lockfile(tmp_path / "lock")
    try:
        flock(first, LOCK_SH)
        flock(second, LOCK_SH | LOCK_NB)
        flock(second, LOCK_UN)
        flock(first, LOCK_UN)
    finally:
        _close(first, second)


def test_posix_exclusive_blocks_a_shared_nonblocking_reader(tmp_path: Path) -> None:
    first, second = _open_lockfile(tmp_path / "lock"), _open_lockfile(tmp_path / "lock")
    try:
        flock(first, LOCK_EX)
        with pytest.raises(BlockingIOError):
            flock(second, LOCK_SH | LOCK_NB)
        flock(first, LOCK_UN)
        flock(second, LOCK_SH | LOCK_NB)
        flock(second, LOCK_UN)
    finally:
        _close(first, second)


def test_posix_exclusive_blocks_another_thread_until_unlock(tmp_path: Path) -> None:
    first, second = _open_lockfile(tmp_path / "lock"), _open_lockfile(tmp_path / "lock")
    started = threading.Event()
    finished = threading.Event()

    def waiter() -> None:
        started.set()
        flock(second, LOCK_EX)
        finished.set()

    try:
        flock(first, LOCK_EX)
        worker = threading.Thread(target=waiter)
        worker.start()
        assert started.wait(timeout=1)
        assert not finished.wait(timeout=0.05)
        flock(first, LOCK_UN)
        worker.join(timeout=1)
        assert not worker.is_alive()
        assert finished.is_set()
        flock(second, LOCK_UN)
    finally:
        _close(first, second)


def test_posix_locked_context_releases_on_exception(tmp_path: Path) -> None:
    first, second = _open_lockfile(tmp_path / "lock"), _open_lockfile(tmp_path / "lock")
    try:
        with pytest.raises(RuntimeError, match="boom"):
            with locked(first, LOCK_EX):
                raise RuntimeError("boom")
        flock(second, LOCK_EX | LOCK_NB)
        flock(second, LOCK_UN)
    finally:
        _close(first, second)


def test_posix_locked_does_not_unlock_when_acquire_fails(tmp_path: Path) -> None:
    first, second = _open_lockfile(tmp_path / "lock"), _open_lockfile(tmp_path / "lock")
    unlocked = []

    def tracking_flock(target: int, operation: int) -> None:
        if operation & LOCK_UN:
            unlocked.append(target)
        return file_lock._posix_flock(int(target), operation)

    try:
        flock(first, LOCK_EX)
        original = file_lock.flock
        file_lock.flock = tracking_flock  # type: ignore[method-assign]
        try:
            with pytest.raises(BlockingIOError):
                with locked(second, LOCK_EX | LOCK_NB):
                    pass
        finally:
            file_lock.flock = original  # type: ignore[method-assign]
        assert unlocked == []
        flock(first, LOCK_UN)
    finally:
        _close(first, second)


def test_posix_accepts_a_file_object(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    path.write_bytes(b"data")
    with path.open("r+b") as handle:
        flock(handle, LOCK_EX)
        flock(handle, LOCK_UN)


def test_posix_failure_keeps_the_real_cause_in_the_debug_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    descriptor = _open_lockfile(tmp_path / "lock")
    os.close(descriptor)
    with caplog.at_level(logging.DEBUG, logger="core.utils.file_lock"):
        with pytest.raises(OSError) as raised:
            flock(descriptor, LOCK_EX)
    assert raised.value.errno == errno.EBADF
    assert "Bad file descriptor" in caplog.text or "EBADF" in caplog.text
    assert "cause=OSError" in caplog.text
    assert "_posix_flock" in caplog.text


def test_win32_prefers_lockfileex_and_supports_shared_and_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_msvcrt, fake_win32 = _install_win32(monkeypatch, with_win32=True)
    assert fake_win32 is not None
    first, second = _open_lockfile(tmp_path / "lock"), _open_lockfile(tmp_path / "lock")
    try:
        flock(first, LOCK_SH)
        flock(second, LOCK_SH)
        assert fake_win32.lock_calls[0][1] & LOCKFILE_EXCLUSIVE_LOCK == 0
        assert fake_win32.lock_calls[1][1] & LOCKFILE_EXCLUSIVE_LOCK == 0
        with pytest.raises(BlockingIOError) as raised:
            flock(first, LOCK_EX | LOCK_NB)
        assert raised.value.errno == errno.EAGAIN
        flock(second, LOCK_UN)
        flock(first, LOCK_UN)
        flock(first, LOCK_EX)
        assert fake_win32.lock_calls[-1][1] & LOCKFILE_EXCLUSIVE_LOCK
        flock(first, LOCK_UN)
    finally:
        _close(first, second)
    assert fake_msvcrt.calls == []
    assert fake_msvcrt.handle_calls


def test_win32_unlock_runs_when_the_block_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _msvcrt, fake_win32 = _install_win32(monkeypatch, with_win32=True)
    assert fake_win32 is not None
    descriptor = _open_lockfile(tmp_path / "lock")
    try:
        with pytest.raises(RuntimeError, match="held"):
            with locked(descriptor, LOCK_EX):
                assert descriptor in fake_win32.owners
                raise RuntimeError("held")
        assert descriptor not in fake_win32.owners
        assert fake_win32.unlock_calls == [descriptor]
    finally:
        _close(descriptor)


def test_win32_is_preferred_over_msvcrt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_msvcrt, fake_win32 = _install_win32(monkeypatch, with_win32=True)
    assert fake_win32 is not None
    descriptor = _open_lockfile(tmp_path / "lock")
    try:
        flock(descriptor, LOCK_EX)
        flock(descriptor, LOCK_UN)
    finally:
        _close(descriptor)
    assert fake_win32.lock_calls
    assert fake_msvcrt.calls == []


def test_msvcrt_shared_readers_become_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_msvcrt, _win32 = _install_win32(monkeypatch, with_win32=False)
    first, second = _open_lockfile(tmp_path / "lock"), _open_lockfile(tmp_path / "lock")
    try:
        flock(first, LOCK_SH)
        assert fake_msvcrt.calls[-1][1] == fake_msvcrt.LK_LOCK
        with pytest.raises(BlockingIOError) as raised:
            flock(second, LOCK_SH | LOCK_NB)
        assert raised.value.errno == errno.EAGAIN
        assert fake_msvcrt.calls[-1][1] == fake_msvcrt.LK_NBLCK
        flock(first, LOCK_UN)
        flock(second, LOCK_SH | LOCK_NB)
        flock(second, LOCK_UN)
    finally:
        _close(first, second)


def test_msvcrt_preserves_seek_position(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_msvcrt, _win32 = _install_win32(monkeypatch, with_win32=False)
    path = tmp_path / "lock"
    path.write_bytes(b"abcdefghij")
    descriptor = os.open(path, os.O_RDWR)
    try:
        os.lseek(descriptor, 7, os.SEEK_SET)
        flock(descriptor, LOCK_EX)
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 7
        assert fake_msvcrt.calls[-1][3] == 0
        flock(descriptor, LOCK_UN)
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 7
    finally:
        _close(descriptor)


def test_msvcrt_blocking_retries_after_the_ten_second_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_msvcrt, _win32 = _install_win32(monkeypatch, with_win32=False)
    fake_msvcrt.timeout_failures_remaining = 2
    descriptor = _open_lockfile(tmp_path / "lock")
    try:
        flock(descriptor, LOCK_EX)
        flock(descriptor, LOCK_UN)
    finally:
        _close(descriptor)
    lock_calls = [call for call in fake_msvcrt.calls if call[1] == fake_msvcrt.LK_LOCK]
    assert len(lock_calls) == 3


def test_msvcrt_failure_keeps_the_real_cause_in_the_debug_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake_msvcrt, _win32 = _install_win32(monkeypatch, with_win32=False)
    fake_msvcrt.hard_error = OSError(errno.EIO, "volume went away")
    descriptor = _open_lockfile(tmp_path / "lock")
    try:
        with caplog.at_level(logging.DEBUG, logger="core.utils.file_lock"):
            with pytest.raises(OSError, match="volume went away"):
                flock(descriptor, LOCK_EX)
        assert "volume went away" in caplog.text
        assert "cause=OSError" in caplog.text
        assert "_msvcrt_flock" in caplog.text
    finally:
        _close(descriptor)


def test_msvcrt_permanent_access_error_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_msvcrt, _win32 = _install_win32(monkeypatch, with_win32=False)
    fake_msvcrt.hard_error = OSError(errno.EACCES, "permission denied")
    descriptor = _open_lockfile(tmp_path / "lock")
    try:
        with pytest.raises(OSError, match="permission denied"):
            flock(descriptor, LOCK_EX)
    finally:
        _close(descriptor)
    lock_calls = [call for call in fake_msvcrt.calls if call[1] == fake_msvcrt.LK_LOCK]
    assert len(lock_calls) == 1


def test_win32_failure_keeps_the_real_cause_in_the_debug_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _msvcrt, fake_win32 = _install_win32(monkeypatch, with_win32=True)
    assert fake_win32 is not None

    def explode(*_args: object, **_kwargs: object) -> None:
        raise FakePywinTypesError(5, "LockFileEx", "Access is denied")

    fake_win32.LockFileEx = explode  # type: ignore[method-assign]
    descriptor = _open_lockfile(tmp_path / "lock")
    try:
        with caplog.at_level(logging.DEBUG, logger="core.utils.file_lock"):
            with pytest.raises(OSError, match="Access is denied"):
                flock(descriptor, LOCK_EX)
        assert "Access is denied" in caplog.text
        assert "FakePywinTypesError" in caplog.text or "cause=OSError" in caplog.text
        assert "_win32_flock" in caplog.text
    finally:
        _close(descriptor)
