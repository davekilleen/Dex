"""Instruction-contract checks for calendar degradation in calendar-using skills.

These workflows are prompt-driven, so this suite checks the shipped instructions
at the files that actually receive Calendar MCP results. It does not execute an
LLM or prove that a model will follow the instructions at runtime.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CALENDAR_CONTRACT_HEADING = "#### Calendar response confidence contract"
CALENDAR_CONTRACT_REFERENCE = "Calendar response confidence contract"
CALENDAR_CONTRACT_PATH = REPO_ROOT / "CLAUDE.md"
CALENDAR_EXECUTION_FILES = {
    "daily-plan": REPO_ROOT / ".claude/skills/daily-plan/AGENT_INSTRUCTIONS.md",
    "daily-review": REPO_ROOT / ".claude/skills/daily-review/AGENT_INSTRUCTIONS.md",
    "meeting-prep": REPO_ROOT / ".claude/skills/meeting-prep/SKILL.md",
    "process-meetings": (
        REPO_ROOT / ".claude/skills/process-meetings/AGENT_INSTRUCTIONS.md"
    ),
    "week-plan": REPO_ROOT / ".claude/skills/week-plan/SKILL.md",
    "week-review": REPO_ROOT / ".claude/skills/week-review/AGENT_INSTRUCTIONS.md",
}
DELEGATED_CALENDAR_SKILLS = {
    "daily-plan": (
        REPO_ROOT / ".claude/skills/daily-plan/SKILL.md",
        ".claude/skills/daily-plan/AGENT_INSTRUCTIONS.md",
    ),
    "daily-review": (
        REPO_ROOT / ".claude/skills/daily-review/SKILL.md",
        ".claude/skills/daily-review/AGENT_INSTRUCTIONS.md",
    ),
    "week-review": (
        REPO_ROOT / ".claude/skills/week-review/SKILL.md",
        ".claude/skills/week-review/AGENT_INSTRUCTIONS.md",
    ),
}
NON_CALENDAR_EXECUTION_FILES = {
    "meeting-prep delegated gathering": (
        REPO_ROOT / ".claude/skills/meeting-prep/AGENT_INSTRUCTIONS.md"
    ),
}


def _calendar_contract(body: str) -> str:
    assert CALENDAR_CONTRACT_HEADING in body, "missing Calendar response contract"
    contract = body.split(CALENDAR_CONTRACT_HEADING, 1)[1]
    return contract.split("\n### ", 1)[0]


def _assert_calendar_contract(body: str) -> None:
    contract = _calendar_contract(body)

    for state in (
        "`feature_status: off`",
        "`feature_status: not_installed`",
        "`feature_status: broken`",
        "`feature_status: unknown`",
    ):
        assert state in contract, f"missing {state} branch"

    assert "`user_message`" in contract, "broken state must preserve user guidance"
    assert "permission" in contract, "broken state must preserve permission guidance"
    assert "tool is unavailable" in contract, "missing-tool absence needs its own branch"
    assert "tool errors" in contract, "bare tool errors must not be treated as absence"
    assert "`success: true`" in contract, "healthy response branch is missing"
    assert "`count: 0`" in contract, "genuine empty-result branch is missing"
    assert "`warning`" in contract, "empty results must preserve calendar warnings"
    assert "not an empty calendar" in contract, "unknown/error must not become empty"
    assert "do not call `analyze_calendar_capacity`" in contract, (
        "failed calendar reads must not become a false open-day capacity result"
    )


def _assert_call_site_reference(body: str) -> None:
    assert CALENDAR_CONTRACT_REFERENCE in body, "calendar call site omits canonical policy"


def test_every_calendar_using_skill_has_state_complete_instructions() -> None:
    _assert_calendar_contract(CALENDAR_CONTRACT_PATH.read_text(encoding="utf-8"))

    for skill, path in CALENDAR_EXECUTION_FILES.items():
        body = path.read_text(encoding="utf-8")
        assert "calendar_get_" in body, f"{skill} contract is not at a calendar call site"
        _assert_call_site_reference(body)

    for context, path in NON_CALENDAR_EXECUTION_FILES.items():
        body = path.read_text(encoding="utf-8")
        assert "calendar_get_" not in body, f"{context} unexpectedly became a caller"
        assert CALENDAR_CONTRACT_REFERENCE not in body, (
            f"{context} pretends it can inspect a Calendar MCP response"
        )


@pytest.mark.parametrize("skill", tuple(DELEGATED_CALENDAR_SKILLS))
def test_calendar_skills_delegate_response_handling_to_the_guarded_caller(
    skill: str,
) -> None:
    """Account for parent skills whose Calendar call runs in their gatherer."""

    skill_path, caller_reference = DELEGATED_CALENDAR_SKILLS[skill]
    body = skill_path.read_text(encoding="utf-8")
    assert "calendar_get_" in body, f"{skill} no longer declares Calendar use"
    assert caller_reference in body, f"{skill} no longer delegates to its guarded caller"

    caller = REPO_ROOT / caller_reference
    _assert_call_site_reference(caller.read_text(encoding="utf-8"))


@pytest.mark.parametrize("skill", tuple(CALENDAR_EXECUTION_FILES))
def test_removing_a_real_call_site_reference_is_rejected(skill: str) -> None:
    """Prove each caller is coupled to the one canonical response policy."""

    body = CALENDAR_EXECUTION_FILES[skill].read_text(encoding="utf-8")
    _assert_call_site_reference(body)

    mutated = body.replace(CALENDAR_CONTRACT_REFERENCE, "REMOVED_POLICY_REFERENCE")
    with pytest.raises(AssertionError):
        _assert_call_site_reference(mutated)


@pytest.mark.parametrize(
    ("branch", "needle"),
    [
        ("off", "`feature_status: off`"),
        ("not-installed", "`feature_status: not_installed`"),
        ("broken-permission", "permission"),
        ("broken-guidance", "`user_message`"),
        ("unknown", "`feature_status: unknown`"),
        ("empty-result", "`count: 0`"),
    ],
)
def test_deliberate_calendar_branch_mutations_are_rejected(
    branch: str,
    needle: str,
) -> None:
    """Prove the instruction guard fails when one required branch is removed."""

    body = CALENDAR_CONTRACT_PATH.read_text(encoding="utf-8")
    contract = _calendar_contract(body)
    assert needle in contract, f"test fixture is missing the {branch} branch"

    mutated = body.replace(needle, "REMOVED_REQUIRED_BRANCH")
    with pytest.raises(AssertionError):
        _assert_calendar_contract(mutated)
