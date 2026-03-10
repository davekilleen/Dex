"""Phase 2 coverage for ritual suggestions and prep behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.paths import (
    LEGACY_MEETINGS_DIR,
    MEETING_DAILY_LOGS_DIR,
    RITUAL_INTELLIGENCE_DB_FILE,
    TRACKED_MEETINGS_DIR,
)
from core.ritual_intelligence.actions import confirm_ritual
from core.ritual_intelligence.db import transaction
from core.ritual_intelligence.models import NormalizedAttendee, NormalizedCalendarEvent
from core.ritual_intelligence.service import RitualIntelligenceService


def _cleanup_runtime_artifacts() -> None:
    for path in (
        RITUAL_INTELLIGENCE_DB_FILE,
        RITUAL_INTELLIGENCE_DB_FILE.with_suffix(".db-shm"),
        RITUAL_INTELLIGENCE_DB_FILE.with_suffix(".db-wal"),
    ):
        if path.exists():
            path.unlink()
    for pattern in ("*.md",):
        for directory in (TRACKED_MEETINGS_DIR, MEETING_DAILY_LOGS_DIR, LEGACY_MEETINGS_DIR):
            if directory.exists():
                for path in directory.glob(pattern):
                    path.unlink()


def _event(*, source_event_id: str, source_series_id: str, starts_at: datetime, external: bool = True):
    attendees = [NormalizedAttendee(name="Test User", email="test@example.com", status="Accepted", attendee_type="Person")]
    if external:
        attendees.append(
            NormalizedAttendee(name="Client", email="client@acme.com", status="Accepted", attendee_type="Person")
        )
    else:
        attendees.append(
            NormalizedAttendee(name="Teammate", email="teammate@example.com", status="Accepted", attendee_type="Person")
        )
    return NormalizedCalendarEvent(
        provider="eventkit",
        source_event_id=source_event_id,
        source_series_id=source_series_id,
        title="Weekly Ritual",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        calendar_id="primary",
        calendar_name="primary",
        attendees=attendees,
    )


def test_confirmed_ritual_on_wednesday_generates_rest_of_week_prep():
    _cleanup_runtime_artifacts()
    service = RitualIntelligenceService()
    wednesday = datetime(2026, 3, 11, 9, 0, tzinfo=timezone.utc)
    friday = datetime(2026, 3, 13, 9, 0, tzinfo=timezone.utc)
    service.refresh_calendar(events=[
        _event(source_event_id="wed", source_series_id="series-w", starts_at=wednesday),
        _event(source_event_id="fri", source_series_id="series-w", starts_at=friday),
    ])

    suggestions = service.list_ritual_suggestions()
    result = confirm_ritual(suggestions[0]["series_id"], now=datetime(2026, 3, 11, 12, 0, tzinfo=timezone.utc))

    assert result["status"] == "confirmed"
    assert len(result["generated"]) == 2
    assert any("2026-03-11" in item["note_path"] for item in result["generated"])
    assert any("2026-03-13" in item["note_path"] for item in result["generated"])


def test_confirmed_ritual_on_friday_generates_next_week_prep_too():
    _cleanup_runtime_artifacts()
    service = RitualIntelligenceService()
    friday = datetime(2026, 3, 13, 9, 0, tzinfo=timezone.utc)
    monday_next = datetime(2026, 3, 16, 9, 0, tzinfo=timezone.utc)
    service.refresh_calendar(events=[
        _event(source_event_id="fri-2", source_series_id="series-f", starts_at=friday),
        _event(source_event_id="mon-next", source_series_id="series-f", starts_at=monday_next),
    ])

    suggestions = service.list_ritual_suggestions()
    result = confirm_ritual(suggestions[0]["series_id"], now=datetime(2026, 3, 13, 12, 0, tzinfo=timezone.utc))

    assert result["status"] == "confirmed"
    assert len(result["generated"]) == 2
    assert any("2026-03-16" in item["note_path"] for item in result["generated"])


def test_non_ritual_meetings_do_not_get_speculative_prep():
    _cleanup_runtime_artifacts()
    service = RitualIntelligenceService()
    starts_at = datetime.now(timezone.utc) + timedelta(days=1)
    service.refresh_calendar(events=[_event(source_event_id="internal-1", source_series_id="series-i", starts_at=starts_at, external=False)])

    occurrences = service.list_occurrences()
    assert occurrences[0]["capture_mode"] == "activity log"
    assert list(TRACKED_MEETINGS_DIR.glob("*.md")) == []


def test_one_off_prep_is_occurrence_scoped_only():
    _cleanup_runtime_artifacts()
    service = RitualIntelligenceService()
    starts_at = datetime.now(timezone.utc) + timedelta(days=2)
    service.refresh_calendar(events=[_event(source_event_id="one-off", source_series_id="series-one", starts_at=starts_at, external=False)])
    occurrence_id = service.list_occurrences()[0]["id"]

    result = service.generate_one_off_prep(occurrence_id)

    assert result["status"] == "one_off_ready"
    with transaction(create=True) as conn:
        occurrence = conn.execute(
            "SELECT capture_mode, one_off_prep, ritual_series_id FROM occurrences WHERE id = ?",
            (occurrence_id,),
        ).fetchone()
    assert occurrence["capture_mode"] == "tracked meeting"
    assert occurrence["one_off_prep"] == 1
    assert occurrence["ritual_series_id"] is None


def test_user_edited_prep_block_locks_regeneration():
    _cleanup_runtime_artifacts()
    service = RitualIntelligenceService()
    starts_at = datetime.now(timezone.utc) + timedelta(days=2)
    service.refresh_calendar(events=[_event(source_event_id="lock-me", source_series_id="series-lock", starts_at=starts_at, external=False)])
    occurrence_id = service.list_occurrences()[0]["id"]

    first = service.generate_one_off_prep(occurrence_id)
    note_path = Path(first["note_path"])
    original = note_path.read_text(encoding="utf-8")
    edited = original.replace("## Prep (AI-generated)", "## Prep (User edited)")
    note_path.write_text(edited, encoding="utf-8")

    second = service.generate_one_off_prep(occurrence_id)

    assert second["prep_status"] == "skipped"
    with transaction(create=True) as conn:
        locked = conn.execute("SELECT user_locked FROM occurrences WHERE id = ?", (occurrence_id,)).fetchone()
    assert locked["user_locked"] == 1
