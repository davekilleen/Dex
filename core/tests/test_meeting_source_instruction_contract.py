"""Instruction contract for provider-neutral meeting-source discovery.

This is an instruction-contract and journey-order test. It reads the shipped
profile and prompt surfaces together; it does not execute an AI agent, query a
recorder, or claim that a live meeting-processing run succeeded.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from core.utils.validators import validate_user_profile_config

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = REPO_ROOT / "System/user-profile-template.yaml"
ONBOARDING = REPO_ROOT / ".claude/flows/onboarding.md"
CLOSEOUT = REPO_ROOT / ".claude/skills/meeting-closeout/SKILL.md"
PROCESS_AGENT = REPO_ROOT / ".claude/skills/process-meetings/AGENT_INSTRUCTIONS.md"
PROCESS_ADAPTER = REPO_ROOT / ".agents/skills/process-meetings/SKILL.md"
DAILY_AGENT = REPO_ROOT / ".claude/skills/daily-review/AGENT_INSTRUCTIONS.md"
VALIDATORS = REPO_ROOT / "core/utils/validators.py"


def _split_primary_list(raw: str, separator: str) -> list[str]:
    primaries = [part.strip() for part in raw.split(separator) if part.strip()]
    assert primaries, f"empty primary list from {raw!r}"
    return primaries


def _onboarding_persist_primaries() -> list[str]:
    text = ONBOARDING.read_text(encoding="utf-8")
    persist = text.split("**Persist the choice.**", 1)[1].split("\n", 1)[0]
    match = re.search(r"set `primary` \(([^)]+)\)", persist)
    assert match, "onboarding persist-choice primary list missing"
    return _split_primary_list(match.group(1), "/")


def _agent_instruction_primaries() -> list[str]:
    text = PROCESS_AGENT.read_text(encoding="utf-8")
    match = re.search(r"^  primary: (.+)$", text, re.M)
    assert match, "process-meetings documented primary list missing"
    return _split_primary_list(match.group(1), "|")


def _template_primaries() -> list[str]:
    text = PROFILE.read_text(encoding="utf-8")
    match = re.search(r"^# primary: (.+)$", text, re.M)
    assert match, "user-profile-template primary comment missing"
    return _split_primary_list(match.group(1), "|")


def _validator_allowed_primaries() -> set[str]:
    text = VALIDATORS.read_text(encoding="utf-8")
    match = re.search(r"allowed_primaries = \{([^}]+)\}", text)
    assert match, "validators allowed_primaries set missing"
    primaries = set(re.findall(r'"([^"]+)"', match.group(1)))
    assert primaries, "validators allowed_primaries set is empty"
    return primaries


def _section(body: str, start: str, end: str) -> str:
    return body.split(start, 1)[1].split(end, 1)[0]


def _assert_local_source_contract(body: str) -> None:
    """A processing prompt resolves safe local sources without tool fiction."""

    for required in (
        "meeting_sources",
        "notes_folder",
        "vault-relative",
        "provider-neutral",
        "00-Inbox/Meetings",
        "missing",
        "malformed",
        "absolute",
        "symlink",
        "external service",
    ):
        assert required in body

    # Configuration is read before the default landing zone is searched.
    assert body.index("meeting_sources") < body.index("00-Inbox/Meetings")

    # Recorder provenance is provider-neutral and never excludes manual notes.
    for required in (
        "non-empty scalar",
        "ending in `_id`",
        "granola_id",
        "wispr_id",
        "multiple",
        "mismatch",
        "non-scalar",
        "manual note",
        "normalized vault-relative Markdown path",
        "`.md`",
        "basename",
    ):
        assert required in body


def test_meeting_source_instruction_journey_matches_the_profile_contract() -> None:
    """All shipped prompt surfaces share one safe source-selection ladder."""

    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    assert validate_user_profile_config(profile) == []
    assert profile["meeting_sources"] == {"primary": "none", "notes_folder": ""}

    closeout_step = _section(
        CLOSEOUT.read_text(encoding="utf-8"),
        "## Step 1 — Get the meeting",
        "## Step 2 — Extract",
    )
    assert closeout_step.index("configured meeting source") < closeout_step.index(
        "provider-neutral source note"
    )
    assert "Never go looking in external services" in closeout_step
    assert "ask for\nthe notes" in closeout_step

    process_step = _section(
        PROCESS_AGENT.read_text(encoding="utf-8"),
        "## Step 1:",
        "## Step 3: Update Person Pages",
    )
    adapter_step = _section(
        PROCESS_ADAPTER.read_text(encoding="utf-8"),
        "### Step 1:",
        "### Step 3: Update Person Pages",
    )
    _assert_local_source_contract(process_step)
    _assert_local_source_contract(adapter_step)

    daily_catch_up = _section(
        DAILY_AGENT.read_text(encoding="utf-8"),
        "## Step 0: Meeting Catch-Up",
        "## Step 1: File Discovery",
    )
    assert "meeting_sources" in daily_catch_up
    assert "process-meetings/AGENT_INSTRUCTIONS.md" in daily_catch_up
    assert "does not grant access" in daily_catch_up
    assert "vault" in daily_catch_up


def test_contract_helper_rejects_removed_configured_source_lookup() -> None:
    """The gate has signal when the configured-source lookup disappears."""

    valid = (
        "meeting_sources notes_folder vault-relative provider-neutral "
        "00-Inbox/Meetings missing malformed absolute symlink external service "
        "non-empty scalar ending in `_id` granola_id wispr_id multiple mismatch "
        "non-scalar manual note normalized vault-relative Markdown path `.md` basename"
    )
    without_lookup = valid.replace("meeting_sources", "")

    try:
        _assert_local_source_contract(without_lookup)
    except AssertionError:
        pass
    else:
        raise AssertionError("contract accepted removal of meeting_sources lookup")


def test_contract_helper_rejects_removed_provider_neutral_capture_ids() -> None:
    """The gate has signal when provider-neutral capture IDs disappear."""

    valid = (
        "meeting_sources notes_folder vault-relative provider-neutral "
        "00-Inbox/Meetings missing malformed absolute symlink external service "
        "non-empty scalar ending in `_id` granola_id wispr_id multiple mismatch "
        "non-scalar manual note normalized vault-relative Markdown path `.md` basename"
    )
    granola_only = valid.replace("ending in `_id`", "fixed key").replace(
        "wispr_id", ""
    )

    try:
        _assert_local_source_contract(granola_only)
    except AssertionError:
        pass
    else:
        raise AssertionError("contract accepted a provider-specific capture ID")


def test_validate_user_profile_accepts_wispr_as_meeting_source_primary() -> None:
    assert (
        validate_user_profile_config(
            {"meeting_sources": {"primary": "wispr", "notes_folder": ""}}
        )
        == []
    )


def test_validate_user_profile_rejects_unknown_meeting_source_primary() -> None:
    errors = validate_user_profile_config(
        {"meeting_sources": {"primary": "not-a-recorder"}}
    )
    assert errors == [
        "meeting_sources.primary must be granola, zoom, teams, "
        "exported-folder, wispr, or none"
    ]


def test_onboarding_meeting_source_primaries_pass_the_validator() -> None:
    primaries = _onboarding_persist_primaries()
    assert "wispr" in primaries
    for primary in primaries:
        assert (
            validate_user_profile_config({"meeting_sources": {"primary": primary}})
            == []
        ), primary


def test_documented_meeting_source_primary_lists_stay_in_lockstep() -> None:
    onboarding = _onboarding_persist_primaries()
    instructions = _agent_instruction_primaries()
    template = _template_primaries()
    allowed = _validator_allowed_primaries()
    assert onboarding == instructions == template
    assert set(onboarding) == allowed
    assert "wispr" in allowed
