"""Reusable validators for shipped Dex skills and MCP configuration."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER_PATTERN = re.compile(r"\{\{[^{}]+\}\}")


def validate_user_profile_config(config: object) -> list[str]:
    """Return minimal schema errors for ``System/user-profile.yaml``."""
    if not isinstance(config, Mapping):
        return ["user profile must be a YAML object"]

    errors = []
    string_fields = ("name", "role", "role_group", "company", "email_domain")
    for field in string_fields:
        if field in config and not isinstance(config[field], str):
            errors.append(f"{field} must be a string")
    object_fields = (
        "communication",
        "meeting_processing",
        "meeting_intelligence",
        "journaling",
        "quarterly_planning",
        "analytics",
        "calendar",
    )
    for field in object_fields:
        if field in config and not isinstance(config[field], Mapping):
            errors.append(f"{field} must be an object")
    return errors


def validate_pillars_config(config: object) -> list[str]:
    """Return minimal schema errors for ``System/pillars.yaml``."""
    if not isinstance(config, Mapping):
        return ["pillars config must be a YAML object"]

    pillars = config.get("pillars")
    if not isinstance(pillars, list):
        return ["pillars must be a list"]

    errors = []
    for index, pillar in enumerate(pillars):
        label = f"pillars[{index}]"
        if not isinstance(pillar, Mapping):
            errors.append(f"{label} must be an object")
            continue
        for field in ("id", "name"):
            value = pillar.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{label}.{field} must be a non-empty string")
        if "description" in pillar and not isinstance(pillar["description"], str):
            errors.append(f"{label}.description must be a string")
        keywords = pillar.get("keywords", [])
        if not isinstance(keywords, list) or not all(isinstance(keyword, str) for keyword in keywords):
            errors.append(f"{label}.keywords must be a list of strings")

    limits = config.get("priority_limits")
    if limits is not None:
        if not isinstance(limits, Mapping):
            errors.append("priority_limits must be an object")
        else:
            for priority, limit in limits.items():
                if priority not in {"P0", "P1", "P2", "P3"}:
                    errors.append(f"priority_limits contains unknown priority {priority!r}")
                if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                    errors.append(f"priority_limits.{priority} must be a non-negative integer")
    return errors


def validate_integration_config(config: object, *, main: bool = False) -> list[str]:
    """Return minimal schema errors for one ``System/integrations`` YAML file."""
    if not isinstance(config, Mapping):
        return ["integration config must be a YAML object"]

    errors = []
    enabled = config.get("enabled")
    if main:
        if enabled is not None and (
            not isinstance(enabled, Mapping)
            or not all(isinstance(name, str) and isinstance(value, bool) for name, value in enabled.items())
        ):
            errors.append("enabled must be an object of boolean values")
    elif enabled is not None and not isinstance(enabled, bool):
        errors.append("enabled must be a boolean")
    if "hooks" in config and not isinstance(config["hooks"], Mapping):
        errors.append("hooks must be an object")
    return errors


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

        remote = entry.get("type") in {"http", "sse", "streamable-http"} or "url" in entry
        if remote:
            url = entry.get("url")
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                errors.append(f"{label}: url must be an http(s) string")
        else:
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
