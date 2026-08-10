"""Owner-safe mutation lock — one mutating engine per vault at a time.

A faithful Python port of the semantics proven in the v1→v2 migrator's
``owned-lock.cjs`` (PR #141):

- create-exclusive lock file (0o600) carrying ``{pid, kind, token, at}``,
  fsynced, parent directory fsynced — so a crash cannot leave a torn lock
  (on Windows the directory fsync is skipped: directories cannot be opened
  there, and attempting it orphaned the just-created lock — issue #257);
- liveness by signal-0 probe of the recorded PID (EPERM counts as alive);
  on Windows a query-only process handle is used instead, because os.kill
  is documented to unconditionally TerminateProcess the target there;
- a lock naming our own live PID that no acquisition in this process holds
  is our own crash orphan and is reclaimed instead of reported busy;
- stale-lock takeover only via *pinned removal*: the lock is removed only if
  its device+inode+exact bytes still match what was observed, so two waiters
  can never both "clean up" and race into ownership;
- release only removes the lock if it still carries our token on our inode —
  releasing after a takeover is a no-op, never a theft.

The lock file is shared with the CJS migrator by PATH (both engines lock the
same file), which is what guarantees "one mutator per vault" across languages.
"""

from __future__ import annotations

import errno
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.path_safety import unsafe_existing_parent

LOCK_RELATIVE = Path("System") / ".dex" / "mutation.lock"
_MAX_ACQUIRE_ATTEMPTS = 32

# Locks currently held by THIS process (lock path → owning token). Lets a
# later acquisition distinguish "a live acquisition in this process still
# holds the file" (busy) from "the file carries our PID but nothing in this
# process holds it" — an orphan from a crashed earlier acquire that only we
# can safely reclaim, because no other live process can share our PID.
# (Issue #257: on Windows a failure between creating the lock file and
# returning its release left exactly such an orphan, and the doctor's next
# write then reported the doctor's own PID as a foreign process.)
_HELD_LOCKS: dict[str, str] = {}
_HELD_LOCKS_GUARD = threading.Lock()


class LockError(RuntimeError):
    """The mutation lock path is unsafe."""


class LockBusyError(RuntimeError):
    """Another live process owns the vault mutation lock."""

    def __init__(self, pid: object, kind: object) -> None:
        self.owner_pid = pid
        self.owner_kind = kind
        super().__init__(
            f"another Dex process (pid {pid}, {kind}) is already changing this "
            "vault; wait for it to finish, then retry"
        )


class LockContentionError(RuntimeError):
    """Lock ownership kept changing while we tried to acquire it."""


