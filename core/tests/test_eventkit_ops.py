"""Shared EventKit ops used by Dex Helper and the fallback scripts."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

sys.modules.setdefault("EventKit", SimpleNamespace())
sys.modules.setdefault(
    "Foundation",
    SimpleNamespace(NSDate=SimpleNamespace(), NSRunLoop=SimpleNamespace()),
)

from core.utils import eventkit_ops


def test_version_op_reads_the_helper_source_version():
    code, text = eventkit_ops.run_op("version")
    assert code == 0
    payload = json.loads(text)
    assert payload["version"]


def test_unknown_op_is_an_error():
    code, text = eventkit_ops.run_op("unknown.thing")
    assert code == 1
    assert "Unknown helper op" in text


def test_calendar_and_reminders_ops_call_the_existing_script_mains(monkeypatch):
    called: list[tuple[str, list[str]]] = []

    def calendar_main():
        called.append(("calendar", list(sys.argv[1:])))
        print('{"calendars":[]}')

    def reminders_main():
        called.append(("reminders", list(sys.argv[1:])))
        print("[]")

    monkeypatch.setattr("core.mcp.scripts.calendar_eventkit.main", calendar_main)
    monkeypatch.setattr("core.mcp.scripts.reminders_eventkit.main", reminders_main)

    code, text = eventkit_ops.run_op("calendar.list", {"args": []})
    assert code == 0
    assert text == '{"calendars":[]}'
    code, text = eventkit_ops.run_op("reminders.list_items", {"args": ["Dex Today"]})
    assert code == 0
    assert text == "[]"
    assert called == [("calendar", ["list"]), ("reminders", ["list_items", "Dex Today"])]
