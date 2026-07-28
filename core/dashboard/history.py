"""Read and summarize the private, append-only Dex Dashboard history."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any

from core.paths import DEX_RUNTIME_DIR, VAULT_ROOT

ISO_WEEK = re.compile(r"^\d{4}-W\d{2}$")
_MILESTONE_RULES = (
    ("tasks_done", ("tasks_done", "tasks", "completed_tasks"), (100, 500, 1000)),
    ("meetings", ("meetings", "meeting_notes"), (50, 100, 250)),
    ("people", ("people", "person_pages"), (50, 100)),
)
_MILESTONE_PRIORITY = {"tasks_done": 0, "vault_age": 1, "meetings": 2, "people": 3}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _non_negative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _count(source: Any, keys: tuple[str, ...]) -> int:
    values = _mapping(source)
    for key in keys:
        value = _non_negative_int(values.get(key))
        if value is not None:
            return value
    return 0


def _optional_count(source: Any, keys: tuple[str, ...]) -> int | None:
    values = _mapping(source)
    for key in keys:
        value = _non_negative_int(values.get(key))
        if value is not None:
            return value
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_week(value: datetime) -> str:
    iso = value.date().isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _history_path(vault: Path) -> Path:
    return vault / DEX_RUNTIME_DIR.relative_to(VAULT_ROOT) / "dashboard" / "history.jsonl"


def load_history(vault: Path | str) -> list[dict[str, Any]]:
    """Return valid snapshot objects, quietly ignoring damaged history lines."""
    path = _history_path(Path(vault).expanduser())
    if not path.is_file():
        return []
    snapshots = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            snapshot = json.loads(line)
        except json.JSONDecodeError:
            continue
        is_snapshot = isinstance(snapshot, dict) and isinstance(snapshot.get("counts"), dict)
        if is_snapshot and _parse_timestamp(snapshot.get("ts")):
            snapshots.append(snapshot)
    return snapshots


def _history_entries(data: Any) -> list[dict[str, Any]]:
    source = _mapping(data)
    entries = source.get("history", source.get("entries", []))
    return [entry for entry in _list(entries) if isinstance(entry, dict)]


def weekly_trends(data: dict[str, Any]) -> dict[str, list[Any]]:
    """Build a shared ISO-week axis from analytics and cumulative history snapshots."""
    analytics = _mapping(_mapping(data).get("analytics"))
    raw_activity = _mapping(analytics.get("by_iso_week"))
    activity = {
        label: count
        for label, value in raw_activity.items()
        if isinstance(label, str)
        and ISO_WEEK.fullmatch(label)
        and (count := _non_negative_int(value)) is not None
    }
    snapshots_by_week: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for snapshot in _history_entries(data):
        timestamp = _parse_timestamp(snapshot.get("ts"))
        if timestamp is None:
            continue
        snapshots_by_week.setdefault(_iso_week(timestamp), []).append((timestamp, snapshot))

    labels = sorted(set(activity) | set(snapshots_by_week))
    meetings: list[int] = []
    tasks: list[int] = []
    snapshots: list[int] = []
    previous_counts: dict[str, int] | None = None
    for label in labels:
        week_entries = sorted(snapshots_by_week.get(label, []), key=lambda item: item[0])
        snapshots.append(len(week_entries))
        if not week_entries:
            meetings.append(0)
            tasks.append(0)
            continue
        current_counts = _mapping(week_entries[-1][1].get("counts"))
        current_meetings = _count(current_counts, ("meetings", "meeting_notes"))
        current_tasks = _count(current_counts, ("tasks_done", "tasks", "completed_tasks"))
        if previous_counts is None:
            meetings.append(0)
            tasks.append(0)
        else:
            meetings.append(max(0, current_meetings - previous_counts["meetings"]))
            tasks.append(max(0, current_tasks - previous_counts["tasks_done"]))
        previous_counts = {"meetings": current_meetings, "tasks_done": current_tasks}

    return {
        "labels": labels,
        "activity": [activity.get(label, 0) for label in labels],
        "meetings": meetings,
        "tasks": tasks,
        "snapshots": snapshots,
    }


def _milestone_label(identifier: str, threshold: int) -> str:
    formatted = f"{threshold:,}"
    if identifier == "tasks_done":
        return f"{formatted} completed tasks"
    if identifier == "meetings":
        return f"{formatted} meeting notes"
    if identifier == "people":
        return f"{formatted} people in Dex"
    return "Six months with Dex" if threshold == 180 else "One year with Dex"


def detect_milestones(
    prev_counts: dict[str, Any], new_counts: dict[str, Any], vault_age: int | None
) -> list[dict[str, Any]]:
    """Return milestones crossed since the prior snapshot, largest threshold first."""
    milestones = []
    for identifier, keys, thresholds in _MILESTONE_RULES:
        previous = _count(prev_counts, keys)
        current = _count(new_counts, keys)
        for threshold in thresholds:
            if previous < threshold <= current:
                milestones.append(
                    {
                        "id": identifier,
                        "threshold": threshold,
                        "label": _milestone_label(identifier, threshold),
                    }
                )

    current_age = _non_negative_int(vault_age)
    if current_age is not None:
        previous_age = _optional_count(prev_counts, ("vault_age_days", "vault_age"))
        if previous_age is None:
            previous_age = max(0, current_age - 1)
        for threshold in (180, 365):
            if previous_age < threshold <= current_age:
                milestones.append(
                    {
                        "id": "vault_age",
                        "threshold": threshold,
                        "label": _milestone_label("vault_age", threshold),
                    }
                )

    return sorted(
        milestones,
        key=lambda milestone: (-int(milestone["threshold"]), _MILESTONE_PRIORITY[milestone["id"]]),
    )


def sparkline_svg(values: list[int | float], width: int, height: int) -> str:
    """Render numeric values as a tiny self-contained SVG polyline."""
    safe_width = (
        width if isinstance(width, int) and not isinstance(width, bool) and width > 0 else 120
    )
    safe_height = (
        height if isinstance(height, int) and not isinstance(height, bool) and height > 0 else 32
    )
    numeric_values = [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
    ]
    if not numeric_values:
        points = ""
    else:
        minimum = min(numeric_values)
        maximum = max(numeric_values)
        span = maximum - minimum
        x_step = safe_width / max(1, len(numeric_values) - 1)
        points_list = []
        for index, value in enumerate(numeric_values):
            y = safe_height / 2 if span == 0 else safe_height - (
                (value - minimum) / span * safe_height
            )
            points_list.append(f"{index * x_step:.2f},{y:.2f}")
        points = " ".join(points_list)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {safe_width} {safe_height}" '
        'role="img" aria-label="Trend" focusable="false">'
        f'<polyline points="{points}" fill="none" stroke="#62d7d1" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )
