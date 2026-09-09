"""Read calendar events for attribution, from a process with no host attached.

The meeting-source sweep runs on a schedule, so it cannot ask an MCP client for
the calendar. It uses the same EventKit helper the calendar server shells to,
which is an ordinary script and works anywhere the vault does.

Calendar absence is not calendar emptiness. Every failure here returns None, and
callers must treat that as "attendance could not be checked" rather than "nobody
was there". Returning an empty list instead would let a machine with no calendar
access silently mark every capture as having no attendees.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HELPER = Path("core/mcp/scripts/calendar_eventkit.py")
TIMEOUT_SECONDS = 30


def default_calendar_name(vault_root: Path) -> str | None:
    """The calendar the user configured, if they configured one.

    Follows the same order the calendar server uses, so a vault that works
    there works here: ``calendar.work_calendar``, then ``work_email``, then a
    name built from ``name`` and ``email_domain``. Unlike the server this
    returns None rather than falling back to a guessed "Work" calendar, because
    querying a calendar the user does not have would produce an empty result
    that reads exactly like a meeting with nobody in it.
    """
    profile = vault_root / "System" / "user-profile.yaml"
    try:
        import yaml

        data = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 - an unreadable profile is not a calendar fault
        return None
    if not isinstance(data, dict):
        return None

    calendar = data.get("calendar")
    if isinstance(calendar, dict):
        configured = calendar.get("work_calendar")
        if isinstance(configured, str) and configured.strip():
            return configured.strip()

    work_email = data.get("work_email")
    if isinstance(work_email, str) and work_email.strip():
        return work_email.strip()

    name, domain = data.get("name"), data.get("email_domain")
    if isinstance(name, str) and name.strip() and isinstance(domain, str) and domain.strip():
        return f"{name.strip().lower().replace(' ', '.')}@{domain.strip()}"
    return None


def events_around(
    vault_root: Path,
    *,
    start_offset_days: int,
    end_offset_days: int,
    calendar_name: str | None = None,
) -> list[dict[str, Any]] | None:
    """Events with attendees in the window, or None when they cannot be read."""
    helper = vault_root / HELPER
    if not helper.is_file():
        logger.info("Calendar helper not present at %s; attribution will stay unresolved", helper)
        return None

    name = calendar_name or default_calendar_name(vault_root)
    if not name:
        logger.info("No calendar configured; attribution will stay unresolved")
        return None

    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(helper),
                "attendees",
                name,
                str(start_offset_days),
                str(end_offset_days),
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            env={**os.environ, "PYTHONPATH": str(vault_root)},
        )
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Calendar could not be read: %s", error)
        return None

    if completed.returncode != 0:
        logger.warning("Calendar helper failed: %s", (completed.stderr or "").strip()[:200])
        return None

    try:
        payload = json.loads(completed.stdout or "null")
    except json.JSONDecodeError:
        logger.warning("Calendar helper returned output that is not JSON")
        return None

    if isinstance(payload, dict):
        payload = payload.get("events")
    if not isinstance(payload, list):
        return None
    return [event for event in payload if isinstance(event, dict)]
