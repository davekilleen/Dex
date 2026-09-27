"""Cross-platform advisory file lock used by the ledger and sibling lockers.

POSIX behaviour is unchanged: ``fcntl.flock`` with the same flags, blocking
rules, and timeouts (there is no timeout — a blocking lock waits until the
kernel grants it).

On Windows there is no ``fcntl`` module (native python.org builds, including
those launched from Git Bash). The helper then prefers ``LockFileEx`` via
pywin32 when that package is importable, which can take shared and exclusive
locks. Otherwise it falls back to ``msvcrt.locking`` with no new hard
dependency:

- exclusive-only — a shared request is upgraded to exclusive
- byte-range — one byte at offset 0, not a whole-file lock
- ``LK_LOCK`` itself retries for about ten seconds; blocking callers loop
  that call so they still wait indefinitely, matching POSIX

Lock failures are re-raised unchanged. The original exception is also written
to the debug log so a Windows ``ModuleNotFoundError: fcntl`` can never hide
behind a generic "lock failed".
"""

from __future__ import annotations

import errno
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Any, Callable

logger = logging.getLogger(__name__)

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - native Windows Python
    _fcntl = None
    LOCK_SH = 1
    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8
else:
    LOCK_SH = _fcntl.LOCK_SH
    LOCK_EX = _fcntl.LOCK_EX
    LOCK_NB = _fcntl.LOCK_NB
    LOCK_UN = _fcntl.LOCK_UN

# msvcrt.locking is a byte-range lock. One byte at offset 0 is the conventional
# exclusive-only stand-in for a whole-file flock. Shared readers become
# exclusive under this fallback — see the module docstring.
_MSVCRT_LOCK_LENGTH = 1
_WIN32_MAXDWORD = 0xFFFFFFFF
_ERROR_LOCK_VIOLATION = 33
_ERROR_IO_PENDING = 997
_ERROR_NOT_LOCKED = 158

# win32con values, duplicated so tests can build flags without pywin32.
LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
LOCKFILE_EXCLUSIVE_LOCK = 0x00000002

FileTarget = int | IO[Any]
_Backend = Callable[[int, int], None]


def flock(target: FileTarget, operation: int) -> None:
    """Acquire, upgrade, or release an advisory lock on ``target``.

    ``target`` may be a raw descriptor or a file object with ``fileno()``.
    ``operation`` is a ``LOCK_*`` flag, optionally OR'd with ``LOCK_NB``.
    """
    descriptor = _fileno(target)
    backend_name = "unknown"
    try:
        backend = _choose_backend()
        backend_name = backend.__name__
        backend(descriptor, operation)
    except Exception as error:
        logger.debug(
            "file lock failed: backend=%s fd=%s operation=%s cause=%s: %r",
            backend_name,
            descriptor,
            operation,
            type(error).__name__,
            error,
            exc_info=True,
        )
        raise


@contextmanager
def locked(target: FileTarget, operation: int) -> Iterator[None]:
    """Hold ``operation`` until the block exits, then unlock.

    Unlock always runs, including when the block raises. The lock is taken
    before the block starts, so a failed acquire never unlocks.
    """
    flock(target, operation)
    try:
        yield
    finally:
        flock(target, LOCK_UN)


def _fileno(target: FileTarget) -> int:
    if isinstance(target, int):
        return target
    fileno = getattr(target, "fileno", None)
    if not callable(fileno):
        raise TypeError(f"file lock target has no fileno: {type(target)!r}")
    return int(fileno())


def _choose_backend() -> _Backend:
    if os.name != "nt":
        return _posix_flock
    if _win32_api() is not None:
        return _win32_flock
    return _msvcrt_flock


def _posix_flock(descriptor: int, operation: int) -> None:
    if _fcntl is None:  # pragma: no cover - only when tests force POSIX without fcntl
        raise OSError(errno.ENOSYS, "fcntl.flock is unavailable on this Python")
    _fcntl.flock(descriptor, operation)


def _win32_api() -> tuple[Any, Any, Any, Any] | None:
    try:
        import msvcrt

        import pywintypes
        import win32con
        import win32file
    except ImportError:
        return None
    if not hasattr(win32file, "LockFileEx") or not hasattr(win32file, "UnlockFileEx"):
        return None
    return msvcrt, pywintypes, win32con, win32file


