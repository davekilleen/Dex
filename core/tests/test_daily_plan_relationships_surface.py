from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "daily-plan" / "SKILL.md"
AGENT = ROOT / ".claude" / "skills" / "daily-plan" / "AGENT_INSTRUCTIONS.md"


def test_daily_plan_has_one_confirm_gated_relationships_nudge() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "System/.dex/entity-relationships.json" in text
    assert "present and fresh" in text
    assert "degrade silently" in text
    assert "confirm_relationship" in text
    assert "dismiss_relationship" in text
    assert "relationship-radar" not in text
    assert text.count("{{🔗 Relationships to confirm:") == 1


def test_daily_plan_delegated_prompt_includes_previous_working_day_notes() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    agent = AGENT.read_text(encoding="utf-8")
    phase_1 = agent.split("## Phase 1:", 1)[1].split("## Phase 2:", 1)[0]
    report = agent.split("## Final Output", 1)[1]

    for text in (skill, agent, phase_1):
        assert "previous-working-day notes" in text
        assert "working_week.days" in text
        assert "strictly before" in text
        assert "Do not skip this step silently" in text
        assert "lookup_person" in text
        assert "none for that named date" in text
        assert "Recent Interactions" in text
        assert "Do not create person pages" in text

    assert "Previous-working-day notes: [found YYYY-MM-DD `path`, or none for YYYY-MM-DD]" in report
    assert "{{Previous-working-day notes: found YYYY-MM-DD `path` / none for YYYY-MM-DD}}" in skill
    assert "Use `AGENT_INSTRUCTIONS.md` verbatim" in skill
