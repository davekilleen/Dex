"""Instruction contract for calendar-first meeting preparation.

The meeting-prep surface is an instruction workflow rather than Python code, so
this static test evaluates the two shipped prompts together. A
presence-only check can stay green while the inline skill reads a rich calendar
record and then hands only display names to its gathering agent.  This contract
pins the written information flow across that boundary; it does not execute an
LLM or Calendar MCP response.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = REPO_ROOT / ".claude/skills/meeting-prep/SKILL.md"
AGENT_PATH = REPO_ROOT / ".claude/skills/meeting-prep/AGENT_INSTRUCTIONS.md"


def _section(body: str, start: str, end: str) -> str:
    return body.split(start, 1)[1].split(end, 1)[0]


def _assert_calendar_first_instruction_contract(skill: str, agent: str) -> None:
    arguments = _section(skill, "## Arguments", "## What This Does")
    calendar_step = _section(skill, "### Step 0:", "### Step 1:")
    delegation = _section(
        skill,
        "### Delegated gathering (large-vault scaling)",
        "Prepare for an upcoming meeting",
    )
    agent_lookup = _section(agent, "### 1.2 Attendee Lookup", "### 1.3 Related Projects")

    # Default journey: calendar first, across the user's calendars, then ask
    # only when the returned status or matching result requires a fallback.
    assert "calendar before prompting" in arguments
    assert 'calendar_name="all"' in calendar_step
    assert calendar_step.index("calendar_get_events_with_attendees") < calendar_step.index(
        "**Ask when the calendar cannot answer.**"
    )
    assert "Calendar response confidence contract" in calendar_step
    for state in (
        "success: true",
        "warning",
        "feature_status: off",
        "feature_status: not_installed",
        "feature_status: broken",
        "permission",
        "user_message",
        "feature_status: unknown",
        "unstructured tool error",
        "No Calendar tool response",
    ):
        assert state in calendar_step

    # The instruction contract requires attendee filtering before delegation.
    for field in ("person_page", "email", "status", "type", "is_current_user"):
        assert field in calendar_step
        assert field in delegation
        assert field in agent
    for excluded in (
        "is_current_user",
        "Room",
        "Resource",
        "Group",
        "Declined",
        "Delegated",
    ):
        assert excluded in calendar_step

    # The cross-context seam is structured records, not a comma-separated
    # display-name placeholder.  Resolved pages win; email/name lookup is only
    # a fallback for records without one.
    assert "{{ATTENDEE_RECORDS}}" in delegation
    assert "{{ATTENDEE_RECORDS}}" in agent
    assert "{{ATTENDEES}}" not in delegation
    assert "{{ATTENDEES}}" not in agent
    assert agent_lookup.index("person_page") < agent_lookup.index("lookup_person")
    assert "only when `person_page` is empty" in agent_lookup


def test_calendar_first_instruction_contract_preserves_structured_attendee_handoff() -> None:
    """The written journey keeps calendar identity fields across delegation.

    This is an instruction-contract and journey-order test. It checks the
    shipped inline and delegated prompts together; it does not simulate a
    Calendar MCP response or execute a representative mixed invite at runtime.
    """

    _assert_calendar_first_instruction_contract(
        SKILL_PATH.read_text(encoding="utf-8"),
        AGENT_PATH.read_text(encoding="utf-8"),
    )
