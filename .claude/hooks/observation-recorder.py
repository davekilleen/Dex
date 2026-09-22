#!/usr/bin/env python3
"""Stamp a knowledge source the moment a tool that reads it is called.

Runs on PostToolUse. The point is that observation recording must not depend on
the assistant choosing to record: an assistant that cannot notice its context
has gone stale is exactly the one that will forget to write down when it last
looked. This watches what actually happened instead.

Mapping is by tool name, deliberately coarse. A calendar tool means the calendar
was observed; which calendar, and whether the assistant then used the result
correctly, are different questions this does not pretend to answer.

Silent and exit 0 throughout. A vault that cannot record an observation is no
worse off than one with no ledger at all, and nothing here is worth interrupting
a tool call for.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Substring match against the tool name, first hit wins. Ordered so that more
# specific patterns precede general ones.
TOOL_SOURCES: tuple[tuple[str, str], ...] = (
    ("calendar_get", "calendar"),
    ("calendar_search", "calendar"),
    ("calendar_", "calendar"),
    ("apple-mail", "email"),
    ("apple_mail", "email"),
    ("gmail", "email"),
    ("search_meetings", "meetings"),
    ("get_meeting", "meetings"),
    ("granola", "meetings"),
    ("wispr", "meetings"),
    ("list_tasks", "tasks"),
    ("update_task", "tasks"),
    ("create_task", "tasks"),
    ("get_week_progress", "week_priorities"),
    ("get_week_priorities", "week_priorities"),
    ("get_quarterly_goals", "quarter_goals"),
    ("get_goal_status", "quarter_goals"),
    ("pipedrive", "pipeline"),
    ("lookup_person", "people"),
    ("build_people_index", "people"),
    ("list_companies", "accounts"),
    ("refresh_company", "accounts"),
)


def _source_for(tool_name: str) -> str | None:
    lowered = (tool_name or "").lower()
    for needle, source in TOOL_SOURCES:
        if needle in lowered:
            return source
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    tool_name = ""
    for key in ("tool_name", "toolName", "name", "tool"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            tool_name = value
            break

    source = _source_for(tool_name)
    if source is None:
        return 0

    vault = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    sys.path.insert(0, str(vault))
    try:
        from core.utils.freshness import observe
    except Exception:  # noqa: BLE001 - a vault without the module is not a fault
        return 0
    try:
        observe(vault, source)
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
