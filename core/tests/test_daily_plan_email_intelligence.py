"""Keep daily-plan email headlines scoped to mail that may need attention."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DAILY_PLAN = ROOT / ".claude" / "skills" / "daily-plan"
EMAIL_INSTRUCTION_PATHS = (
    DAILY_PLAN / "SKILL.md",
    DAILY_PLAN / "AGENT_INSTRUCTIONS.md",
)


def test_daily_plan_headline_unread_count_uses_the_attention_inbox() -> None:
    for path in EMAIL_INSTRUCTION_PATHS:
        text = path.read_text(encoding="utf-8")
        contract = " ".join(text.split())
        assert "never a provider-wide unread total" in contract, path
        assert "`is:unread category:primary`" in contract, path
        assert "unread messages in Inbox mailboxes" in contract, path
        assert "omit the headline unread count" in contract, path

    skill = (DAILY_PLAN / "SKILL.md").read_text(encoding="utf-8")
    assert '"Email: [X] unread in Primary/Inbox' in skill
