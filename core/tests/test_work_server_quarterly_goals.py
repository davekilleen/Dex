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


@pytest.mark.parametrize("boundary", ["## Carried From Last Quarter", "---"])
def test_get_quarterly_goals_excludes_checklists_after_goal_section(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    goals_file = tmp_path / "01-Quarter_Goals/Quarter_Goals.md"
    goals_file.parent.mkdir(parents=True)
    goals_file.write_text(
        "# Q4 2026 Goals\n\n"
        "### 1. Make planning trustworthy — **Product** ^Q4-2026-goal-1\n\n"
        "**Key milestones:**\n"
        "- [x] This milestone belongs to the goal\n\n"
        f"{boundary}\n\n"
        "- [ ] This is unrelated carried work\n",
        encoding="utf-8",
    )
    profile = tmp_path / "System/user-profile.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        "capabilities:\n  quarter_goals:\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals_file)
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)

    payload = _get_quarterly_goals()

    assert payload["goals"][0]["milestones"] == [
        {"title": "This milestone belongs to the goal", "completed": True}
    ]
