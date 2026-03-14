"""Phase 3 coverage for transcript ingestion and reconciliation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.paths import MEETING_INTEL_DIR, RITUAL_INTELLIGENCE_DB_FILE, TRACKED_MEETINGS_DIR
from core.ritual_intelligence.actions import confirm_ritual, reassign_transcript_to_occurrence
from core.ritual_intelligence.models import NormalizedAttendee, NormalizedCalendarEvent, TranscriptArtifact
from core.ritual_intelligence.ritual_match import list_ritual_suggestions
from core.ritual_intelligence.service import RitualIntelligenceService
from core.ritual_intelligence.transcript_ingest import ingest_artifacts
from core.ritual_intelligence.transcript_reconcile import reconcile_unmatched_transcripts


def _cleanup() -> None:
    for path in (
        RITUAL_INTELLIGENCE_DB_FILE,
        RITUAL_INTELLIGENCE_DB_FILE.with_suffix(".db-shm"),
        RITUAL_INTELLIGENCE_DB_FILE.with_suffix(".db-wal"),
    ):
        if path.exists():
            path.unlink()
    for directory in (TRACKED_MEETINGS_DIR, MEETING_INTEL_DIR / "raw", MEETING_INTEL_DIR / "summaries"):
        if directory.exists():
            for path in directory.glob("*.md"):
                path.unlink()


def _event(*, source_event_id: str, source_series_id: str, title: str, starts_at: datetime) -> NormalizedCalendarEvent:
    return NormalizedCalendarEvent(
        provider="eventkit",
        source_event_id=source_event_id,
        source_series_id=source_series_id,
        title=title,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=30),
        calendar_id="primary",
        calendar_name="primary",
        attendees=[
            NormalizedAttendee(name="Test User", email="test@example.com", status="Accepted", attendee_type="Person"),
            NormalizedAttendee(name="Client", email="client@acme.com", status="Accepted", attendee_type="Person"),
        ],
    )


def test_granola_transcript_attaches_to_right_occurrence():
    _cleanup()
    service = RitualIntelligenceService()
    starts_at = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
    service.refresh_calendar(events=[_event(source_event_id="evt-a", source_series_id="series-a", title="Client Sync", starts_at=starts_at)])
    occurrence_id = service.list_occurrences()[0]["id"]

    ingest_artifacts(
        [
            TranscriptArtifact(
                transcript_id="trn-granola-a",
                source="granola",
                source_transcript_id="granola-a",
                title="Client Sync",
                started_at=starts_at,
                ended_at=starts_at + timedelta(minutes=30),
                attendees=[NormalizedAttendee(name="Client", email="client@acme.com")],
                raw_text="Decision: proceed\nAction: send recap",
            )
        ]
    )
    results = reconcile_unmatched_transcripts()

    assert results[0]["status"] == "matched"
    assert results[0]["occurrence_id"] == occurrence_id
    assert results[0]["occurrenceMatchConfidence"] >= 0.75


def test_ambiguous_transcript_is_held_for_review():
    _cleanup()
    service = RitualIntelligenceService()
    service.refresh_calendar(
        events=[
            _event(
                source_event_id="evt-b1",
                source_series_id="series-b1",
                title="Design Review",
                starts_at=datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc),
            ),
            _event(
                source_event_id="evt-b2",
                source_series_id="series-b2",
                title="Design Review",
                starts_at=datetime(2026, 3, 10, 10, 30, tzinfo=timezone.utc),
            ),
        ]
    )
    ingest_artifacts(
        [
            TranscriptArtifact(
                transcript_id="trn-granola-b",
                source="granola",
                source_transcript_id="granola-b",
                title="Design Review",
                started_at=datetime(2026, 3, 10, 10, 15, tzinfo=timezone.utc),
                ended_at=None,
                raw_text="Discussed roadmap and designs.",
            )
        ]
    )

    results = reconcile_unmatched_transcripts()

    assert results[0]["status"] == "ambiguous"
    assert results[0]["occurrenceMatchConfidence"] >= 0.5


def test_reassign_transcript_to_previous_session():
    _cleanup()
    service = RitualIntelligenceService()
    prior = datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc)
    current = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
    service.refresh_calendar(
        events=[
            _event(source_event_id="evt-c1", source_series_id="series-c", title="1:1", starts_at=prior),
            _event(source_event_id="evt-c2", source_series_id="series-c", title="1:1", starts_at=current),
        ]
    )
    occurrences = service.list_occurrences()
    prior_id = occurrences[0]["id"]
    current_id = occurrences[1]["id"]
    ingest_artifacts(
        [
            TranscriptArtifact(
                transcript_id="trn-granola-c",
                source="granola",
                source_transcript_id="granola-c",
                title="1:1",
                started_at=current,
                ended_at=None,
                raw_text="Action: send draft",
            )
        ]
    )
    reconcile_unmatched_transcripts()

    result = reassign_transcript_to_occurrence("trn-granola-c", prior_id)

    assert result["status"] == "reassigned"
    assert result["occurrence_id"] == prior_id
    assert current_id != prior_id


def test_confirmed_ritual_brief_uses_previous_transcript_summary():
    _cleanup()
    service = RitualIntelligenceService()
    prior = datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc)
    upcoming = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)
    service.refresh_calendar(
        events=[
            _event(source_event_id="evt-d1", source_series_id="series-d", title="Weekly 1:1", starts_at=prior),
            _event(source_event_id="evt-d2", source_series_id="series-d", title="Weekly 1:1", starts_at=upcoming),
        ]
    )
    ingest_artifacts(
        [
            TranscriptArtifact(
                transcript_id="trn-granola-d",
                source="granola",
                source_transcript_id="granola-d",
                title="Weekly 1:1",
                started_at=prior,
                ended_at=None,
                attendees=[NormalizedAttendee(name="Client", email="client@acme.com")],
                raw_text="Decision: ship the update\nAction: share launch notes",
            )
        ]
    )
    reconcile_unmatched_transcripts()

    suggestions = list_ritual_suggestions()
    result = confirm_ritual(suggestions[0]["series_id"], now=datetime(2026, 3, 10, 8, 0, tzinfo=timezone.utc))
    upcoming_note = Path([item["note_path"] for item in result["generated"] if "2026-03-10" in item["note_path"]][0])
    rendered = upcoming_note.read_text(encoding="utf-8")

    assert "Transcript continuity: Decision: ship the update" in rendered
