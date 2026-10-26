"""Regression coverage for DEX-255 week-progress honesty.

On main, get_week_progress treated every weekly priority as not started:
in-progress marks were ignored, goal ids without brackets were not linked,
lines without a pillar were dropped, and the goal link was not returned.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from core.mcp import work_server

TEST_PILLARS = {
    "pillar_1": {
        "name": "Test Pillar",
        "description": "Neutral test work",
        "keywords": ["test"],
    },
}


def _decode(result) -> dict:
    return json.loads(result[0].text)


def _call(name: str, arguments: dict | None = None) -> dict:
    return _decode(asyncio.run(work_server.handle_call_tool(name, arguments or {})))


@pytest.fixture
def planning_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    tasks = tmp_path / "03-Tasks" / "Tasks.md"
    priorities = tmp_path / "02-Week_Priorities" / "Week_Priorities.md"
    goals = tmp_path / "01-Quarter_Goals" / "Quarter_Goals.md"
    profile = tmp_path / "System" / "user-profile.yaml"
    meetings = tmp_path / "00-Inbox" / "Meetings"
    people = tmp_path / "05-Areas" / "People" / "External"
    for path in (tasks, priorities, goals, profile):
        path.parent.mkdir(parents=True, exist_ok=True)
    meetings.mkdir(parents=True)
    people.mkdir(parents=True)
    tasks.write_text("# Tasks\n\n## Next Week\n", encoding="utf-8")
    profile.write_text(
        "capabilities:\n  quarter_goals:\n    enabled: true\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: priorities)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals)
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)
    monkeypatch.setattr(work_server, "get_meetings_dir", lambda: meetings)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: people.parent)
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    monkeypatch.setattr(
        work_server, "_PILLARS_SIGNATURE", work_server._pillars_file_signature()
    )
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *a, **k: None)
    monkeypatch.setattr(work_server, "refresh_search_index", lambda: None)
    monkeypatch.setattr(work_server, "_tz_today", lambda: date(2026, 10, 2))
    monkeypatch.setattr(
        work_server, "_tz_now", lambda: datetime(2026, 10, 2, 9, 15)
    )

    return {
        "root": tmp_path,
        "tasks": tasks,
        "priorities": priorities,
        "goals": goals,
    }


def test_in_progress_mark_on_heading_is_not_not_started(planning_vault):
    priority_id = "week-2026-W40-p1"
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. Review the proposal — **Test Pillar** 🔄 ^{priority_id}\n",
        encoding="utf-8",
    )

    progress = _call("get_week_progress")
    [priority] = progress["priorities"]

    assert priority["priority_id"] == priority_id
    assert priority["status"] == "in_progress"
    assert progress["summary"]["in_progress"] == 1
    assert progress["summary"]["not_started"] == 0


def test_in_progress_words_on_metadata_count(planning_vault):
    priority_id = "week-2026-W40-p2"
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. Draft the customer brief — **Test Pillar** ^{priority_id}\n"
        "   - Status: In progress\n",
        encoding="utf-8",
    )

    progress = work_server.get_week_progress_data()
    [priority] = progress["priorities"]

    assert priority["status"] == "in_progress"
    assert progress["summary"]["in_progress"] == 1


def test_started_checkbox_on_heading_counts_as_in_progress(planning_vault):
    priority_id = "week-2026-W40-p3"
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. [/] Collect launch evidence — **Test Pillar** ^{priority_id}\n",
        encoding="utf-8",
    )

    parsed = work_server.parse_weekly_priorities(planning_vault["priorities"])
    assert parsed[0]["in_progress"] is True

    progress = work_server.get_week_progress_data()
    assert progress["priorities"][0]["status"] == "in_progress"


def test_completion_mark_still_wins_over_in_progress(planning_vault):
    priority_id = "week-2026-W40-p4"
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. Finish the brief — **Test Pillar** 🔄 ✅ 2026-10-01 ^{priority_id}\n",
        encoding="utf-8",
    )

    progress = work_server.get_week_progress_data()
    [priority] = progress["priorities"]
    assert priority["status"] == "complete"
    assert progress["summary"]["complete"] == 1
    assert progress["summary"]["in_progress"] == 0


@pytest.mark.parametrize(
    "goal_text",
    (
        "Q4-2026-goal-2",
        "^Q4-2026-goal-2",
        "[Q4-2026-goal-2]",
    ),
)
def test_goal_id_without_required_brackets_is_linked(planning_vault, goal_text):
    priority_id = "week-2026-W40-p5"
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. Close the renewal — **Test Pillar** ^{priority_id} {goal_text}\n",
        encoding="utf-8",
    )

    parsed = work_server.parse_weekly_priorities(planning_vault["priorities"])
    assert parsed[0]["linked_goal_id"] == "Q4-2026-goal-2"

    progress = work_server.get_week_progress_data()
    assert progress["priorities"][0]["linked_goal_id"] == "Q4-2026-goal-2"


def test_bare_goal_id_on_quarterly_goal_bullet_is_linked(planning_vault):
    priority_id = "week-2026-W40-p6"
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. Publish renewal proof — **Test Pillar** ^{priority_id}\n"
        "   - Quarterly goal: Q4-2026-goal-3\n",
        encoding="utf-8",
    )

    parsed = work_server.parse_weekly_priorities(planning_vault["priorities"])
    assert parsed[0]["linked_goal_id"] == "Q4-2026-goal-3"

    progress = _call("get_week_progress")
    assert progress["priorities"][0]["linked_goal_id"] == "Q4-2026-goal-3"


def test_priority_without_a_pillar_is_not_dropped(planning_vault):
    priority_id = "week-2026-W40-p7"
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        "## Top 3 This Week\n\n"
        f"1. Ship the launch ^{priority_id}\n"
        "2. \n"
        "3. \n",
        encoding="utf-8",
    )

    parsed = work_server.parse_weekly_priorities(planning_vault["priorities"])
    assert [item["title"] for item in parsed] == ["Ship the launch"]
    assert parsed[0]["priority_id"] == priority_id
    assert parsed[0]["pillar"] is None

    progress = work_server.get_week_progress_data()
    assert progress["summary"]["total"] == 1
    assert progress["priorities"][0]["priority_id"] == priority_id
    assert progress["priorities"][0]["title"] == "Ship the launch"


def test_week_progress_returns_the_goal_link(planning_vault):
    priority_id = "week-2026-W40-p8"
    goal_id = "Q4-2026-goal-2"
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. Restore customer confidence — **Test Pillar** ^{priority_id}\n"
        f"   - Quarterly goal: [{goal_id}]\n",
        encoding="utf-8",
    )

    progress = _call("get_week_progress")
    [priority] = progress["priorities"]
    assert "linked_goal_id" in priority
    assert priority["linked_goal_id"] == goal_id
