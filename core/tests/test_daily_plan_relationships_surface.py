from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude" / "skills" / "daily-plan" / "SKILL.md"


def test_daily_plan_has_one_confirm_gated_relationships_nudge() -> None:
    text = SKILL.read_text(encoding="utf-8")

    assert "System/.dex/entity-relationships.json" in text
    assert "present and fresh" in text
    assert "degrade silently" in text
    assert "relationship-radar" in text
    assert text.count("{{🔗 Relationships to confirm:") == 1
