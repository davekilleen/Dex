"""Regression coverage for the work-planning feedback desk batch.

DEX-185 complete_weekly_priority must write
DEX-186 get_week_progress must not invent completed counts or leave priorities stuck
DEX-188 check_priority_limits must ignore Tasks.md legend examples
DEX-195 update_task_status must not hang the harness
DEX-214 update_task_status must sync the weekly priorities file
DEX-216 create_quarterly_goal must honor quarter=
DEX-219 get_commitments_due must not extract single-character garbage
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
        "meetings": meetings,
        "people": people,
        "profile": profile,
    }


def test_complete_weekly_priority_writes_completion_mark(planning_vault):
    priority_id = "week-2026-W40-p1"
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. Ship customer launch — **Test Pillar** ^{priority_id}\n",
        encoding="utf-8",
    )

    result = _call("complete_weekly_priority", {"priority_id": priority_id})

    assert result["success"] is True
    assert result["completed"] is True
    written = planning_vault["priorities"].read_text(encoding="utf-8")
    assert f"✅ 2026-10-02 ^{priority_id}" in written

    progress = _call("get_week_progress")
    [priority] = progress["priorities"]
    assert priority["status"] == "complete"
    assert progress["summary"]["complete"] == 1
    assert progress["summary"]["not_started"] == 0


def test_week_progress_does_not_invent_completed_task_counts(planning_vault):
    planning_vault["tasks"].write_text(
        "# Tasks\n\n"
        "- [x] Old completed work without a stamp ^task-20260101-001\n"
        "- [x] Finished last month ^task-20260901-002 ✅ 2026-09-01 08:00\n"
        "- [x] Finished this week ^task-20261001-003 ✅ 2026-10-01 11:00\n"
        "- [ ] Still open ^task-20261002-004\n",
        encoding="utf-8",
    )
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        "1. Open priority — **Test Pillar** ^week-2026-W40-p1\n",
        encoding="utf-8",
    )

    progress = work_server.get_week_progress_data()

    assert progress["tasks_completed_this_week"] == 1
    assert progress["summary"]["complete"] == 0
    assert progress["priorities"][0]["status"] == "not_started"


def test_check_priority_limits_ignores_tasks_md_legend(planning_vault):
    planning_vault["tasks"].write_text(
        "# Tasks\n\n"
        "## P2 - Normal (max 10)\n"
        "- [ ] Real backlog item ^task-20261002-001\n\n"
        "## Task Format\n\n"
        "```\n"
        "- [ ] **Task title** ^task-YYYYMMDD-XXX\n"
        "	- Pillar: Pillar Name | Priority: P2 | Due: 2026-01-31\n"
        "- [/] Started task\n"
        "- [b] Blocked task (note blocker)\n"
        "- [x] Completed task\n"
        "```\n",
        encoding="utf-8",
    )

    result = _call("check_priority_limits")

    assert result["priority_counts"] == {"P2": 1}
    assert result["alerts"] == []
    assert result["balanced"] is True
    parsed = work_server.parse_tasks_file(planning_vault["tasks"])
    assert [task["title"] for task in parsed] == ["Real backlog item"]


def test_update_task_status_skips_non_user_markdown(planning_vault):
    task_id = "task-20261002-010"
    planning_vault["tasks"].write_text(
        f"# Tasks\n\n- [ ] Ship the brief ^{task_id}\n",
        encoding="utf-8",
    )
    decoy = planning_vault["root"] / "docs" / "examples.md"
    decoy.parent.mkdir(parents=True)
    decoy.write_text(f"- [ ] Ship the brief ^{task_id}\n", encoding="utf-8")

    read_paths: list[Path] = []
    original = work_server.read_vault_text

    def track(path: Path) -> str:
        read_paths.append(Path(path))
        return original(path)

    work_server.read_vault_text = track
    try:
        result = work_server.update_task_status_everywhere(task_id, "d")
    finally:
        work_server.read_vault_text = original

    assert result["success"] is True
    assert not any(path == decoy or "docs" in path.parts for path in read_paths)
    assert decoy.read_text(encoding="utf-8") == f"- [ ] Ship the brief ^{task_id}\n"
    assert "- [x]" in planning_vault["tasks"].read_text(encoding="utf-8")


def test_update_task_status_marks_weekly_priority_when_linked_tasks_finish(
    planning_vault,
):
    priority_id = "week-2026-W40-p2"
    task_id = "task-20261002-020"
    planning_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. Restore customer confidence — **Test Pillar** ^{priority_id}\n"
        f"   - Success criteria: Complete {task_id}\n"
        "## Supporting Tasks\n"
        f"- [ ] Restore customer confidence ^{task_id}\n",
        encoding="utf-8",
    )
    planning_vault["tasks"].write_text(
        "# Tasks\n\n"
        f"- [ ] Restore customer confidence ^{task_id}\n"
        f"\t- Weekly priority: [{priority_id}]\n",
        encoding="utf-8",
    )

    result = _call("update_task_status", {"task_id": task_id, "status": "d"})

    assert result["success"] is True
    week_text = planning_vault["priorities"].read_text(encoding="utf-8")
    assert f"✅ 2026-10-02 ^{priority_id}" in week_text
    assert f"- [x] Restore customer confidence ✅ 2026-10-02 09:15 ^{task_id}" in week_text

    progress = _call("get_week_progress")
    [priority] = progress["priorities"]
    assert priority["status"] == "complete"
    assert priority["tasks_done"] == 1
    assert priority["tasks_total"] == 1


def test_create_quarterly_goal_honors_explicit_quarter(planning_vault):
    result = _call(
        "create_quarterly_goal",
        {
            "title": "Prepare next-quarter launch",
            "pillar": "pillar_1",
            "success_criteria": "Launch plan is written",
            "quarter": "Q1-2027",
        },
    )

    assert result["success"] is True
    assert result["goal_id"] == "Q1-2027-goal-1"
    written = planning_vault["goals"].read_text(encoding="utf-8")
    assert "quarter: Q1 2027" in written
    assert "^Q1-2027-goal-1" in written

    listed = _call("get_quarterly_goals", {"quarter": "Q1 2027"})
    assert listed["count"] == 1
    assert listed["goals"][0]["quarter"] == "Q1 2027"
    assert listed["goals"][0]["goal_id"] == "Q1-2027-goal-1"


def test_create_quarterly_goal_keeps_requested_quarter_on_existing_file(
    planning_vault,
):
    planning_vault["goals"].write_text(
        "---\nquarter: Q4 2026\n---\n\n"
        "### 1. Finish this quarter — **Test Pillar** ^Q4-2026-goal-1\n",
        encoding="utf-8",
    )

    result = _call(
        "create_quarterly_goal",
        {
            "title": "Start the next quarter early",
            "pillar": "pillar_1",
            "success_criteria": "Next quarter goal exists",
            "quarter": "Q1 2027",
        },
    )

    assert result["success"] is True
    assert result["goal_id"] == "Q1-2027-goal-1"
    parsed = work_server.parse_quarterly_goals(planning_vault["goals"])
    by_id = {goal["goal_id"]: goal["quarter"] for goal in parsed}
    assert by_id == {
        "Q4-2026-goal-1": "Q4 2026",
        "Q1-2027-goal-1": "Q1 2027",
    }


def test_get_commitments_due_drops_single_character_garbage(planning_vault):
    planning_vault["meetings"].joinpath("2026-10-01 - Follow up.md").write_text(
        "# Follow up\n\n"
        "I'll send x.\n"
        "We will provide a.\n"
        "I'll send the deck by Friday.\n"
        "Action items: x\n"
        "Follow-up: send the signed contract\n",
        encoding="utf-8",
    )

    extracted = work_server.extract_commitments_from_text(
        "I'll send x. We will provide a. I'll send the deck by Friday."
    )
    texts = [item["commitment"] for item in extracted]
    assert "x" not in texts
    assert "a" not in texts
    assert any("deck" in item for item in texts)

    result = _call("get_commitments_due", {"date_range": "all"})
    commitments = (
        result["commitments_due_today"]
        + result["commitments_due_this_week"]
        + result["commitments_no_date"]
    )
    captured = [item["commitment"] for item in commitments]
    assert "x" not in captured
    assert "a" not in captured
    assert any("deck" in item for item in captured)
    assert any("signed contract" in item for item in captured)
