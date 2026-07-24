"""Guard for the product CLAUDE.md 'Learning Capture' command name.

Part of the /review -> /daily-review retirement: the "Learning Capture" behavior
section in the shipped CLAUDE.md must name the canonical /daily-review command, not
the retired /review. This is the one product-CLAUDE.md repoint, split into its own PR
so it can be reviewed separately.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = ROOT / "CLAUDE.md"


def test_learning_capture_section_names_daily_review() -> None:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert "### Learning Capture via `/daily-review`" in text
    assert "### Learning Capture via `/review`" not in text


def test_no_bare_review_command_in_learning_capture_body() -> None:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    # The learning-capture behavior body should reference /daily-review, not the retired
    # /review command. (Other "review" words like "daily review process" are fine.)
    assert "When the user runs `/daily-review`" in text
    assert "When the user runs `/review`" not in text
