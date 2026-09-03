"""Behavioral coverage for blocked/started statuses, orphan detection, and
provisional quarterly-goal recovery."""

from __future__ import annotations

import asyncio
import json
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


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    result = asyncio.run(work_server.handle_call_tool(name, arguments or {}))
    return json.loads(result[0].text)


@pytest.fixture
def task_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    tasks_file = tmp_path / "03-Tasks" / "Tasks.md"
    priorities_file = tmp_path / "02-Week_Priorities" / "Week_Priorities.md"
    goals_file = tmp_path / "01-Quarter_Goals" / "Quarter_Goals.md"
    tasks_file.parent.mkdir(parents=True)
    priorities_file.parent.mkdir(parents=True)
    goals_file.parent.mkdir(parents=True)
    tasks_file.write_text("# Tasks\n\n## Next Week\n", encoding="utf-8")

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: priorities_file)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals_file)
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    monkeypatch.setattr(
        work_server,
        "PRIORITY_LIMITS",
        {"P0": 20, "P1": 20, "P2": 20},
    )
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(work_server, "refresh_search_index", lambda: None)

    next_id = 80

    def generate_task_id() -> str:
        nonlocal next_id
        next_id += 1
        return f"task-20260903-{next_id:03d}"

    monkeypatch.setattr(work_server, "generate_task_id", generate_task_id)

    return {
        "root": tmp_path,
        "tasks": tasks_file,
        "priorities": priorities_file,
        "goals": goals_file,
    }


def test_get_blocked_tasks_returns_status_b_tasks_and_dedupes_keyword_matches(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [b] Ship integration handoff notes ^task-20260903-050\n"
        "- [b] Blocked on legal review of contract ^task-20260903-051\n"
        "- [ ] Waiting on vendor pricing sheet ^task-20260903-052\n"
        "- [ ] Draft launch summary email ^task-20260903-053\n",
        encoding="utf-8",
    )

    result = _call_tool("get_blocked_tasks")

    by_id = {task["task_id"]: task for task in result["blocked_tasks"]}
    assert result["count"] == 3
    assert by_id["task-20260903-050"]["blocked_signal"] == "status"
    # A status-blocked task with a keyword title appears exactly once.
    assert by_id["task-20260903-051"]["blocked_signal"] == "status"
    assert by_id["task-20260903-052"]["blocked_signal"] == "title_keyword"
    assert "task-20260903-053" not in by_id


def test_started_status_round_trips_through_write_and_parse(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Prepare renewal talking points ^task-20260903-060\n",
        encoding="utf-8",
    )

    started = _call_tool(
        "update_task_status",
        {"task_id": "task-20260903-060", "status": "s"},
    )

    assert started["success"] is True
    content = task_vault["tasks"].read_text(encoding="utf-8")
    assert "- [/] Prepare renewal talking points ^task-20260903-060" in content

    [task] = work_server.parse_tasks_file(task_vault["tasks"])
    assert task["status"] == "s"
    assert task["completed"] is False

    completed = _call_tool(
        "update_task_status",
        {"task_id": "task-20260903-060", "status": "d"},
    )

    assert completed["success"] is True
    [task] = work_server.parse_tasks_file(task_vault["tasks"])
    assert task["status"] == "d"


def test_legacy_s_checkbox_is_read_as_started_without_migration(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [s] Legacy started task ^task-20260903-061\n",
        encoding="utf-8",
    )

    [task] = work_server.parse_tasks_file(task_vault["tasks"])

    assert task["status"] == "s"
    assert work_server.find_task_by_id("task-20260903-061")


def test_check_goal_alignment_reports_tasks_without_goal_or_weekly_priority(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Orphaned launch checklist item ^task-20260903-070\n"
        "- [ ] Goal-linked migration task ^task-20260903-071\n"
        "\t- Pillar: Test Pillar | Priority: P1 | Goal: Q3-2026-goal-1\n"
        "- [ ] Priority-linked rollout task ^task-20260903-072\n"
        "\t- Weekly priority: [week-2026-W36-p1]\n",
        encoding="utf-8",
    )

    result = _call_tool("check_goal_alignment")

    orphans = result["tasks_without_priority"]
    assert orphans["count"] == 1
    assert orphans["items"][0]["task_id"] == "task-20260903-070"
    assert any("neither" in rec for rec in result["recommendations"])


