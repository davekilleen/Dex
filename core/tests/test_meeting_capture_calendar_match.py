"""Behavioral contract for capture-to-calendar identity matching."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json

import pytest

from core.mcp import work_server


def _match(capture: dict, events: list[dict]) -> dict:
    spec = importlib.util.find_spec("core.meeting_capture_match")
    assert spec is not None, "the deterministic capture/calendar matcher does not exist"
    module = importlib.import_module("core.meeting_capture_match")
    return module.match_capture_to_calendar(capture, events)


def _event(
    *,
    title: str = "Customer discovery",
    start: str = "2026-07-15T10:00:00+01:00",
    attendees: list[dict] | None = None,
    **extra,
) -> dict:
    return {
        "title": title,
        "start": start,
        "attendees": attendees or [],
        **extra,
    }


def test_rejects_naive_capture_timestamp_instead_of_guessing_a_zone() -> None:
    result = _match(
        {"title": "Customer discovery", "start_time": "2026-07-15T09:00:00"},
        [_event()],
    )

    assert result == {
        "status": "unmatched",
        "reason": "capture_timestamp_missing_timezone",
    }


def test_ignores_naive_calendar_timestamp_instead_of_comparing_wall_times() -> None:
    result = _match(
        {"title": "Customer discovery", "start_time": "2026-07-15T09:00:00Z"},
        [_event(start="2026-07-15T09:00:00")],
    )

    assert result["status"] == "unmatched"
    assert result["reason"] == "no_valid_calendar_timestamp"


@pytest.mark.parametrize(
    ("capture_start", "calendar_start"),
    [
        ("2026-07-15T09:00:00Z", "2026-07-15T10:01:12+01:00"),
        ("2026-10-25T00:58:00Z", "2026-10-25T01:58:00+01:00"),
        ("2026-10-25T01:02:00Z", "2026-10-25T01:02:00+00:00"),
    ],
)
def test_compares_z_and_uk_offsets_as_common_instants_across_dst(
    capture_start: str,
    calendar_start: str,
) -> None:
    result = _match(
        {"title": "Customer discovery", "start_time": capture_start},
        [_event(start=calendar_start)],
    )

    assert result["status"] == "matched"


def test_accepts_a_one_point_two_minute_match() -> None:
    result = _match(
        {"title": "Customer discovery", "start_time": "2026-07-15T09:00:00Z"},
        [_event(start="2026-07-15T10:01:12+01:00")],
    )

    assert result["status"] == "matched"
    assert result["delta_seconds"] == 72


def test_five_minutes_is_a_hard_inclusive_maximum() -> None:
    at_boundary = _match(
        {"title": "Customer discovery", "start_time": "2026-07-15T09:00:00Z"},
        [_event(start="2026-07-15T09:05:00Z")],
    )
    over_boundary = _match(
        {"title": "Customer discovery", "start_time": "2026-07-15T09:00:00Z"},
        [_event(start="2026-07-15T09:05:01Z")],
    )

    assert at_boundary["status"] == "matched"
    assert over_boundary == {"status": "unmatched", "reason": "outside_five_minute_window"}


def test_nearest_start_wins_before_title_corroboration() -> None:
    result = _match(
        {"title": "Customer discovery", "start_time": "2026-07-15T09:00:00Z"},
        [
            _event(title="Different title", start="2026-07-15T09:00:30Z"),
            _event(title="Customer discovery", start="2026-07-15T09:01:00Z"),
        ],
    )

    assert result["status"] == "matched"
    assert result["delta_seconds"] == 30
    assert result["title_corroborated"] is False


def test_title_corroboration_breaks_equal_time_ties() -> None:
    result = _match(
        {"title": "Customer discovery", "start_time": "2026-07-15T09:00:00Z"},
        [
            _event(title="Other", start="2026-07-15T08:59:00Z"),
            _event(title="Customer discovery", start="2026-07-15T09:01:00Z"),
        ],
    )

    assert result["status"] == "matched"
    assert result["title_corroborated"] is True


def test_participant_overlap_breaks_a_tie_after_title() -> None:
    result = _match(
        {
            "title": "Customer discovery",
            "start_time": "2026-07-15T09:00:00Z",
            "attendees": [{"name": "Alex", "email": "alex@example.com"}],
        },
        [
            _event(
                start="2026-07-15T08:59:00Z",
                attendees=[{"name": "Someone else", "email": "other@example.com"}],
            ),
            _event(
                start="2026-07-15T09:01:00Z",
                attendees=[{"name": "Alex", "email": "ALEX@example.com"}],
            ),
        ],
    )

    assert result["status"] == "matched"
    assert result["participant_overlap"] > 0
    assert result["identity"]["attendees"] == [
        {"name": "Alex", "email": "alex@example.com"}
    ]


def test_participant_overlap_uses_names_when_capture_has_no_email() -> None:
    result = _match(
        {
            "title": "Customer discovery",
            "start_time": "2026-07-15T09:00:00Z",
            "attendees": ["Alex Morgan"],
        },
        [
            _event(
                start="2026-07-15T08:59:00Z",
                attendees=[{"name": "Someone else", "email": "other@example.com"}],
            ),
            _event(
                start="2026-07-15T09:01:00Z",
                attendees=[{"name": "Alex Morgan", "email": "alex@example.com"}],
            ),
        ],
    )

    assert result["status"] == "matched"
    assert result["participant_overlap"] > 0
    assert result["identity"]["attendees"][0]["name"] == "Alex Morgan"


def test_true_ambiguity_remains_unmatched() -> None:
    result = _match(
        {"title": "Customer discovery", "start_time": "2026-07-15T09:00:00Z"},
        [
            _event(start="2026-07-15T08:59:00Z"),
            _event(start="2026-07-15T09:01:00Z"),
        ],
    )

    assert result == {
        "status": "ambiguous",
        "reason": "tie_unresolved_after_title_and_participants",
        "candidate_count": 2,
    }


def test_unrelated_title_mismatch_does_not_reject_or_overwrite_a_strong_time_match() -> None:
    result = _match(
        {"title": "Budget questions", "start_time": "2026-07-15T09:00:00Z"},
        [_event(title="Customer discovery", start="2026-07-15T09:00:10Z")],
    )

    assert result["status"] == "matched"
    assert result["title_corroborated"] is False
    assert result["identity"]["title"] == "Budget questions"


@pytest.mark.parametrize("capture_title", ["Alex Morgan", "alex@example.com"])
def test_capture_named_for_its_participant_inherits_calendar_title(capture_title: str) -> None:
    result = _match(
        {
            "title": capture_title,
            "start_time": "2026-07-15T09:00:00Z",
            "attendees": [{"name": "Alex Morgan", "email": "alex@example.com"}],
        },
        [_event(title="Customer discovery", start="2026-07-15T09:00:10Z")],
    )

    assert result["status"] == "matched"
    assert result["identity"]["title"] == "Customer discovery"


def test_untitled_capture_inherits_calendar_title() -> None:
    result = _match(
        {"title": "Untitled Meeting", "start_time": "2026-07-15T09:00:00Z"},
        [_event(title="Customer discovery", start="2026-07-15T09:00:10Z")],
    )

    assert result["status"] == "matched"
    assert result["identity"]["title"] == "Customer discovery"


def test_missing_capture_and_calendar_titles_never_serialize_none() -> None:
    result = _match(
        {"title": None, "start_time": "2026-07-15T09:00:00Z"},
        [_event(title="", start="2026-07-15T09:00:10Z")],
    )

    assert result["status"] == "matched"
    assert result["identity"]["title"] == ""


def test_match_result_imports_identity_only_and_never_invite_secrets() -> None:
    result = _match(
        {"title": "Untitled", "start_time": "2026-07-15T09:00:00Z"},
        [
            _event(
                start="2026-07-15T09:00:10Z",
                attendees=[{"name": "Alex", "email": "ALEX@example.com", "status": "accepted"}],
                url="https://meet.example/secret",
                location="Dial 555-0100, code 1234",
                notes="Access code: swordfish",
                raw_payload={"password": "never-copy-this"},
            )
        ],
    )

    serialized = json.dumps(result, sort_keys=True)
    assert result["identity"] == {
        "title": "Customer discovery",
        "start_time": "2026-07-15T09:00:10Z",
        "attendees": [{"name": "Alex", "email": "alex@example.com"}],
    }
    for secret in ("meet.example", "555-0100", "1234", "swordfish", "never-copy-this"):
        assert secret not in serialized


def test_work_mcp_exposes_the_same_deterministic_matcher() -> None:
    response = asyncio.run(
        work_server.handle_call_tool(
            "match_capture_to_calendar",
            {
                "capture": {
                    "title": "Customer discovery",
                    "start_time": "2026-07-15T09:00:00Z",
                },
                "calendar_events": [_event(start="2026-07-15T10:01:12+01:00")],
            },
        )
    )

    result = json.loads(response[0].text)
    assert result["status"] == "matched"
    assert result["delta_seconds"] == 72
