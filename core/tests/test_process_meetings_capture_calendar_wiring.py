"""The capture/calendar matcher is wired only where both inputs exist."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESS = ROOT / ".claude/skills/process-meetings/AGENT_INSTRUCTIONS.md"
DAILY = ROOT / ".claude/skills/daily-review/AGENT_INSTRUCTIONS.md"
PREP = ROOT / ".claude/skills/meeting-prep/AGENT_INSTRUCTIONS.md"
CODEX_PROCESS = ROOT / ".agents/skills/process-meetings/SKILL.md"


def test_process_meetings_calls_calendar_and_deterministic_matcher() -> None:
    text = PROCESS.read_text(encoding="utf-8")

    assert "capture_started_at" in text
    assert "calendar_get_events_with_attendees" in text
    assert "match_capture_to_calendar" in text
    assert "Calendar response confidence contract" in text
    assert "`events` array" in text
    assert "identity only" in text.casefold()
    assert "join URLs" in text


def test_non_owning_consumers_do_not_duplicate_match_policy() -> None:
    for path in (DAILY, PREP):
        text = path.read_text(encoding="utf-8")
        assert "## Matching a capture to a calendar event" not in text
        assert "match_capture_to_calendar" not in text


def test_codex_adapter_calls_the_same_matcher_with_identity_only() -> None:
    text = CODEX_PROCESS.read_text(encoding="utf-8")

    assert "capture_started_at" in text
    assert "calendar_get_events_with_attendees" in text
    assert "match_capture_to_calendar" in text
    assert "Calendar response confidence contract" in text
    assert "`events` array" in text
    assert "identity only" in text.casefold()
    assert "join URLs" in text
