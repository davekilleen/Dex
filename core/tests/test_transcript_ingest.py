"""Coverage for safe manual transcript folder imports."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.ritual_intelligence import db, meeting_intel_projection, transcript_ingest


@pytest.fixture
def ritual_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    runtime_dir = vault / "System" / ".dex"
    meeting_intel_dir = vault / "06-Resources" / "Intel" / "Meeting_Intel"
    runtime_dir.mkdir(parents=True)
    meeting_intel_dir.mkdir(parents=True)
    monkeypatch.setattr(db, "SYSTEM_DIR", vault / "System")
    monkeypatch.setattr(db, "DEX_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(
        db,
        "RITUAL_INTELLIGENCE_DB_FILE",
        runtime_dir / "ritual-intelligence.db",
    )
    monkeypatch.setattr(
        meeting_intel_projection,
        "MEETING_INTEL_DIR",
        meeting_intel_dir,
    )
    return vault


def _transcript_count() -> int:
    connection = sqlite3.connect(db.RITUAL_INTELLIGENCE_DB_FILE)
    try:
        return connection.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
    finally:
        connection.close()


def test_folder_imports_supported_transcript_formats(ritual_runtime: Path):
    exports = ritual_runtime / "exports"
    exports.mkdir()
    for file_name in ("planning.md", "standup.txt", "demo.vtt", "retro.srt"):
        (exports / file_name).write_text(f"Notes from {file_name}\n", encoding="utf-8")
    (exports / "ignore.pdf").write_bytes(b"%PDF-not-a-transcript")

    result = transcript_ingest.import_manual_transcript_folder(folder_path=exports)

    assert result["imported"] == 4
    assert result["skipped"] == 0
    assert result["failed"] == 0
    assert _transcript_count() == 4


def test_folder_import_is_idempotent(ritual_runtime: Path):
    exports = ritual_runtime / "exports"
    exports.mkdir()
    (exports / "planning.md").write_text("Planning notes\n", encoding="utf-8")

    first = transcript_ingest.import_manual_transcript_folder(folder_path=exports)
    second = transcript_ingest.import_manual_transcript_folder(folder_path=exports)

    assert first["imported"] == 1
    assert second["imported"] == 0
    assert second["skipped"] == 1
    assert second["failed"] == 0
    assert _transcript_count() == 1


def test_folder_skips_unreadable_and_binary_files_without_aborting(
    ritual_runtime: Path,
):
    exports = ritual_runtime / "exports"
    exports.mkdir()
    unreadable = exports / "unreadable.md"
    unreadable.write_text("secret\n", encoding="utf-8")
    unreadable.chmod(0)
    (exports / "binary.txt").write_bytes(b"\x00\x01\x02")
    (exports / "valid.vtt").write_text("WEBVTT\n\nUseful notes\n", encoding="utf-8")

    try:
        result = transcript_ingest.import_manual_transcript_folder(folder_path=exports)
    finally:
        unreadable.chmod(0o600)

    assert result["imported"] == 1
    assert result["skipped"] == 2
    assert result["failed"] == 0
    assert _transcript_count() == 1


def test_folder_does_not_follow_symlink_outside_root(ritual_runtime: Path):
    exports = ritual_runtime / "exports"
    exports.mkdir()
    outside = ritual_runtime / "outside.md"
    outside.write_text("Must not be imported\n", encoding="utf-8")
    link = exports / "escaped.md"
    try:
        link.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    result = transcript_ingest.import_manual_transcript_folder(folder_path=exports)

    assert result["imported"] == 0
    assert result["skipped"] == 1
    assert result["failed"] == 0
    assert not db.RITUAL_INTELLIGENCE_DB_FILE.exists()


def test_empty_folder_reports_zero_counts(ritual_runtime: Path):
    exports = ritual_runtime / "exports"
    exports.mkdir()

    result = transcript_ingest.import_manual_transcript_folder(folder_path=exports)

    assert result == {
        "imported": 0,
        "skipped": 0,
        "failed": 0,
        "files": [],
    }
