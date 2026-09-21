"""Reading the calendar must fail loudly enough to be distinguishable from silence.

Every failure path here returns None, and the whole point is that callers can
tell "the calendar could not be read" apart from "the meeting had no
attendees". If any of these ever returns an empty list instead, a machine
without calendar access will start reporting confident, false statements about
who was in a room.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from core.meeting_sources import calendar_lookup


def _profile(tmp_path, payload: str):
    system = tmp_path / "System"
    system.mkdir(parents=True, exist_ok=True)
    (system / "user-profile.yaml").write_text(payload, encoding="utf-8")


def _helper(tmp_path):
    helper = tmp_path / calendar_lookup.HELPER
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("# stub\n", encoding="utf-8")
    return helper


def test_the_configured_work_calendar_wins(tmp_path):
    _profile(tmp_path, "calendar:\n  work_calendar: Team Diary\nwork_email: fixture-a@invalid.test\n")

    assert calendar_lookup.default_calendar_name(tmp_path) == "Team Diary"


def test_work_email_is_the_next_choice(tmp_path):
    _profile(tmp_path, "work_email: fixture-person@invalid.test\n")

    assert calendar_lookup.default_calendar_name(tmp_path) == "fixture-person@invalid.test"


def test_a_name_and_domain_are_the_last_resort(tmp_path):
    _profile(tmp_path, "name: Fixture-Person\nemail_domain: invalid.test\n")

    assert calendar_lookup.default_calendar_name(tmp_path) == "fixture-person@invalid.test"


def test_an_unconfigured_profile_yields_nothing_rather_than_a_guess(tmp_path):
    """The calendar server falls back to a "Work" calendar; this must not.

    Querying a calendar the user does not have returns an empty result, and an
    empty result here is indistinguishable from a meeting nobody attended.
    """
    _profile(tmp_path, "name: Fixture-Person\n")

    assert calendar_lookup.default_calendar_name(tmp_path) is None


def test_an_unreadable_profile_is_not_a_calendar_fault(tmp_path):
    _profile(tmp_path, "this: [is: not: valid: yaml\n")

    assert calendar_lookup.default_calendar_name(tmp_path) is None


def test_a_missing_helper_returns_unavailable_not_empty(tmp_path):
    _profile(tmp_path, "calendar:\n  work_calendar: Team Diary\n")

    assert calendar_lookup.events_around(tmp_path, start_offset_days=-1, end_offset_days=1) is None


def test_no_configured_calendar_returns_unavailable(tmp_path):
    _helper(tmp_path)
    _profile(tmp_path, "name: Fixture-Person\n")

    assert calendar_lookup.events_around(tmp_path, start_offset_days=-1, end_offset_days=1) is None


def _run(monkeypatch, *, returncode=0, stdout="", stderr=""):
    def fake(*_args, **_kwargs):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    monkeypatch.setattr(calendar_lookup.subprocess, "run", fake)


def test_events_are_returned_on_success(tmp_path, monkeypatch):
    _helper(tmp_path)
    _profile(tmp_path, "calendar:\n  work_calendar: Team Diary\n")
    events = [{"start": "2026-08-14T09:00:00+01:00", "title": "Review", "attendees": []}]
    _run(monkeypatch, stdout=json.dumps(events))

    assert calendar_lookup.events_around(tmp_path, start_offset_days=-1, end_offset_days=1) == events


def test_an_events_key_is_unwrapped(tmp_path, monkeypatch):
    _helper(tmp_path)
    _profile(tmp_path, "calendar:\n  work_calendar: Team Diary\n")
    _run(monkeypatch, stdout=json.dumps({"events": [{"start": "x"}]}))

    assert calendar_lookup.events_around(tmp_path, start_offset_days=-1, end_offset_days=1) == [
        {"start": "x"}
    ]


def test_a_failing_helper_returns_unavailable(tmp_path, monkeypatch):
    _helper(tmp_path)
    _profile(tmp_path, "calendar:\n  work_calendar: Team Diary\n")
    _run(monkeypatch, returncode=1, stderr="calendar access denied")

    assert calendar_lookup.events_around(tmp_path, start_offset_days=-1, end_offset_days=1) is None


def test_output_that_is_not_json_returns_unavailable(tmp_path, monkeypatch):
    _helper(tmp_path)
    _profile(tmp_path, "calendar:\n  work_calendar: Team Diary\n")
    _run(monkeypatch, stdout="not json at all")

    assert calendar_lookup.events_around(tmp_path, start_offset_days=-1, end_offset_days=1) is None


def test_a_timeout_returns_unavailable(tmp_path, monkeypatch):
    _helper(tmp_path)
    _profile(tmp_path, "calendar:\n  work_calendar: Team Diary\n")

    def boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="calendar", timeout=30)

    monkeypatch.setattr(calendar_lookup.subprocess, "run", boom)

    assert calendar_lookup.events_around(tmp_path, start_offset_days=-1, end_offset_days=1) is None


def test_non_mapping_entries_are_discarded(tmp_path, monkeypatch):
    _helper(tmp_path)
    _profile(tmp_path, "calendar:\n  work_calendar: Team Diary\n")
    _run(monkeypatch, stdout=json.dumps([{"start": "ok"}, "junk", 7]))

    assert calendar_lookup.events_around(tmp_path, start_offset_days=-1, end_offset_days=1) == [
        {"start": "ok"}
    ]


@pytest.mark.parametrize("payload", ["null", '"a string"', "42"])
def test_a_payload_that_is_not_a_list_returns_unavailable(tmp_path, monkeypatch, payload):
    _helper(tmp_path)
    _profile(tmp_path, "calendar:\n  work_calendar: Team Diary\n")
    _run(monkeypatch, stdout=payload)

    assert calendar_lookup.events_around(tmp_path, start_offset_days=-1, end_offset_days=1) is None
