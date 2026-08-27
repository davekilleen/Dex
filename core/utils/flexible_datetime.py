"""Parse meeting and calendar dates that older Mac Python cannot read."""

from __future__ import annotations

from datetime import datetime


def parse_flexible_datetime(value: str) -> datetime:
    """Parse an ISO date or timestamp, including date-only and trailing Z.

    Apple's bundled Python is often 3.9. ``datetime.fromisoformat`` there
    rejects ``YYYY-MM-DD`` and a trailing ``Z``.
    """
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError("empty date")
    cleaned = cleaned.replace("Z", "+00:00").replace(" +0000", "+00:00")
    if len(cleaned) == 10 and cleaned[4] == "-" and cleaned[7] == "-":
        return datetime.strptime(cleaned, "%Y-%m-%d")
    return datetime.fromisoformat(cleaned)
