"""Regression coverage for weekly-priority file writes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.mcp import work_server

WEEK_DATE = "2026-07-13"
TOP_3 = "## 🎯 Top 3 This Week"
PILLARS = {
    "customer": {
        "name": "Customer Growth",
        "description": "Customer outcomes",
        "keywords": ["customer"],
    }
}


def _call_create_priority(**overrides) -> dict:
    arguments = {
        "title": "Publish customer renewal playbook",
        "pillar": "customer",
        "week_date": WEEK_DATE,
        **overrides,
    }
    result = asyncio.run(
        work_server.handle_call_tool("create_weekly_priority", arguments)
    )
    return json.loads(result[0].text)


@pytest.fixture
def priority_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "02-Week_Priorities" / "Week_Priorities.md"
    path.parent.mkdir(parents=True)
    goals = tmp_path / "01-Quarter_Goals" / "Quarter_Goals.md"

    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: path)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals)
    monkeypatch.setattr(work_server, "PILLARS", PILLARS)
    return path


def test_create_weekly_priority_fills_empty_section_without_losing_following_content(
    priority_file: Path,
):
    before = (
        "# Week Priorities\n\n"
        "**Week of:** 2026-07-13\n\n"
        "---\n\n"
        f"{TOP_3}\n\n"
        "## 📋 Supporting Tasks\n\n"
        "- [ ] Preserve this task exactly\n\n"
        "## 📝 Notes\n\n"
        "This text must survive the splice.\n"
    )
    priority_file.write_text(before, encoding="utf-8")

    result = _call_create_priority(success_criteria="Playbook is shared with Sales")

    assert result["success"] is True
    assert result["linked_goal"] is None
    assert priority_file.read_text(encoding="utf-8") == (
        "# Week Priorities\n\n"
        "**Week of:** 2026-07-13\n\n"
        "---\n\n"
        f"{TOP_3}\n\n"
        "1. Publish customer renewal playbook — **Customer Growth** "
        "^week-2026-W29-p1\n"
        "   - Success criteria: Playbook is shared with Sales\n\n\n"
        "## 📋 Supporting Tasks\n\n"
        "- [ ] Preserve this task exactly\n\n"
        "## 📝 Notes\n\n"
        "This text must survive the splice.\n"
    )


def test_create_weekly_priority_writes_explicit_goal_link_without_mangling_headings(
    priority_file: Path,
):
    priority_file.write_text(
        "# Week Priorities\n\n"
        f"{TOP_3}\n\n"
        "## 📊 Review\n\n"
        "Review notes stay here.\n",
        encoding="utf-8",
    )

    result = _call_create_priority(quarterly_goal_id="Q3-2026-goal-2")

    assert result["linked_goal"] == "Q3-2026-goal-2"
    content = priority_file.read_text(encoding="utf-8")
    assert content == (
        "# Week Priorities\n\n"
        f"{TOP_3}\n\n"
        "1. Publish customer renewal playbook — **Customer Growth** "
        "^week-2026-W29-p1\n"
        "   - Quarterly goal: [Q3-2026-goal-2]\n\n\n"
        "## 📊 Review\n\n"
        "Review notes stay here.\n"
    )
    assert content.count(TOP_3) == 1
    assert content.count("## 📊 Review") == 1


@pytest.mark.parametrize("existing_count", [1, 2])
@pytest.mark.xfail(
    reason=(
        "BUG: create_weekly_priority inserts a newly numbered priority before "
        "existing priorities, leaving Top 3 out of numeric order"
    ),
    strict=False,
)
def test_create_weekly_priority_appends_after_existing_priorities_in_number_order(
    priority_file: Path,
    existing_count: int,
):
    existing = "".join(
        f"{number}. Existing priority {number} — **Customer Growth** "
        f"^week-2026-W29-p{number}\n"
        for number in range(1, existing_count + 1)
    )
    priority_file.write_text(
        "# Week Priorities\n\n"
        f"{TOP_3}\n\n"
        f"{existing}\n"
        "## 📊 Review\n\n"
        "Tail sentinel.\n",
        encoding="utf-8",
    )

    result = _call_create_priority()

    assert result["success"] is True
    new_number = existing_count + 1
    assert priority_file.read_text(encoding="utf-8") == (
        "# Week Priorities\n\n"
        f"{TOP_3}\n\n"
        f"{existing}"
        f"{new_number}. Publish customer renewal playbook — **Customer Growth** "
        f"^week-2026-W29-p{new_number}\n\n"
        "## 📊 Review\n\n"
        "Tail sentinel.\n"
    )


@pytest.mark.xfail(
    reason=(
        "BUG: create_weekly_priority accepts a fourth Top-3 item and writes a "
        "second priority numbered 3"
    ),
    strict=False,
)
def test_create_weekly_priority_rejects_fourth_item_without_changing_file(
    priority_file: Path,
):
    before = (
        "# Week Priorities\n\n"
        f"{TOP_3}\n\n"
        "1. First priority — **Customer Growth** ^week-2026-W29-p1\n"
        "2. Second priority — **Customer Growth** ^week-2026-W29-p2\n"
        "3. Third priority — **Customer Growth** ^week-2026-W29-p3\n\n"
        "## 📊 Review\n\n"
        "Tail sentinel.\n"
    )
    priority_file.write_text(before, encoding="utf-8")

    result = _call_create_priority()

    assert result["success"] is False
    assert "top 3" in result["error"].lower()
    assert priority_file.read_text(encoding="utf-8") == before
