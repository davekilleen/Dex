from __future__ import annotations

import asyncio
import json

import pytest

from core.mcp import calendar_server


def _decode_tool_result(result):
    return json.loads(result[0].text)


def test_add_missing_calendar_warning_reports_available_calendars(monkeypatch):
    monkeypatch.setattr(
        calendar_server,
        "_get_available_calendar_names",
        lambda: ["Home", "Team Calendar"],
    )
    result = {
        "success": True,
        "calendar": "Guessed Work",
        "events": [],
        "count": 0,
    }

    warned = calendar_server._add_missing_calendar_warning(
        result,
        "Guessed Work",
        event_count=0,
    )

    assert warned["warning"] == (
        "Calendar 'Guessed Work' was not found. Available calendars: "
        "['Home', 'Team Calendar']. Set calendar.work_calendar in "
        "System/user-profile.yaml."
    )


def test_add_missing_calendar_warning_skips_calendar_list_for_nonempty_results(
    monkeypatch,
):
    def fail_if_called():
        raise AssertionError("calendar list should only be fetched for empty results")

    monkeypatch.setattr(
        calendar_server,
        "_get_available_calendar_names",
        fail_if_called,
    )
    result = {"success": True, "events": [{"title": "Standup"}], "count": 1}

    unchanged = calendar_server._add_missing_calendar_warning(
        result,
        "Work",
        event_count=1,
    )

    assert unchanged == result
    assert "warning" not in unchanged


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("calendar_get_events", {}),
        ("calendar_get_today", {}),
        ("calendar_search_events", {"query": "planning"}),
        ("calendar_get_next_event", {}),
        ("calendar_get_events_with_attendees", {}),
    ],
)
def test_empty_calendar_queries_warn_when_default_calendar_is_missing(
    monkeypatch,
    tool_name,
    arguments,
):
    def fake_run_shell_script(script_name, operation, *args):
        assert script_name == "calendar_eventkit.py"
        if operation == "list":
            return True, json.dumps([{"title": "Home"}])
        if operation == "next":
            return True, json.dumps({"message": "No upcoming events"})
        return True, "[]"

    monkeypatch.setattr(calendar_server, "run_shell_script", fake_run_shell_script)
    monkeypatch.setattr(calendar_server, "DEFAULT_WORK_CALENDAR", "Guessed Work")
    calendar_server._get_available_calendar_names.cache_clear()

    payload = _decode_tool_result(
        asyncio.run(calendar_server._handle_call_tool_inner(tool_name, arguments))
    )

    assert payload["warning"] == (
        "Calendar 'Guessed Work' was not found. Available calendars: ['Home']. "
        "Set calendar.work_calendar in System/user-profile.yaml."
    )
