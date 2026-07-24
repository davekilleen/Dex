"""Contract tests for the /commitments skill.

The skill is a thin present -> confirm -> create layer over the EXISTING
Work-MCP `get_commitments_due` scanner. These tests lock the load-bearing
promises: it composes the existing tool (does not rebuild the data layer),
never auto-creates tasks, degrades honestly, and routes cleanly against its
nearest neighbors.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude/skills/commitments/SKILL.md"
EVALS = ROOT / ".claude/skills/commitments/evals/trigger-cases.yaml"


def _frontmatter_description() -> str:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    fm = text.split("---\n", 2)[1]
    for line in fm.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("no description in frontmatter")


def test_commitments_skill_exists_with_evals() -> None:
    assert SKILL.is_file()
    assert EVALS.is_file()


def test_description_is_a_router_with_when_and_anti_triggers() -> None:
    desc = _frontmatter_description().lower()
    # WHEN trigger with real user phrasing.
    assert "when the user says" in desc
    # Anti-triggers naming the true nearest neighbors.
    assert "delegate-check" in desc
    assert "decision-log" in desc


def test_body_composes_existing_scanner_and_does_not_rebuild_it() -> None:
    text = SKILL.read_text(encoding="utf-8")
    # Uses the existing Work-MCP tool by name...
    assert "get_commitments_due" in text
    # ...and explicitly refuses to rebuild the data layer.
    assert "do not rebuild the data layer" in text.lower()


def test_confirm_before_create_hard_gate_is_present() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    # No task write without per-item authority, and it precedes the create step.
    assert "confirm before creating" in text
    assert "never auto-create" in text
    confirm = text.index("confirm before creating")
    create = text.index("create, then inspect")
    assert confirm < create


def test_degrades_honestly_without_fabricating() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    # Tool unavailable -> stop, never invent a list.
    assert "never fabricate" in text or "do not fabricate" in text
    # ScreenPipe enrichment is optional and silent, never a dependency.
    assert "screenpipe" in text
    assert "must never depend on the beta" in text


def test_inspects_output_before_claiming_done() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "read back what was created" in text
    assert "task id" in text


@pytest.mark.parametrize(
    "needle",
    ["positive:", "negative:", "ambiguous:", "missing_prerequisite:", "failure_recovery:"],
)
def test_evals_carry_the_canonical_case_buckets(needle: str) -> None:
    text = EVALS.read_text(encoding="utf-8")
    assert needle in text
