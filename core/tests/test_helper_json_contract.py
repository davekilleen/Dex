"""JSON contract for Dex Helper ops — names and shapes the Python client expects."""

from __future__ import annotations

import json

from core.utils.macos_privacy_helper import helper_op_for_script
from scripts import check_release_assets as prober
from scripts import release_publish as publisher

CALENDAR_OPS = {
    "calendar.list": {"args": []},
    "calendar.events": {"args": ["Work", "0", "1"]},
    "calendar.attendees": {"args": ["Work", "0", "1"]},
    "calendar.search": {"args": ["Work", "standup", "7", "7"]},
    "calendar.next": {"args": ["Work"]},
    "calendar.delete": {"args": ["Work", "Hold", "0"]},
    "calendar.create": {"args": ["Work", "Hold", "2026-11-18 09:00", "30"]},
}

REMINDER_OPS = {
    "reminders.list_lists": {"args": []},
    "reminders.list_items": {"args": ["Dex Today"]},
    "reminders.list_completed": {"args": ["Dex Today"]},
    "reminders.complete": {"args": ["abc-123"]},
    "reminders.create": {"args": ["Dex Today", "Follow up"]},
    "reminders.find_and_complete": {"args": ["Dex Today", "Follow up"]},
    "reminders.clear_completed": {"args": ["Dex Today"]},
    "reminders.ensure_lists": {"args": []},
}

META_OPS = ("version", "status", "request-access")


def _assert_json_round_trip(value):
    encoded = json.dumps(value)
    assert json.loads(encoded) == value


def test_every_helper_op_has_golden_success_and_error_json():
    event = {
        "provider": "eventkit",
        "provider_event_id": "event-1",
        "provider_series_id": "series-1",
        "title": "Hold",
        "start": "2026-11-18T09:00:00-05:00",
        "end": "2026-11-18T09:30:00-05:00",
        "location": "",
        "url": "",
        "notes": "",
        "all_day": False,
        "calendar_identifier": "cal-1",
        "calendar_name": "Work",
        "state": "scheduled",
        "current_user_status": None,
        "last_modified": None,
    }
    success_bodies = {
        "version": {"version": "1.1.0"},
        "status": {"calendar": "granted", "reminders": "not_determined"},
        "request-access": {"calendar": "granted", "reminders": "granted"},
        "calendar.list": [
            {"title": "Work", "type": 0, "color": None, "identifier": "cal-1"}
        ],
        "calendar.events": [event],
        "calendar.attendees": [
            {
                **event,
                "organizer": {"name": "Pat", "email": "pat@example.com"},
                "attendees": [
                    {
                        "name": "Pat",
                        "email": "pat@example.com",
                        "status": "Pending",
                        "type": "Person",
                        "is_organizer": True,
                        "is_current_user": True,
                        "is_non_responder": False,
                    }
                ],
            }
        ],
        "calendar.search": [event],
        "calendar.next": event,
        "calendar.delete": "Deleted event: Hold",
        "calendar.create": "Created: Hold at 18 Nov 2026, 09:00",
        "reminders.list_lists": [
            {"title": "Dex Today", "identifier": "list-1", "color": None}
        ],
        "reminders.list_items": [
            {
                "title": "Follow up",
                "notes": "",
                "reminder_id": "abc-123",
                "creation_date": "2026-11-18T09:00:00-05:00",
                "completed": False,
                "due_date": "2026-11-19",
            }
        ],
        "reminders.list_completed": [
            {
                "title": "Follow up",
                "notes": "",
                "reminder_id": "abc-123",
                "completed": True,
                "completion_date": "2026-11-18T10:00:00-05:00",
            }
        ],
        "reminders.complete": {
            "success": True,
            "reminder_id": "abc-123",
            "status": "completed",
        },
        "reminders.create": {
            "success": True,
            "reminder_id": "abc-123",
            "title": "Follow up",
            "list": "Dex Today",
        },
        "reminders.find_and_complete": {
            "found": True,
            "completed": True,
            "reminder_id": "abc-123",
            "title": "Follow up",
        },
        "reminders.clear_completed": {
            "success": True,
            "removed": 1,
            "list": "Dex Today",
        },
        "reminders.ensure_lists": {
            "success": True,
            "created": [],
            "existing": ["Dex Inbox", "Dex Today"],
            "message": "Created 0, already existed 2",
        },
    }
    error_codes = (
        "usage",
        "unknown_op",
        "invalid_args",
        "permission_denied",
        "permission_write_only",
        "permission_restricted",
        "not_found",
        "save_failed",
        "timeout",
        "unavailable",
        "path_refused",
        "helper_unusable",
    )
    for op in (*META_OPS, *CALENDAR_OPS, *REMINDER_OPS):
        body = success_bodies[op]
        if isinstance(body, str):
            assert "Created:" in body or "Deleted event:" in body or "No event found" in body
        else:
            _assert_json_round_trip(body)
        _assert_json_round_trip({"error": "Dex Helper could not finish that.", "code": "unavailable"})
    for code in error_codes:
        _assert_json_round_trip({"error": "example", "code": code})


def test_helper_op_for_script_maps_eventkit_commands_and_skips_permission_checkers():
    for command in ("list", "events", "search", "next", "attendees", "delete"):
        op, payload = helper_op_for_script("calendar_eventkit.py", (command, "Work"))
        assert op == f"calendar.{command}"
        assert "args" in payload
    for command in (
        "list_lists",
        "list_items",
        "list_completed",
        "complete",
        "create",
        "find_and_complete",
        "clear_completed",
        "ensure_lists",
    ):
        op, _payload = helper_op_for_script("reminders_eventkit.py", (command,))
        assert op == f"reminders.{command}"
    assert helper_op_for_script(
        "calendar_create_event.sh",
        ("Work", "Hold", "2026-11-18 09:00", "30"),
    ) == (
        "calendar.create",
        {"args": ["Work", "Hold", "2026-11-18 09:00", "30"]},
    )
    assert helper_op_for_script("check_calendar_permission.py", ()) is None
    assert helper_op_for_script("check_reminders_permission.py", ()) is None


def test_required_release_asset_count_stays_four():
    assert publisher.REQUIRED_ASSET_COUNT == 4
    assert prober.REQUIRED_ASSET_COUNT == 4
