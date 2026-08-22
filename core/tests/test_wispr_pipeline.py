"""Wispr captures must reach the vault, and must not arrive claiming more than they know."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.meeting_sources import landing_zone, wispr_adapter, wispr_sync
from core.meeting_sources.record import Attendee, MeetingRecord

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)

SUMMARY = """Weekly commercial review covering pipeline and delivery.

### Platform
- Hosting change agreed
- Gateway rollout scheduled

### Next Steps
- (Speaker 1) Set up the platform call
- (Ada) Add the deal id to the dashboard

### Decisions Made
- PM rate card set at $45/hr
"""


def _payload(**overrides):
    payload = {
        "id": "cap-1",
        "title": "",
        "summary": SUMMARY,
        "start": "2026-08-14T12:57:49.639000Z",
        "end": "2026-08-14T13:38:32.854000Z",
        "finalized": True,
        "has_transcript": True,
        "attendees": [],
    }
    payload.update(overrides)
    return payload


def test_action_items_come_only_from_next_steps():
    """Decisions and observations are not commitments.

    Sweeping the whole summary would turn "PM rate card set at $45/hr" into a
    task nobody agreed to do.
    """
    items = wispr_adapter.extract_action_items(SUMMARY)

    assert len(items) == 2
    assert all("rate card" not in item for item in items)
    assert all("Cloud ops swap" not in item for item in items)


def test_a_missing_title_is_derived_and_flagged():
    record = wispr_adapter.to_record(_payload())

    assert record.title.startswith("Weekly commercial review")
    assert record.extra["title_was_derived"] is True
    assert " " in record.title and not record.title.endswith(" ")


def test_a_provider_title_is_preferred_and_not_flagged():
    record = wispr_adapter.to_record(_payload(title="Commercial Review"))

    assert record.title == "Commercial Review"
    assert record.extra["title_was_derived"] is False


def test_no_attendees_means_attribution_is_not_reliable():
    """This source names speakers it cannot identify. Say so, do not resolve it."""
    assert wispr_adapter.to_record(_payload()).attribution_is_reliable is False
    assert wispr_adapter.to_record(
        _payload(attendees=[{"name": "Ken", "email": "ken@example.com"}])
    ).attribution_is_reliable is True


def test_a_capture_without_a_start_is_refused():
    with pytest.raises(ValueError):
        wispr_adapter.to_record(_payload(start=None))


def test_the_note_carries_source_and_id_as_separate_keys(tmp_path):
    """Dedup and person-page touch tracking key on this pair.

    Folding the id into the source line makes every note look new on every sweep.
    """
    record = wispr_adapter.to_record(_payload())
    path = landing_zone.write(tmp_path, record)
    text = path.read_text()

    assert "\nsource: wispr\n" in text
    assert "\nwispr_id: cap-1\n" in text
    assert "ai_analyzed: false" in text, "the detector needs this to pick the note up"
    assert "### For Me" in text and "- [ ] " in text


def test_an_unresolved_capture_warns_against_attributing_it(tmp_path):
    path = landing_zone.write(tmp_path, wispr_adapter.to_record(_payload()))
    assert "Attendance unresolved" in path.read_text()


def test_a_resolved_capture_carries_no_warning(tmp_path):
    record = wispr_adapter.to_record(_payload(attendees=[{"email": "ken@example.com"}]))
    text = landing_zone.write(tmp_path, record).read_text()

    assert "Attendance unresolved" not in text
    assert "attribution_resolved: true" in text


def test_the_same_capture_is_never_written_twice(tmp_path):
    record = wispr_adapter.to_record(_payload())

    assert landing_zone.write(tmp_path, record) is not None
    assert landing_zone.write(tmp_path, record) is None, "dedup must be on the source id"
    assert len(list(landing_zone.meetings_dir(tmp_path).glob("*.md"))) == 1


def test_hand_dropped_notes_do_not_break_the_id_scan(tmp_path):
    """The landing zone accepts manual notes. A sweep must survive them."""
    folder = landing_zone.meetings_dir(tmp_path)
    folder.mkdir(parents=True)
    (folder / "2026-08-14 - Pasted.md").write_text("no frontmatter here\n")
    (folder / "2026-08-13 - Odd.md").write_text("---\nnot: valid\n---\nbody\n")

    assert landing_zone.existing_source_ids(tmp_path, "wispr") == set()


class _FakeClient:
    """Stands in for the remote MCP server."""

    def __init__(self, meetings, *, fail=None):
        self.meetings = meetings
        self.fail = fail

    def search_meetings(self, _vault, *, limit=25, cursor=None):
        if self.fail:
            raise self.fail
        return {"meetings": self.meetings, "has_more": False, "next_cursor": None}

    def get_meeting(self, _vault, identifier, with_transcript=False):
        return next(m for m in self.meetings if m["id"] == identifier)


def test_unreachable_is_reported_as_unavailable_not_as_no_meetings(tmp_path, monkeypatch):
    """The failure this whole design exists to avoid: a quiet week that was an outage."""
    from core.meeting_sources import wispr_client

    fake = _FakeClient([], fail=wispr_client.WisprUnavailable("connection refused"))
    monkeypatch.setattr(wispr_sync.wispr_client, "search_meetings", fake.search_meetings)

    result = wispr_sync.sync(tmp_path)

    assert result.ok is False
    assert result.written == 0
    assert "could not be reached" in result.summary()
    assert "No new" not in result.summary()


def test_a_sweep_writes_new_captures_and_skips_known_ones(tmp_path, monkeypatch):
    fake = _FakeClient([_payload(), _payload(id="cap-2")])
    monkeypatch.setattr(wispr_sync.wispr_client, "search_meetings", fake.search_meetings)
    monkeypatch.setattr(wispr_sync.wispr_client, "get_meeting", fake.get_meeting)

    first = wispr_sync.sync(tmp_path, days_back=3650)
    assert first.written == 2 and first.ok

    second = wispr_sync.sync(tmp_path, days_back=3650)
    assert second.written == 0 and second.skipped == 2


def test_unfinalized_captures_are_left_alone(tmp_path, monkeypatch):
    """A capture still being written would be stored partial and never revisited."""
    fake = _FakeClient([_payload(finalized=False)])
    monkeypatch.setattr(wispr_sync.wispr_client, "search_meetings", fake.search_meetings)
    monkeypatch.setattr(wispr_sync.wispr_client, "get_meeting", fake.get_meeting)

    result = wispr_sync.sync(tmp_path, days_back=3650)

    assert result.written == 0 and result.skipped == 1


def test_captures_older_than_the_window_stop_the_sweep(tmp_path, monkeypatch):
    old = (NOW - timedelta(days=90)).isoformat().replace("+00:00", "Z")
    fake = _FakeClient([_payload(id="old", start=old)])
    monkeypatch.setattr(wispr_sync.wispr_client, "search_meetings", fake.search_meetings)
    monkeypatch.setattr(wispr_sync.wispr_client, "get_meeting", fake.get_meeting)

    result = wispr_sync.sync(tmp_path, days_back=7)

    assert result.written == 0


def test_one_bad_capture_does_not_end_the_sweep(tmp_path, monkeypatch):
    broken = _payload(id="broken", start=None)
    fake = _FakeClient([broken, _payload(id="good")])
    monkeypatch.setattr(wispr_sync.wispr_client, "search_meetings", fake.search_meetings)
    monkeypatch.setattr(wispr_sync.wispr_client, "get_meeting", fake.get_meeting)

    result = wispr_sync.sync(tmp_path, days_back=3650)

    assert result.written == 1
    assert result.failed == 1


def test_a_record_must_carry_provenance():
    with pytest.raises(ValueError):
        MeetingRecord(source="wispr", source_id="", start=NOW)


def test_an_attendee_needs_something_to_identify_them():
    with pytest.raises(ValueError):
        Attendee()


def test_a_calendar_that_cannot_be_read_is_never_reported_as_no_attendees(tmp_path, monkeypatch):
    """"Attendance unknown" and "nobody was there" must not share a sentence.

    A machine without calendar access would otherwise mark every capture as
    having no attendees, which is a confident false statement about who was in
    the room.
    """
    fake = _FakeClient([_payload()])
    monkeypatch.setattr(wispr_sync.wispr_client, "search_meetings", fake.search_meetings)
    monkeypatch.setattr(wispr_sync.wispr_client, "get_meeting", fake.get_meeting)
    monkeypatch.setattr(wispr_sync.calendar_lookup, "events_around", lambda *a, **k: None)

    result = wispr_sync.sync(tmp_path, days_back=3650)

    assert result.written == 1
    assert result.calendar_unavailable is True
    assert "could not be read" in result.summary()
    assert "no attendees" not in result.summary()


def test_a_matched_capture_is_written_with_its_real_attendees(tmp_path, monkeypatch):
    fake = _FakeClient([_payload()])
    monkeypatch.setattr(wispr_sync.wispr_client, "search_meetings", fake.search_meetings)
    monkeypatch.setattr(wispr_sync.wispr_client, "get_meeting", fake.get_meeting)
    events = [
        {
            "start": "2026-08-14T12:57:49.639000Z",
            "title": "Weekly commercial review",
            "attendees": [{"name": "Ada Reeve", "email": "fixture-ken@invalid.test"}],
        }
    ]

    result = wispr_sync.sync(tmp_path, days_back=3650, calendar_events=events)

    assert result.written == 1 and result.attributed == 1
    text = result.paths[0].read_text()
    assert "fixture-ken@invalid.test" in text
    assert "Attendance unresolved" not in text


def test_an_unmatched_capture_says_attendance_is_unconfirmed(tmp_path, monkeypatch):
    fake = _FakeClient([_payload()])
    monkeypatch.setattr(wispr_sync.wispr_client, "search_meetings", fake.search_meetings)
    monkeypatch.setattr(wispr_sync.wispr_client, "get_meeting", fake.get_meeting)
    far_away = [{"start": "2026-08-14T18:00:00Z", "title": "Something else", "attendees": []}]

    result = wispr_sync.sync(tmp_path, days_back=3650, calendar_events=far_away)

    assert result.written == 1 and result.attributed == 0
    assert "unconfirmed" in result.summary()
    assert "Attendance unresolved" in result.paths[0].read_text()
