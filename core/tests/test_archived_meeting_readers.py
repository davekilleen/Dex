"""PR 1 readers: live inbox plus 07-Archives, no file moves."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from core.mcp import work_server
from core.meeting_sources.landing_zone import existing_source_ids, write
from core.meeting_sources.record import MeetingRecord
from core.ritual_intelligence import calendar_ingest, manual_note_match
from core.utils import qmd_query


def _meeting_record(source_id: str, title: str = "Archived Sync") -> MeetingRecord:
    start = datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc)
    return MeetingRecord(
        source="granola",
        source_id=source_id,
        title=title,
        start=start,
        body="Pricing discussion at Acme.",
    )


def test_rebuild_meeting_cache_includes_archived_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    day = date.today().isoformat()
    live = tmp_path / "00-Inbox" / "Meetings"
    archived = tmp_path / "07-Archives" / "Meetings"
    live.mkdir(parents=True)
    archived.mkdir(parents=True)
    (live / f"{day} - Live Sync.md").write_text(
        f"---\ndate: {day}\n---\n# Live Sync\n",
        encoding="utf-8",
    )
    (archived / f"{day} - Archive Sync.md").write_text(
        f"---\ndate: {day}\n---\n# Archive Sync\n",
        encoding="utf-8",
    )
    cache_file = tmp_path / "System" / "Memory" / "meeting-cache.json"
    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_meetings_dir", lambda: live)
    monkeypatch.setattr(work_server, "get_archived_meetings_dir", lambda: archived)
    monkeypatch.setattr(work_server, "MEETING_CACHE_FILE", cache_file)

    result = work_server.rebuild_meeting_cache_data()

    assert result["success"] is True
    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    assert {entry["title"] for entry in cache["meetings"]} == {"Live Sync", "Archive Sync"}


def test_find_meetings_for_company_is_recursive_and_reads_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = tmp_path / "00-Inbox" / "Meetings"
    archived = tmp_path / "07-Archives" / "Meetings"
    nested = live / "2026-09-02"
    nested.mkdir(parents=True)
    archived.mkdir(parents=True)
    (nested / "2026-09-02 - Nested Acme.md").write_text(
        "# Nested Acme\n\nTalked with acme.com about renewal.\n",
        encoding="utf-8",
    )
    (archived / "2026-01-15 - Old Acme.md").write_text(
        "# Old Acme\n\nEarlier acme.com pricing discussion.\n",
        encoding="utf-8",
    )
    (archived / "README.md").write_text("# Archived Meetings\n", encoding="utf-8")
    monkeypatch.setattr(work_server, "get_meetings_dir", lambda: live)
    monkeypatch.setattr(work_server, "get_archived_meetings_dir", lambda: archived)

    found = work_server.find_meetings_for_company("Acme", ["acme.com"])

    titles = {item["title"] for item in found}
    assert "Nested Acme" in titles
    assert "Old Acme" in titles
    assert "Archived Meetings" not in titles


def test_meeting_context_fallback_globs_cover_the_archive() -> None:
    assert work_server._MEETING_NOTE_GLOBS == (
        "00-Inbox/Meetings/**/*.md",
        "07-Archives/Meetings/**/*.md",
    )


def test_qmd_query_accepts_multiple_fallback_globs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(qmd_query, "is_qmd_available", lambda: False)
    monkeypatch.setattr(qmd_query.shutil, "which", lambda _name: None)
    live = tmp_path / "00-Inbox" / "Meetings"
    archived = tmp_path / "07-Archives" / "Meetings"
    other = tmp_path / "04-Projects"
    live.mkdir(parents=True)
    archived.mkdir(parents=True)
    other.mkdir(parents=True)
    live_note = live / "2026-09-02 - Live.md"
    nested_note = live / "2026-09-02" / "nested.md"
    archived_note = archived / "2026-01-15 - Old.md"
    nested_note.parent.mkdir()
    live_note.write_text("retention plan for the account\n", encoding="utf-8")
    nested_note.write_text("retention in a dated folder\n", encoding="utf-8")
    archived_note.write_text("older retention notes\n", encoding="utf-8")
    (other / "Roadmap.md").write_text("retention is also a project theme\n", encoding="utf-8")

    results = qmd_query.vault_search(
        "retention",
        fallback_glob=[
            "00-Inbox/Meetings/**/*.md",
            "07-Archives/Meetings/**/*.md",
        ],
    )

    paths = {Path(item["path"]).resolve() for item in results}
    assert live_note.resolve() in paths
    assert nested_note.resolve() in paths
    assert archived_note.resolve() in paths
    assert (other / "Roadmap.md").resolve() not in paths


def test_landing_zone_dedup_sees_archived_source_ids(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    archived = tmp_path / "07-Archives" / "Meetings"
    archived.mkdir(parents=True)
    start = datetime(2026, 1, 15, 15, 0, tzinfo=timezone.utc)
    (archived / "2026-01-15 - Old.md").write_text(
        "---\ndate: 2026-01-15\ntype: meeting\nsource: granola\n"
        "granola_id: gran-archive-1\nstart: 2026-01-15T15:00:00+00:00\n"
        "has_transcript: false\nattribution_resolved: true\nai_analyzed: false\n"
        "---\n\n# Old\n",
        encoding="utf-8",
    )

    assert existing_source_ids(tmp_path, "granola") == {"gran-archive-1"}
    assert write(tmp_path, _meeting_record("gran-archive-1")) is None
    assert list((tmp_path / "00-Inbox" / "Meetings").glob("*.md")) == []


def test_manual_note_match_reads_archived_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archived = tmp_path / "archive"
    archived.mkdir()
    note = archived / "2026-03-20 - Weekly Ritual.md"
    note.write_text("# Weekly Ritual\n", encoding="utf-8")
    monkeypatch.setattr(manual_note_match, "TRACKED_MEETINGS_DIR", tmp_path / "missing-tracked")
    monkeypatch.setattr(manual_note_match, "LEGACY_MEETINGS_DIR", tmp_path / "missing-legacy")
    monkeypatch.setattr(manual_note_match, "ARCHIVED_MEETINGS_DIR", archived)

    candidates = manual_note_match._candidate_files()

    assert ("archived_read_only", note) in candidates


def test_calendar_ingest_includes_the_archive_root() -> None:
    roots = calendar_ingest.candidate_manual_note_roots(Path("."))
    assert calendar_ingest.ARCHIVED_MEETINGS_DIR in roots
    assert calendar_ingest.LEGACY_MEETINGS_DIR in roots
