"""Bounded, conservative static reference extraction."""

from __future__ import annotations

import ast
import json
import posixpath
import re
from pathlib import PurePosixPath
from typing import Iterable, Mapping

from core.customization_migration.model import (
    EdgeKind,
    ReferenceConfidence,
    ReferenceEdge,
)

MAX_SOURCE_BYTES = 1024 * 1024
PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_.:/-])"
    r"((?:\.{0,2}/)?[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)"
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*]\(([^)\s]+)\)")
WIKI_LINK = re.compile(r"\[\[([^]|#]+)(?:[|#][^]]*)?]]")
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
SKILL_MENTION = re.compile(r"(?<![A-Za-z0-9_.-])/([a-z0-9][a-z0-9-]*)\b")
ENV_NAME = re.compile(
    r"(?:\$\{?([A-Z][A-Z0-9_]*)\}?|"
    r"os\.environ(?:\.get)?\(\s*[\"']([A-Z][A-Z0-9_]*)[\"']|"
    r"os\.environ\[\s*[\"']([A-Z][A-Z0-9_]*)[\"']\s*]|"
    r"process\.env\.([A-Z][A-Z0-9_]*))"
)
JS_REQUIRE = re.compile(r"\brequire\(\s*[\"']([^\"']+)[\"']\s*\)")
YAML_SCALAR = re.compile(r"^[ \t]*[A-Za-z0-9_.-]+[ \t]*:[ \t]*(.+?)[ \t]*$")


def _normalize_target(source_path: str, target: str) -> str | None:
    stripped = target.strip().strip("\"'")
    if not stripped or stripped.startswith(("http://", "https://", "#", "mailto:")):
        return None
    stripped = stripped.split("#", 1)[0].replace("\\", "/")
    if stripped.startswith("/"):
        return f"unsafe-absolute:{stripped}"
    rooted = stripped.startswith(
        (
            ".claude/",
            ".scripts/",
            "scripts/",
            "System/",
            "core/",
        )
    ) or re.match(r"^[0-9]{2}-[^/]+/", stripped)
    if rooted or re.match(r"^[A-Z][A-Za-z0-9_-]*/", stripped):
        candidate = posixpath.normpath(stripped)
    else:
        candidate = posixpath.normpath(
            posixpath.join(PurePosixPath(source_path).parent.as_posix(), stripped)
        )
    if candidate in {"", "."}:
        return None
    if candidate == ".." or candidate.startswith("../"):
        return f"unsafe-escape:{stripped}"
    return candidate


def _edge_kind_for_path(source_path: str, target: str) -> EdgeKind:
    if source_path == ".mcp.json":
        return EdgeKind.MCP_TO_SERVER
    if source_path.startswith(".claude/hooks/"):
        return EdgeKind.HOOK_TO_SCRIPT
    if source_path.endswith((".md", ".markdown")) and target.startswith(
        (".scripts/", "scripts/")
    ):
        return EdgeKind.SKILL_TO_SCRIPT
    return EdgeKind.LITERAL_PATH


def _path_edges(
    source_path: str,
    values: Iterable[str],
    *,
    confidence: ReferenceConfidence,
    kind: EdgeKind | None = None,
) -> list[ReferenceEdge]:
    edges: list[ReferenceEdge] = []
    for value in values:
        target = _normalize_target(source_path, value)
        if target is None:
            continue
        edges.append(
            ReferenceEdge.create(
                source_path,
                target,
                kind or _edge_kind_for_path(source_path, target),
                confidence,
            )
        )
    return edges


def _markdown_edges(
    source_path: str,
    text: str,
    skill_paths: Mapping[str, str],
) -> list[ReferenceEdge]:
    edges = _path_edges(
        source_path,
        [*WIKI_LINK.findall(text), *MARKDOWN_LINK.findall(text)],
        confidence=ReferenceConfidence.PROVED,
        kind=EdgeKind.MARKDOWN_LINK,
    )
    command_paths: list[str] = []
    for fenced in FENCE.findall(text):
        command_paths.extend(PATH_TOKEN.findall(fenced))
    edges.extend(
        _path_edges(
            source_path,
            command_paths,
            confidence=ReferenceConfidence.PROVED,
        )
    )
    for skill_name in SKILL_MENTION.findall(text):
        target = skill_paths.get(skill_name)
        if target is None:
            continue
        edges.append(
            ReferenceEdge.create(
                source_path,
                target,
                EdgeKind.INSTRUCTIONS_TO_SKILL,
                ReferenceConfidence.PROVED,
            )
        )
    return edges


