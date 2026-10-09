"""Daily-plan must not call the organiser someone who has not accepted."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DAILY_PLAN = ROOT / ".claude" / "skills" / "daily-plan"
INSTRUCTION_PATHS = (
    DAILY_PLAN / "SKILL.md",
    DAILY_PLAN / "AGENT_INSTRUCTIONS.md",
    ROOT / ".claude" / "skills" / "meeting-prep" / "SKILL.md",
)


def test_daily_plan_and_meeting_prep_never_flag_the_organiser() -> None:
    for path in INSTRUCTION_PATHS:
        text = path.read_text(encoding="utf-8")
        contract = " ".join(text.split())
        assert "has not accepted" in contract, path
        assert "organiser" in contract, path
        assert "is_organizer" in contract, path
