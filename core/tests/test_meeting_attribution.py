"""An unattributed capture must become attributed only where the calendar proves it.

The failure this prevents has already happened once in practice: a note claimed
a calendar match at 300 seconds when the real delta was 346, and the attendance
it asserted was invented. The boundary is therefore tested exactly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.meeting_sources import attribution, wispr_adapter
from core.meeting_sources.landing_zone import write

START = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def _capture(**overrides):
    payload = {
        "id": "cap-1",
        "title": "",
        "summary": "Weekly review.\n\n### Next Steps\n- (Speaker 1) Chase the credit\n",
        "start": START.isoformat().replace("+00:00", "Z"),
        "finalized": True,
        "attendees": [],
    }
    payload.update(overrides)
    return wispr_adapter.to_record(payload)


def _event(offset_seconds=0, *, title="Commercial Review", attendees=None):
    return {
        "start": (START + timedelta(seconds=offset_seconds)).isoformat(),
        "title": title,
        "attendees": attendees if attendees is not None else [
            {"name": "Ada Reeve", "email": "fixture-ken@invalid.test"},
            {"name": "Bea Nolan", "email": "fixture-emily@invalid.test"},
        ],
    }


def test_a_matching_event_resolves_attendance_and_the_real_title():
    resolved = attribution.resolve(_capture(), [_event()])

    assert resolved.attribution_is_reliable is True
    assert {person.email for person in resolved.attendees} == {
        "fixture-ken@invalid.test",
        "fixture-emily@invalid.test",
    }
    assert resolved.title == "Commercial Review"
    assert resolved.extra["title_from_calendar"] is True


def test_the_five_minute_boundary_is_exact():
    """300 seconds matches, 301 does not. This is the case that bit before."""
    assert attribution.resolve(_capture(), [_event(300)]).attribution_is_reliable is True

    beyond = attribution.resolve(_capture(), [_event(301)])
    assert beyond.attribution_is_reliable is False
    assert beyond.extra["attribution_match"] == "unmatched"


def test_no_calendar_events_leaves_the_capture_honestly_unattributed():
    resolved = attribution.resolve(_capture(), [])

    assert resolved.attribution_is_reliable is False
    assert resolved.extra["attribution_match"] == "unmatched"
    assert resolved.extra["attribution_reason"]


def test_an_ambiguous_match_does_not_pick_one():
    """Two equally close events with nothing to separate them must not be guessed."""
    resolved = attribution.resolve(
        _capture(),
        [_event(0, title="Review A", attendees=[{"email": "fixture-a@invalid.test"}]),
         _event(0, title="Review B", attendees=[{"email": "fixture-b@invalid.test"}])],
    )

    assert resolved.attribution_is_reliable is False
    assert resolved.extra["attribution_match"] == "ambiguous"


def test_a_matched_event_with_no_attendees_is_still_unresolved():
    """The match is real; the attendance is not thereby known."""
    resolved = attribution.resolve(_capture(), [_event(attendees=[])])

    assert resolved.attribution_is_reliable is False
    assert resolved.extra["attribution_reason"] == "matched_event_has_no_attendees"


def test_a_capture_that_already_knows_its_attendees_is_left_alone():
    already = _capture(attendees=[{"name": "Sarah", "email": "fixture-sarah@invalid.test"}])

    resolved = attribution.resolve(already, [_event()])

    assert resolved is already, "no calendar lookup is needed or wanted"


def test_a_derived_title_is_not_offered_to_the_matcher_as_corroboration():
    """The matcher tie-breaks on title. A title we invented is not evidence."""
    capture = attribution.record_as_capture(_capture())
    assert capture["title"] == ""


def test_the_note_reports_resolved_attendance_and_drops_the_warning(tmp_path):
    resolved = attribution.resolve(_capture(), [_event()])
    text = write(tmp_path, resolved).read_text()

    assert "attribution_resolved: true" in text
    assert "Attendance unresolved" not in text
    assert "fixture-ken@invalid.test" in text


def test_the_note_keeps_the_warning_when_the_calendar_could_not_confirm(tmp_path):
    resolved = attribution.resolve(_capture(), [])
    text = write(tmp_path, resolved).read_text()

    assert "attribution_resolved: false" in text
    assert "Attendance unresolved" in text
