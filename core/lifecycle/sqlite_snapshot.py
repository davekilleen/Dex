"""Consistent, manifest-backed snapshots for externally owned SQLite databases.

Raw file copies are not SQLite snapshots: committed pages may still live in a
WAL sidecar, and copying a database while its owner writes can capture torn
state. This adapter therefore uses SQLite's online backup API for both capture
and restoration, verifies each resulting database with ``PRAGMA quick_check``,
and publishes restores with one atomic replace.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

MANIFEST_NAME = "manifest.json"
BACKUP_NAME = "database.sqlite3"
SCHEMA_VERSION = 1
_KIND = "sqlite-online-backup"
_HEX = frozenset("0123456789abcdef")
_DEFAULT_BACKUP_TIMEOUT_SECONDS = 5.0
_BACKUP_PAGES = 256
_BACKUP_SLEEP_SECONDS = 0.01
_SYNC_MARKER_SCHEMA_VERSION = 1
_SYNC_MARKER_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "sync-folder-markers.json"
_SYNC_MARKER_KINDS = frozenset(
    {
        "path-segment",
        "cloudstorage-provider",
        "child",
        "paired-children",
        "icloud-materialization",
    }
)


class SQLiteSnapshotError(RuntimeError):
    """A SQLite snapshot or restore could not complete without risking data."""


class _BackupDeadlineExpired(Exception):
    """The online backup did not finish within its bounded retry budget."""


def _refuse(message: str) -> SQLiteSnapshotError:
    return SQLiteSnapshotError(f"SQLite snapshot refused: {message}")


@dataclass(frozen=True)
class SQLiteSnapshotResult:
    """Capture result; data-file owner activity is informational, not a failure."""

    snapshot_dir: Path
    sha256: str
    size: int
    owner_activity: bool
    database_changed: bool
    wal_changed: bool
    shm_changed: bool


@dataclass(frozen=True)
class _StoredEntry:
    relative: str
    sha256: str
    size: int


@dataclass(frozen=True)
class _SyncMarker:
    provider: str
    kind: str
    values: tuple[str, ...]


def _sync_marker_data_error(message: str) -> RuntimeError:
    return RuntimeError(f"Could not safely read sync-folder marker data: {message}")


def _ascii_marker(value: object, context: str) -> str:
    if not isinstance(value, str) or not value or not value.isascii():
        raise _sync_marker_data_error(f"{context} must be a non-empty ASCII string")
    return value


def _load_sync_folder_markers(
    data_path: Path = _SYNC_MARKER_DATA_PATH,
) -> tuple[tuple[_SyncMarker, ...], tuple[tuple[str, str], ...]]:
    try:
        document = json.loads(Path(data_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _sync_marker_data_error(f"{data_path}: {error}") from error
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "markers", "cloudstorage_provider_prefixes"}
        or document.get("schema_version") != _SYNC_MARKER_SCHEMA_VERSION
        or not isinstance(document.get("markers"), list)
        or not document["markers"]
        or not isinstance(document.get("cloudstorage_provider_prefixes"), list)
    ):
        raise _sync_marker_data_error(f"{data_path} has an unsupported schema or shape")

    markers: list[_SyncMarker] = []
    for index, marker in enumerate(document["markers"]):
        if (
            not isinstance(marker, dict)
            or set(marker) != {"provider", "kind", "values"}
            or not isinstance(marker.get("provider"), str)
            or not marker["provider"]
            or marker.get("kind") not in _SYNC_MARKER_KINDS
            or not isinstance(marker.get("values"), list)
            or not marker["values"]
        ):
            raise _sync_marker_data_error(f"{data_path} marker {index} is invalid")
        values = tuple(
            _ascii_marker(value, f"marker {index} value {value_index}")
            for value_index, value in enumerate(marker["values"])
        )
        if marker["kind"] == "path-segment" and len(values) != 2:
            raise _sync_marker_data_error(
                f"{data_path} path-segment marker {index} needs exactly two values"
            )
        if marker["kind"] == "icloud-materialization" and values != (".icloud",):
            raise _sync_marker_data_error(f"{data_path} iCloud marker {index} is invalid")
        markers.append(_SyncMarker(marker["provider"], marker["kind"], values))

    provider_prefixes: list[tuple[str, str]] = []
    for index, entry in enumerate(document["cloudstorage_provider_prefixes"]):
        if (
            not isinstance(entry, dict)
            or set(entry) != {"prefix", "provider"}
            or not isinstance(entry.get("provider"), str)
            or not entry["provider"]
        ):
            raise _sync_marker_data_error(
                f"{data_path} CloudStorage prefix {index} is invalid"
            )
        provider_prefixes.append(
            (
                _ascii_marker(entry.get("prefix"), f"CloudStorage prefix {index}"),
                entry["provider"],
            )
        )
    return tuple(markers), tuple(provider_prefixes)


@lru_cache(maxsize=1)
def _sync_folder_marker_data() -> tuple[
    tuple[_SyncMarker, ...],
    tuple[tuple[str, str], ...],
]:
    return _load_sync_folder_markers()


class _LazySyncMarkers(Sequence[_SyncMarker]):
    """Compatibility view that does not read marker data during module import."""

    def __getitem__(self, index: int | slice) -> _SyncMarker | tuple[_SyncMarker, ...]:
        return _sync_folder_marker_data()[0][index]

    def __len__(self) -> int:
        return len(_sync_folder_marker_data()[0])


# Keep the existing public name without restoring import-time file I/O.
SYNC_MARKERS: Sequence[_SyncMarker] = _LazySyncMarkers()


def _ancestors(path: Path) -> tuple[Path, ...]:
    current = path.absolute()
    return (current, *current.parents)


def _child_names(directory: Path) -> frozenset[str]:
    try:
        return frozenset(child.name.casefold() for child in directory.iterdir())
    except OSError:
        return frozenset()


def _cloudstorage_provider(
    folded_parts: tuple[str, ...],
    sequence: tuple[str, ...],
    provider_prefixes: tuple[tuple[str, str], ...],
) -> str | None:
    width = len(sequence)
    for index in range(len(folded_parts)):
        if folded_parts[index : index + width] != sequence:
            continue
        provider_index = index + width
        if provider_index >= len(folded_parts):
            return "a cloud-synced folder"
        provider_directory = folded_parts[provider_index]
        for prefix, provider in provider_prefixes:
            if provider_directory.startswith(prefix):
                return provider
        return "a cloud-synced folder"
    return None


def detect_sync_folder(path: Path) -> str | None:
    """Return a known sync provider for ``path`` or an ancestor, else ``None``.

    Signals intentionally cover only documented, high-confidence markers:
    Dropbox marker entries, Apple's CloudStorage/materialization convention,
    and OneDrive path or paired folder identifiers. Unknown provider folders
    under CloudStorage receive a generic cloud-synced label instead of a guess;
    paths without a documented signal remain unknown.
    """

    ancestors = _ancestors(Path(path))
    folded_parts = tuple(part.casefold() for part in Path(path).absolute().parts)
    names_by_directory: dict[Path, frozenset[str]] = {}
    markers, provider_prefixes = _sync_folder_marker_data()

    for marker in markers:
        if marker.kind == "path-segment":
            exact, tenant_prefix = marker.values
            if any(part == exact or part.startswith(tenant_prefix) for part in folded_parts):
                return marker.provider
            continue
        if marker.kind == "cloudstorage-provider":
            provider = _cloudstorage_provider(folded_parts, marker.values, provider_prefixes)
            if provider is not None:
                return provider
            continue

        for directory in ancestors:
            names = names_by_directory.setdefault(directory, _child_names(directory))
            if marker.kind == "child" and any(value.casefold() in names for value in marker.values):
                return marker.provider
            if marker.kind == "paired-children" and all(value.casefold() in names for value in marker.values):
                return marker.provider
            if marker.kind == "icloud-materialization" and any(
                name == ".icloud" or name.endswith(".icloud") for name in names
            ):
                return marker.provider
    return None


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _optional_sha256(path: Path) -> str | None:
    try:
        return _sha256(path)[0]
    except FileNotFoundError:
        return None


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("manifest write made no progress")
        offset += written


def _write_manifest(root: Path, result: SQLiteSnapshotResult) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": _KIND,
        "entries": [
            {
                "relative": BACKUP_NAME,
                "sha256": result.sha256,
                "size": result.size,
            }
        ],
        "owner_activity": result.owner_activity,
        "source_changes": {
            "database": result.database_changed,
            "shm": result.shm_changed,
            "wal": result.wal_changed,
        },
    }
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path = root / MANIFEST_NAME
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _readonly_uri(path: Path, *, immutable: bool = False) -> str:
    query = "mode=ro&immutable=1" if immutable else "mode=ro"
    return f"{path.resolve(strict=True).as_uri()}?{query}"


def _quick_check(connection: sqlite3.Connection, context: str) -> None:
    try:
        rows = connection.execute("PRAGMA quick_check").fetchall()
    except sqlite3.Error as error:
        raise _refuse(f"{context} quick_check could not run: {error}") from error
    details = []
    for row in rows:
        if len(row) != 1:
            details.append(repr(row))
        elif row[0] != "ok":
            details.append(str(row[0]))
    if not rows or details:
        reported = "; ".join(details) if details else "no result"
        raise _refuse(f"{context} quick_check failed: {reported}")


def _cleanup_partial_snapshot(root: Path, *, remove_root: bool) -> None:
    for name in (MANIFEST_NAME, BACKUP_NAME, f"{BACKUP_NAME}-journal", f"{BACKUP_NAME}-wal", f"{BACKUP_NAME}-shm"):
        path = root / name
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    if remove_root:
        try:
            root.rmdir()
        except OSError:
            pass


def snapshot_sqlite(
    source_db: Path,
    dest_dir: Path,
    *,
    acknowledged_sync_risk: bool = False,
    backup_timeout_seconds: float = _DEFAULT_BACKUP_TIMEOUT_SECONDS,
) -> SQLiteSnapshotResult:
    """Capture one consistent SQLite database using the online backup API.

    The source is opened with SQLite URI ``mode=ro`` and the online backup is
    refused after ``backup_timeout_seconds`` rather than retrying a busy source
    forever. A hot WAL database must either still have its owner running or live
    in a directory where SQLite can create a missing ``-shm`` file; ``mode=ro``
    does not make that directory operation read-only.

    Changes to database, WAL, and SHM bytes are observed before/after. Database
    and WAL changes are reported as owner activity without invalidating the
    transactionally consistent backup. Creating or updating SHM is benign lock
    coordination that the snapshot connection itself may cause, so it is
    reported separately as ``shm_changed`` rather than as an owner data write.
    """

    source = Path(source_db)
    destination = Path(dest_dir)
    if type(acknowledged_sync_risk) is not bool:
        raise _refuse("acknowledged_sync_risk must be a boolean")
    if source.is_symlink() or not source.is_file():
        raise _refuse(f"source is not a regular database file: {source}")
    # Resolve ancestor symlinks before provider detection so a vault cannot
    # accidentally hide that it physically lives inside a sync root.
    source = source.resolve(strict=True)
    provider = detect_sync_folder(source.parent)
    if provider is not None and not acknowledged_sync_risk:
        raise _refuse(
            f"{provider} sync-folder risk was not acknowledged; "
            "sync services can corrupt SQLite databases mid-write"
        )
    if destination.is_symlink() or destination.exists():
        raise _refuse(f"destination snapshot directory already exists: {destination}")

    sidecars = (source, Path(f"{source}-wal"), Path(f"{source}-shm"))
    before = tuple(_optional_sha256(path) for path in sidecars)
    destination.mkdir(mode=0o700)
    backup = destination / BACKUP_NAME
    source_connection: sqlite3.Connection | None = None
    backup_connection: sqlite3.Connection | None = None
    try:
        try:
            source_connection = sqlite3.connect(_readonly_uri(source), uri=True)
            source_connection.execute("PRAGMA query_only=ON")
            busy_timeout_ms = max(1, int(backup_timeout_seconds * 1000))
            source_connection.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
            backup_connection = sqlite3.connect(backup)
            deadline = time.monotonic() + backup_timeout_seconds

            def refuse_after_deadline(_status: int, _remaining: int, _total: int) -> None:
                if time.monotonic() >= deadline:
                    raise _BackupDeadlineExpired

            try:
                source_connection.backup(
                    backup_connection,
                    pages=_BACKUP_PAGES,
                    progress=refuse_after_deadline,
                    sleep=min(_BACKUP_SLEEP_SECONDS, backup_timeout_seconds),
                )
            except _BackupDeadlineExpired as error:
                raise _refuse(
                    "source database is busy; try again when the owning app is idle"
                ) from error
            _quick_check(backup_connection, "backup")
            backup_connection.close()
            backup_connection = None
            os.chmod(backup, 0o600)
            _fsync_file(backup)
            digest, size = _sha256(backup)

            source_connection.close()
            source_connection = None
            after = tuple(_optional_sha256(path) for path in sidecars)
            changes = tuple(first != last for first, last in zip(before, after, strict=True))
            result = SQLiteSnapshotResult(
                destination,
                digest,
                size,
                changes[0] or changes[1],
                changes[0],
                changes[1],
                changes[2],
            )
            _write_manifest(destination, result)
            _fsync_directory(destination)
            return result
        finally:
            if backup_connection is not None:
                backup_connection.close()
            if source_connection is not None:
                source_connection.close()
    except SQLiteSnapshotError:
        _cleanup_partial_snapshot(destination, remove_root=True)
        raise
    except (OSError, sqlite3.Error) as error:
        _cleanup_partial_snapshot(destination, remove_root=True)
        raise _refuse(f"capture failed: {error}") from error


def _require_mapping(value: object, context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _refuse(f"{context} must be an object with string fields")
    return value


def _require_fields(value: dict[str, Any], required: set[str], context: str) -> None:
    if set(value) != required:
        raise _refuse(f"{context} has an unsupported shape")


def _read_manifest(root: Path) -> _StoredEntry:
    if root.is_symlink() or not root.is_dir():
        raise _refuse("snapshot directory is missing or not a regular directory")
    manifest = root / MANIFEST_NAME
    if manifest.is_symlink():
        raise _refuse("snapshot manifest must not be a symlink")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise _refuse("snapshot manifest is missing") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _refuse(f"snapshot manifest is unreadable: {error}") from error
    value = _require_mapping(payload, "snapshot manifest")
    _require_fields(
        value,
        {"schema_version", "kind", "entries", "owner_activity", "source_changes"},
        "snapshot manifest",
    )
    if type(value["schema_version"]) is not int or value["schema_version"] != SCHEMA_VERSION:
        raise _refuse("snapshot manifest version or kind is unsupported")
    if not isinstance(value["kind"], str) or value["kind"] != _KIND:
        raise _refuse("snapshot manifest version or kind is unsupported")
    if type(value["owner_activity"]) is not bool:
        raise _refuse("snapshot manifest owner_activity must be a boolean")
    changes = _require_mapping(value["source_changes"], "snapshot source_changes")
    _require_fields(changes, {"database", "shm", "wal"}, "snapshot source_changes")
    if any(type(changes[name]) is not bool for name in ("database", "shm", "wal")):
        raise _refuse("snapshot source_changes values must be booleans")
    if value["owner_activity"] is not (changes["database"] or changes["wal"]):
        raise _refuse("snapshot owner_activity disagrees with source_changes")

    entries = value["entries"]
    if not isinstance(entries, list) or len(entries) != 1:
        raise _refuse("snapshot manifest must contain exactly one database entry")
    entry = _require_mapping(entries[0], "snapshot entry")
    _require_fields(entry, {"relative", "sha256", "size"}, "snapshot entry")
    digest = entry["sha256"]
    size = entry["size"]
    if entry["relative"] != BACKUP_NAME:
        raise _refuse("snapshot entry does not name the fixed database backup")
    if not isinstance(digest, str) or len(digest) != 64 or any(character not in _HEX for character in digest):
        raise _refuse("snapshot entry sha256 is not a lowercase digest")
    if type(size) is not int or size < 0:
        raise _refuse("snapshot entry size must be a non-negative integer")
    return _StoredEntry(BACKUP_NAME, digest, size)


def _reserve_restore_temp(destination: Path) -> Path:
    for attempt in range(100):
        temporary = destination.parent / f".{destination.name}.sqlite-restore-{os.getpid()}-{attempt}"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        os.close(descriptor)
        return temporary
    raise _refuse("could not reserve a unique restore temporary file")


def restore_sqlite(snapshot_dir: Path, dest_db: Path) -> None:
    """Verify and atomically restore a SQLite snapshot to ``dest_db``.

    Existing ``-wal`` and ``-shm`` files belong to the pre-restore database
    generation. They are removed and that directory change is synced before the
    checked temporary database atomically replaces the destination. Therefore,
    whenever the new main database is durably visible, old-generation sidecars
    cannot be durably paired with it.

    This ordering deliberately does not preserve WAL-only commits if the atomic
    replace then fails: an existing old main database remains without its
    sidecars, and the caller receives a detectable failure. That state is
    degraded but consistent and retryable instead of silently replaying a stale
    WAL against the restored main database.
    """

    root = Path(snapshot_dir)
    destination = Path(dest_db)
    if not destination.parent.is_dir():
        raise _refuse(f"restore destination directory does not exist: {destination.parent}")
    if destination.is_dir():
        raise _refuse(f"restore destination is a directory: {destination}")
    entry = _read_manifest(root)
    stored = root / entry.relative
    if stored.is_symlink() or not stored.is_file():
        raise _refuse("stored database backup is missing or not a regular file")
    digest, size = _sha256(stored)
    if digest != entry.sha256 or size != entry.size:
        raise _refuse("stored database bytes do not match the manifest; refusing restore")

    stale_sidecars = (Path(f"{destination}-wal"), Path(f"{destination}-shm"))
    if any(path.exists() and not (path.is_file() or path.is_symlink()) for path in stale_sidecars):
        raise _refuse("a stale destination sidecar is not a removable file")

    temporary = _reserve_restore_temp(destination)
    source_connection: sqlite3.Connection | None = None
    temporary_connection: sqlite3.Connection | None = None
    replaced = False
    try:
        # The stored backup has already been closed and verified byte-for-byte,
        # so immutable mode is truthful and prevents SQLite from creating WAL/
        # SHM coordination files inside the read-only snapshot store.
        source_connection = sqlite3.connect(_readonly_uri(stored, immutable=True), uri=True)
        source_connection.execute("PRAGMA query_only=ON")
        temporary_connection = sqlite3.connect(temporary)
        source_connection.backup(temporary_connection)
        _quick_check(temporary_connection, "restore temporary")
        temporary_connection.close()
        temporary_connection = None
        source_connection.close()
        source_connection = None
        final_digest, final_size = _sha256(stored)
        if final_digest != entry.sha256 or final_size != entry.size:
            raise _refuse("stored database changed during restore; refusing atomic replace")
        os.chmod(temporary, 0o600)
        _fsync_file(temporary)
        # These files contain state and coordination for the old inode. Keeping
        # either beside the restored main file could replay the wrong generation.
        for sidecar in stale_sidecars:
            try:
                sidecar.unlink()
            except FileNotFoundError:
                pass
        _fsync_directory(destination.parent)
        os.replace(temporary, destination)
        replaced = True
        _fsync_directory(destination.parent)
    except SQLiteSnapshotError:
        raise
    except (OSError, sqlite3.Error) as error:
        state = "after atomic replace" if replaced else "before atomic replace"
        raise _refuse(f"restore failed {state}: {error}") from error
    finally:
        if temporary_connection is not None:
            temporary_connection.close()
        if source_connection is not None:
            source_connection.close()
        suffixes = ("-journal", "-wal", "-shm") if replaced else ("", "-journal", "-wal", "-shm")
        for suffix in suffixes:
            try:
                Path(f"{temporary}{suffix}").unlink()
            except FileNotFoundError:
                pass


__all__ = [
    "BACKUP_NAME",
    "MANIFEST_NAME",
    "SYNC_MARKERS",
    "SQLiteSnapshotError",
    "SQLiteSnapshotResult",
    "detect_sync_folder",
    "restore_sqlite",
    "snapshot_sqlite",
]
