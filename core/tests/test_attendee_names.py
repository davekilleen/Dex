from __future__ import annotations

from datetime import datetime, timezone

from core.meeting_sources import granola_adapter, landing_zone
from core.meeting_sources.action_items import action_item_bucket
from core.meeting_sources.attendee_names import (
    attendee_note_label,
    display_name_from_fields,
)
from core.meeting_sources.record import Attendee, MeetingRecord


def test_display_name_beats_an_email_used_as_the_name() -> None:
    assert display_name_from_fields(
        "jane.doe@acme.test",
        "Jane Doe",
        email="jane.doe@acme.test",
    ) == "Jane Doe"


def test_email_only_attendee_gets_a_prettified_fallback() -> None:
    assert display_name_from_fields(email="john.smith+ops@acme.test") == "John Smith"


def test_granola_adapter_does_not_keep_an_email_as_the_page_name() -> None:
    record = granola_adapter.to_record(
        {
            "id": "gran-name",
            "title": "Review",
            "created_at": "2026-08-14T09:00:00Z",
            "summary_markdown": "- [ ] Done\n",
            "attendees": [
                {
                    "name": "jane.doe@acme.test",
                    "displayName": "Jane Doe",
                    "email": "jane.doe@acme.test",
                }
            ],
        }
    )

    assert record.attendees[0].name == "Jane Doe"
    assert record.attendees[0].email == "jane.doe@acme.test"


def test_landing_zone_routes_at_name_items_to_for_others(tmp_path) -> None:
    record = MeetingRecord(
        source="fathom",
        source_id="fth-route",
        start=datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc),
        title="Pipeline review",
        body="Notes.",
        attendees=(Attendee(name="Jane Doe", email="jane@acme.test"),),
        action_items=("Write the recap", "@Sarah: send the deck"),
    )

    text = landing_zone.write(tmp_path, record).read_text()

    for_me, for_others = text.split("### For Others")
    assert "Write the recap" in for_me
    assert "@Sarah: send the deck" not in for_me
    assert "@Sarah: send the deck" in for_others
    assert "Jane Doe <jane@acme.test>" in text


def test_action_item_bucket_and_note_label() -> None:
    assert action_item_bucket("Write the recap") == "me"
    assert action_item_bucket("@Sarah: send the deck") == "others"
    assert action_item_bucket("@Dana: book the room", {"Dana Wells"}) == "me"
    assert attendee_note_label("Jane Doe", "jane@acme.test") == "Jane Doe <jane@acme.test>"
    assert attendee_note_label(None, "jane.doe@acme.test") == "Jane Doe <jane.doe@acme.test>"
