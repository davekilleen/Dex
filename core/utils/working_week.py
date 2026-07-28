"""
Working-week utilities for Dex planning engines.

Reads the user's configured working days from user-profile.yaml and falls back
to Monday-Friday whenever the profile cannot provide a safe configuration.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

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
