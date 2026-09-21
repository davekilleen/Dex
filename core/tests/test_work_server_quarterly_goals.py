"""Behavioral coverage for quarterly-goal reads through the Work MCP."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.mcp import work_server


def _get_quarterly_goals() -> dict:
    result = asyncio.run(work_server.handle_call_tool("get_quarterly_goals", {}))
    return json.loads(result[0].text)


def _use_goals_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goals_text: str
) -> None:
    goals_file = tmp_path / "01-Quarter_Goals/Quarter_Goals.md"
    goals_file.parent.mkdir(parents=True)
    goals_file.write_text(goals_text, encoding="utf-8")
    profile = tmp_path / "System/user-profile.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        "capabilities:\n  quarter_goals:\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals_file)
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)


# Headings at every level, every kind of divider, and a labelled list.
# "## " and "---" were the first boundaries; the others still leaked.
TRAILING_SECTION_BOUNDARIES = [
    "## Carried From Last Quarter",
    "## 🔄 Carried From Last Quarter",
    "# Notes",
    "#### Notes",
    "---",
    "----",
    "--------",
    "***",
    "___",
    "- - -",
    "**Carried from last quarter:**",
]


@pytest.mark.parametrize("boundary", TRAILING_SECTION_BOUNDARIES)
def test_get_quarterly_goals_excludes_checklists_after_goal_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    _use_goals_file(
        tmp_path,
        monkeypatch,
        "# Q4 2026 Goals\n\n"
        "### 1. Make planning trustworthy — **Product** ^Q4-2026-goal-1\n\n"
        "**Key milestones:**\n"
        "- [x] This milestone belongs to the goal\n\n"
        f"{boundary}\n\n"
        "- [ ] This is unrelated carried work\n",
    )

    payload = _get_quarterly_goals()

    assert payload["goals"][0]["milestones"] == [
        {"title": "This milestone belongs to the goal", "completed": True}
    ]


def test_milestone_list_keeps_boxes_around_progress_and_drops_a_later_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Progress is part of the goal. A labelled list after it is not."""
    _use_goals_file(
        tmp_path,
        monkeypatch,
        "### 1. First goal — **Product** ^Q4-2026-goal-1\n\n"
        "**Key milestones:**\n"
        "- [x] First milestone\n\n"
        "### 2. Last goal — **Product** ^Q4-2026-goal-2\n\n"
        "- [ ] First milestone of the last goal\n\n"
        "**Progress:** 5%\n\n"
        "- [x] Second milestone still part of the goal\n\n"
        "**important**\n\n"
        "- [ ] Emphasis between milestones is not a new section\n\n"
        "**Carried from last quarter:**\n"
        "- [x] This is unrelated carried work\n\n"
        "# Notes\n"
        "- [ ] Also unrelated\n",
    )

    payload = _get_quarterly_goals()
    goals = payload["goals"]

    assert [goal["title"] for goal in goals] == ["First goal", "Last goal"]
    assert goals[0]["milestones"] == [
        {"title": "First milestone", "completed": True}
    ]
    assert goals[1]["progress"] == 5
    assert goals[1]["milestones"] == [
        {"title": "First milestone of the last goal", "completed": False},
        {"title": "Second milestone still part of the goal", "completed": True},
        {"title": "Emphasis between milestones is not a new section", "completed": False},
    ]
