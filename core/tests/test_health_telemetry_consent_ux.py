"""Instruction contracts for the separate health-telemetry consent UX."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT = (
    "Want to help catch bad releases early? Dex can send anonymous nightly health counts — "
    "no names, notes, or file contents, ever. Share them? (y/N)"
)


def test_usage_log_defaults_health_telemetry_to_pending() -> None:
    usage_log = (REPO_ROOT / "System" / "usage_log.md").read_text(encoding="utf-8")

    assert "## Health Telemetry Consent" in usage_log
    assert "**Health telemetry:** pending" in usage_log
    assert "missing or pending means nothing is sent" in usage_log


def test_dex_doctor_offers_health_telemetry_once_with_default_no() -> None:
    doctor_skill = (REPO_ROOT / ".claude" / "skills" / "dex-doctor" / "SKILL.md").read_text(encoding="utf-8")

    assert PROMPT in doctor_skill
    assert "only when `**Health telemetry:** pending` or the line is missing" in doctor_skill
    assert "record `**Health telemetry:** opted-out`" in doctor_skill
    assert "Never read or change the separate analytics consent" in doctor_skill


def test_claude_instructions_wire_independent_natural_language_choices() -> None:
    instructions = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    health_block = instructions.split("### Health Telemetry Opt-In/Out (Anytime)", 1)[1].split("### Skill Rating", 1)[0]

    assert '"Share anonymous nightly health counts"' in health_block
    assert '"Turn off health telemetry"' in health_block
    assert "`**Health telemetry:** opted-in`" in health_block
    assert "`**Health telemetry:** opted-out`" in health_block
    assert "Do not change analytics consent" in health_block
