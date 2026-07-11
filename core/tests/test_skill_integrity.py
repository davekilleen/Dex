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
    r"\b(?:node|bash|sh|python3?)[ \t]+[\"']?(?:\./)?"
    r"(?P<prefix>\$(?:\{VAULT_PATH\}|VAULT_PATH)/|<skill-dir>/)?"
    r"(?P<path>(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_./-]+\.(?:cjs|js|mjs|sh|py))"
)

# Keep in sync with Check 15's MISSING_RUNNABLE_ALLOWLIST in
# scripts/verify-distribution.sh.
# These are intentionally not distribution-owned implementations:
# - prompt-improver checks for the optional script and documents two fallbacks.
# - dex-add-mcp shows a user-managed Gmail MCP command as an example.
MISSING_RUNNABLE_ALLOWLIST = {
    ".scripts/improve-prompt.cjs",
    ".scripts/mcp/gmail-mcp.js",
}


def _runnable_target(match: re.Match[str], skill_path: Path, repo_root: Path) -> Path:
    """Resolve a referenced implementation from the root or its owning skill."""
    relative_path = Path(match.group("path"))
    prefix = match.group("prefix")
    if prefix == "<skill-dir>/":
        return skill_path.parent / relative_path
    if prefix is not None:
        return repo_root / relative_path

    # Bundled skills conventionally invoke their own scripts as `scripts/...`
    # or `ooxml/...`. A same-named directory beside SKILL.md makes that intent
    # explicit; otherwise the invocation is rooted at the vault/repository.
    if (skill_path.parent / relative_path.parts[0]).is_dir():
        return skill_path.parent / relative_path
    return repo_root / relative_path


def _missing_runnable_references(skill_path: Path, repo_root: Path = REPO_ROOT) -> set[str]:
    """Return canonical repo-relative paths for missing runnable references."""
    body = skill_path.read_text(encoding="utf-8").split("---", 2)[-1]
    missing = set()
    for match in RUNNABLE_REFERENCE.finditer(body):
        target = _runnable_target(match, skill_path, repo_root)
        if not target.exists():
            missing.add(target.relative_to(repo_root).as_posix())
    return missing


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=[path.parent.name for path in SKILL_FILES])
def test_skill_frontmatter_is_valid(skill_path: Path) -> None:
    assert validate_skill_frontmatter(skill_path) == []


def test_skill_runnable_references_exist_or_are_documented_dynamic_paths() -> None:
    missing: dict[str, list[str]] = {}
    for skill_path in SKILL_FILES:
        for relative_path in _missing_runnable_references(skill_path):
            missing.setdefault(relative_path, []).append(skill_path.parent.name)

    assert set(missing) == MISSING_RUNNABLE_ALLOWLIST, missing


def test_missing_skill_relative_runnable_is_reported(tmp_path: Path) -> None:
    skill_path = tmp_path / ".claude" / "skills" / "example" / "SKILL.md"
    (skill_path.parent / "scripts").mkdir(parents=True)
    skill_path.write_text(
        "---\nname: example\ndescription: Example skill\n---\n"
        "Run `python scripts/missing.py` to perform the work.\n",
        encoding="utf-8",
    )

    assert _missing_runnable_references(skill_path, tmp_path) == {
        ".claude/skills/example/scripts/missing.py"
    }


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
