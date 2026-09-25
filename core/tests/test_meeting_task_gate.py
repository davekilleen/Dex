"""Meeting action items become tracked tasks only when they carry a when, a who, or urgency.

A user with forty open tasks, twelve of them top priority, traced most of them
back to meeting notes: every "think about X" had become a task. The gate lives
in the process-meetings skill (conversation and delegated helper alike), in its
portable mirrors, and at the source in the Granola analysis prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude/skills/process-meetings/SKILL.md"
HELPER = ROOT / ".claude/skills/process-meetings/AGENT_INSTRUCTIONS.md"
MIRRORS = (
    ROOT / ".agents/skills/process-meetings/SKILL.md",
    ROOT / ".agents/skills/process-meetings/AGENT_INSTRUCTIONS.md",
    ROOT / "packages/dex-agent-plugin/skills/process-meetings/SKILL.md",
    ROOT / "packages/dex-agent-plugin/skills/process-meetings/AGENT_INSTRUCTIONS.md",
)
GRANOLA_SYNC = ROOT / ".scripts/meeting-intel/sync-from-granola.cjs"

GATE_TESTS = ("**It has a when:**", "**It has a who:**", "**It is urgent or blocking:**")


def _flat(path: Path) -> str:
    """The skill text with markdown line-wrapping collapsed, so phrases can be matched whole."""
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", [SKILL, HELPER, *MIRRORS], ids=lambda p: str(p.relative_to(ROOT)))
def test_every_copy_of_the_skill_carries_the_same_gate(path: Path) -> None:
    text = _flat(path)
    assert "Decide whether the item is a task at all" in text
    for gate in GATE_TESTS:
        assert gate in text
    # Ungated items are left alone, surfaced, and never block the marker.
    assert "stay in the meeting note exactly as they are" in text
    assert "Left in the note" in text
    assert "`tasks-extracted` marker still goes on the note" in text


def test_the_gate_runs_before_create_task_in_both_briefs() -> None:
    for path in (SKILL, HELPER):
        text = _flat(path)
        gate = text.index("Decide whether the item is a task at all")
        create = text.index("create_task(", gate)
        assert gate < create, f"{path.name}: the gate must come before the create_task call"


def test_the_summary_reports_what_was_left_untracked() -> None:
    skill = _flat(SKILL)
    helper = _flat(HELPER)
    assert "**Left in the note (not tracked):**" in skill
    assert "**Left in the note (not tracked):**" in helper
    # The helper quotes the exact line so the user can promote it without opening the note.
    assert '- [Meeting title]: "[exact line]"' in helper


def test_granola_analysis_only_writes_real_commitments_as_action_items() -> None:
    text = GRANOLA_SYNC.read_text(encoding="utf-8")
    assert "Only list an action item that someone actually committed to." in text
    assert 'things to "consider" or "think about"' in text
    assert "belong under Key Discussion Points, not here" in text
    assert "[Something this person committed to doing] - by [timeframe if mentioned]" in text
    assert "[Specific task]" not in text
