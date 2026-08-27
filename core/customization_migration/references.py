"""Bounded, conservative static reference extraction."""

from __future__ import annotations

import ast
import json
import plistlib
import posixpath
import re
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

from core.customization_migration.model import (
    EdgeKind,
    ReferenceConfidence,
    ReferenceEdge,
)

MAX_SOURCE_BYTES = 1024 * 1024
MAX_STRUCTURED_DEPTH = 64
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
SHELL_WORD = re.compile(r"""(?:'[^']*'|"[^"]*"|[^\s;&|<>]+)""")
# A requirement line names a package. Lines opening with a dash are pip options
# (`-r other.txt`, `--hash=sha256:...` continuations in a locked file), never
# package names, so they must not become dependency edges.
REQUIREMENTS_NAME = re.compile(
    r"^\s*(?!-)([A-Za-z0-9_.-]{1,256})(?:\[[A-Za-z0-9_,.-]+\])?"
    r"\s*(?:[<>=!~;@]|$)"
)
PACKAGE_NAME = re.compile(r"^[A-Za-z0-9@/_.-]{1,256}$")


class ReferenceParseError(ValueError):
    """A structural reference source could not be parsed safely."""


def _load_json(value: str | bytes, description: str) -> object:
    try:
        return json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ReferenceParseError(f"{description} is malformed") from error


def is_reference_read_restricted_path(path: str) -> bool:
    """Classify credential-bearing sources before callers read their bytes."""
    parts = PurePosixPath(path).parts
    secret_adjacent = any(
        part.lower() == ".env"
        or part.lower().startswith(".env.")
        or "credential" in part.lower()
        for part in parts
    )
    return (
        path in {
            ".claude/settings.json",
            ".claude/settings.local.json",
        }
        or (
            path.startswith("System/integrations/")
            and PurePosixPath(path).suffix.lower() in {".yaml", ".yml"}
        )
        or secret_adjacent
    )


def _normalize_target(source_path: str, target: str) -> str | None:
    stripped = target.strip().strip("\"'")
    if not stripped or stripped.startswith(("http://", "https://", "#", "mailto:")):
        return None
    stripped = stripped.split("#", 1)[0].replace("\\", "/")
    if stripped.startswith("/"):
        return "outside-vault:absolute"
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
        return "outside-vault:escape"
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


def _shell_static_text(text: str) -> str:
    """Blank shell words containing expansion before applying PATH_TOKEN."""
    if text.startswith("#!"):
        _, separator, remainder = text.partition("\n")
        text = (" " * (len(text) - len(remainder) - len(separator))) + separator + remainder
    return SHELL_WORD.sub(
        lambda match: " " * len(match.group(0))
        if "$" in match.group(0)
        else match.group(0),
        text,
    )


def _shell_edges(
    source_path: str,
    text: str,
    skill_paths: Mapping[str, str],
) -> list[ReferenceEdge]:
    static_text = _shell_static_text(text)
    edges = _path_edges(
        source_path,
        PATH_TOKEN.findall(static_text),
        confidence=ReferenceConfidence.INFERRED,
    )
    for skill_name in SKILL_MENTION.findall(static_text):
        target = skill_paths.get(skill_name)
        if target is not None:
            edges.append(
                ReferenceEdge.create(
                    source_path,
                    target,
                    EdgeKind.INSTRUCTIONS_TO_SKILL,
                    ReferenceConfidence.INFERRED,
                )
            )
    return edges


def _plist_edges(source_path: str, raw: bytes) -> list[ReferenceEdge]:
    try:
        payload = plistlib.loads(raw)
    except (plistlib.InvalidFileException, ValueError, TypeError) as error:
        raise ReferenceParseError("launch-agent plist is malformed") from error
    if not isinstance(payload, dict):
        raise ReferenceParseError("launch-agent plist root must be a dictionary")
    values: list[str] = []
    arguments = payload.get("ProgramArguments")
    if isinstance(arguments, list):
        values.extend(value for value in arguments if isinstance(value, str))
    working_directory = payload.get("WorkingDirectory")
    if isinstance(working_directory, str):
        values.append(working_directory)
    paths = [
        value
        for value in values
        if "$" not in value
        and "\x00" not in value
        and not value.startswith("-")
        and "/" in value
    ]
    return [
        edge
        for edge in _path_edges(
            source_path,
            paths,
            confidence=ReferenceConfidence.PROVED,
            kind=EdgeKind.LAUNCH_AGENT_TO_EXECUTABLE,
        )
        if not edge.target.startswith("outside-vault:")
    ]


