"""Contract tests for the /initiative-kickoff skill.

Kickoff turns a decision to start a NON-product initiative (hire, partnership,
GTM, internal bet) into a real project: outcome, checkable success criteria, owner,
an honest ladder to a pillar/goal, and first steps as confirmed tasks. These tests
lock the load-bearing promises: it routes cleanly against product-brief and
project-health, never manufactures a fake goal link, keeps writes confirm-gated,
respects entity_creation, degrades honestly, and inspects what it created.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude/skills/initiative-kickoff/SKILL.md"
EVALS = ROOT / ".claude/skills/initiative-kickoff/evals/trigger-cases.yaml"


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
    assert "product-brief" in desc
    assert "project-health" in desc


def test_ladders_to_goals_without_manufacturing_a_fake_link() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "get_quarterly_goals" in text
    lower = text.lower()
    assert "standalone bet" in lower
    assert "never manufacture" in lower or "manufacturing a goal link" in lower


def test_success_criteria_must_be_checkable() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "success criteria" in text
    assert "checkable" in text
    assert "vanity" in text  # names the anti-pattern to avoid


def test_confirm_gated_writes_and_respects_entity_creation() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "entity_creation" in text
    assert "per-item confirmation" in text
    assert "read back the created task ids" in text


def test_degrades_when_no_goals_or_pillars() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "no quarterly goals" in text
    assert "pillars.yaml" in text


@pytest.mark.parametrize(
    "needle",
    ["positive:", "negative:", "ambiguous:", "missing_prerequisite:", "failure_recovery:"],
)
def test_evals_carry_the_canonical_case_buckets(needle: str) -> None:
    text = EVALS.read_text(encoding="utf-8")
    assert needle in text