def _win32_error_code(error: BaseException) -> int | None:
    winerror = getattr(error, "winerror", None)
    if isinstance(winerror, int):
        return winerror
    args = getattr(error, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def _raise_win32_lock_error(error: BaseException, *, nonblocking: bool) -> None:
    winerror = _win32_error_code(error)
    if winerror in (_ERROR_LOCK_VIOLATION, _ERROR_IO_PENDING):
        if nonblocking:
            raise BlockingIOError(errno.EAGAIN, os.strerror(errno.EAGAIN)) from error
        raise OSError(errno.EAGAIN, os.strerror(errno.EAGAIN)) from error
    raise OSError(errno.EIO, f"LockFileEx failed: {error}") from error


def _win32_flock(descriptor: int, operation: int) -> None:
    api = _win32_api()
    if api is None:  # pragma: no cover - choose_backend already gated this
        raise OSError(errno.ENOSYS, "pywin32 LockFileEx is unavailable")
    msvcrt, pywintypes, win32con, win32file = api
    handle = msvcrt.get_osfhandle(descriptor)
    overlapped = pywintypes.OVERLAPPED()

    if operation & LOCK_UN:
        try:
            win32file.UnlockFileEx(
                handle, 0, _WIN32_MAXDWORD, _WIN32_MAXDWORD, overlapped
            )
        except pywintypes.error as error:
            if _win32_error_code(error) == _ERROR_NOT_LOCKED:
                return
            _raise_win32_lock_error(error, nonblocking=False)
        return

    if not (operation & (LOCK_SH | LOCK_EX)):
        raise ValueError(f"unsupported file lock operation: {operation}")

    flags = 0
    if operation & LOCK_EX:
        flags |= int(getattr(win32con, "LOCKFILE_EXCLUSIVE_LOCK", LOCKFILE_EXCLUSIVE_LOCK))
    if operation & LOCK_NB:
        flags |= int(
            getattr(win32con, "LOCKFILE_FAIL_IMMEDIATELY", LOCKFILE_FAIL_IMMEDIATELY)
        )

    try:
        win32file.LockFileEx(
            handle, flags, 0, _WIN32_MAXDWORD, _WIN32_MAXDWORD, overlapped
        )
    except pywintypes.error as error:
        _raise_win32_lock_error(error, nonblocking=bool(operation & LOCK_NB))


def _is_lock_busy(error: OSError) -> bool:
    """Contention / timeout, not a permanent permission or I/O failure."""
    if isinstance(error, BlockingIOError):
        return True
    deadlock = {errno.EDEADLK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}
    return error.errno in {errno.EACCES, errno.EAGAIN} | deadlock


def _is_blocking_timeout(error: OSError) -> bool:
    """``msvcrt.LK_LOCK`` raises after ~10s; only those errors may be retried.

    ``EACCES`` is also used for non-blocking contention and for some permanent
    access failures. Retrying it on a blocking lock would spin forever.
    """
    deadlock = {errno.EDEADLK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}
    return error.errno in deadlock | {errno.EAGAIN}


def _msvcrt_apply(descriptor: int, mode: int) -> None:
    import msvcrt

    try:
        position = os.lseek(descriptor, 0, os.SEEK_CUR)
    except OSError as error:
        raise OSError(
            error.errno,
            f"msvcrt file lock requires a seekable file descriptor: {error.strerror}",
        ) from error
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, mode, _MSVCRT_LOCK_LENGTH)
    finally:
        try:
            os.lseek(descriptor, position, os.SEEK_SET)
        except OSError:
            pass


def _msvcrt_flock(descriptor: int, operation: int) -> None:
    # Caveat: msvcrt.locking is exclusive-only and locks a byte range (one byte
    # at offset 0). Shared readers are therefore taken as exclusive locks.
    try:
        import msvcrt
    except ImportError as error:  # pragma: no cover - os.name == "nt" implies msvcrt
        raise OSError(errno.ENOSYS, "no Windows file-lock backend is available") from error

    if operation & LOCK_UN:
        try:
            _msvcrt_apply(descriptor, msvcrt.LK_UNLCK)
        except OSError as error:
            if error.errno in {errno.EINVAL, errno.EPERM, errno.EACCES}:
                return
            raise
        return

    if not (operation & (LOCK_SH | LOCK_EX)):
        raise ValueError(f"unsupported file lock operation: {operation}")

    if operation & LOCK_NB:
        try:
            _msvcrt_apply(descriptor, msvcrt.LK_NBLCK)
        except OSError as error:
            if _is_lock_busy(error):
                raise BlockingIOError(errno.EAGAIN, os.strerror(errno.EAGAIN)) from error
            raise
        return

    while True:
        try:
            _msvcrt_apply(descriptor, msvcrt.LK_LOCK)
            return
        except OSError as error:
            if _is_blocking_timeout(error):
                # LK_LOCK already waited ~10s. Loop so blocking matches POSIX.
                continue
            raise
