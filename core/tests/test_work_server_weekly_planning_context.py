"""Weekly planning context must survive a hand-written goal with no hidden ID.

A quarterly goal typed by hand has no `^Qx-YYYY-goal-N` anchor, so the parser
yields `goal_id=None`. Weekly planning context has to keep working, must not
claim priorities or backlog tasks that belong to nobody, and must say plainly
which goal needs an ID.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.mcp import work_server

TEST_PILLARS = {
    "pillar_1": {
        "name": "Growth",
        "description": "Neutral test work",
        "keywords": ["growth"],
    },
}

ANCHORLESS_TITLE = "Hand written goal without an anchor"
ANCHORED_ID = "Q3-2026-goal-1"


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    result = asyncio.run(work_server.handle_call_tool(name, arguments or {}))
    return json.loads(result[0].text)


@pytest.fixture
def planning_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    tasks_file = tmp_path / "03-Tasks" / "Tasks.md"
    priorities_file = tmp_path / "02-Week_Priorities" / "Week_Priorities.md"
    goals_file = tmp_path / "01-Quarter_Goals" / "Quarter_Goals.md"
    for path in (tasks_file, priorities_file, goals_file):
        path.parent.mkdir(parents=True, exist_ok=True)

    tasks_file.write_text("# Tasks\n\n## Next Week\n", encoding="utf-8")

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: priorities_file)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals_file)
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *a, **k: None)
    monkeypatch.setattr(work_server, "refresh_search_index", lambda: None)

    return {"tasks": tasks_file, "priorities": priorities_file, "goals": goals_file}


def _write_goals(goals_file: Path, *, with_anchored: bool = True) -> None:
    anchored = (
        f"### 1. Ship the launch — **Growth** ^{ANCHORED_ID}\n\n"
        "**What success looks like:**\nLaunch is out.\n\n"
        "- [ ] Draft the launch plan\n\n"
        if with_anchored
        else ""
    )
    goals_file.write_text(
        "# Quarter Goals\n\n"
        f"{anchored}"
        f"### 2. {ANCHORLESS_TITLE} — **Growth**\n\n"
        "**What success looks like:**\nSomething good happens.\n\n"
        "- [ ] Write the first milestone\n",
        encoding="utf-8",
    )


def _write_priorities(priorities_file: Path) -> None:
    priorities_file.write_text(
        "# Week Priorities\n\n"
        f"1. **Ship the launch** — Growth (Goal: {ANCHORED_ID}) ^week-2026-W37-p1\n"
        "2. **Unrelated operational work** — Growth ^week-2026-W37-p2\n",
        encoding="utf-8",
    )


def test_goal_without_id_does_not_crash_weekly_planning_context(planning_vault):
    """The reported failure: TypeError instead of usable planning context."""
    _write_goals(planning_vault["goals"])
    _write_priorities(planning_vault["priorities"])

    result = _call_tool("get_weekly_planning_context")

    titles = [goal["title"] for goal in result["goal_health"]]
    assert ANCHORLESS_TITLE in titles
    anchorless = next(g for g in result["goal_health"] if g["title"] == ANCHORLESS_TITLE)
    assert anchorless["goal_id"] is None
    assert anchorless["linked_priority_count"] == 0


def test_goal_without_id_is_not_reported_as_neglected(planning_vault):
    """An unknowable link is not evidence of zero weekly activity."""
    _write_goals(planning_vault["goals"])
    _write_priorities(planning_vault["priorities"])

    result = _call_tool("get_weekly_planning_context")

    anchorless = next(g for g in result["goal_health"] if g["title"] == ANCHORLESS_TITLE)
    assert anchorless["activity_known"] is False
    # The anchored goal has a real linked priority, so nothing is neglected.
    assert result["neglected_goals_count"] == 0
    assert all("Goal None" not in rec for rec in result["recommendations"])
    assert all(
        s["from_goal"] is not None
        for s in (result["suggested_priorities_from_goals"] or [])
    )


def test_goal_without_id_is_named_with_the_fix(planning_vault):
    """The user is told which goal needs which anchor, and where to add it."""
    _write_goals(planning_vault["goals"])
    _write_priorities(planning_vault["priorities"])

    result = _call_tool("get_weekly_planning_context")

    text = " ".join(result["recommendations"])
    assert ANCHORLESS_TITLE in text
    assert "^Qx-YYYY-goal-N" in text
    assert "Quarter_Goals.md" in text


def test_goal_without_id_does_not_absorb_unlinked_backlog_tasks(planning_vault):
    """Open tasks with no goal belong to no goal, not to the anchorless one."""
    planning_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Unlinked backlog work ^task-20260903-001\n"
        "\t- Pillar: Growth | Priority: P1\n"
        "- [ ] Linked backlog work ^task-20260903-002\n"
        f"\t- Pillar: Growth | Priority: P1 | Goal: {ANCHORED_ID}\n",
        encoding="utf-8",
    )
    _write_goals(planning_vault["goals"])
    _write_priorities(planning_vault["priorities"])

    result = _call_tool("get_weekly_planning_context")

    anchorless = next(g for g in result["goal_health"] if g["title"] == ANCHORLESS_TITLE)
    assert anchorless["open_task_count"] == 0
    assert anchorless["next_up_tasks"] == []
    # The real link still lands on the goal that actually owns it.
    anchored = next(g for g in result["goal_health"] if g["goal_id"] == ANCHORED_ID)
    assert anchored["open_task_count"] == 1


def test_anchored_goals_keep_their_linked_priorities(planning_vault):
    """The guard must not cost healthy goals their real linked context."""
    _write_goals(planning_vault["goals"])
    _write_priorities(planning_vault["priorities"])

    result = _call_tool("get_weekly_planning_context")

    anchored = next(g for g in result["goal_health"] if g["goal_id"] == ANCHORED_ID)
    assert anchored["linked_priority_count"] == 1
    assert anchored["has_activity"] is True


def test_goal_without_id_is_never_offered_as_a_priority_link(planning_vault):
    """Suggesting a link that create_weekly_priority would refuse helps nobody."""
    _write_goals(planning_vault["goals"], with_anchored=False)
    _write_priorities(planning_vault["priorities"])

    result = _call_tool(
        "get_weekly_planning_context",
        {"proposed_priorities": [{"title": ANCHORLESS_TITLE, "pillar": "Growth"}]},
    )

    matched = result["matched_priorities"][0]
    # Even an exact title match against the ID-less goal yields no link.
    assert matched["inferred_goal"] is None
    assert matched["is_operational"] is True
    assert matched["alternatives"] == []


def test_anchored_goals_are_still_inferred_normally(planning_vault):
    """The guard must not cost healthy goals their priority matching."""
    _write_goals(planning_vault["goals"])
    _write_priorities(planning_vault["priorities"])

    result = _call_tool(
        "get_weekly_planning_context",
        {"proposed_priorities": [{"title": "Ship the launch", "pillar": "Growth"}]},
    )

    matched = result["matched_priorities"][0]
    assert matched["inferred_goal"]["goal_id"] == ANCHORED_ID
    assert all(alt["goal_id"] is not None for alt in matched["alternatives"])
