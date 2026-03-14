"""Coverage for EventKit script helpers."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

sys.modules.setdefault("EventKit", SimpleNamespace())

from core.mcp.scripts import calendar_eventkit


class _NSDate:
    def __init__(self, timestamp: float):
        self._timestamp = timestamp

    def timeIntervalSince1970(self):
        return self._timestamp


class _URL:
    def absoluteString(self):
        return "https://example.com"


class _Calendar:
    def calendarIdentifier(self):
        return "cal-1"

    def title(self):
        return "Work"


class _Attendee:
    def __init__(self, *, current_user: bool = False):
        self._current_user = current_user

    def isCurrentUser(self):
        return self._current_user

    def isOrganizer(self):
        return False

    def participantStatus(self):
        return 2

    def participantType(self):
        return 1

    def name(self):
        return "Pat Customer"

    def emailAddress(self):
        return "pat@example.com"


class _Event:
    def eventIdentifier(self):
        return "evt-1"

    def calendarItemIdentifier(self):
        return "series-1"

    def calendarItemExternalIdentifier(self):
        return "series-ext"

    def calendar(self):
        return _Calendar()

    def attendees(self):
        return [_Attendee(current_user=True), _Attendee()]

    def title(self):
        return "Weekly Ritual"

    def startDate(self):
        return _NSDate(1_710_000_000)

    def endDate(self):
        return _NSDate(1_710_000_900)

    def location(self):
        return "Room A"

    def URL(self):
        return _URL()

    def notes(self):
        return "Agenda"

    def isAllDay(self):
        return False

    def lastModifiedDate(self):
        return _NSDate(1_710_000_100)


def test_helper_functions_and_formatters_cover_event_shape():
    event = _Event()

    assert calendar_eventkit._safe_call(event, "title") == "Weekly Ritual"
    assert calendar_eventkit._safe_call(event, "missing") is None
    assert calendar_eventkit._nsdate_to_iso(_NSDate(1_710_000_000))

    formatted = calendar_eventkit.format_event(event)
    assert formatted["provider"] == "eventkit"
    assert formatted["provider_event_id"] == "evt-1"
    assert formatted["provider_series_id"] == "series-1"
    assert formatted["calendar_identifier"] == "cal-1"
    assert formatted["current_user_status"] == "Accepted"

    with_attendees = calendar_eventkit.format_event_with_attendees(event)
    assert with_attendees["attendees"][0]["email"] == "pat@example.com"
    assert with_attendees["attendees"][0]["is_current_user"] is True


def test_get_events_prints_json(monkeypatch, capsys):
    monkeypatch.setattr(
        calendar_eventkit,
        "get_events_data",
        lambda *args, **kwargs: [{"title": "Weekly Ritual", "start": "2026-03-10T09:00:00"}],
    )

    calendar_eventkit.get_events("Work", 0, 1)

    assert json.loads(capsys.readouterr().out)[0]["title"] == "Weekly Ritual"
