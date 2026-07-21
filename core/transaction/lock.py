"""Owner-safe mutation lock — one mutating engine per vault at a time.

A faithful Python port of the semantics proven in the v1→v2 migrator's
``owned-lock.cjs`` (PR #141):

- create-exclusive lock file (0o600) carrying ``{pid, kind, token, at}``,
  fsynced, parent directory fsynced — so a crash cannot leave a torn lock;
- liveness by signal-0 probe of the recorded PID (EPERM counts as alive);
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from core.path_safety import unsafe_existing_parent

LOCK_RELATIVE = Path("System") / ".dex" / "mutation.lock"
_MAX_ACQUIRE_ATTEMPTS = 32


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
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _process_is_running(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
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
            if _process_is_running(payload.get("pid")):
                raise LockBusyError(payload.get("pid"), payload.get("kind")) from None
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
            current = _read_snapshot(_lock)
            if (
                current is not None
                and current.payload is not None
                and current.payload.get("token") == _token
                and current.device == _device
                and current.inode == _inode
            ):
                os.unlink(_lock)
                try:
                    _fsync_directory(_lock.parent)
                except OSError:
                    # A restore may have removed the now-empty runtime dir.
                    pass

        return release

    raise LockContentionError(
        "Dex could not safely acquire its mutation lock because ownership kept "
        "changing. Wait a moment, then retry."
    )
