"""Coverage for the Reminders EventKit command boundary."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

sys.modules.setdefault("EventKit", SimpleNamespace())
sys.modules.setdefault(
    "Foundation",
    SimpleNamespace(NSDate=SimpleNamespace(), NSRunLoop=SimpleNamespace()),
)

from core.mcp.scripts import reminders_eventkit


class _DeniedStore:
    def calendarsForEntityType_(self, entity_type):
        return []

    def defaultCalendarForNewReminders(self):
        return None


class _DeniedEventStore:
    @classmethod
    def authorizationStatusForEntityType_(cls, entity_type):
        return 2

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return _DeniedStore()


class _UndeterminedStore:
    def __init__(self):
        self.granted = False
        self.requests = []

    def requestFullAccessToRemindersWithCompletion_(self, completion):
        self.requests.append("requestFullAccessToRemindersWithCompletion_")
        self.granted = True
        completion(True, None)

    def calendarsForEntityType_(self, entity_type):
        if not self.granted:
            raise AssertionError("Reminders were read before access was granted")
        return []


class _UndeterminedEventStore:
    store = _UndeterminedStore()

    @classmethod
    def authorizationStatusForEntityType_(cls, entity_type):
        return 0

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self.store


def test_ensure_lists_reports_how_to_grant_denied_reminders_access(monkeypatch, capsys):
    monkeypatch.setattr(
        reminders_eventkit,
        "EventKit",
        SimpleNamespace(EKEntityTypeReminder=1, EKEventStore=_DeniedEventStore),
    )

    with pytest.raises(SystemExit) as exc:
        reminders_eventkit.ensure_lists()

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "error": (
            "Reminders access denied. Enable it in System Settings → "
            "Privacy & Security → Reminders, then try again."
        )
    }


def test_list_lists_requests_fresh_reminders_access_before_reading(monkeypatch, capsys):
    store = _UndeterminedStore()
    _UndeterminedEventStore.store = store
    monkeypatch.setattr(
        reminders_eventkit,
        "EventKit",
        SimpleNamespace(EKEntityTypeReminder=1, EKEventStore=_UndeterminedEventStore),
    )

    reminders_eventkit.list_lists()

    assert json.loads(capsys.readouterr().out) == []
    assert store.requests == ["requestFullAccessToRemindersWithCompletion_"]
