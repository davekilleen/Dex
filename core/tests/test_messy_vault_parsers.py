from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from core.entity_engine import index as entity_index
from core.mcp import work_server
from core.mcp.update_checker import parse_version
from core.ritual_intelligence.models import NormalizedAttendee, NormalizedCalendarEvent, TranscriptArtifact
from core.ritual_intelligence.service import RitualIntelligenceService
from core.ritual_intelligence.transcript_ingest import ingest_artifacts
from core.ritual_intelligence.transcript_reconcile import reconcile_unmatched_transcripts
from core.tests.support.vault_builder import build_messy_vault


def _point_ritual_runtime_at(monkeypatch, vault) -> None:
    from core.ritual_intelligence import calendar_ingest, db, meeting_intel_projection

    runtime_dir = vault.root / "System" / ".dex"
    monkeypatch.setattr(db, "SYSTEM_DIR", vault.root / "System")
    monkeypatch.setattr(db, "DEX_RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(db, "RITUAL_INTELLIGENCE_DB_FILE", runtime_dir / "ritual-intelligence.db")
    monkeypatch.setattr(calendar_ingest, "USER_PROFILE_FILE", vault.profile)
    monkeypatch.setattr(meeting_intel_projection, "MEETING_INTEL_DIR", vault.meeting_intel_dir)


def _event(identifier: str, series: str, title: str, starts_at: datetime) -> NormalizedCalendarEvent:
    return NormalizedCalendarEvent(
        provider="fixture",
        source_event_id=identifier,
        source_series_id=series,
        title=title,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        attendees=[
            NormalizedAttendee(name="Fixture User", email="fixture@example.com"),
            NormalizedAttendee(name="Client", email="client@example.org"),
        ],
    )


def test_vault_builder_task_parser_handles_duplicate_headings_and_half_written_lines(tmp_path):
    vault = build_messy_vault(tmp_path, file_count=17)

    tasks = work_server.parse_tasks_file(vault.tasks)

    assert len(vault.content_files) == 17
    assert tasks
    assert all(task["title"].strip() and task["line_number"] > 0 for task in tasks)
    assert any("café" in task["title"] or "東京" in task["title"] for task in tasks)


def test_vault_builder_content_survives_transcript_reconcile(tmp_path, monkeypatch):
    vault = build_messy_vault(tmp_path, file_count=9)
    _point_ritual_runtime_at(monkeypatch, vault)
    starts_at = datetime.now(timezone.utc) - timedelta(days=1)
    service = RitualIntelligenceService()
    service.refresh_calendar(events=[_event("messy-transcript", "messy-series", vault.ritual_title, starts_at)])
    ingest_artifacts(
        [
            TranscriptArtifact(
                transcript_id="trn-messy-vault",
                source="fixture",
                source_transcript_id="half-written-note",
                title=vault.ritual_title,
                started_at=starts_at,
                ended_at=None,
                raw_text=vault.half_written_transcript.read_text(encoding="utf-8"),
            )
        ]
    )

    results = reconcile_unmatched_transcripts()

    assert results
    assert results[0]["status"] in {"matched", "ambiguous", "unmatched"}
    assert 0.0 <= results[0]["occurrenceMatchConfidence"] <= 1.0


def test_vault_builder_unicode_content_survives_ritual_matching(tmp_path, monkeypatch):
    vault = build_messy_vault(tmp_path, file_count=7)
    _point_ritual_runtime_at(monkeypatch, vault)
    recent = datetime.now(timezone.utc) - timedelta(days=8)
    service = RitualIntelligenceService()
    service.refresh_calendar(
        events=[
            _event("ritual-one", "unicode-series", vault.ritual_title, recent),
            _event("ritual-two", "unicode-series", vault.ritual_title, recent + timedelta(days=7)),
        ]
    )

    suggestions = service.list_ritual_suggestions()

    assert suggestions
    assert suggestions[0]["occurrence_count"] >= 2
    assert suggestions[0]["title"].strip()


def test_vault_builder_malformed_frontmatter_is_quarantined_but_findable(
    tmp_path,
    monkeypatch,
):
    vault = build_messy_vault(tmp_path, file_count=5)
    monkeypatch.setattr(work_server, "BASE_DIR", vault.root)
    monkeypatch.setattr(work_server, "PEOPLE_INDEX_FILE", vault.people_index)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: vault.people_dir)

    index = work_server.build_people_index_data()

    assert index["total"] >= 2
    assert index["people"]
    assert all(person["name"] and person["path"].endswith(".md") for person in index["people"])
    quarantined_entry = next(
        person
        for person in index["people"]
        if person["name"] == "Malformed YAML – 東京"
    )
    assert quarantined_entry["status"] == "quarantined"
    assert quarantined_entry["email"] is None
    assert quarantined_entry["emails"] == []
    assert quarantined_entry["aliases"] == []
    with sqlite3.connect(entity_index.database_path(vault.root)) as connection:
        quarantined = connection.execute(
            "SELECT path FROM source_files WHERE quarantined = 1"
        ).fetchall()
    assert quarantined == [
        ("05-Areas/People/External/Malformed YAML – 東京.md",)
    ]


def test_parse_version_accepts_release_prerelease_forms():
    assert parse_version("1.4.0-beta.1") == (1, 4, 0)
    assert parse_version("v2.0.3-rc.12") == (2, 0, 3)
