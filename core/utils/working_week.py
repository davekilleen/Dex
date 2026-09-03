"""
Working-week utilities for Dex planning engines.

Reads the user's configured working days from user-profile.yaml and falls back
to Monday-Friday whenever the profile cannot provide a safe configuration.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

DEFAULT_WORKING_DAYS = frozenset({0, 1, 2, 3, 4})
DAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
DAY_NAME_TO_WEEKDAY = {
    alias.casefold(): weekday
    for weekday, name in enumerate(DAY_NAMES)
    for alias in (name, name[:3])
}

_cached_working_days: set[int] | None = None
_cache_loaded = False


def normalize_working_days(configured_days: Any) -> list[str]:
    """Normalize supported profile values to unique lowercase day names."""
    if not isinstance(configured_days, list):
        return []

    normalized_days = []
    seen_weekdays = set()
    for configured_day in configured_days:
        weekday = None
        if isinstance(configured_day, bool):
            continue
        if isinstance(configured_day, int):
            if 0 <= configured_day <= 6:
                weekday = configured_day
        elif isinstance(configured_day, str):
            weekday = DAY_NAME_TO_WEEKDAY.get(configured_day.strip().casefold())

        if weekday is not None and weekday not in seen_weekdays:
            normalized_days.append(DAY_NAMES[weekday].casefold())
            seen_weekdays.add(weekday)

    return normalized_days


def _load_working_days() -> set[int]:
    """Load working days from user-profile.yaml, returning the safe default."""
    try:
        import yaml
    except ImportError:
        return set(DEFAULT_WORKING_DAYS)

    vault_path = Path(os.environ.get("VAULT_PATH", Path.cwd()))
    profile_path = vault_path / "System" / "user-profile.yaml"

    try:
        with open(profile_path, "r", encoding="utf-8") as profile_file:
            profile = yaml.safe_load(profile_file)
        working_week = (profile or {}).get("working_week", {})
        configured_days = working_week.get("days", [])
        parsed_days = {
            DAY_NAME_TO_WEEKDAY[day]
            for day in normalize_working_days(configured_days)
        }
        return parsed_days or set(DEFAULT_WORKING_DAYS)
    except Exception:
        return set(DEFAULT_WORKING_DAYS)


def get_working_days() -> set[int]:
    """Get the user's configured working days, with caching."""
    global _cached_working_days, _cache_loaded
    if not _cache_loaded:
        _cached_working_days = _load_working_days()
        _cache_loaded = True
    return set(_cached_working_days)


def is_working_day(d: date) -> bool:
    """Return whether ``d`` is one of the user's working days."""
    return d.weekday() in get_working_days()


def next_working_day(d: date) -> date:
    """Return the first configured working day strictly after ``d``."""
    working_days = get_working_days()
    for days_ahead in range(1, 8):
        candidate = d + timedelta(days=days_ahead)
        if candidate.weekday() in working_days:
            return candidate
    return d + timedelta(days=1)


_OUT_OF_OFFICE_PHRASES = (
    "out of office",
    "out of the office",
    "annual leave",
    "on leave",
    "away from office",
    "not in office",
)
_OUT_OF_OFFICE_WORDS = re.compile(r"\b(?:ooo|pto|vacation|holiday)\b", re.IGNORECASE)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned[:10])
    except ValueError:
        return None


def _is_date_only(value: Any) -> bool:
    if isinstance(value, datetime):
        return False
    if isinstance(value, date):
        return True
    if not isinstance(value, str):
        return False
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()))


def is_out_of_office_event(event: Any) -> bool:
    """True when a calendar event means she is not working that day."""
    if not isinstance(event, dict):
        return False
    event_type = str(
        event.get("eventType") or event.get("event_type") or ""
    ).casefold().replace("_", "")
    if event_type in {"outofoffice", "ooo"}:
        return True
    title = str(event.get("title") or event.get("summary") or "").casefold()
    if not title:
        return False
    if any(phrase in title for phrase in _OUT_OF_OFFICE_PHRASES):
        return True
    return bool(_OUT_OF_OFFICE_WORDS.search(title))


def out_of_office_dates(events: Iterable[Any]) -> set[date]:
    """Return every calendar date covered by an out-of-office event."""
    covered: set[date] = set()
    for event in events:
        if not is_out_of_office_event(event):
            continue
        start = _as_date(event.get("start"))
        end = _as_date(event.get("end")) or start
        if start is None:
            continue
        if end is None or end < start:
            end = start
        last = end
        # Google all-day ends are the morning after the last day out.
        if end > start and (
            event.get("all_day") is True
            or _is_date_only(event.get("start"))
            or _is_date_only(event.get("end"))
        ):
            last = end - timedelta(days=1)
        cursor = start
        while cursor <= last:
            covered.add(cursor)
            cursor += timedelta(days=1)
    return covered


def speak_working_day(d: date) -> str:
    """Weekday plus date, e.g. 'Monday 7 September'."""
    return f"{DAY_NAMES[d.weekday()]} {d.day} {d.strftime('%B')}"


def next_working_day_from_events(
    today: date,
    events: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """First working day after today, skipping out-of-office on the calendar."""
    out_days = out_of_office_dates(events or [])
    future_out = {day for day in out_days if day >= today}
    out_until = max(future_out) if future_out else None
    working_days = get_working_days()
    chosen = today + timedelta(days=1)
    for days_ahead in range(1, 61):
        candidate = today + timedelta(days=days_ahead)
        if candidate.weekday() not in working_days:
            continue
        if candidate in out_days:
            continue
        chosen = candidate
        break
    return {
        "date": chosen.isoformat(),
        "spoken": speak_working_day(chosen),
        "skipped_out_of_office": bool(future_out),
        "out_until": out_until.isoformat() if out_until else None,
    }


def _week_start_weekday() -> int:
    """Return the working day immediately after the user's longest break."""
    working_days = sorted(get_working_days())
    start_weekday = working_days[0]
    longest_break = -1

    for index, weekday in enumerate(working_days):
        previous_weekday = working_days[index - 1]
        break_length = (weekday - previous_weekday - 1) % 7
        if break_length > longest_break:
            start_weekday = weekday
            longest_break = break_length

    return start_weekday


def first_working_day_of_week(d: date) -> date:
    """Return the first working day in the user's week containing ``d``."""
    start_weekday = _week_start_weekday()
    return d - timedelta(days=(d.weekday() - start_weekday) % 7)


def last_working_day_of_week(d: date) -> date:
    """Return the last working day in the user's week containing ``d``."""
    start_weekday = _week_start_weekday()
    last_offset = max(
        (weekday - start_weekday) % 7
        for weekday in get_working_days()
    )
    return first_working_day_of_week(d) + timedelta(days=last_offset)


def working_day_names() -> list[str]:
    """Return full working-day names ordered from the user's week start."""
    start_weekday = _week_start_weekday()
    ordered_weekdays = sorted(
        get_working_days(),
        key=lambda weekday: (weekday - start_weekday) % 7,
    )
    return [DAY_NAMES[weekday] for weekday in ordered_weekdays]


def _reset_cache() -> None:
    """Reset the working-week cache for tests."""
    global _cached_working_days, _cache_loaded
    _cached_working_days = None
    _cache_loaded = False
