"""Split “I owe this” and “waiting on them” so overdue cannot mean both.

Person pages used to grow a single follow-up date (often written as
``next_action_date``) that skills then treated as overdue either way. A date
you are waiting on someone else is a nudge, not a late mark. Only
``i_owe_date`` can be overdue.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal, Mapping

_AMBIGUOUS_DATE_LINE = re.compile(
    r"(?im)^(?:next_action_date\s*:|\*\*next action date:\*\*|\|\s*\*?\*?next action date\*?\*?\s*\|)\s*[\"']?(\d{4}-\d{2}-\d{2})"
)

I_OWE_DATE_FIELD = "i_owe_date"
WAITING_ON_DATE_FIELD = "waiting_on_date"
AMBIGUOUS_ACTION_DATE_FIELDS = ("next_action_date",)

ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"

ActionKind = Literal["owed", "waiting", "ambiguous", "unknown"]
ActionStatus = Literal[
    "owed_overdue",
    "owed_due",
    "waiting_stale",
    "waiting_open",
    "ambiguous",
    "none",
]


def parse_iso_date(value: Any) -> date | None:
    """Return a calendar date only when ``value`` is exactly YYYY-MM-DD."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def action_date_kind(field: str | None) -> ActionKind:
    """Classify a field name. ``next_action_date`` is never owed or waiting."""
    key = (field or "").strip().casefold().replace(" ", "_")
    if key == I_OWE_DATE_FIELD:
        return "owed"
    if key == WAITING_ON_DATE_FIELD:
        return "waiting"
    if key in AMBIGUOUS_ACTION_DATE_FIELDS:
        return "ambiguous"
    return "unknown"


def classify_action_date(
    field: str | None,
    value: Any,
    *,
    today: date,
) -> ActionStatus:
    """Return the status for one named date. Ambiguous fields are never overdue."""
    kind = action_date_kind(field)
    parsed = parse_iso_date(value)
    if kind == "ambiguous":
        return "ambiguous"
    if kind == "unknown" or parsed is None:
        return "none"
    if kind == "owed":
        return "owed_overdue" if parsed < today else "owed_due"
    return "waiting_stale" if parsed < today else "waiting_open"


def _first_field(record: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in record:
            return record.get(name)
        lowered = name.casefold()
        for key, value in record.items():
            if str(key).casefold().replace(" ", "_") == lowered:
                return value
    return None


def owed_status(record: Mapping[str, Any], *, today: date) -> ActionStatus:
    """Overdue applies only to ``i_owe_date``. A lone ``next_action_date`` is not."""
    return classify_action_date(
        I_OWE_DATE_FIELD,
        _first_field(record, I_OWE_DATE_FIELD),
        today=today,
    )


def waiting_status(record: Mapping[str, Any], *, today: date) -> ActionStatus:
    """A past ``waiting_on_date`` is stale, never overdue."""
    return classify_action_date(
        WAITING_ON_DATE_FIELD,
        _first_field(record, WAITING_ON_DATE_FIELD),
        today=today,
    )


def ambiguous_action_date(record: Mapping[str, Any]) -> Any:
    """Return a leftover dual-meaning date so callers can refuse to judge it."""
    return _first_field(record, *AMBIGUOUS_ACTION_DATE_FIELDS)


def read_ambiguous_action_date(text: str) -> str | None:
    """Find ``next_action_date`` on a page without treating it as overdue."""
    if not isinstance(text, str) or not text:
        return None
    match = _AMBIGUOUS_DATE_LINE.search(text)
    return match.group(1) if match else None


def is_owed_overdue(record: Mapping[str, Any], *, today: date) -> bool:
    return owed_status(record, today=today) == "owed_overdue"


def is_waiting_stale(record: Mapping[str, Any], *, today: date) -> bool:
    return waiting_status(record, today=today) == "waiting_stale"
