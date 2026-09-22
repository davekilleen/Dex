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


def test_daily_plan_probes_only_apple_mail_health_not_the_whole_deep_checkup() -> None:
    """The morning plan asks Doctor one question, not for every live probe.

    A full ``--deep`` run before the email step ran smoke journeys, the search
    index, and every connected tool each morning. The plan needs one answer:
    is Apple Mail search usable. Google Workspace carries its own status.
    """
    for path in EMAIL_INSTRUCTION_PATHS:
        text = path.read_text(encoding="utf-8")
        contract = " ".join(text.split())
        assert "python3 core/utils/doctor.py --deep --only mail.apple-search" in contract, path
        assert "python3 core/utils/doctor.py --deep`" not in contract, path
        assert "Google Workspace needs no local probe" in contract, path
