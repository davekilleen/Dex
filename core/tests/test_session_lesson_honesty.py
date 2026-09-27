"""DEX-121: lesson capture must match what CLAUDE.md promises.

The alert-counter half (pending-learning reminder) is already automatic.
This contract keeps the extraction half honest: session-end actually writes
candidate lessons, and the shipped instructions no longer claim that
/daily-review is the only way they appear.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
SESSION_END = REPO_ROOT / ".claude" / "hooks" / "session-end.sh"
EXTRACTOR = REPO_ROOT / "core" / "utils" / "session_lesson_extract.py"
LEARNING_CAPTURE_TEST = REPO_ROOT / "core" / "tests" / "test_learning_capture_command_name.py"


def test_session_end_invokes_the_extractor() -> None:
    text = SESSION_END.read_text(encoding="utf-8")
    assert "session_lesson_extract.py" in text
    assert EXTRACTOR.is_file()
    assert "Learning EXTRACTION happens in /daily-review" not in text


def test_background_self_learning_names_session_close_and_daily_review() -> None:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    section = text.split("### Background Self-Learning Automation", 1)[1]
    section = section.split("### ", 1)[0]
    lowered = section.lower()
    assert "session" in lowered and "pending" in lowered
    assert "/daily-review" in section
    assert "does not invent lessons" in lowered or "confirm" in lowered


def test_learning_capture_section_still_names_daily_review() -> None:
    # The dedicated command-name guard stays the source of truth; this just
    # makes the pairing visible next to the session-end contract.
    assert LEARNING_CAPTURE_TEST.is_file()
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert "### Learning Capture via `/daily-review`" in text
