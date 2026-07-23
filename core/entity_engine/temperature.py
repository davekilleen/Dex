"""Pure relationship-temperature classification from canonical touch records."""

from __future__ import annotations

from datetime import date, datetime
from statistics import median
from typing import Any, Iterable, Mapping

TEMPERATURE_WINDOWS = {
    "person": {"warm": 14, "cold": 45},
    "company": {"warm": 30, "cold": 90},
}

_MAX_CADENCE_COLD_DAYS = 365


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _is_engagement(touch: Mapping[str, Any]) -> bool:
    touch_type = str(touch.get("type") or "").casefold()
    direction = str(touch.get("direction") or "").casefold()
    return (
        (touch_type == "meeting" and direction in {"", "none"})
        or direction == "in"
    )


def _days_since(now: date, then: date) -> int:
    return max(0, (now - then).days)


def classify_temperature(
    touches: Iterable[Mapping[str, Any]] | None,
    *,
    entity_type: str,
    now: datetime | date,
) -> dict[str, Any]:
    """Classify momentum and freshness without reading time or external state."""
    current_date = _as_date(now)
    if current_date is None:
        raise TypeError("now must be a date or datetime")

    dated_touches = [
        (touch_date, touch)
        for touch in touches or ()
        if isinstance(touch, Mapping)
        if (touch_date := _as_date(touch.get("ts"))) is not None
    ]
    engagement_dates = sorted(
        touch_date
        for touch_date, touch in dated_touches
        if _is_engagement(touch)
    )
    last_touch_date = max(
        (touch_date for touch_date, _touch in dated_touches),
        default=None,
    )
    last_engagement_date = engagement_dates[-1] if engagement_dates else None

    base = {
        "temperature": None,
        "last_touch": last_touch_date.isoformat() if last_touch_date else None,
        "last_engagement": (
            last_engagement_date.isoformat() if last_engagement_date else None
        ),
        "days_since_touch": (
            _days_since(current_date, last_touch_date)
            if last_touch_date
            else None
        ),
        "days_since_engagement": (
            _days_since(current_date, last_engagement_date)
            if last_engagement_date
            else None
        ),
        "touch_count": len(dated_touches),
        "engagement_count": len(engagement_dates),
        "cadence_days": None,
        "reason": "no logged touches",
    }
    if not dated_touches:
        return base

    windows = TEMPERATURE_WINDOWS.get(
        str(entity_type or "").casefold(),
        TEMPERATURE_WINDOWS["person"],
    )
    warm_days = windows["warm"]
    cold_days = windows["cold"]
    if len(engagement_dates) >= 3:
        gaps = [
            (later - earlier).days
            for earlier, later in zip(
                engagement_dates,
                engagement_dates[1:],
            )
        ]
        cadence_days = round(median(gaps))
        base["cadence_days"] = cadence_days
        warm_days = max(1, min(warm_days, cadence_days))
        cold_days = max(
            cold_days,
            min(_MAX_CADENCE_COLD_DAYS, round(2 * median(gaps))),
        )

    days_since_touch = base["days_since_touch"]
    days_since_engagement = base["days_since_engagement"]
    if last_engagement_date is None:
        if days_since_touch <= cold_days:
            base["temperature"] = "cooling"
            base["reason"] = "recent one-sided touch without engagement"
        else:
            base["temperature"] = "cold"
            base["reason"] = "no engagement and weak touches have gone quiet"
        return base

    if days_since_engagement > cold_days:
        base["temperature"] = "cold"
        base["reason"] = f"last engagement was {days_since_engagement} days ago"
        return base

    latest_weak_date = max(
        (
            touch_date
            for touch_date, touch in dated_touches
            if not _is_engagement(touch)
        ),
        default=None,
    )
    if latest_weak_date and latest_weak_date > last_engagement_date:
        base["temperature"] = "cooling"
        base["reason"] = "most recent touch is one-sided"
    elif days_since_engagement <= warm_days:
        base["temperature"] = "warm"
        base["reason"] = "recent engagement"
    else:
        base["temperature"] = "cooling"
        base["reason"] = f"last engagement was {days_since_engagement} days ago"
    return base