def _package_edges(source_path: str, text: str) -> list[ReferenceEdge]:
    name = PurePosixPath(source_path).name
    package_names: set[str] = set()
    if name == "package.json":
        payload = _load_json(text, "package manifest")
        if not isinstance(payload, dict):
            return []
        for key in ("dependencies", "devDependencies"):
            dependencies = payload.get(key)
            if not isinstance(dependencies, dict):
                continue
            package_names.update(
                dependency
                for dependency in dependencies
                if isinstance(dependency, str)
                and PACKAGE_NAME.fullmatch(dependency) is not None
            )
    elif (
        name == "requirements.txt"
        or name.startswith("requirements-") and name.endswith(".txt")
    ):
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0]
            match = REQUIREMENTS_NAME.match(line)
            if match is not None:
                package_names.add(match.group(1))
    return [
        ReferenceEdge.create(
            source_path,
            f"package:{package_name}",
            EdgeKind.PACKAGE_DEPENDENCY,
            ReferenceConfidence.PROVED,
        )
        for package_name in sorted(package_names)
    ]


def _hook_commands(value: object, depth: int = 0) -> list[str]:
    if depth > MAX_STRUCTURED_DEPTH:
        raise ReferenceParseError("hook settings exceed the structural depth bound")
    if isinstance(value, dict):
        commands = [
            nested
            for key, nested in value.items()
            if key == "command" and isinstance(nested, str)
        ]
        for nested in value.values():
            commands.extend(_hook_commands(nested, depth + 1))
        return commands
    if isinstance(value, list):
        return [
            command
            for nested in value
            for command in _hook_commands(nested, depth + 1)
        ]
    return []


def extract_settings_hook_edges(
    source_path: str,
    raw: bytes,
    *,
    known_paths: frozenset[str],
) -> tuple[ReferenceEdge, ...]:
    """Structurally extract existing hook targets without exposing commands."""
    if source_path not in {
        ".claude/settings.json",
        ".claude/settings.local.json",
    }:
        raise ValueError("hook settings extractor only accepts Claude settings")
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("source exceeds the reference extraction bound")
    payload = _load_json(raw, "hook settings")
    if not isinstance(payload, dict):
        return ()
    hooks = payload.get("hooks")
    paths = [
        path
        for command in _hook_commands(hooks)
        for path in PATH_TOKEN.findall(_shell_static_text(command))
    ]
    edges = _path_edges(
        source_path,
        paths,
        confidence=ReferenceConfidence.PROVED,
        kind=EdgeKind.HOOK_TO_SCRIPT,
    )
    unique = {
        edge.edge_id: edge
        for edge in edges
        if edge.target in known_paths
    }
    return tuple(sorted(unique.values(), key=lambda edge: edge.edge_id))


def read_settings_hook_edges(
    root: Path,
    source_path: str,
    *,
    known_paths: frozenset[str],
) -> tuple[ReferenceEdge, ...]:
    """Bounded no-follow read dedicated to the structural hook extractor."""
    from core.lifecycle.filesystem import FilesystemInspectionError, bounded_read

    try:
        raw = bounded_read(root, source_path, max_bytes=MAX_SOURCE_BYTES)
    except FilesystemInspectionError:
        return ()
    return extract_settings_hook_edges(
        source_path,
        raw,
        known_paths=known_paths,
    )


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
            confidence=ReferenceConfidence.INFERRED,
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
            confidence=ReferenceConfidence.INFERRED,
        )
    )
    return edges


def _structured_values(value: object, depth: int = 0) -> list[str]:
    if depth > MAX_STRUCTURED_DEPTH:
        raise ReferenceParseError("configuration exceeds the structural depth bound")
    if isinstance(value, dict):
        return [
            item
            for key, nested in value.items()
            if key != "env"
            for item in _structured_values(nested, depth + 1)
        ]
    if isinstance(value, list):
        return [
            item
            for nested in value
            for item in _structured_values(nested, depth + 1)
        ]
    return [value] if isinstance(value, str) else []


