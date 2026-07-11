#!/usr/bin/env python3
"""Fail when Dex instructions name an MCP tool that is not available."""

from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = REPO_ROOT / "scripts" / "instructed-tools-allowlist.txt"

TOOL_NAME_PATTERN = r"[a-z][a-z0-9_]+"
TOOL_DECLARATION = re.compile(
    rf"\b(?:types\.)?Tool\s*\(\s*name\s*=\s*['\"]({TOOL_NAME_PATTERN})['\"]",
    re.MULTILINE,
)
FASTMCP_TOOL_DECLARATION = re.compile(
    rf"^[ \t]*@mcp\.tool[ \t]*\([^\r\n]*\)[ \t]*\r?\n"
    rf"[ \t]*(?:async[ \t]+)?def[ \t]+({TOOL_NAME_PATTERN})[ \t]*\(",
    re.MULTILINE,
)
CALL_REFERENCE = re.compile(rf"`(?P<name>{TOOL_NAME_PATTERN})\([^`\r\n]*\)`")
MCP_NAME_REFERENCE = re.compile(rf"`(?P<name>{TOOL_NAME_PATTERN})`")
SNAKE_CASE_NAME = re.compile(r"[a-z][a-z0-9]*_[a-z0-9_]+")


class ToolReference(NamedTuple):
    """An instructed tool name and its source location."""

    name: str
    path: Path
    line: int


def extract_defined_tool_names(source: str) -> set[str]:
    """Extract names from static Tool declarations and FastMCP decorators."""
    return set(TOOL_DECLARATION.findall(source)) | set(
        FASTMCP_TOOL_DECLARATION.findall(source)
    )


def parse_allowlist(source: str) -> set[str]:
    """Parse one tool name per line, ignoring comments and blank lines."""
    names: set[str] = set()
    for line_number, line in enumerate(source.splitlines(), start=1):
        name = line.split("#", 1)[0].strip()
        if not name:
            continue
        if re.fullmatch(TOOL_NAME_PATTERN, name) is None:
            raise ValueError(f"invalid allowlist entry on line {line_number}: {name!r}")
        names.add(name)
    return names


def extract_instructed_references(source: str, path: Path) -> list[ToolReference]:
    """Extract precise MCP-like references from an instruction surface."""
    references: list[ToolReference] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        references.extend(
            ToolReference(match.group("name"), path, line_number)
            for match in CALL_REFERENCE.finditer(line)
        )
        if "mcp" not in line.casefold():
            continue
        references.extend(
            ToolReference(name, path, line_number)
            for match in MCP_NAME_REFERENCE.finditer(line)
            if SNAKE_CASE_NAME.fullmatch(name := match.group("name"))
        )
    return references


def find_unknown_references(
    source: str,
    path: Path,
    defined_tools: set[str],
    allowlisted_tools: set[str],
) -> list[ToolReference]:
    """Return instructed references absent from local and external tool sets."""
    known_tools = defined_tools | allowlisted_tools
    return [
        reference
        for reference in extract_instructed_references(source, path)
        if reference.name not in known_tools
    ]


def _relative_path(path: Path, repo_root: Path) -> Path:
    if path.is_absolute():
        try:
            return path.relative_to(repo_root)
        except ValueError:
            return path
    return path


def is_instruction_surface(path: Path, repo_root: Path = REPO_ROOT) -> bool:
    """Return whether a path belongs to the Dex-owned instruction surfaces."""
    relative_path = _relative_path(path, repo_root)
    parts = relative_path.parts
    if parts[:2] == (".claude", "plugins"):
        return False
    if parts == ("CLAUDE.md",):
        return True
    if len(parts) >= 3 and parts[:2] == (".claude", "skills"):
        return relative_path.name == "SKILL.md"
    if len(parts) == 3 and parts[:2] == (".claude", "flows"):
        return relative_path.suffix == ".md"
    if len(parts) >= 3 and parts[:2] == (".agents", "skills"):
        return relative_path.name == "SKILL.md"
    return False


def collect_defined_tools(repo_root: Path = REPO_ROOT) -> set[str]:
    """Collect every statically declared top-level MCP tool."""
    defined_tools: set[str] = set()
    for path in sorted((repo_root / "core" / "mcp").glob("*.py")):
        defined_tools.update(extract_defined_tool_names(path.read_text(encoding="utf-8")))
    return defined_tools


def collect_instruction_files(repo_root: Path = REPO_ROOT) -> list[Path]:
    """Collect Dex-owned instruction files, excluding bundled plugins."""
    candidates = [repo_root / "CLAUDE.md"]
    candidates.extend((repo_root / ".claude" / "skills").rglob("SKILL.md"))
    candidates.extend((repo_root / ".claude" / "flows").glob("*.md"))
    candidates.extend((repo_root / ".agents" / "skills").rglob("SKILL.md"))
    return sorted(
        path for path in set(candidates) if path.is_file() and is_instruction_surface(path, repo_root)
    )


def format_findings(findings: list[ToolReference], defined_tools: set[str]) -> str:
    """Format missing tools with the closest locally defined suggestion."""
    lines: list[str] = []
    candidates = sorted(defined_tools)
    for finding in findings:
        suggestion = difflib.get_close_matches(
            finding.name,
            candidates,
            n=1,
            cutoff=0.0,
        )
        suggestion_text = (
            f" Did you mean '{suggestion[0]}'?" if suggestion else " No defined tools found."
        )
        lines.append(
            f"{finding.path}:{finding.line}: unknown instructed MCP tool "
            f"'{finding.name}'.{suggestion_text}"
        )
    return "\n".join(lines)


def main() -> int:
    """Run the instructed-tool existence gate for this repository."""
    try:
        allowlisted_tools = parse_allowlist(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"❌ Instructed-tool existence gate could not read its allowlist: {error}")
        return 1

    defined_tools = collect_defined_tools()
    instruction_files = collect_instruction_files()
    findings: list[ToolReference] = []
    for path in instruction_files:
        findings.extend(
            find_unknown_references(
                path.read_text(encoding="utf-8"),
                path.relative_to(REPO_ROOT),
                defined_tools,
                allowlisted_tools,
            )
        )

    if findings:
        print("❌ Instructed-tool existence gate failed:")
        print(format_findings(findings, defined_tools))
        return 1

    print(
        "✅ Instructed-tool existence gate passed: "
        f"{len(defined_tools)} defined tools, "
        f"{len(allowlisted_tools)} allowlisted tools, "
        f"{len(instruction_files)} instruction files checked"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
