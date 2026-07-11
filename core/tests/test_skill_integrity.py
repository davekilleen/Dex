"""Validate shipped skill metadata and executable references."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.utils.validators import validate_mcp_config, validate_skill_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / ".claude" / "skills"
SKILL_FILES = sorted(SKILLS_ROOT.glob("*/SKILL.md"))

RUNNABLE_REFERENCE = re.compile(
    r"\b(?:node|bash|sh|python3?)\s+(?:\./)?"
    r"(?P<path>(?:\.scripts|\.claude|core)/[A-Za-z0-9_./-]+\.(?:cjs|js|sh|py))"
)

# These are intentionally not distribution-owned implementations:
# - prompt-improver checks for the optional script and documents two fallbacks.
# - dex-add-mcp shows a user-managed Gmail MCP command as an example.
MISSING_RUNNABLE_ALLOWLIST = {
    ".scripts/improve-prompt.cjs",
    ".scripts/mcp/gmail-mcp.js",
}


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=[path.parent.name for path in SKILL_FILES])
def test_skill_frontmatter_is_valid(skill_path: Path) -> None:
    assert validate_skill_frontmatter(skill_path) == []


def test_skill_runnable_references_exist_or_are_documented_dynamic_paths() -> None:
    missing: dict[str, list[str]] = {}
    for skill_path in SKILL_FILES:
        text = skill_path.read_text(encoding="utf-8")
        body = text.split("---", 2)[-1]
        for match in RUNNABLE_REFERENCE.finditer(body):
            relative_path = match.group("path")
            if not (REPO_ROOT / relative_path).exists():
                missing.setdefault(relative_path, []).append(skill_path.parent.name)

    assert set(missing) == MISSING_RUNNABLE_ALLOWLIST, missing


def test_validate_mcp_config_accepts_resolved_stdio_entries() -> None:
    config = {
        "mcpServers": {
            "work-mcp": {
                "command": "/vault/.venv/bin/python",
                "args": ["/vault/core/mcp/work_server.py"],
                "env": {"VAULT_PATH": "/vault"},
            }
        }
    }

    assert validate_mcp_config(config) == []
    assert validate_mcp_config('{"mcpServers":{"server":{"command":"python","args":[]}}}') == []


@pytest.mark.parametrize(
    ("config", "expected_error"),
    [
        ({}, "mcpServers"),
        ({"mcpServers": []}, "object"),
        ({"mcpServers": {"bad": []}}, "entry must be an object"),
        ({"mcpServers": {"bad": {"command": "", "args": []}}}, "command"),
        ({"mcpServers": {"bad": {"command": "python", "args": "server.py"}}}, "args"),
        (
            {
                "mcpServers": {
                    "bad": {
                        "command": "python",
                        "args": ["{{VAULT_PATH}}/server.py"],
                    }
                }
            },
            "unresolved placeholder",
        ),
    ],
)
def test_validate_mcp_config_reports_structural_errors(config: object, expected_error: str) -> None:
    errors = validate_mcp_config(config)

    assert any(expected_error in error for error in errors), errors