@dataclass(frozen=True)
class _Snapshot:
    device: int
    inode: int
    raw: bytes
    payload: dict | None


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        # Windows cannot open a directory through os.open (CreateFile needs
        # FILE_FLAG_BACKUP_SEMANTICS, which os.open never passes), so this
        # raised PermissionError AFTER the lock file was already created —
        # orphaning a lock that named our own PID (issue #257). There is no
        # user-space directory fsync on Windows; entry durability is the
        # filesystem's, exactly like every other Windows write in Dex.
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _windows_process_is_running(pid: int) -> bool:
    """Liveness by opening a query-only process handle; never signals."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means the process exists but is not ours to query —
        # the same "counts as alive" stance as EPERM on POSIX.
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True  # it opened; treat as alive rather than steal a lock
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _process_is_running(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if pid == os.getpid():
        return True  # trivially alive — and never worth signalling ourselves
    if os.name == "nt":
        # os.kill is NOT a liveness probe on Windows: for any sig other than
        # the console-control events, CPython documents that the target "will
        # be unconditionally killed by the TerminateProcess API" — so probing
        # a recorded PID with os.kill(pid, 0) could terminate a live process.
        return _windows_process_is_running(pid)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def _read_snapshot(lock: Path) -> _Snapshot | None:
    try:
        descriptor = os.open(lock, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        stat = os.fstat(descriptor)
        raw = b""
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(descriptor)
    payload: dict | None
    try:
        parsed = json.loads(raw.decode("utf-8"))
        payload = parsed if isinstance(parsed, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Malformed data has no live owner, but its exact bytes and inode
        # still guard removal.
        payload = None
    return _Snapshot(stat.st_dev, stat.st_ino, raw, payload)


def _same_snapshot(left: _Snapshot | None, right: _Snapshot | None) -> bool:
    return bool(
        left
        and right
        and left.device == right.device
        and left.inode == right.inode
        and left.raw == right.raw
    )


def _remove_if_unchanged(lock: Path, observed: _Snapshot) -> bool:
    current = _read_snapshot(lock)
    if not _same_snapshot(observed, current):
        return False
    try:
        os.unlink(lock)
    except FileNotFoundError:
        return False
    _fsync_directory(lock.parent)
    return True


def acquire_owned_lock(vault_root: Path, kind: str):
    """Acquire the vault mutation lock; returns a zero-argument release().

    Raises :class:`LockBusyError` when a live process holds it and
    :class:`LockContentionError` when ownership churns for 32 attempts.
    """
    root = Path(vault_root).resolve()
    unsafe_parent = unsafe_existing_parent(root, LOCK_RELATIVE.as_posix())
    if unsafe_parent is not None:
        raise LockError(
            f"refusing unsafe mutation lock path {LOCK_RELATIVE.as_posix()}: "
            f"{unsafe_parent}"
        )
    lock = root / LOCK_RELATIVE
    lock.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(24)

    for _attempt in range(_MAX_ACQUIRE_ATTEMPTS):
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as error:
            if error.errno != errno.EEXIST:
                raise
            observed = _read_snapshot(lock)
            if observed is None:
                continue  # vanished between EEXIST and read — retry
            payload = observed.payload or {}
            owner_pid = payload.get("pid")
            with _HELD_LOCKS_GUARD:
                held_here = str(lock) in _HELD_LOCKS
            if owner_pid == os.getpid() and not held_here:
                # The file names our own PID but nothing in this process
                # holds it: an earlier acquisition here crashed between
                # creating the file and returning its release (issue #257).
                # No other live process can share our PID, so this orphan is
                # ours to reclaim — through the same pinned removal as any
                # stale lock, so a concurrent waiter can never race us in.
                _remove_if_unchanged(lock, observed)
                continue
            if _process_is_running(owner_pid):
                raise LockBusyError(owner_pid, payload.get("kind")) from None
            if not _remove_if_unchanged(lock, observed):
                continue  # someone else took it over — retry
            continue

        try:
            body = (
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "kind": str(kind),
                        "token": token,
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                + "\n"
            ).encode("utf-8")
            os.write(descriptor, body)
            os.fsync(descriptor)
            stat = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(lock.parent)

        def release(
            _lock: Path = lock,
            _token: str = token,
            _device: int = stat.st_dev,
            _inode: int = stat.st_ino,
        ) -> None:
            # Whatever the file now says, this acquisition is over: drop our
            # registry entry (only if it is still ours) before touching disk.
            with _HELD_LOCKS_GUARD:
                if _HELD_LOCKS.get(str(_lock)) == _token:
                    del _HELD_LOCKS[str(_lock)]
            current = _read_snapshot(_lock)
            if (
                current is not None
                and current.payload is not None
                and current.payload.get("token") == _token
                and current.device == _device
                and current.inode == _inode
            ):
                try:
                    os.unlink(_lock)
                except FileNotFoundError:
                    return  # already gone — released is released
                try:
                    _fsync_directory(_lock.parent)
                except OSError:
                    # A restore may have removed the now-empty runtime dir.
                    pass

        # Register only after the acquisition can no longer fail, so a crash
        # anywhere above leaves the path out of the registry and the orphan
        # reclaim path (EEXIST + our PID + not held here) stays reachable.
        with _HELD_LOCKS_GUARD:
            _HELD_LOCKS[str(lock)] = token
        return release

    raise LockContentionError(
        "Dex could not safely acquire its mutation lock because ownership kept "
        "changing. Wait a moment, then retry."
    )
