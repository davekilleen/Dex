"""Contract tests for the /meeting-closeout skill.

Closeout is the single-meeting, in-the-moment ritual: capture the decisions,
owned actions, the user's own commitments, and the next step for ONE meeting that
just happened. These tests lock the load-bearing promises: it is distinct from the
bulk process-meetings pass, extracts only what the notes support (owners named or
TBD, never invented), respects the entity_creation setting, never auto-creates tasks,
degrades honestly, and inspects what it wrote before claiming done.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".claude/skills/meeting-closeout/SKILL.md"
EVALS = ROOT / ".claude/skills/meeting-closeout/evals/trigger-cases.yaml"


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
    # Anti-triggers naming the true nearest neighbors.
    assert "process-meetings" in desc
    assert "meeting-prep" in desc


def test_captures_the_closeout_essentials() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    for essential in ["decisions", "action item", "commitment", "next step"]:
        assert essential in text


def test_owners_named_or_honestly_tbd_never_invented() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "tbd" in text
    assert "never invent" in text or "do not invent" in text or "inventing" in text


def test_respects_entity_creation_and_confirm_gates_writes() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "entity_creation" in text
    assert "never automatic" in text or "never auto-create" in text
    assert "read back the created task ids" in text


def test_degrades_without_fabricating_a_recap() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "never fabricate" in text or "do not fabricate" in text
    assert "ask for the notes" in text


def test_named_meeting_discovery_is_provider_neutral_and_not_folder_bound() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()

    assert "provider-neutral" in text
    assert "search the vault" in text
    assert "clickup" in text
    assert "not only `00-inbox/meetings/`" in text
    assert "original source note" in text
    assert "meeting_sources" in text


def test_source_boundary_forbids_external_services() -> None:
    text = SKILL.read_text(encoding="utf-8").lower()
    assert "source boundary" in text
    assert "never go looking in external services" in text
    assert "google drive" in text
    assert "do not widen the search to external tools" in text


@pytest.mark.parametrize(
    "needle",
    ["positive:", "negative:", "ambiguous:", "missing_prerequisite:", "failure_recovery:"],
)
def test_evals_carry_the_canonical_case_buckets(needle: str) -> None:
    text = EVALS.read_text(encoding="utf-8")
    assert needle in text
