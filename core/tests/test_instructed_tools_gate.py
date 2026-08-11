"""Tests for the instructed MCP tool existence gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-instructed-tools.py"


def _load_checker():
    assert SCRIPT.exists(), f"missing instructed-tool checker: {SCRIPT}"
    spec = importlib.util.spec_from_file_location("check_instructed_tools", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _find_unknown(
    source: str,
    *,
    defined: set[str] | None = None,
    allowlisted: set[str] | None = None,
):
    checker = _load_checker()
    return checker.find_unknown_references(
        source,
        Path("fixture/SKILL.md"),
        defined or set(),
        allowlisted or set(),
    )


def test_defined_tool_extraction_handles_multiline_and_inline_declarations() -> None:
    checker = _load_checker()
    source = """
tools = [
    types.Tool(
        name="multiline_tool",
        description="Example",
    ),
    Tool(name='inline_tool', description="Example"),
]
"""

    assert checker.extract_defined_tool_names(source) == {
        "inline_tool",
        "multiline_tool",
    }


def test_defined_tool_extraction_handles_fastmcp_decorated_functions() -> None:
    checker = _load_checker()
    source = """
@mcp.tool()
def sync_tool(value: str) -> str:
    return value

@mcp.tool ( description="Example" )
async def async_tool() -> dict:
    return {}

def plain_helper() -> None:
    pass
"""

    assert checker.extract_defined_tool_names(source) == {
        "async_tool",
        "sync_tool",
    }


def test_public_lifecycle_operation_extraction_uses_the_explicit_public_surface() -> None:
    checker = _load_checker()
    source = '''
__all__ = [
    "build_and_preview_mcp_registration",
    "execute_approved_mcp_registration",
    "not an operation",
]
'''

    assert checker.extract_public_lifecycle_operations(source) == {
        "build_and_preview_mcp_registration",
        "execute_approved_mcp_registration",
    }


def test_unknown_call_reference_is_detected() -> None:
    findings = _find_unknown("First line.\nCall `missing_tool()` now.\n")

    assert [(finding.name, finding.line) for finding in findings] == [
        ("missing_tool", 2)
    ]


def test_known_call_reference_passes() -> None:
    findings = _find_unknown(
        "Call `known_tool(arg=\"value\")` now.\n",
        defined={"known_tool"},
    )

    assert findings == []


def test_allowlisted_call_reference_passes() -> None:
    checker = _load_checker()
    allowlisted = checker.parse_allowlist(
        "# Provided by an external MCP.\nexternal_tool  # inline comments work\n"
    )

    findings = checker.find_unknown_references(
        "Call `external_tool()` now.\n",
        Path("fixture/SKILL.md"),
        set(),
        allowlisted,
    )

    assert findings == []


def test_mcp_line_snake_case_reference_is_detected() -> None:
    findings = _find_unknown("Use the MCP tool `missing_tool` for this step.\n")

    assert [(finding.name, finding.line) for finding in findings] == [
        ("missing_tool", 1)
    ]


def test_unknown_reference_report_includes_closest_defined_tool() -> None:
    checker = _load_checker()
    findings = _find_unknown(
        "Call `create_taks()` now.\n",
        defined={"create_task"},
    )

    report = checker.format_findings(findings, {"create_task"})

    assert "Did you mean 'create_task'?" in report


def test_plugin_skill_path_is_not_an_instruction_surface() -> None:
    checker = _load_checker()

    assert not checker.is_instruction_surface(
        Path(".claude/plugins/example/skills/example/SKILL.md")
    )
    assert checker.is_instruction_surface(Path(".claude/skills/example/SKILL.md"))


def test_agent_instructions_are_an_instruction_surface() -> None:
    """A heavy skill's delegated-gathering brief names tools and must be gated.

    AGENT_INSTRUCTIONS.md is the prompt a heavy skill hands to its gathering
    subagent. It names MCP tools exactly as SKILL.md does, and it also tells the
    subagent to skip a failing source silently -- so an invented tool name there
    costs the user a whole source with no error shown, which is worse than in
    SKILL.md, not better.
    """
    checker = _load_checker()

    assert checker.is_instruction_surface(
        Path(".claude/skills/example/AGENT_INSTRUCTIONS.md")
    )
    assert checker.is_instruction_surface(
        Path(".agents/skills/example/AGENT_INSTRUCTIONS.md")
    )
    assert not checker.is_instruction_surface(
        Path(".claude/plugins/example/skills/example/AGENT_INSTRUCTIONS.md")
    )


def test_shipped_agent_instructions_are_actually_collected() -> None:
    """Guard the wiring, not just the predicate."""
    checker = _load_checker()
    collected = {path.name for path in checker.collect_instruction_files()}

    assert "AGENT_INSTRUCTIONS.md" in collected, (
        "No AGENT_INSTRUCTIONS.md reached the gate, so the delegated-gathering "
        "briefs are unchecked even though the predicate accepts them."
    )


def test_use_directive_reference_is_detected() -> None:
    """`Use: tool(...)` is how skills and briefs write a call inside a fence.

    Inline backticks are absent inside fenced blocks, so a gate that only
    matches backticked calls reads these files and finds nothing.
    """
    findings = _find_unknown("```\nUse: missing_tool(start_date=\"2026-08-11\")\n```\n")

    assert [(finding.name, finding.line) for finding in findings] == [
        ("missing_tool", 2)
    ]


def test_known_use_directive_reference_passes() -> None:
    findings = _find_unknown(
        "Use: known_tool(days_ahead=1)\n",
        defined={"known_tool"},
    )

    assert findings == []