def _python_edges(source_path: str, text: str) -> list[ReferenceEdge]:
    try:
        tree = ast.parse(text, filename=source_path)
    except (SyntaxError, ValueError):
        return []
    paths: list[str] = []
    edges: list[ReferenceEdge] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                edges.append(
                    ReferenceEdge.create(
                        source_path,
                        f"python:{alias.name}",
                        EdgeKind.LITERAL_PATH,
                        ReferenceConfidence.INFERRED,
                    )
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level and not node.module:
                for alias in node.names:
                    edges.append(
                        ReferenceEdge.create(
                            source_path,
                            f"python-relative:{node.level}:{alias.name}",
                            EdgeKind.LITERAL_PATH,
                            ReferenceConfidence.INFERRED,
                        )
                    )
            elif node.module:
                prefix = (
                    f"python-relative:{node.level}:"
                    if node.level
                    else "python:"
                )
                edges.append(
                    ReferenceEdge.create(
                        source_path,
                        f"{prefix}{node.module}",
                        EdgeKind.LITERAL_PATH,
                        ReferenceConfidence.INFERRED,
                    )
                )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(("/", "../")):
                paths.append(node.value)
            paths.extend(PATH_TOKEN.findall(node.value))
    edges.extend(
        _path_edges(
            source_path,
            paths,
            confidence=ReferenceConfidence.PROVED,
        )
    )
    return edges


def _structured_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [
            item
            for key, nested in value.items()
            if key != "env"
            for item in _structured_values(nested)
        ]
    if isinstance(value, list):
        return [item for nested in value for item in _structured_values(nested)]
    return [value] if isinstance(value, str) else []


def _environment_names(value: object) -> list[str]:
    if isinstance(value, dict):
        names: list[str] = []
        for key, nested in value.items():
            if key == "env" and isinstance(nested, dict):
                names.extend(
                    name
                    for name in nested
                    if isinstance(name, str)
                    and re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
                )
            else:
                names.extend(_environment_names(nested))
        return names
    if isinstance(value, list):
        return [name for nested in value for name in _environment_names(nested)]
    return []


def _mcp_commands(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    servers = value.get("mcpServers", value)
    if not isinstance(servers, dict):
        return []
    return [
        config["command"]
        for config in servers.values()
        if isinstance(config, dict)
        and isinstance(config.get("command"), str)
        and config["command"]
    ]


def _config_edges(source_path: str, text: str) -> list[ReferenceEdge]:
    values: list[str] = []
    environment_names: list[str] = []
    if source_path.endswith(".json") or source_path == ".mcp.json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        values.extend(_structured_values(payload))
        environment_names.extend(_environment_names(payload))
        if source_path == ".mcp.json":
            for command in _mcp_commands(payload):
                if "/" not in command and "\\" not in command:
                    values.append(f"command:{command}")
    else:
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0]
            match = YAML_SCALAR.match(line)
            if match is None:
                continue
            value = match.group(1).strip()
            if value.startswith(("[", "{")):
                try:
                    values.extend(_structured_values(json.loads(value)))
                except json.JSONDecodeError:
                    continue
            else:
                values.append(value.strip("\"'"))
    paths = [
        path
        for value in values
        for path in (
            ([value] if value.startswith(("/", "../")) else [])
            + PATH_TOKEN.findall(value)
        )
    ]
    paths.extend(
        value for value in values if value.startswith("command:")
    )
    kind = EdgeKind.MCP_TO_SERVER if source_path == ".mcp.json" else None
    edges = _path_edges(
        source_path,
        paths,
        confidence=ReferenceConfidence.PROVED,
        kind=kind,
    )
    edges.extend(
        ReferenceEdge.create(
            source_path,
            f"env:{name}",
            EdgeKind.ENV_VAR_NAME,
            ReferenceConfidence.PROVED,
        )
        for name in sorted(set(environment_names))
    )
    return edges


def extract_reference_edges(
    source_path: str,
    raw: bytes,
    *,
    skill_paths: Mapping[str, str],
) -> tuple[ReferenceEdge, ...]:
    """Extract deterministic edges from already safety-checked source bytes."""
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("source exceeds the reference extraction bound")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ()
    suffix = PurePosixPath(source_path).suffix.lower()
    edges: list[ReferenceEdge] = []
    if suffix in {".md", ".markdown"} or PurePosixPath(source_path).name == "SKILL.md":
        edges.extend(_markdown_edges(source_path, text, skill_paths))
    if suffix == ".py":
        edges.extend(_python_edges(source_path, text))
    elif suffix in {".js", ".cjs", ".mjs"}:
        require_values = JS_REQUIRE.findall(text)
        literal_values = PATH_TOKEN.findall(text)
        edges.extend(
            _path_edges(
                source_path,
                [*require_values, *literal_values],
                confidence=ReferenceConfidence.INFERRED,
            )
        )
    elif suffix in {".json", ".yaml", ".yml"} or source_path == ".mcp.json":
        edges.extend(_config_edges(source_path, text))
    for match in ENV_NAME.finditer(text):
        name = next(value for value in match.groups() if value is not None)
        edges.append(
            ReferenceEdge.create(
                source_path,
                f"env:{name}",
                EdgeKind.ENV_VAR_NAME,
                ReferenceConfidence.PROVED,
            )
        )
    unique = {edge.edge_id: edge for edge in edges}
    return tuple(sorted(unique.values(), key=lambda edge: edge.edge_id))


__all__ = ["MAX_SOURCE_BYTES", "extract_reference_edges"]