FREEFORM_GOALS = (
    "# Quarter Goals\n\n"
    "## 🎯 This Quarter\n\n"
    "1. Launch the partner portal beta\n"
    "2. Cut onboarding time in half\n"
)


def test_lenient_parse_recovers_freeform_list_as_provisional_goals(task_vault):
    task_vault["goals"].write_text(FREEFORM_GOALS, encoding="utf-8")

    goals = work_server.parse_quarterly_goals(task_vault["goals"])

    assert [goal["title"] for goal in goals] == [
        "Launch the partner portal beta",
        "Cut onboarding time in half",
    ]
    assert all(goal["provisional"] for goal in goals)
    assert all(goal["goal_id"] for goal in goals)

    payload = _call_tool("get_quarterly_goals")
    assert payload["provisional_count"] == 2
    assert "provisional" in payload["provisional_note"]


def test_seed_placeholder_numbered_list_recovers_nothing(task_vault):
    task_vault["goals"].write_text(
        "# Quarter Goals\n\n## 🎯 This Quarter\n\n1.\n2.\n3.\n",
        encoding="utf-8",
    )

    assert work_server.parse_quarterly_goals(task_vault["goals"]) == []


def test_infer_goal_link_refuses_to_auto_link_against_provisional_goals(task_vault):
    task_vault["goals"].write_text(FREEFORM_GOALS, encoding="utf-8")
    goals = work_server.parse_quarterly_goals(task_vault["goals"])

    # An exact-title match would score 'strong' against a structured goal.
    candidates = work_server.infer_goal_link(
        "Launch the partner portal beta", "", goals
    )

    assert candidates
    assert all(candidate["confidence"] == "none" for candidate in candidates)
    assert all(candidate.get("provisional") for candidate in candidates)


def test_create_task_never_links_to_provisional_goals(task_vault):
    task_vault["goals"].write_text(FREEFORM_GOALS, encoding="utf-8")

    created = _call_tool(
        "create_task",
        {
            "title": "Launch the partner portal beta rollout checklist",
            "pillar": "pillar_1",
            "priority": "P2",
        },
    )

    assert created["success"] is True
    assert created["task"]["goal"] is None
    assert "Goal:" not in task_vault["tasks"].read_text(encoding="utf-8")

    provisional_id = work_server.parse_quarterly_goals(task_vault["goals"])[0]["goal_id"]
    refused = _call_tool(
        "create_task",
        {
            "title": "Draft partner portal launch communications plan",
            "pillar": "pillar_1",
            "goal": provisional_id,
        },
    )

    assert refused["success"] is False
    assert "structuring" in refused.get("note", "")


CANONICAL_SECTIONS = (
    "# Tasks\n\n"
    "## This Week\n\n"
    "## P0 - Urgent (max 3)\n\n"
    "## P1 - Important (max 5)\n\n"
    "## P2 - Normal (max 10)\n\n"
    "## P3 - Backlog\n"
)


def test_create_task_defaults_to_matching_priority_section(task_vault):
    task_vault["tasks"].write_text(CANONICAL_SECTIONS, encoding="utf-8")

    created = _call_tool(
        "create_task",
        {
            "title": "Draft neutral launch briefing document",
            "pillar": "pillar_1",
            "priority": "P1",
        },
    )

    assert created["success"] is True
    assert created["task"]["section"] == "P1 - Important (max 5)"
    content = task_vault["tasks"].read_text(encoding="utf-8")
    p1_section = content.split("## P1 - Important (max 5)", 1)[1].split("## P2", 1)[0]
    assert "Draft neutral launch briefing document" in p1_section
    # No duplicate section was injected.
    assert content.count("## P1 - Important (max 5)") == 1


def test_create_task_falls_back_to_next_week_without_priority_sections(task_vault):
    created = _call_tool(
        "create_task",
        {
            "title": "Draft neutral launch briefing document",
            "pillar": "pillar_1",
            "priority": "P1",
        },
    )

    assert created["success"] is True
    assert created["task"]["section"] == "Next Week"
    assert "## Next Week" in task_vault["tasks"].read_text(encoding="utf-8")


def test_explicit_section_argument_still_wins(task_vault):
    task_vault["tasks"].write_text(CANONICAL_SECTIONS, encoding="utf-8")

    created = _call_tool(
        "create_task",
        {
            "title": "Draft neutral launch briefing document",
            "pillar": "pillar_1",
            "priority": "P1",
            "section": "This Week",
        },
    )

    assert created["success"] is True
    assert created["task"]["section"] == "This Week"