def _mcp_edges(source_path: str, payload: object) -> list[ReferenceEdge]:
    if not isinstance(payload, dict):
        return []
    servers = payload.get("mcpServers", payload)
    if not isinstance(servers, dict):
        return []
    paths: list[str] = []
    environment_names: set[str] = set()
    for config in servers.values():
        if not isinstance(config, dict):
            continue
        env = config.get("env")
        if isinstance(env, dict):
            environment_names.update(
                name
                for name in env
                if isinstance(name, str)
                and re.fullmatch(r"[A-Z][A-Z0-9_]*", name)
            )
        args = config.get("args")
        if isinstance(args, list):
            paths.extend(
                value
                for value in args
                if isinstance(value, str)
                and value.startswith(("core/", ".scripts/", "scripts/"))
                and PurePosixPath(value).suffix.lower()
                in {".py", ".js", ".cjs", ".mjs", ".sh"}
            )
    edges = _path_edges(
        source_path,
        paths,
        confidence=ReferenceConfidence.PROVED,
        kind=EdgeKind.MCP_TO_SERVER,
    )
    edges.extend(
        ReferenceEdge.create(
            source_path,
            f"env:{name}",
            EdgeKind.ENV_VAR_NAME,
            ReferenceConfidence.PROVED,
        )
        for name in sorted(environment_names)
    )
    return edges


def _config_edges(source_path: str, text: str) -> list[ReferenceEdge]:
    values: list[str] = []
    if source_path.endswith(".json"):
        payload = _load_json(text, "JSON configuration")
        values.extend(_structured_values(payload))
    else:
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0]
            match = YAML_SCALAR.match(line)
            if match is None:
                continue
            value = match.group(1).strip()
            if value.startswith(("[", "{")):
                values.extend(
                    _structured_values(_load_json(value, "structured YAML value"))
                )
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
    return _path_edges(
        source_path,
        paths,
        confidence=(
            ReferenceConfidence.PROVED
            if source_path == "System/folder-paths.yaml"
            or source_path.startswith(".claude/hooks/")
            else ReferenceConfidence.INFERRED
        ),
    )


def extract_reference_edges(
    source_path: str,
    raw: bytes,
    *,
    skill_paths: Mapping[str, str],
) -> tuple[ReferenceEdge, ...]:
    """Extract deterministic edges from already safety-checked source bytes."""
    # .mcp.json is the one credential-adjacent exception because it is the
    # machinery's registration surface. Its structural walk emits env names,
    # never env values or other non-name env tokens.
    if source_path != ".mcp.json" and is_reference_read_restricted_path(source_path):
        return ()
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("source exceeds the reference extraction bound")
    suffix = PurePosixPath(source_path).suffix.lower()
    if suffix == ".plist":
        edges = _plist_edges(source_path, raw)
        unique = {edge.edge_id: edge for edge in edges}
        return tuple(sorted(unique.values(), key=lambda edge: edge.edge_id))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ()
    if source_path == ".mcp.json":
        payload = _load_json(text, "MCP configuration")
        edges = _mcp_edges(source_path, payload)
        unique = {edge.edge_id: edge for edge in edges}
        return tuple(sorted(unique.values(), key=lambda edge: edge.edge_id))
    name = PurePosixPath(source_path).name
    if (
        name == "package.json"
        or name == "requirements.txt"
        or name.startswith("requirements-") and name.endswith(".txt")
    ):
        edges = _package_edges(source_path, text)
        unique = {edge.edge_id: edge for edge in edges}
        return tuple(sorted(unique.values(), key=lambda edge: edge.edge_id))
    edges: list[ReferenceEdge] = []
    if suffix in {".md", ".markdown"} or PurePosixPath(source_path).name == "SKILL.md":
        edges.extend(_markdown_edges(source_path, text, skill_paths))
    if suffix == ".py":
        edges.extend(_python_edges(source_path, text))
    elif suffix in {".sh", ".bash", ".zsh"}:
        edges.extend(_shell_edges(source_path, text, skill_paths))
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
    elif suffix in {".json", ".yaml", ".yml"}:
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


__all__ = [
    "MAX_SOURCE_BYTES",
    "ReferenceParseError",
    "extract_reference_edges",
    "extract_settings_hook_edges",
    "is_reference_read_restricted_path",
    "read_settings_hook_edges",
]
