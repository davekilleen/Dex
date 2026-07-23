"""Contract test for the Soft Commitment Capture behavior in CLAUDE.md.

Task capture must catch soft commitments made in ordinary conversation
("I'll follow up", "let me get back to you", "we should revisit") — not just
explicit "create a task" requests — and surface them for confirmation, never
auto-creating. This behavior complements (does not duplicate) /commitments
(reconciliation across meetings) and /meeting-closeout (one finished meeting).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = ROOT / "CLAUDE.md"


def _section() -> str:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    marker = "### Soft Commitment Capture"
    assert marker in text, "Soft Commitment Capture behavior missing from CLAUDE.md"
    start = text.index(marker)
    # Section runs until the next top-level behavior heading.
    rest = text[start + len(marker):]
    end = rest.find("\n### ")
    return (marker + rest[: end if end != -1 else len(rest)])


def test_behavior_section_exists() -> None:
    assert "### Soft Commitment Capture" in CLAUDE_MD.read_text(encoding="utf-8")


def test_detects_soft_promise_phrasing_not_just_explicit_requests() -> None:
    section = _section().lower()
    # At least the canonical soft-promise cues.
    assert "i'll follow up" in section
    assert "get back to" in section
    assert "revisit" in section


def test_offers_but_never_auto_creates() -> None:
    section = _section().lower()
    assert "never auto-create" in section
    assert "confirm-before-create" in section
    # Reads back what it captured (no false "done").
    assert "read back the task id" in section


def test_does_not_nag() -> None:
    section = _section().lower()
    assert "offer once" in section and "don't nag" in section


def test_complements_commitments_and_meeting_closeout_rather_than_duplicating() -> None:
    section = _section()
    assert "/commitments" in section
    assert "/meeting-closeout" in section
    # Explicitly does not re-scan the vault (that is /commitments' job).
    assert "Don't re-scan the vault here" in section
