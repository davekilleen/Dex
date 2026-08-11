"""Every MCP tool a delegated-gathering brief names must actually exist.

The briefs in `.claude/skills/*/AGENT_INSTRUCTIONS.md` tell a subagent which
tools to call, and they also tell it to skip a source silently when a call
fails. Those two rules combine badly: a tool name that does not exist fails,
gets skipped silently, and the user receives a plan or review that is quietly
missing its calendar (or its tasks, or its goals) with nothing reported. A
misspelled or invented tool name is therefore a silent-data-loss defect, not a
typo, and it cannot be caught by reading the brief.

`calendar_get_my_events` shipped in three briefs and does not exist; the real
tool is `calendar_get_events_with_attendees`. This test exists so the next one
fails in CI instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"
MCP_ROOT = REPO_ROOT / "core" / "mcp"

# Tools provided by MCP servers that are not part of this repository (QMD's
# semantic search, and any optional third-party integration). The briefs
# reference these by design and gate them on an availability check first.
EXTERNAL_TOOLS = frozenset({"query", "status"})

# A call-shaped reference: `some_tool_name(`.
CALL_PATTERN = re.compile(r"\b([a-z][a-z0-9_]{3,})\(")

# How every server in core/mcp registers a tool.
REGISTRATION_PATTERN = re.compile(r'name="([a-z][a-z0-9_]{3,})"')


def _registered_tool_names() -> frozenset[str]:
    names: set[str] = set()
    for server in sorted(MCP_ROOT.glob("*.py")):
        names.update(REGISTRATION_PATTERN.findall(server.read_text(encoding="utf-8")))
    return frozenset(names)


def _brief_paths() -> list[Path]:
    return sorted(SKILLS_ROOT.glob("*/AGENT_INSTRUCTIONS.md"))


def test_mcp_servers_expose_tools() -> None:
    """Guard the guard: an empty registry would make every assertion vacuous."""
    registered = _registered_tool_names()
    assert len(registered) > 50, (
        "Parsed too few tool registrations from core/mcp; the parser has drifted "
        f"from how servers register tools (found {len(registered)})."
    )
    assert "calendar_get_events_with_attendees" in registered


@pytest.mark.parametrize("brief", _brief_paths(), ids=lambda path: path.parent.name)
def test_brief_only_names_real_tools(brief: Path) -> None:
    registered = _registered_tool_names()
    referenced = set(CALL_PATTERN.findall(brief.read_text(encoding="utf-8")))
    unknown = sorted(referenced - registered - EXTERNAL_TOOLS)

    assert not unknown, (
        f"{brief.parent.name}/AGENT_INSTRUCTIONS.md tells its subagent to call "
        f"tools that no MCP server in core/mcp registers: {', '.join(unknown)}. "
        "The brief also says to skip a failing source silently, so the user "
        "would lose that whole source with no error. Use the real tool name, or "
        "add it to EXTERNAL_TOOLS if it comes from an MCP outside this repo."
    )


def test_briefs_exist_to_be_checked() -> None:
    assert _brief_paths(), (
        "No AGENT_INSTRUCTIONS.md briefs found, so this guard is checking "
        "nothing; the delegated-gathering convention or its location changed."
    )
