"""Reusable validators for shipped Dex skills and MCP configuration."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER_PATTERN = re.compile(r"\{\{[^{}]+\}\}")


def validate_skill_frontmatter(path: str | Path) -> list[str]:
    """Return validation errors for one skill's YAML frontmatter."""
    skill_path = Path(path)
    try:
        lines = skill_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [f"could not read {skill_path}: {exc}"]

    if not lines or lines[0].strip() != "---":
        return ["frontmatter must start with ---"]
    try:
        closing_index = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return ["frontmatter is missing its closing ---"]

    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:closing_index]))
    except yaml.YAMLError as exc:
        return [f"frontmatter is not valid YAML: {exc}"]
    if not isinstance(frontmatter, Mapping):
        return ["frontmatter must be a YAML object"]

    errors = []
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name.strip():
        errors.append("frontmatter name must be a non-empty string")
    elif name != skill_path.parent.name:
        errors.append(f"frontmatter name {name!r} must match folder {skill_path.parent.name!r}")
    if not isinstance(description, str) or not description.strip():
        errors.append("frontmatter description must be a non-empty string")
    return errors


def _placeholder_errors(value: object, location: str = "$") -> list[str]:
    errors = []
    if isinstance(value, str):
        if PLACEHOLDER_PATTERN.search(value):
            errors.append(f"{location} contains an unresolved placeholder")
    elif isinstance(value, Mapping):
        for key, child in value.items():
            errors.extend(_placeholder_errors(key, f"{location}.<key>"))
            errors.extend(_placeholder_errors(child, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_placeholder_errors(child, f"{location}[{index}]"))
    return errors


def validate_mcp_config(config: object) -> list[str]:
    """Return structural and unresolved-placeholder errors for an MCP config."""
    parsed: Any = config
    if isinstance(config, str):
        try:
            parsed = json.loads(config)
        except json.JSONDecodeError as exc:
            return [f"config is not valid JSON: {exc}"]

    if not isinstance(parsed, Mapping):
        return ["config must be an object"]
    servers = parsed.get("mcpServers")
    if not isinstance(servers, Mapping):
        return ["mcpServers must be an object"]

    errors = []
    for name, entry in servers.items():
        label = str(name)
        if not isinstance(name, str) or not name.strip():
            errors.append("MCP server names must be non-empty strings")
        if not isinstance(entry, Mapping):
            errors.append(f"{label}: entry must be an object")
            continue

        command = entry.get("command")
        if not isinstance(command, str) or not command.strip():
            errors.append(f"{label}: command must be a non-empty string")
        args = entry.get("args", [])
        if not isinstance(args, list) or not all(isinstance(argument, str) for argument in args):
            errors.append(f"{label}: args must be a list of strings")
        env = entry.get("env", {})
        if not isinstance(env, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in env.items()
        ):
            errors.append(f"{label}: env must be an object of string values")

    errors.extend(_placeholder_errors(parsed))
    return errors
