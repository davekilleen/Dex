"""The record has to fit two unlike providers, or it is not a contract.

Granola and Wispr disagree about almost everything at the edges: titles,
attendees, how action items are written, whether attribution can be trusted.
If the record only fits one of them it is a shape drawn around that one, and
provider three forks the code again. These tests are the contract itself.
"""
from __future__ import annotations

import pytest

from core.meeting_sources import granola_adapter, landing_zone, wispr_adapter
from core.meeting_sources.record import MeetingRecord

GRANOLA_DETAIL = {
    "id": "gran-1",
    "title": "Quarterly review",
    "created_at": "2026-08-14T09:00:00Z",
    "updated_at": "2026-08-14T10:30:00Z",
    "web_url": "https://notes.granola.ai/gran-1",
    "summary_markdown": (
        "## Discussion\n"
        "- Renewal is on track\n\n"
        "## Actions\n"
        "- [ ] Send the revised SOW\n"
        "- [x] Book the follow-up\n"
    ),
    "attendees": [
        {"name": "Cara Vance", "email": "fixture-sarah@invalid.test"},
        {"email": "fixture-ken@invalid.test"},
    ],
    "transcript": [{"text": "hello"}, {"text": "goodbye"}],
}

WISPR_DETAIL = {
    "id": "wis-1",
    "title": "",
    "summary": "Weekly review of pipeline.\n\n### Next Steps\n- (Speaker 1) Chase the credit\n",
    "start": "2026-08-14T12:00:00Z",
    "end": "2026-08-14T12:45:00Z",
    "finalized": True,
    "has_transcript": True,
    "attendees": [],
}


def test_both_providers_produce_the_same_type():
    assert isinstance(granola_adapter.to_record(GRANOLA_DETAIL), MeetingRecord)
    assert isinstance(wispr_adapter.to_record(WISPR_DETAIL), MeetingRecord)


def test_the_record_carries_each_provider_own_identity():
    granola = granola_adapter.to_record(GRANOLA_DETAIL)
    wispr = wispr_adapter.to_record(WISPR_DETAIL)

    assert (granola.source, granola.source_id) == ("granola", "gran-1")
    assert (wispr.source, wispr.source_id) == ("wispr", "wis-1")


def test_attribution_reliability_differs_and_the_record_says_which():
    """This is the difference that matters most downstream.

    Granola knows who was there, so a name in its notes is a person. Wispr does
    not, so a name in its summary is a guess. Collapsing the two is how an
    invented commitment reaches a person page.
    """
    assert granola_adapter.to_record(GRANOLA_DETAIL).attribution_is_reliable is True
    assert wispr_adapter.to_record(WISPR_DETAIL).attribution_is_reliable is False


def test_action_items_survive_two_completely_different_notations():
    granola = granola_adapter.to_record(GRANOLA_DETAIL)
    wispr = wispr_adapter.to_record(WISPR_DETAIL)

    assert granola.action_items == ("Send the revised SOW",)
    assert wispr.action_items == ("(Speaker 1) Chase the credit",)


def test_a_completed_checkbox_is_not_imported_as_an_open_task():
    """Handing back finished work as a new task is worse than missing it."""
    items = granola_adapter.extract_action_items(GRANOLA_DETAIL["summary_markdown"])
    assert all("follow-up" not in item for item in items)


def test_a_provider_title_is_kept_and_a_missing_one_is_flagged():
    assert granola_adapter.to_record(GRANOLA_DETAIL).extra["title_was_derived"] is False
    assert wispr_adapter.to_record(WISPR_DETAIL).extra["title_was_derived"] is True


def test_both_land_in_the_same_folder_with_the_same_frontmatter_grammar(tmp_path):
    """Downstream must not be able to tell which source a note came from."""
    granola_path = landing_zone.write(tmp_path, granola_adapter.to_record(GRANOLA_DETAIL))
    wispr_path = landing_zone.write(tmp_path, wispr_adapter.to_record(WISPR_DETAIL))

    assert granola_path.parent == wispr_path.parent
    granola_text, wispr_text = granola_path.read_text(), wispr_path.read_text()

    assert "\nsource: granola\n" in granola_text and "\ngranola_id: gran-1\n" in granola_text
    assert "\nsource: wispr\n" in wispr_text and "\nwispr_id: wis-1\n" in wispr_text
    for text in (granola_text, wispr_text):
        assert "type: meeting" in text
        assert "ai_analyzed: false" in text


