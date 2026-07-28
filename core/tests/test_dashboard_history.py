"""Behavioral coverage for Dashboard history and its rendered section."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from xml.etree import ElementTree


def _history_module():
    return importlib.import_module("core.dashboard.history")


def _history_section():
    return importlib.import_module("core.dashboard.sections.history")


def _history_file(vault: Path) -> Path:
    paths = importlib.import_module("core.paths")
    return (
        vault
        / paths.DEX_RUNTIME_DIR.relative_to(paths.VAULT_ROOT)
        / "dashboard"
        / "history.jsonl"
    )


def _snapshot(ts: str, *, tasks: int, meetings: int, people: int) -> dict:
    return {
        "ts": ts,
        "counts": {
            "tasks_done": tasks,
            "meetings": meetings,
            "people": people,
        },
    }


def test_load_history_skips_malformed_jsonl_lines(tmp_path: Path) -> None:
    history = _history_module()
    vault = tmp_path / "vault"
    path = _history_file(vault)
    path.parent.mkdir(parents=True)
    first = _snapshot("2026-07-06T12:00:00Z", tasks=90, meetings=45, people=49)
    last = _snapshot("2026-07-20T12:00:00Z", tasks=105, meetings=51, people=50)
    path.write_text(
        "\n".join(
            [json.dumps(first), "{not json", json.dumps(["not a snapshot"]), json.dumps(last)]
        )
        + "\n",
        encoding="utf-8",
    )

    assert history.load_history(vault) == [first, last]


def test_weekly_trends_uses_analytics_weeks_and_snapshot_count_changes() -> None:
    history = _history_module()
    snapshots = [
        _snapshot("2026-07-06T12:00:00Z", tasks=90, meetings=45, people=40),
        _snapshot("2026-07-13T12:00:00Z", tasks=95, meetings=48, people=42),
        _snapshot("2026-07-20T12:00:00Z", tasks=105, meetings=51, people=50),
    ]

    trends = history.weekly_trends(
        {
            "analytics": {"by_iso_week": {"2026-W28": 2, "2026-W29": 4, "2026-W30": 1}},
            "history": snapshots,
        }
    )

    assert trends == {
        "labels": ["2026-W28", "2026-W29", "2026-W30"],
        "activity": [2, 4, 1],
        "meetings": [0, 3, 3],
        "tasks": [0, 5, 10],
        "snapshots": [1, 1, 1],
    }


def test_detect_milestones_only_reports_thresholds_crossed_since_last_snapshot() -> None:
    history = _history_module()

    crossed = history.detect_milestones(
        {"tasks_done": 99, "meetings": 49, "people": 49},
        {"tasks_done": 100, "meetings": 50, "people": 50},
        vault_age=179,
    )
    not_crossed = history.detect_milestones(
        {"tasks_done": 100, "meetings": 50, "people": 50},
        {"tasks_done": 101, "meetings": 51, "people": 51},
        vault_age=179,
    )

    assert [milestone["id"] for milestone in crossed] == ["tasks_done", "meetings", "people"]
    assert not_crossed == []


def test_detect_milestones_orders_simultaneous_crossings_biggest_first() -> None:
    history = _history_module()

    milestones = history.detect_milestones(
        {"tasks_done": 499, "meetings": 99, "people": 99, "vault_age_days": 364},
        {"tasks_done": 500, "meetings": 100, "people": 100},
        vault_age=365,
    )

    assert [milestone["id"] for milestone in milestones] == [
        "tasks_done",
        "vault_age",
        "meetings",
        "people",
    ]
    assert milestones[0]["threshold"] == 500
    assert milestones[0]["label"] == "500 completed tasks"


def test_sparkline_svg_is_well_formed_and_contains_a_polyline() -> None:
    history = _history_module()

    svg = history.sparkline_svg([0, 4, 2, 7], width=120, height=32)
    root = ElementTree.fromstring(svg)

    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["viewBox"] == "0 0 120 32"
    assert root.find("{http://www.w3.org/2000/svg}polyline") is not None


def test_render_history_hides_empty_history_and_marks_a_first_snapshot() -> None:
    section = _history_section()
    first = _snapshot("2026-07-20T12:00:00Z", tasks=3, meetings=1, people=2)

    assert section.render_history({"history": []}) == ""

    page = section.render_history({"history": [first]})
    assert 'id="history"' in page
    assert "This is your first snapshot." in page
    assert "<svg" not in page


def test_render_history_shows_three_sparklines_one_milestone_and_escaped_looking_back() -> None:
    history = _history_module()
    section = _history_section()
    snapshots = [
        _snapshot("2026-07-13T12:00:00Z", tasks=499, meetings=99, people=40),
        _snapshot("2026-07-20T12:00:00Z", tasks=500, meetings=100, people=42),
    ]
    trends = history.weekly_trends(
        {"analytics": {"by_iso_week": {"2026-W29": 2, "2026-W30": 3}}, "history": snapshots}
    )
    milestones = history.detect_milestones(
        snapshots[0]["counts"], snapshots[-1]["counts"], vault_age=200
    )

    page = section.render_history(
        {
            "history": snapshots,
            "trends": trends,
            "milestones": milestones,
            "looking_back": "Then <now>; now steadier.",
        }
    )

    assert page.count("<svg") == 3
    assert page.count("✦") == 1
    assert "500 completed tasks" in page
    assert "Looking back" in page
    assert "Then &lt;now&gt;; now steadier." in page
    assert "Then <now>; now steadier." not in page
