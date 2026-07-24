"""Contract tests for the /relationship-radar skill.

The skill surfaces relationships going cold using the signal that exists TODAY
(person-page last-interaction + meeting recency), and is explicit that the entity
engine's automatic temperature surface is not yet built. These tests lock the
load-bearing promises: it composes the existing people index, degrades honestly
when signal is thin, never fabricates a coldness score, never auto-creates tasks,
and routes cleanly against its nearest neighbors.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude/skills/relationship-radar/SKILL.md"
EVALS = ROOT / ".claude/skills/relationship-radar/evals/trigger-cases.yaml"


def _frontmatter_description() -> str:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    fm = text.split("---\n", 2)[1]
    for line in fm.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("no description in frontmatter")


def test_skill_exists_with_evals() -> None:
    assert SKILL.is_file()
    assert EVALS.is_file()


def test_description_is_a_router_with_when_and_anti_triggers() -> None:
    desc = _frontmatter_description().lower()
    assert "when the user says" in desc
    assert "meeting-prep" in desc
    assert "commitments" in desc


def test_body_uses_the_existing_people_index() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "build_people_index" in text
    assert "last_interaction" in text or "last-interaction" in text


def test_is_honest_about_the_unbuilt_temperature_surface() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    # Must not claim the entity temperature surface exists...
    assert "isn't built" in text or "not yet built" in text or "not built" in text
    # ...and must scope to today's signal instead.
    assert "meeting recency" in text


def test_degrades_without_faking_coldness() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "can't assess" in text
    assert "never guess" in text or "don't guess" in text or "do not guess" in text
    # An empty index is not reported as "all healthy".
    assert "all healthy" in text  # appears in the "never present ... as all healthy" guard


def test_reconnect_is_confirm_gated_and_inspects_output() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "never automatic" in text or "never auto-create" in text
    assert "read back the created task ids" in text


@pytest.mark.parametrize(
    "needle",
    ["positive:", "negative:", "ambiguous:", "missing_prerequisite:", "failure_recovery:"],
)
def test_evals_carry_the_canonical_case_buckets(needle: str) -> None:
    text = EVALS.read_text(encoding="utf-8")
    assert needle in text
