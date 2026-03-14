"""Phase 1 coverage for the Ritual Intelligence runtime."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.paths import RITUAL_INTELLIGENCE_DB_FILE
from core.ritual_intelligence.db import ensure_runtime_dir
from core.ritual_intelligence.models import NormalizedAttendee, NormalizedCalendarEvent
from core.ritual_intelligence.service import RitualIntelligenceService


def _cleanup_db() -> None:
    for path in (
        RITUAL_INTELLIGENCE_DB_FILE,
        RITUAL_INTELLIGENCE_DB_FILE.with_suffix(".db-shm"),
        RITUAL_INTELLIGENCE_DB_FILE.with_suffix(".db-wal"),
    ):
        if path.exists():
            path.unlink()


def _event(*, source_event_id: str, starts_at: datetime, ends_at: datetime | None = None) -> NormalizedCalendarEvent:
    return NormalizedCalendarEvent(
        provider="eventkit",
        source_event_id=source_event_id,
        source_series_id="series-123",
        title="Weekly Ritual",
        starts_at=starts_at,
        ends_at=ends_at or (starts_at + timedelta(minutes=30)),
        calendar_id="primary",
        calendar_name="primary",
        attendees=[
            NormalizedAttendee(name="Test User", email="test@example.com", status="Accepted", attendee_type="Person"),
            NormalizedAttendee(name="Client", email="client@acme.com", status="Accepted", attendee_type="Person"),
        ],
    )


def test_runtime_bootstrap_creates_vault_local_database():
    _cleanup_db()

    runtime_dir = ensure_runtime_dir()
    service = RitualIntelligenceService()
    result = service.refresh_calendar(events=[])

    assert runtime_dir.exists()
    assert RITUAL_INTELLIGENCE_DB_FILE.exists()
    assert result["total"] == 0


def test_refresh_calendar_is_idempotent_for_same_source_event():
    _cleanup_db()
    service = RitualIntelligenceService()
    starts_at = datetime.now(timezone.utc) + timedelta(days=1)
    event = _event(source_event_id="evt-1", starts_at=starts_at)

    first = service.refresh_calendar(events=[event])
    second = service.refresh_calendar(events=[event])
    occurrences = service.list_occurrences()

    assert first["created"] == 1
    assert second["updated"] == 1
    assert len(occurrences) == 1
    assert occurrences[0]["capture_mode"] == "tracked meeting"


def test_reschedule_updates_existing_occurrence_instead_of_creating_duplicate():
    _cleanup_db()
    service = RitualIntelligenceService()
    starts_at = datetime.now(timezone.utc) + timedelta(days=2)
    original = _event(source_event_id="evt-2", starts_at=starts_at)
    moved = _event(source_event_id="evt-2", starts_at=starts_at + timedelta(days=1))

    service.refresh_calendar(events=[original])
    service.refresh_calendar(events=[moved])
    occurrences = service.list_occurrences()

    assert len(occurrences) == 1
    assert occurrences[0]["starts_at"] == moved.starts_at.isoformat()


def test_empty_refresh_marks_missing_occurrence_cancelled():
    _cleanup_db()
    service = RitualIntelligenceService()
    starts_at = datetime.now(timezone.utc) + timedelta(days=3)
    event = _event(source_event_id="evt-3", starts_at=starts_at)

    service.refresh_calendar(events=[event], start_offset_days=0, end_offset_days=7)
    service.refresh_calendar(events=[], start_offset_days=0, end_offset_days=7)
    occurrences = service.list_occurrences()

    assert len(occurrences) == 1
    assert occurrences[0]["state"] == "cancelled"
