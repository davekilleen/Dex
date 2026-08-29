"""Week-review must name the Tasks.md clear-down as a parent follow-up.

The parent skill already tells Dex to remove whole completed task blocks
after confirming the count. These tests keep that instruction on both
halves of the skill, and keep the delegated gatherer from deleting
``03-Tasks/Tasks.md`` itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEEK_REVIEW_SKILL = REPO_ROOT / ".claude/skills/week-review/SKILL.md"
WEEK_REVIEW_AGENT = REPO_ROOT / ".claude/skills/week-review/AGENT_INSTRUCTIONS.md"
WEEK_REVIEW_FILES = (
    WEEK_REVIEW_SKILL,
    WEEK_REVIEW_AGENT,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", WEEK_REVIEW_FILES, ids=lambda path: path.name)
def test_week_review_names_whole_block_clear_down_and_confirm(path: Path) -> None:
    text = _read(path)
    lowered = text.lower()

    assert "03-Tasks/Tasks.md" in text
    assert "whole task blocks" in lowered
    assert "confirm" in lowered
    assert "per-line" in lowered
    assert "[x]" in text


def test_week_review_agent_names_clear_down_as_parent_interactive_input() -> None:
    text = _read(WEEK_REVIEW_AGENT)
    final_output = text.split("## Final Output", 1)[1]

    assert "Sections needing interactive input" in final_output
    assert "clear completed tasks from 03-Tasks/Tasks.md" in final_output
    assert "parent only" in final_output.lower()
    assert "after confirm" in final_output.lower()


def test_week_review_agent_does_not_instruct_subagent_to_delete_tasks_md() -> None:
    text = _read(WEEK_REVIEW_AGENT)
    lowered = text.lower()

    assert "do not delete or edit `03-tasks/tasks.md`" in lowered
    assert "read only" in lowered
    assert "parent clears completed tasks" in lowered or "parent only" in lowered

    write_verbs = (
        "write `03-tasks/tasks.md`",
        "edit `03-tasks/tasks.md` to remove",
        "clear completed tasks out of `03-tasks/tasks.md`",
        "delete completed tasks from `03-tasks/tasks.md`",
    )
    for phrase in write_verbs:
        assert phrase not in lowered


def test_week_review_skill_says_delegated_summary_names_the_clear_down() -> None:
    text = _read(WEEK_REVIEW_SKILL)

    assert "delegated summary names this step" in text.lower() or (
        "delegated gatherer's structured summary names the Tasks.md clear-down"
        in text
    )
    assert "Do not skip it after a delegated run" in text
