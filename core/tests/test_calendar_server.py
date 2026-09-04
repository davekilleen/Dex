from __future__ import annotations

import asyncio
import json
import subprocess
import sys

import pytest

from core.mcp import calendar_server


def _decode_tool_result(result):
    return json.loads(result[0].text)


def _capture_subprocess_command(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(calendar_server.subprocess, "run", fake_run)
    return captured


def test_run_shell_script_dispatches_sh_scripts_to_bash(monkeypatch):
    captured = _capture_subprocess_command(monkeypatch)

    success, output = calendar_server.run_shell_script(
        "calendar_create_event.sh", "Work", "Test", "2026-08-08 10:00", "30"
    )

    assert success
    assert output == "ok"
    assert captured["command"][0] == "/bin/bash"
    assert captured["command"][1].endswith("calendar_create_event.sh")
    assert captured["command"][2:] == ["Work", "Test", "2026-08-08 10:00", "30"]


def test_run_shell_script_dispatches_py_scripts_to_python(monkeypatch):
    captured = _capture_subprocess_command(monkeypatch)

    success, output = calendar_server.run_shell_script(
        "calendar_eventkit.py", "list"
    )

    assert success
    assert output == "ok"
    assert captured["command"][0] == sys.executable
    assert captured["command"][1].endswith("calendar_eventkit.py")


def test_run_shell_script_failure_surfaces_stdout_when_stderr_is_empty(monkeypatch):
    """Helper scripts print actionable errors (e.g. calendar-access-denied
    guidance) as JSON on stdout and exit 1 with an empty stderr. Users used
    to see a bare "Exit code: 1" instead of the guidance (#377)."""
    denial = json.dumps({"error": "Calendar access denied. Enable in System Settings."})

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout=denial + "\n", stderr="")

    monkeypatch.setattr(calendar_server.subprocess, "run", fake_run)

    success, output = calendar_server.run_shell_script("calendar_eventkit.py", "list")

    assert not success
    assert output == denial


def test_run_shell_script_failure_still_prefers_stderr(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 1, stdout="partial output\n", stderr="Traceback: boom\n"
        )

    monkeypatch.setattr(calendar_server.subprocess, "run", fake_run)

    success, output = calendar_server.run_shell_script("calendar_eventkit.py", "list")

    assert not success
    assert output == "Traceback: boom"


