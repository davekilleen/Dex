"""Goal anchors written with a fiscal quarter are read, not silently dropped.

Field report (2026-09-21): a vault running a fiscal year wrote its goal anchors
as ^FY27-Q2-goal-1. The anchor pattern accepted only the calendar form
(^Q3-2026-goal-1), so parse_quarterly_goals returned goal_id None for every
goal. Nothing errored. get_weekly_planning_context then reported
activity_known False, null linked-priority and open-task counts, and
recommended adding IDs that were already present on the heading line. Goal
tracking had been dead for the life of the vault.

The module already supports fiscal quarters for date windows
(_fiscal_quarter_window), so only the anchor pattern was calendar-only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.mcp import work_server

CALENDAR = "Q3-2026-goal-1"
FISCAL = "FY27-Q2-goal-1"


@pytest.mark.parametrize("goal_id", [CALENDAR, FISCAL, "FY2027-Q4-goal-12"])
def test_extract_goal_id_reads_both_quarter_shapes(goal_id: str) -> None:
    assert work_server.extract_goal_id(f"^{goal_id}") == goal_id


@pytest.mark.parametrize(
    "anchor",
    [
        "^FYX-Q2-goal-1",   # no fiscal year digits
        "^Q1-26-goal-1",    # two-digit calendar year
        "^goal-1",          # no quarter at all
        "^FY27-Q2-goal-",   # no goal number
    ],
)
def test_extract_goal_id_still_rejects_malformed_anchors(anchor: str) -> None:
    """A loose pattern would make a broken anchor look linked. It must not."""
    assert work_server.extract_goal_id(anchor) is None


@pytest.mark.parametrize("goal_id", [CALENDAR, FISCAL])
def test_quarterly_goal_heading_yields_its_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal_id: str
) -> None:
    goals = tmp_path / "Quarter_Goals.md"
    goals.write_text(
        "## Q3 2026\n\n"
        f"### 1. Revenue Converts — **deliver** ^{goal_id}\n\n"
        "**Success criteria:** bill the signed work\n\n"
        "**Key milestones:**\n"
        "- [ ] First invoice raised\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)

    parsed = work_server.parse_quarterly_goals(goals)

    assert len(parsed) == 1
    assert parsed[0]["goal_id"] == goal_id
    assert parsed[0]["pillar"] == "deliver"


@pytest.mark.parametrize("goal_id", [CALENDAR, FISCAL])
def test_career_evidence_scan_reads_the_same_two_shapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, goal_id: str
) -> None:
    """career_server carries its own copy of the goal-heading regex.

    Left calendar-only it would drop the goal ID while work_server kept it, so
    the same goal would be linked in one server and anonymous in the other.
    The goal below is written so it survives the handler's own filters
    (complete, and high impact), which is what makes the ID observable.
    """
    import asyncio
    import json

    from core.mcp import career_server

    goals_dir = tmp_path / "01-Quarter_Goals"
    goals_dir.mkdir(parents=True)
    (goals_dir / "Quarter_Goals.md").write_text(
        f"### 1. Revenue Converts — **deliver** ^{goal_id}\n"
        "**Progress:** 100%\n"
        "**Impact level:** high\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(career_server, "BASE_DIR", tmp_path)

    result = asyncio.run(
        career_server.handle_scan_work_for_evidence(
            {"include_goals": True, "include_priorities": False}
        )
    )
    payload = json.loads(result[0].text)

    assert payload["candidates_found"] == 1
    assert payload["evidence_candidates"][0]["goal_id"] == goal_id
