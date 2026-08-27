"""Instruction contract for Google Workspace setup identity and connectedness.

This is an instruction-contract test. It reads the shipped setup skill; it does
not start an MCP server, run OAuth, or claim a live Google account is connected.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL = REPO_ROOT / ".claude/skills/google-workspace-setup/SKILL.md"
INSTALL_IDENTITY = "google-workspace-mcp"
UNDERSCORE_PACKAGE = "google_workspace_mcp"


def _body() -> str:
    return SKILL.read_text(encoding="utf-8")


def _section(body: str, start: str, end: str) -> str:
    assert start in body, f"missing heading {start!r}"
    rest = body.split(start, 1)[1]
    assert end in rest, f"missing closing heading {end!r} after {start!r}"
    return rest.split(end, 1)[0]


def _step1(body: str) -> str:
    return _section(body, "### Step 1: Check if Already Connected", "### Step 2:")


def _step3(body: str) -> str:
    return _section(body, "### Step 3: Add the Google Workspace MCP Server", "### Step 4:")


def _step6(body: str) -> str:
    return _section(body, "### Step 6: Test the Connection", "### Step 7:")


def test_step3_prose_and_config_name_the_same_install_identity() -> None:
    """The explanation and the config block must name one package, not two."""

    step3 = _step3(_body())
    assert f"`{INSTALL_IDENTITY}`" in step3, "Step 3 prose must name the install identity"
    assert UNDERSCORE_PACKAGE not in step3, "Step 3 must not name a different underscore package"

    match = re.search(r"```json\n(\{.*?\})\n```", step3, re.S)
    assert match, "Step 3 is missing its MCP config JSON block"
    config = json.loads(match.group(1))
    assert list(config) == [INSTALL_IDENTITY], config
    entry = config[INSTALL_IDENTITY]
    assert entry["command"] == "npx", entry
    assert entry["args"] == ["-y", INSTALL_IDENTITY], entry["args"]


def test_skill_never_names_the_underscore_package_as_the_install_target() -> None:
    body = _body()
    assert UNDERSCORE_PACKAGE not in body
    assert INSTALL_IDENTITY in body
    frontmatter = body.split("---", 2)[1]
    assert f"mcp_server: {INSTALL_IDENTITY}" in frontmatter


def test_step1_checks_session_connectors_without_waiting_on_dex_config() -> None:
    """Session connectors already in this session must be checked first.

    Gating the only test query on `google-workspace.enabled: true` skips
    already-available session connectors and can add a second server.
    """

    step1 = _step1(_body())
    lowered = step1.lower()
    assert "session connector" in lowered, "Step 1 must name session connectors"
    assert "already available" in lowered
    assert "this session" in lowered
    assert "gmail" in lowered
    assert "google calendar" in lowered
    assert "google drive" in lowered
    assert "without" in lowered and "enabled first" in lowered
    assert "if any of those connectors" not in lowered
    assert "calendar-only" in lowered
    assert "drive-only" in lowered
    assert "do not skip setup" in lowered

    # The intro may name config.yaml to say it is *not* the only signal.
    # Connectedness order is the numbered list: session connectors first.
    numbered = re.findall(r"^\d+\.\s+\*\*([^*]+)\*\*", step1, re.M)
    assert numbered, "Step 1 must use a numbered connectedness list"
    assert numbered[0].lower().startswith("session connector"), numbered
    assert any(item.lower().startswith("dex config") for item in numbered[1:]), numbered
    enabled_lines = [
        line
        for line in step1.splitlines()
        if "google-workspace.enabled: true" in line and line.lstrip()[:1].isdigit()
    ]
    assert len(enabled_lines) == 1, enabled_lines
    assert enabled_lines[0].lstrip().startswith("2."), enabled_lines[0]


def test_dex_config_skip_requires_gmail_not_any_workspace_query() -> None:
    """A Calendar-healthy, Gmail-broken Dex config must not skip to label setup."""

    step1 = _step1(_body())
    dex_config = next(
        line
        for line in step1.splitlines()
        if line.lstrip().startswith("2.") and "Dex config" in line
    )
    lowered = dex_config.lower()
    assert "gmail" in lowered
    assert "calendar or drive responding is not enough" in lowered
    assert "if gmail fails" in lowered
    assert "if healthy and responding" not in lowered


def test_step3_does_not_add_a_second_server_when_gmail_session_connector_is_healthy() -> None:
    step3 = _step3(_body())
    lowered = step3.lower()
    assert "gmail" in lowered
    assert "session connector" in lowered
    assert "skip this step" in lowered
    assert "second" in lowered
    assert "alone is not a reason to skip" in lowered


def test_calendar_or_drive_alone_does_not_skip_gmail_setup() -> None:
    """Partial session connectors must not be treated as a full Workspace connection."""

    body = _body()
    step1 = _step1(body)
    step3 = _step3(body)
    troubleshooting = _section(
        body,
        '### "Google Workspace MCP not found"',
        "### Permission Errors",
    )
    for section in (step1, step3, troubleshooting):
        lowered = section.lower()
        assert "gmail" in lowered
        assert "calendar-only" in lowered or "calendar or drive" in lowered
        assert "not" in lowered
        assert "skip" in lowered or "not enough" in lowered


def test_gmail_only_connection_test_still_saves_config() -> None:
    """Missing calendar must not block writing google-workspace.enabled after Gmail works."""

    step6 = _step6(_body())
    lowered = step6.lower()
    assert "email is the connectedness bar" in lowered
    assert "required" in lowered
    assert "optional" in lowered
    assert "do not block saving config" in lowered
    assert "gmail-only" in lowered
    assert "only email failure blocks saving configuration" in lowered
    assert "if either fails" not in lowered
