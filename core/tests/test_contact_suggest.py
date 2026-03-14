"""Phase 4 coverage for contact suggestions and correction actions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.paths import PEOPLE_DIR, RITUAL_INTELLIGENCE_DB_FILE, TRACKED_MEETINGS_DIR
from core.ritual_intelligence.actions import confirm_ritual
from core.ritual_intelligence.models import NormalizedAttendee, NormalizedCalendarEvent
from core.ritual_intelligence.ritual_match import list_ritual_suggestions
from core.ritual_intelligence.service import RitualIntelligenceService


def _cleanup() -> None:
    protected_people = {"Alice_Smith.md", "Bob_Jones.md"}
    for path in (
        RITUAL_INTELLIGENCE_DB_FILE,
        RITUAL_INTELLIGENCE_DB_FILE.with_suffix(".db-shm"),
        RITUAL_INTELLIGENCE_DB_FILE.with_suffix(".db-wal"),
    ):
        if path.exists():
            path.unlink()
    for directory in (TRACKED_MEETINGS_DIR, PEOPLE_DIR / "Internal", PEOPLE_DIR / "External"):
        if directory.exists():
            for path in directory.glob("*.md"):
                if path.name in protected_people:
                    continue
                path.unlink()


def _event(*, source_event_id: str, starts_at: datetime) -> NormalizedCalendarEvent:
    return NormalizedCalendarEvent(
        provider="eventkit",
        source_event_id=source_event_id,
        source_series_id="series-contact",
        title="Customer Ritual",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        calendar_id="primary",
        calendar_name="primary",
        attendees=[
            NormalizedAttendee(name="Test User", email="test@example.com", status="Accepted", attendee_type="Person"),
            NormalizedAttendee(name="Pat Customer", email="pat@acme.com", status="Accepted", attendee_type="Person"),
        ],
    )


def test_contact_suggestion_renders_inside_tracked_brief_and_actions_work():
    _cleanup()
    service = RitualIntelligenceService()
    prior = datetime(2026, 3, 3, 9, 0, tzinfo=timezone.utc)
    current = datetime(2026, 3, 17, 9, 0, tzinfo=timezone.utc)
    service.refresh_calendar(events=[_event(source_event_id="c1", starts_at=prior), _event(source_event_id="c2", starts_at=current)])

    suggestion = list_ritual_suggestions()[0]
    result = confirm_ritual(suggestion["series_id"], now=datetime(2026, 3, 17, 8, 0, tzinfo=timezone.utc))
    note_path = Path([item["note_path"] for item in result["generated"] if "2026-03-17" in item["note_path"]][0])
    note_text = note_path.read_text(encoding="utf-8")

    assert "Suggested contact pages" in note_text
    assert "[Create page] [Not now] [Never suggest]" in note_text

    contact_id = service.list_occurrences()[0]["id"]  # placeholder to keep pylint happy
    # Pull the real contact id from the DB-backed action response via the generated brief rows.
    from core.ritual_intelligence.db import transaction
    with transaction(create=True) as conn:
        row = conn.execute("SELECT id FROM contacts WHERE email = 'pat@acme.com'").fetchone()
        contact_id = row["id"]
        current_occurrence = conn.execute(
            "SELECT id FROM occurrences WHERE substr(starts_at, 1, 10) = '2026-03-17'"
        ).fetchone()["id"]

    dismissed = service.dismiss_contact_suggestion(contact_id, current_occurrence)
    suppressed = service.suppress_contact_suggestion(contact_id)
    created = service.create_contact_page(contact_id)

    assert dismissed["status"] == "dismissed"
    assert suppressed["status"] == "suppressed"
    assert created["status"] == "created"
    assert Path(created["page_path"]).exists()


def test_contact_pages_are_not_auto_created():
    _cleanup()
    service = RitualIntelligenceService()
    service.refresh_calendar(events=[_event(source_event_id="c3", starts_at=datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc))])

    assert not (PEOPLE_DIR / "External" / "Pat_Customer.md").exists()
