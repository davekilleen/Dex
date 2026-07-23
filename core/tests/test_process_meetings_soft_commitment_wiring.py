"""Tests for deterministic soft-commitment meeting processing instructions."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / ".claude" / "skills" / "process-meetings" / "SKILL.md"


def test_process_meetings_wires_detector_into_confirmation_flow() -> None:
    source = SKILL.read_text(encoding="utf-8").casefold()

    assert "detect_soft_commitments" in source
    assert "soft commitment — confirm before creating" in source
    assert "never auto-create" in source
