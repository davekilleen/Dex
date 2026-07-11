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
