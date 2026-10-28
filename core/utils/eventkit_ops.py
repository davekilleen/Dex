"""Shared Calendar and Reminders EventKit operations.

The fallback scripts and Dex Helper call the same functions so EventKit
logic is not copied. When the helper app is launched through LaunchServices,
these functions run inside that app and the permission ask belongs to it.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any


def run_op(op: str, payload: Mapping[str, Any] | None = None) -> tuple[int, str]:
    """Run a helper op and return ``(exit_code, stdout)``.

    ``payload`` may include ``args`` (positional CLI arguments). Titles and
    other event data stay in this payload, never on argv of ``open``.
    """
    if op == "version":
        from core.utils.macos_privacy_helper import helper_source_version

        return 0, json.dumps({"version": helper_source_version()})
    if op == "status":
        return 0, json.dumps(_authorization_snapshot())
    if op == "request-access":
        return _request_access()

    domain, _, command = op.partition(".")
    args = [str(item) for item in list((payload or {}).get("args") or [])]
    if domain == "calendar":
        from core.mcp.scripts import calendar_eventkit as module
    elif domain == "reminders":
        from core.mcp.scripts import reminders_eventkit as module
    else:
        return 1, json.dumps({"error": f"Unknown helper op: {op}"})
    return _run_script_main(module, [command, *args])


def _run_script_main(module: Any, argv: Sequence[str]) -> tuple[int, str]:
    buffer = io.StringIO()
    previous = sys.argv
    try:
        sys.argv = [getattr(module, "__file__", "eventkit"), *argv]
        with contextlib.redirect_stdout(buffer):
            try:
                module.main()
            except SystemExit as error:
                code = error.code
                if code is None:
                    code = 0
                if not isinstance(code, int):
                    code = 1
                return code, buffer.getvalue().rstrip()
        return 0, buffer.getvalue().rstrip()
    finally:
        sys.argv = previous


def _authorization_snapshot() -> dict[str, str]:
    try:
        import EventKit
    except ImportError:
        return {"calendar": "unavailable", "reminders": "unavailable"}
    return {
        "calendar": _status_name(
            EventKit.EKEventStore.authorizationStatusForEntityType_(
                EventKit.EKEntityTypeEvent
            )
        ),
        "reminders": _status_name(
            EventKit.EKEventStore.authorizationStatusForEntityType_(
                EventKit.EKEntityTypeReminder
            )
        ),
    }


def _status_name(status: int) -> str:
    return {
        0: "not_determined",
        1: "restricted",
        2: "denied",
        3: "granted",
        4: "granted",
        5: "write_only",
    }.get(int(status), "unknown")


def _request_access() -> tuple[int, str]:
    try:
        import EventKit
    except ImportError:
        return 1, json.dumps({"error": "EventKit is not installed."})
    from core.mcp.scripts.calendar_eventkit import ensure_calendar_access
    from core.mcp.scripts.reminders_eventkit import ensure_reminders_access

    store = EventKit.EKEventStore.alloc().init()
    calendar_ok = bool(ensure_calendar_access(store))
    reminders_ok = bool(ensure_reminders_access(store))
    body = {
        "calendar": "granted" if calendar_ok else "denied",
        "reminders": "granted" if reminders_ok else "denied",
    }
    return (0 if calendar_ok and reminders_ok else 1), json.dumps(body)
