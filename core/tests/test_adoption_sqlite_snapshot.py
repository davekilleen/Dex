"""Adversarial contract tests for lifecycle SQLite snapshots (Gate E8)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from core.lifecycle.sqlite_snapshot import (
    BACKUP_NAME,
    MANIFEST_NAME,
    SQLiteSnapshotError,
    detect_sync_folder,
    restore_sqlite,
    snapshot_sqlite,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(database: Path) -> list[tuple[int, str]]:
    connection = sqlite3.connect(database)
    try:
        return connection.execute("SELECT id, value FROM entries ORDER BY id").fetchall()
    finally:
        connection.close()


def _create_database(path: Path, rows: int = 3) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE entries(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO entries(value) VALUES (?)",
            [(f"row-{index}",) for index in range(rows)],
        )
        connection.commit()
    finally:
        connection.close()


def test_wal_snapshot_restores_all_committed_rows_without_touching_source_database_or_wal(
    tmp_path: Path,
) -> None:
    """E8: online backup includes committed WAL pages and is read-only to its source."""
    source = tmp_path / "source.sqlite3"
    owner = sqlite3.connect(source)
    try:
        assert owner.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        owner.execute("PRAGMA wal_autocheckpoint=0")
        owner.execute("CREATE TABLE entries(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        owner.executemany(
            "INSERT INTO entries(value) VALUES (?)",
            [("main",), ("wal-only-1",), ("wal-only-2",)],
        )
        owner.commit()

        source_wal = Path(f"{source}-wal")
        source_shm = Path(f"{source}-shm")
        assert source_wal.stat().st_size > 0
        assert source_shm.is_file()
        # SQLite's WAL locking protocol may update read-mark bytes in an
        # already-live SHM file. The externally meaningful persistent bytes we
        # promise to leave invariant are the database and WAL themselves.
        before = {path: path.read_bytes() for path in (source, source_wal)}

        snapshot_dir = tmp_path / "snapshot"
        result = snapshot_sqlite(source, snapshot_dir)

        assert {path: path.read_bytes() for path in before} == before
        assert result.owner_activity is False
        manifest = json.loads((snapshot_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
        entry = manifest["entries"][0]
        backup = snapshot_dir / BACKUP_NAME
        assert entry == {
            "relative": BACKUP_NAME,
            "sha256": _sha256(backup),
            "size": backup.stat().st_size,
        }
        stored_before_restore = {
            path.name: path.read_bytes() for path in snapshot_dir.iterdir()
        }

        restored = tmp_path / "restored.sqlite3"
        restore_sqlite(snapshot_dir, restored)
        assert _rows(restored) == [(1, "main"), (2, "wal-only-1"), (3, "wal-only-2")]
        assert {path.name: path.read_bytes() for path in snapshot_dir.iterdir()} == stored_before_restore
    finally:
        owner.close()


def test_quiescent_source_open_creates_or_changes_no_sqlite_sidecars(tmp_path: Path) -> None:
    source = tmp_path / "quiescent.sqlite3"
    _create_database(source)
    before = source.read_bytes()
    assert not Path(f"{source}-wal").exists()
    assert not Path(f"{source}-shm").exists()

    result = snapshot_sqlite(source, tmp_path / "snapshot")

    assert source.read_bytes() == before
    assert not Path(f"{source}-wal").exists()
    assert not Path(f"{source}-shm").exists()
    assert result.owner_activity is False


@pytest.mark.parametrize(
    ("layout", "provider"),
    [
        ("dropbox", "Dropbox"),
        ("dropbox-cache", "Dropbox"),
        ("cloud-storage-dropbox", "Dropbox"),
        ("cloud-storage-google-drive", "GoogleDrive"),
        ("cloud-storage-onedrive", "OneDrive"),
        ("cloud-storage-box", "Box"),
        ("cloud-storage-unknown", "a cloud-synced folder"),
        ("icloud-materialization", "iCloud Drive"),
        ("onedrive-segment", "OneDrive"),
        ("onedrive-markers", "OneDrive"),
    ],
)
def test_sync_folder_detection_uses_only_documented_markers(
    tmp_path: Path,
    layout: str,
    provider: str,
) -> None:
    root = tmp_path / "sync-root"
    vault = root / "Vault"
    if layout == "dropbox":
        (root / ".dropbox").mkdir(parents=True)
    elif layout == "dropbox-cache":
        (root / ".dropbox.cache").mkdir(parents=True)
    elif layout.startswith("cloud-storage-"):
        provider_directory = {
            "cloud-storage-dropbox": "Dropbox",
            "cloud-storage-google-drive": "GoogleDrive-example.com",
            "cloud-storage-onedrive": "OneDrive-ExampleOrg",
            "cloud-storage-box": "Box-Box",
            "cloud-storage-unknown": "AcmeSync-example.com",
        }[layout]
        vault = tmp_path / "Library" / "CloudStorage" / provider_directory / "Vault"
    elif layout == "icloud-materialization":
        root.mkdir(parents=True)
        (root / "pending-note.md.icloud").write_bytes(b"")
    elif layout == "onedrive-segment":
        vault = tmp_path / "OneDrive - Example Org" / "Vault"
    elif layout == "onedrive-markers":
        root.mkdir(parents=True)
        (root / "desktop.ini").write_bytes(b"")
        (root / ".849C9593-D756-4E56-8D6E-42412F2A707B").write_bytes(b"")
    vault.mkdir(parents=True, exist_ok=True)

    assert detect_sync_folder(vault) == provider


def test_unknown_folder_is_not_guessed_to_be_synced(tmp_path: Path) -> None:
    vault = tmp_path / "ordinary" / "Vault"
    vault.mkdir(parents=True)
    (vault.parent / "desktop.ini").write_bytes(b"not enough for OneDrive")

    assert detect_sync_folder(vault) is None


def test_onedrive_detection_requires_a_full_provider_path_segment(tmp_path: Path) -> None:
    ordinary = tmp_path / "not-onedrive-backup" / "Vault"
    onedrive = tmp_path / "OneDrive" / "Vault"
    tenant = tmp_path / "OneDrive - Example Org" / "Vault"
    ordinary.mkdir(parents=True)
    onedrive.mkdir(parents=True)
    tenant.mkdir(parents=True)

    assert detect_sync_folder(ordinary) is None
    assert detect_sync_folder(onedrive) == "OneDrive"
    assert detect_sync_folder(tenant) == "OneDrive"


def test_sync_folder_snapshot_requires_named_explicit_acknowledgement(tmp_path: Path) -> None:
    sync_root = tmp_path / "team-files"
    (sync_root / ".dropbox").mkdir(parents=True)
    vault = sync_root / "Vault"
    vault.mkdir()
    source = vault / "external.sqlite3"
    _create_database(source)
    snapshot_dir = tmp_path / "snapshot"

    with pytest.raises(SQLiteSnapshotError, match="Dropbox.*sync services can corrupt SQLite databases mid-write"):
        snapshot_sqlite(source, snapshot_dir)
    assert not snapshot_dir.exists()

    snapshot_sqlite(source, snapshot_dir, acknowledged_sync_risk=True)
    assert (snapshot_dir / MANIFEST_NAME).is_file()


def test_concurrent_owner_write_is_reported_instead_of_rejected(tmp_path: Path) -> None:
    source = tmp_path / "owner.sqlite3"
    owner = sqlite3.connect(source)
    snapshot_dir = tmp_path / "snapshot"
    writer_finished = threading.Event()
    try:
        owner.execute("PRAGMA journal_mode=WAL")
        owner.execute("PRAGMA wal_autocheckpoint=0")
        owner.execute("CREATE TABLE entries(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        owner.execute("CREATE TABLE ballast(content BLOB NOT NULL)")
        owner.execute("INSERT INTO entries(value) VALUES ('before')")
        owner.execute("INSERT INTO ballast(content) VALUES (zeroblob(33554432))")
        owner.commit()

        def owner_write() -> None:
            while not (snapshot_dir / BACKUP_NAME).exists():
                writer_finished.wait(0.001)
            connection = sqlite3.connect(source)
            try:
                connection.execute("INSERT INTO entries(value) VALUES ('during')")
                connection.commit()
            finally:
                connection.close()
                writer_finished.set()

        writer = threading.Thread(target=owner_write)
        writer.start()
        result = snapshot_sqlite(source, snapshot_dir)
        writer.join(timeout=5)

        assert writer_finished.is_set()
        assert result.owner_activity is True
        assert result.wal_changed is True
        manifest = json.loads((snapshot_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert manifest["owner_activity"] is True
        assert manifest["source_changes"]["wal"] is True
        restored = tmp_path / "restored.sqlite3"
        restore_sqlite(snapshot_dir, restored)
        connection = sqlite3.connect(restored)
        try:
            assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert connection.execute("SELECT value FROM entries ORDER BY id").fetchall() in (
                [("before",)],
                [("before",), ("during",)],
            )
        finally:
            connection.close()
    finally:
        owner.close()


def test_locked_rollback_journal_source_refuses_within_backup_deadline(
    tmp_path: Path,
) -> None:
    source = tmp_path / "locked.sqlite3"
    _create_database(source)
    owner = sqlite3.connect(source)
    snapshot_dir = tmp_path / "snapshot"
    finished = threading.Event()
    outcomes: list[Exception] = []

    def capture() -> None:
        try:
            snapshot_sqlite(source, snapshot_dir, backup_timeout_seconds=0.05)
        except Exception as error:
            outcomes.append(error)
        finally:
            finished.set()

    worker = threading.Thread(target=capture, daemon=True)
    try:
        assert owner.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",)
        owner.execute("BEGIN EXCLUSIVE")
        owner.execute("INSERT INTO entries(value) VALUES ('uncommitted')")

        started = time.monotonic()
        worker.start()
        finished_within_bound = finished.wait(0.75)
        elapsed = time.monotonic() - started
    finally:
        owner.rollback()
        owner.close()
        worker.join(timeout=2)

    assert finished_within_bound, "snapshot_sqlite hung on an exclusively locked source"
    assert elapsed < 0.75
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], SQLiteSnapshotError)
    assert "source database is busy; try again when the owning app is idle" in str(outcomes[0])
    assert not snapshot_dir.exists()


def test_hot_wal_without_shm_reports_benign_snapshot_created_shm(tmp_path: Path) -> None:
    source = tmp_path / "hot-wal.sqlite3"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "\n".join(
                (
                    "import os, sqlite3, sys",
                    "connection = sqlite3.connect(sys.argv[1])",
                    "connection.execute('PRAGMA journal_mode=WAL')",
                    "connection.execute('PRAGMA wal_autocheckpoint=0')",
                    "connection.execute('CREATE TABLE entries(id INTEGER PRIMARY KEY, value TEXT NOT NULL)')",
                    "connection.execute(\"INSERT INTO entries(value) VALUES ('wal-only')\")",
                    "connection.commit()",
                    "os._exit(0)",
                )
            ),
            str(source),
        ],
        check=True,
    )

    wal = Path(f"{source}-wal")
    shm = Path(f"{source}-shm")
    assert wal.stat().st_size > 0
    assert shm.is_file()
    shm.unlink()
    assert not shm.exists()

    snapshot_dir = tmp_path / "snapshot"
    result = snapshot_sqlite(source, snapshot_dir)

    assert shm.is_file()
    assert result.shm_changed is True
    assert result.owner_activity is False
    manifest = json.loads((snapshot_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["source_changes"] == {
        "database": False,
        "shm": True,
        "wal": False,
    }


def test_corrupt_manifest_refuses_without_touching_destination_or_sidecars(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source)
    snapshot_dir = tmp_path / "snapshot"
    snapshot_sqlite(source, snapshot_dir)
    manifest_path = snapshot_dir / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    destination = tmp_path / "destination.sqlite3"
    _create_database(destination, rows=1)
    before = destination.read_bytes()
    wal = Path(f"{destination}-wal")
    shm = Path(f"{destination}-shm")
    wal.write_bytes(b"old-wal")
    shm.write_bytes(b"old-shm")

    with pytest.raises(SQLiteSnapshotError, match="do not match the manifest"):
        restore_sqlite(snapshot_dir, destination)
    assert destination.read_bytes() == before
    assert wal.read_bytes() == b"old-wal"
    assert shm.read_bytes() == b"old-shm"


def test_corrupt_backup_refuses_without_touching_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source)
    snapshot_dir = tmp_path / "snapshot"
    snapshot_sqlite(source, snapshot_dir)
    backup = snapshot_dir / BACKUP_NAME
    damaged = bytearray(backup.read_bytes())
    damaged[len(damaged) // 2] ^= 0xFF
    backup.write_bytes(damaged)

    destination = tmp_path / "destination.sqlite3"
    _create_database(destination, rows=1)
    before = destination.read_bytes()
    with pytest.raises(SQLiteSnapshotError, match="do not match the manifest"):
        restore_sqlite(snapshot_dir, destination)
    assert destination.read_bytes() == before


def test_restore_quick_check_rejects_malformed_backup_even_with_matching_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source)
    snapshot_dir = tmp_path / "snapshot"
    snapshot_sqlite(source, snapshot_dir)
    backup = snapshot_dir / BACKUP_NAME
    connection = sqlite3.connect(backup)
    try:
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute("UPDATE sqlite_schema SET rootpage=999999 WHERE name='entries'")
        connection.commit()
    finally:
        connection.close()
    manifest_path = snapshot_dir / MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"][0]["sha256"] = _sha256(backup)
    manifest["entries"][0]["size"] = backup.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    destination = tmp_path / "destination.sqlite3"
    _create_database(destination, rows=1)
    before = destination.read_bytes()
    with pytest.raises(SQLiteSnapshotError, match="restore temporary quick_check"):
        restore_sqlite(snapshot_dir, destination)
    assert destination.read_bytes() == before
    assert not list(tmp_path.glob(f".{destination.name}.sqlite-restore-*"))


def test_snapshot_quick_check_failure_deletes_partial_output(tmp_path: Path) -> None:
    source = tmp_path / "malformed.sqlite3"
    _create_database(source)
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute("UPDATE sqlite_schema SET rootpage=999999 WHERE name='entries'")
        connection.commit()
    finally:
        connection.close()

    snapshot_dir = tmp_path / "snapshot"
    with pytest.raises(SQLiteSnapshotError, match="quick_check"):
        snapshot_sqlite(source, snapshot_dir)
    assert not snapshot_dir.exists()


def test_successful_restore_removes_only_old_generation_sidecars(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source, rows=4)
    snapshot_dir = tmp_path / "snapshot"
    snapshot_sqlite(source, snapshot_dir)

    destination = tmp_path / "destination.sqlite3"
    _create_database(destination, rows=1)
    wal = Path(f"{destination}-wal")
    shm = Path(f"{destination}-shm")
    wal.write_bytes(b"pre-restore generation")
    shm.write_bytes(b"pre-restore generation")

    restore_sqlite(snapshot_dir, destination)

    assert _rows(destination) == [
        (1, "row-0"),
        (2, "row-1"),
        (3, "row-2"),
        (4, "row-3"),
    ]
    assert not wal.exists()
    assert not shm.exists()


def test_existing_snapshot_destination_is_refused_without_reusing_its_contents(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source)
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    sentinel = snapshot_dir / "belongs-to-someone-else"
    sentinel.write_bytes(b"preserve")

    with pytest.raises(SQLiteSnapshotError, match="already exists"):
        snapshot_sqlite(source, snapshot_dir)
    assert {path.name: path.read_bytes() for path in snapshot_dir.iterdir()} == {
        sentinel.name: b"preserve"
    }


def test_sync_acknowledgement_must_be_an_actual_boolean(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source)

    with pytest.raises(SQLiteSnapshotError, match="acknowledged_sync_risk must be a boolean"):
        snapshot_sqlite(source, tmp_path / "snapshot", acknowledged_sync_risk="yes")  # type: ignore[arg-type]


def test_failed_atomic_replace_preserves_destination_but_removes_old_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source, rows=4)
    snapshot_dir = tmp_path / "snapshot"
    snapshot_sqlite(source, snapshot_dir)
    destination = tmp_path / "destination.sqlite3"
    _create_database(destination, rows=1)
    before = destination.read_bytes()
    wal = Path(f"{destination}-wal")
    shm = Path(f"{destination}-shm")
    wal.write_bytes(b"old-wal")
    shm.write_bytes(b"old-shm")

    from core.lifecycle import sqlite_snapshot as sqlite_snapshot_module

    def fail_replace(source_path: Path, destination_path: Path) -> None:
        raise OSError(f"synthetic replace failure: {source_path} -> {destination_path}")

    monkeypatch.setattr(sqlite_snapshot_module.os, "replace", fail_replace)
    with pytest.raises(SQLiteSnapshotError, match="before atomic replace"):
        restore_sqlite(snapshot_dir, destination)

    assert destination.read_bytes() == before
    assert not wal.exists()
    assert not shm.exists()
    assert not list(tmp_path.glob(f".{destination.name}.sqlite-restore-*"))


def test_restore_fsyncs_removed_sidecars_before_atomic_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.sqlite3"
    _create_database(source, rows=4)
    snapshot_dir = tmp_path / "snapshot"
    snapshot_sqlite(source, snapshot_dir)
    destination = tmp_path / "destination.sqlite3"
    _create_database(destination, rows=1)
    wal = Path(f"{destination}-wal")
    shm = Path(f"{destination}-shm")
    wal.write_bytes(b"old-wal")
    shm.write_bytes(b"old-shm")

    from core.lifecycle import sqlite_snapshot as sqlite_snapshot_module

    real_fsync_directory = sqlite_snapshot_module._fsync_directory
    real_replace = sqlite_snapshot_module.os.replace
    fsynced_directories: list[Path] = []

    def observe_fsync(directory: Path) -> None:
        real_fsync_directory(directory)
        fsynced_directories.append(directory)

    def assert_ordering(source_path: Path, destination_path: Path) -> None:
        assert not wal.exists()
        assert not shm.exists()
        assert fsynced_directories == [destination.parent]
        real_replace(source_path, destination_path)

    monkeypatch.setattr(sqlite_snapshot_module, "_fsync_directory", observe_fsync)
    monkeypatch.setattr(sqlite_snapshot_module.os, "replace", assert_ordering)

    restore_sqlite(snapshot_dir, destination)

    assert _rows(destination) == [
        (1, "row-0"),
        (2, "row-1"),
        (3, "row-2"),
        (4, "row-3"),
    ]
    assert fsynced_directories == [destination.parent, destination.parent]
