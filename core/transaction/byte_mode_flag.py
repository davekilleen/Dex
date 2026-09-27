"""Per-transaction byte-mode flag written at the start of each operation.

Windows snapshots taken before Dex started reading files as exact bytes may
have altered line endings. A clock comparison would fail open if the clock
was ahead, so this flag — written when the operation starts — is the only
evidence that a snapshot is safe to restore.

``hash_read_mode`` values:
- ``binary`` — this process wrote the flag; reads were exact.
- ``pre-repair`` — stamped onto an existing snapshot at the start of the
  bookkeeping repair; restore is refused on Windows.
- missing — treated as pre-repair on Windows (fail closed).
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

from core.transaction.fsync import fsync_directory
from core.utils.os_flags import binary_write_flags

FLAG_NAME = "byte-mode.json"
HASH_READ_MODE_BINARY = "binary"
HASH_READ_MODE_PRE_REPAIR = "pre-repair"

MESSAGE_REWIND_REFUSED = (
    "This update was recorded before Dex fixed how it reads files on Windows, "
    "so its undo copy may have altered line endings. Dex will not restore it. "
    "Your current files are untouched; to go back, restore from your own backup."
)


class PreRepairRestoreRefused(RuntimeError):
    """A pre-repair snapshot must not be restored on Windows."""

    def __init__(self, message: str = MESSAGE_REWIND_REFUSED) -> None:
        super().__init__(message)


def flag_path(tx_dir: Path) -> Path:
    return Path(tx_dir) / FLAG_NAME


def _canonical_flag(hash_read_mode: str) -> bytes:
    return (
        json.dumps(
            {"hash_read_mode": hash_read_mode},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def write_operation_flag(tx_dir: Path, hash_read_mode: str) -> None:
    """Write the flag at the start of an operation. Does not compare clocks."""
    if hash_read_mode not in {HASH_READ_MODE_BINARY, HASH_READ_MODE_PRE_REPAIR}:
        raise ValueError(f"unsupported hash_read_mode: {hash_read_mode}")
    directory = Path(tx_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = flag_path(directory)
    if target.exists() and not target.is_symlink() and target.is_file():
        current = target.read_bytes()
        if current == _canonical_flag(hash_read_mode):
            return
        if (
            hash_read_mode == HASH_READ_MODE_PRE_REPAIR
            and current == _canonical_flag(HASH_READ_MODE_BINARY)
        ):
            # A snapshot taken by this code is already exact; do not downgrade.
            return
    _atomic_write(target, _canonical_flag(hash_read_mode))


def read_operation_flag(tx_dir: Path) -> str | None:
    target = flag_path(Path(tx_dir))
    if target.is_symlink() or not target.is_file():
        return None
    try:
        raw = target.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    mode = document.get("hash_read_mode")
    if mode not in {HASH_READ_MODE_BINARY, HASH_READ_MODE_PRE_REPAIR}:
        return None
    if raw != _canonical_flag(mode):
        return None
    return mode


def snapshot_is_pre_repair(tx_dir: Path) -> bool:
    """True when the snapshot must not be restored on Windows."""
    mode = read_operation_flag(tx_dir)
    return mode != HASH_READ_MODE_BINARY


def restore_is_refused(tx_dir: Path) -> bool:
    """Windows-only refuse: missing or pre-repair flag. POSIX always allows."""
    return os.name == "nt" and snapshot_is_pre_repair(tx_dir)


def refuse_pre_repair_restore(tx_dir: Path) -> None:
    if restore_is_refused(tx_dir):
        raise PreRepairRestoreRefused(MESSAGE_REWIND_REFUSED)


def stamp_unmarked_snapshots_pre_repair(vault_root: Path) -> tuple[str, ...]:
    """At the start of repair, mark existing snapshots that have no binary flag."""
    from core.transaction.engine import TX_ROOT_RELATIVE

    stamped: list[str] = []
    tx_root = Path(vault_root) / TX_ROOT_RELATIVE
    if not tx_root.is_dir() or tx_root.is_symlink():
        return ()
    for tx_dir in sorted(tx_root.iterdir(), key=lambda path: path.name):
        if tx_dir.is_symlink() or not tx_dir.is_dir():
            continue
        if read_operation_flag(tx_dir) == HASH_READ_MODE_BINARY:
            continue
        write_operation_flag(tx_dir, HASH_READ_MODE_PRE_REPAIR)
        stamped.append(f"System/.dex/tx/{tx_dir.name}/snapshot")
    return tuple(stamped)


def _atomic_write(target: Path, data: bytes) -> None:
    directory = target.parent
    temporary = directory / f".{target.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            binary_write_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL),
            0o600,
        )
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        fsync_directory(directory)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
