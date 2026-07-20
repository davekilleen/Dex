"""Regression coverage for confirming or clearing tentative task-goal links."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.mcp import work_server

TASK_ID = "task-20260712-001"
GOAL_ID = "Q3-2026-goal-2"

TEST_PILLARS = {
    "pillar_1": {
        "name": "Test Pillar",
        "description": "Neutral test work",
        "keywords": ["test"],
    }
}


def _call_tool(name: str, arguments: dict) -> dict:
    result = asyncio.run(work_server.handle_call_tool(name, arguments))
    return json.loads(result[0].text)


def _write_task(tasks_file: Path, metadata: str) -> None:
    tasks_file.write_text(
        "# Tasks\n\n"
        "## Next Week\n"
        f"- [ ] Prepare review surface ^{TASK_ID}\n"
        f"\t- {metadata}\n",
        encoding="utf-8",
    )


def _parsed_task(tasks_file: Path) -> dict:
    return next(
        task
        for task in work_server.parse_tasks_file(tasks_file)
        if task["task_id"] == TASK_ID
    )


@pytest.fixture
def tasks_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "03-Tasks" / "Tasks.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Tasks\n", encoding="utf-8")

    monkeypatch.setattr(work_server, "get_tasks_file", lambda: path)
    # These tests exercise goal-link logic in isolation; room gating has its
    # own dedicated coverage (test_capabilities / test_feature_status).
    monkeypatch.setattr(
        work_server.capability_rooms, "enabled", lambda room, **kwargs: True
    )
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    monkeypatch.setattr(work_server, "refresh_search_index", lambda: None)

    return path


def test_confirm_goal_link_schema_requires_task_id_and_action():
    tools = asyncio.run(work_server.handle_list_tools())
    confirm_goal_link = next(tool for tool in tools if tool.name == "confirm_goal_link")

    assert confirm_goal_link.inputSchema["required"] == ["task_id", "action"]
    assert confirm_goal_link.inputSchema["properties"]["task_id"]["pattern"] == r"^task-\d{8}-\d{3}$"
    assert confirm_goal_link.inputSchema["properties"]["action"]["enum"] == ["confirm", "clear"]


def test_confirm_goal_link_confirms_tentative_goal_and_round_trips(tasks_file: Path):
    _write_task(
        tasks_file,
        f"Pillar: Test Pillar | Priority: P1 | Goal: {GOAL_ID} (?)",
    )

    result = _call_tool("confirm_goal_link", {"task_id": TASK_ID, "action": "confirm"})

    assert result == {
        "success": True,
        "task_id": TASK_ID,
        "action": "confirm",
        "goal_id": GOAL_ID,
        "goal_tentative": False,
    }
    assert f"Goal: {GOAL_ID} (?)" not in tasks_file.read_text(encoding="utf-8")

    task = _parsed_task(tasks_file)
    assert task["goal"] == GOAL_ID
    assert task["goal_tentative"] is False


def test_confirm_goal_link_clears_tentative_goal_and_round_trips(tasks_file: Path):
    _write_task(
        tasks_file,
        f"Pillar: Test Pillar | Priority: P1 | Goal: {GOAL_ID} (?)",
    )

    result = _call_tool("confirm_goal_link", {"task_id": TASK_ID, "action": "clear"})

    assert result == {
        "success": True,
        "task_id": TASK_ID,
        "action": "clear",
        "goal_id": GOAL_ID,
    }
    assert "Goal:" not in tasks_file.read_text(encoding="utf-8")

    task = _parsed_task(tasks_file)
    assert task["goal"] is None
    assert task["goal_tentative"] is False


def test_confirm_goal_link_rejects_unknown_task_without_writing(tasks_file: Path):
    _write_task(
        tasks_file,
        f"Pillar: Test Pillar | Priority: P1 | Goal: {GOAL_ID} (?)",
    )
    before = tasks_file.read_text(encoding="utf-8")

    result = _call_tool(
        "confirm_goal_link",
        {"task_id": "task-20260712-999", "action": "confirm"},
    )

    assert result == {"success": False, "error": "task not found"}
    assert tasks_file.read_text(encoding="utf-8") == before


def test_confirm_goal_link_rejects_task_without_goal_without_writing(tasks_file: Path):
    _write_task(tasks_file, "Pillar: Test Pillar | Priority: P1 | Due: 2026-07-18")
    before = tasks_file.read_text(encoding="utf-8")

    result = _call_tool("confirm_goal_link", {"task_id": TASK_ID, "action": "confirm"})

    assert result == {"success": False, "error": "no goal link on this task"}
    assert tasks_file.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    ("action", "error"),
    [
        ("confirm", "goal link is already confirmed"),
        ("clear", "goal link is confirmed; edit explicitly if you want to remove it"),
    ],
)
def test_confirm_goal_link_rejects_confirmed_goal_without_writing(
    tasks_file: Path,
    action: str,
    error: str,
):
    _write_task(
        tasks_file,
        f"Pillar: Test Pillar | Priority: P1 | Goal: {GOAL_ID}",
    )
    before = tasks_file.read_text(encoding="utf-8")

    result = _call_tool("confirm_goal_link", {"task_id": TASK_ID, "action": action})

    assert result == {"success": False, "error": error}
    assert tasks_file.read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    ("action", "expected_metadata", "expected_goal"),
    [
        (
            "confirm",
            f"Pillar: Test Pillar | Priority: P1 | Due: 2026-07-18 | Goal: {GOAL_ID} | "
            "Project: 04-Projects/Review.md",
            GOAL_ID,
        ),
        (
            "clear",
            "Pillar: Test Pillar | Priority: P1 | Due: 2026-07-18 | Project: 04-Projects/Review.md",
            None,
        ),
    ],
)
def test_confirm_goal_link_keeps_midline_metadata_separators_valid(
    tasks_file: Path,
    action: str,
    expected_metadata: str,
    expected_goal: str | None,
):
    _write_task(
        tasks_file,
        f"Pillar: Test Pillar | Priority: P1 | Due: 2026-07-18 | Goal: {GOAL_ID} (?) | "
        "Project: 04-Projects/Review.md",
    )

    result = _call_tool("confirm_goal_link", {"task_id": TASK_ID, "action": action})

    assert result["success"] is True
    assert result["goal_id"] == GOAL_ID
    assert f"\t- {expected_metadata}\n" in tasks_file.read_text(encoding="utf-8")
    assert "||" not in tasks_file.read_text(encoding="utf-8")
    assert " | \n" not in tasks_file.read_text(encoding="utf-8")

    task = _parsed_task(tasks_file)
    assert task["due"] == "2026-07-18"
    assert task["project"] == "04-Projects/Review.md"
    assert task["goal"] == expected_goal
    assert task["goal_tentative"] is False
