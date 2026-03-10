"""Coverage for read-only legacy note matching."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.paths import LEGACY_MEETINGS_DIR, RITUAL_INTELLIGENCE_DB_FILE, TRACKED_MEETINGS_DIR
from core.ritual_intelligence.models import NormalizedAttendee, NormalizedCalendarEvent
from core.ritual_intelligence.service import RitualIntelligenceService


def _cleanup() -> None:
    for path in (
        RITUAL_INTELLIGENCE_DB_FILE,
        RITUAL_INTELLIGENCE_DB_FILE.with_suffix(".db-shm"),
        RITUAL_INTELLIGENCE_DB_FILE.with_suffix(".db-wal"),
    ):
        if path.exists():
            path.unlink()
    for directory in (TRACKED_MEETINGS_DIR, LEGACY_MEETINGS_DIR):
        if directory.exists():
            for path in directory.glob("*.md"):
                path.unlink()


def test_clear_legacy_manual_note_is_linked_instead_of_duplicated():
    _cleanup()
    legacy_note = LEGACY_MEETINGS_DIR / "2026-03-20 - Weekly Ritual.md"
    legacy_note.write_text("# Weekly Ritual\n\nManual notes.\n", encoding="utf-8")

    service = RitualIntelligenceService()
    starts_at = datetime(2026, 3, 20, 9, 0, tzinfo=timezone.utc)
    service.refresh_calendar(
        events=[
            NormalizedCalendarEvent(
                provider="eventkit",
                source_event_id="legacy-match",
                source_series_id="series-legacy",
                title="Weekly Ritual",
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30),
                calendar_id="primary",
                calendar_name="primary",
                attendees=[
                    NormalizedAttendee(name="Test User", email="test@example.com", status="Accepted", attendee_type="Person"),
                    NormalizedAttendee(name="Client", email="client@acme.com", status="Accepted", attendee_type="Person"),
                ],
            )
        ]
    )
    occurrence_id = service.list_occurrences()[0]["id"]

    result = service.generate_one_off_prep(occurrence_id)

    assert result["prep_status"] == "linked_existing_note"
    assert result["note_path"] == str(legacy_note)
    assert list(TRACKED_MEETINGS_DIR.glob("*.md")) == []