def test_run_shell_script_failure_without_any_output_reports_exit_code(monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    monkeypatch.setattr(calendar_server.subprocess, "run", fake_run)

    success, output = calendar_server.run_shell_script("calendar_eventkit.py", "list")

    assert not success
    assert output == "Exit code: 1"


def test_allowed_sh_scripts_are_valid_bash():
    """Guard the helper scripts themselves: every allowed .sh must parse under bash."""
    for script_name in sorted(calendar_server.ALLOWED_SCRIPTS):
        if not script_name.endswith(".sh"):
            continue
        script_path = calendar_server.SCRIPTS_DIR / script_name
        assert script_path.exists(), f"Missing allowed script: {script_name}"
        check = subprocess.run(
            ["/bin/bash", "-n", str(script_path)],
            capture_output=True,
            text=True,
        )
        assert check.returncode == 0, (
            f"{script_name} is not valid bash: {check.stderr.strip()}"
        )


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


def test_calendar_get_events_filters_offset_all_day_events_by_calendar_date(
    monkeypatch,
):
    events = [
        {
            "title": "In range",
            "start": "2026-08-20T00:00:00-07:00",
            "all_day": True,
        },
        {
            "title": "Outside range",
            "start": "2026-08-21T00:00:00+01:00",
            "all_day": True,
        },
    ]
    monkeypatch.setattr(calendar_server, "_HAS_HEALTH", False)
    monkeypatch.setattr(calendar_server, "_tz_today", lambda: calendar_server.date(2026, 8, 20))
    monkeypatch.setattr(
        calendar_server,
        "run_shell_script",
        lambda *args: (True, json.dumps(events)),
    )

    payload = _decode_tool_result(
        asyncio.run(
            calendar_server.handle_call_tool(
                "calendar_get_events",
                {
                    "calendar_name": "Work",
                    "start_date": "2026-08-20",
                    "end_date": "2026-08-21",
                },
            )
        )
    )

    assert payload["success"] is True
    assert payload["events"] == [events[0]]
    assert payload["count"] == 1


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
def test_calendar_read_failures_preserve_broken_status_and_fix_guidance(
    monkeypatch,
    tool_name,
    arguments,
):
    guidance = (
        "Calendar access denied. Enable access in System Settings → "
        "Privacy & Security → Calendars."
    )

    monkeypatch.setattr(
        calendar_server,
        "run_shell_script",
        lambda *args: (False, guidance),
    )

    payload = _decode_tool_result(
        asyncio.run(calendar_server._handle_call_tool_inner(tool_name, arguments))
    )

    assert payload == {
        "success": False,
        "feature": "Calendar access",
        "feature_status": "broken",
        "user_message": guidance,
        "error": guidance,
    }


@pytest.mark.parametrize(
    ("tool_name", "arguments", "empty_field"),
    [
        ("calendar_get_events", {"calendar_name": "Work"}, "events"),
        ("calendar_get_today", {"calendar_name": "Work"}, "events"),
        (
            "calendar_search_events",
            {"calendar_name": "Work", "query": "planning"},
            "events",
        ),
        ("calendar_get_next_event", {"calendar_name": "Work"}, "next_event"),
        (
            "calendar_get_events_with_attendees",
            {"calendar_name": "Work"},
            "events",
        ),
    ],
)
def test_calendar_read_empty_results_remain_healthy(
    monkeypatch,
    tool_name,
    arguments,
    empty_field,
):
    def fake_run_shell_script(script_name, operation, *args):
        assert script_name == "calendar_eventkit.py"
        if operation == "list":
            return True, json.dumps([{"title": "Work"}])
        if operation == "next":
            return True, json.dumps({"message": "No upcoming events"})
        return True, "[]"

    monkeypatch.setattr(calendar_server, "run_shell_script", fake_run_shell_script)
    calendar_server._get_available_calendar_names.cache_clear()

    payload = _decode_tool_result(
        asyncio.run(calendar_server._handle_call_tool_inner(tool_name, arguments))
    )

    assert payload["success"] is True
    assert "feature_status" not in payload
    assert "user_message" not in payload
    assert "warning" not in payload
    assert payload[empty_field] == ([] if empty_field == "events" else None)


def test_attendee_resolution_ignores_email_mentions_outside_person_fields(
    monkeypatch,
    tmp_path,
):
    vault = tmp_path / "vault"
    people = vault / "05-Areas" / "People"
    incidental = people / "Internal" / "Incidental_Contact.md"
    actual = people / "External" / "Actual_Attendee.md"
    incidental.parent.mkdir(parents=True)
    actual.parent.mkdir(parents=True)
    incidental.write_text(
        "---\nname: Incidental Contact\nemails: [incidental@example.com]\n---\n"
        "Meeting note: follow up with actual.attendee@example.com next week.\n"
    )
    actual.write_text(
        "---\nname: Actual Attendee\nemails: [actual.attendee@example.com]\n---\n"
    )
    events = [
        {
            "title": "Customer call",
            "attendees": [
                {
                    "name": "Calendar Display Name",
                    "email": "actual.attendee@example.com",
                    "status": "accepted",
                }
            ],
        }
    ]
    monkeypatch.setattr(calendar_server, "VAULT_PATH", vault)
    monkeypatch.setattr(calendar_server, "PEOPLE_DIR", people)
    monkeypatch.setattr(
        calendar_server,
        "run_shell_script",
        lambda *args: (True, json.dumps(events)),
    )

    payload = _decode_tool_result(
        asyncio.run(
            calendar_server._handle_call_tool_inner(
                "calendar_get_events_with_attendees",
                {
                    "calendar_name": "Work",
                    "start_date": "2026-09-04",
                    "end_date": "2026-09-05",
                },
            )
        )
    )

    attendee = payload["events"][0]["attendees"][0]
    assert attendee["has_person_page"] is True
    assert attendee["person_page"] == (
        "05-Areas/People/External/Actual_Attendee.md"
    )
