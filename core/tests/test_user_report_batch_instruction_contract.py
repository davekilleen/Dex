"""Instruction contracts for the user-report batch (settings, capture, review, setup)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_proactive_capture_only_reads_the_current_message_and_skips_morning_plan() -> None:
    claude = _read("CLAUDE.md")
    section = claude.split("### Proactive Improvement Capture", 1)[1]
    section = section.split("### ", 1)[0]
    lowered = section.lower()

    assert "only read the current user message" in lowered
    assert "never capture ideas while running `/daily-plan`" in lowered
    assert "chat history" in lowered or "earlier turns" in lowered

    daily_plan = _read(".claude/skills/daily-plan/SKILL.md")
    agent = _read(".claude/skills/daily-plan/AGENT_INSTRUCTIONS.md")
    assert "Do not harvest improvement ideas during this skill" in daily_plan
    assert "morning plan must not" in daily_plan
    assert "Do not harvest improvement ideas" in agent
    assert "capture_idea" not in daily_plan
    assert "capture_idea" not in agent


def test_daily_review_treats_cancelled_and_moved_meetings_as_not_missed() -> None:
    skill = _read(".claude/skills/daily-review/SKILL.md")
    agent = _read(".claude/skills/daily-review/AGENT_INSTRUCTIONS.md")
    combined = skill + "\n" + agent
    lowered = combined.lower()

    assert "cancelled" in lowered or "canceled" in lowered
    assert "rescheduled" in lowered
    assert "not missed" in lowered or "not missing" in lowered
    assert "verify each" in lowered and "date" in lowered


def test_onboarding_tells_the_user_to_start_a_new_chat_so_tools_load() -> None:
    flow = _read("core/onboarding/FLOW.md")
    bridge = _read(".claude/flows/onboarding.md")
    server = _read("core/mcp/onboarding_server.py")

    assert flow == bridge
    assert "Start a new chat now so Dex can load your tools" in flow
    assert "this same chat will fail until you do" in flow
    assert "All done! Start a new chat now so Dex can load your tools" in flow
    assert "Start a new chat now so Dex can load your tools" in server