def test_only_the_unreliable_source_carries_the_attribution_warning(tmp_path):
    granola_text = landing_zone.write(tmp_path, granola_adapter.to_record(GRANOLA_DETAIL)).read_text()
    wispr_text = landing_zone.write(tmp_path, wispr_adapter.to_record(WISPR_DETAIL)).read_text()

    assert "Attendance unresolved" not in granola_text
    assert "Attendance unresolved" in wispr_text


def test_granola_attendees_reach_the_note_for_person_routing(tmp_path):
    text = landing_zone.write(tmp_path, granola_adapter.to_record(GRANOLA_DETAIL)).read_text()

    assert "fixture-sarah@invalid.test" in text
    assert "fixture-ken@invalid.test" in text


def test_dedup_is_per_source_so_two_providers_never_collide(tmp_path):
    granola = granola_adapter.to_record(GRANOLA_DETAIL)
    wispr = wispr_adapter.to_record(WISPR_DETAIL)
    landing_zone.write(tmp_path, granola)
    landing_zone.write(tmp_path, wispr)

    assert landing_zone.existing_source_ids(tmp_path, "granola") == {"gran-1"}
    assert landing_zone.existing_source_ids(tmp_path, "wispr") == {"wis-1"}


def test_a_payload_without_a_usable_time_is_refused_by_both():
    with pytest.raises(ValueError):
        granola_adapter.to_record({**GRANOLA_DETAIL, "created_at": None})
    with pytest.raises(ValueError):
        wispr_adapter.to_record({**WISPR_DETAIL, "start": None})


# --- The generic layer must stay generic ------------------------------------
#
# Attribution, the landing zone and the record are Dex-level machinery. They
# happen to have been built while wiring one provider, which is exactly the
# circumstance in which a provider name leaks into shared code and the next
# source has to fork it.


def test_attribution_resolves_a_granola_capture_by_the_same_route(tmp_path):
    """The attendee matcher is wired at the note level, not to one connector.

    Granola usually supplies attendees, but it does not always: a note taken
    from a meeting with no calendar entry arrives bare, exactly like a Wispr
    capture. It must resolve through the same path, with no Granola-specific
    handling anywhere.
    """
    from core.meeting_sources import attribution

    bare = granola_adapter.to_record({**GRANOLA_DETAIL, "attendees": []})
    assert bare.attribution_is_reliable is False

    resolved = attribution.resolve(
        bare,
        [
            {
                "start": "2026-08-14T09:00:00+00:00",
                "title": "Quarterly review",
                "attendees": [{"name": "Cara Vance", "email": "fixture-sarah@invalid.test"}],
            }
        ],
    )

    assert resolved.source == "granola"
    assert resolved.attribution_is_reliable is True
    assert [person.email for person in resolved.attendees] == ["fixture-sarah@invalid.test"]


def test_the_generic_modules_name_no_provider():
    """A guard against the obvious future regression.

    If a provider name appears in the record, the attribution join, the landing
    zone or the calendar lookup, the next source has to fork that file instead
    of adding an adapter, which is the whole failure this design avoids.
    """
    import pathlib

    package = pathlib.Path(__file__).resolve().parents[1] / "meeting_sources"
    for module in ("record.py", "attribution.py", "landing_zone.py", "calendar_lookup.py"):
        text = (package / module).read_text(encoding="utf-8").lower()
        for provider in ("wispr", "granola", "otter", "fathom", "zoom"):
            assert provider not in text, f"{module} names {provider}; it must stay provider-neutral"


def test_the_landing_zone_writes_any_source_without_being_taught_it(tmp_path):
    """A source it has never heard of must land correctly on the same rules."""
    from datetime import datetime, timezone

    from core.meeting_sources.record import MeetingRecord

    invented = MeetingRecord(
        source="fathom",
        source_id="fth-9",
        start=datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc),
        title="Pipeline review",
        body="Notes.",
    )

    path = landing_zone.write(tmp_path, invented)
    text = path.read_text()

    assert "\nsource: fathom\n" in text
    assert "\nfathom_id: fth-9\n" in text
    assert landing_zone.existing_source_ids(tmp_path, "fathom") == {"fth-9"}
