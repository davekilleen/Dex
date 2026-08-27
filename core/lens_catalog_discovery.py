"""Repository-backed discovery for Dex Lens catalogue capabilities."""

from __future__ import annotations

import ast
import plistlib
import re
from dataclasses import dataclass
from pathlib import Path

from core.lens_catalog_sources import SkillSourceError, require_release_file

SKILL_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
MCP_SERVER_GLOBS: tuple[str, ...] = (
    "core/mcp/*_server.py",
    "core/integrations/*/*_server.py",
)


class LensDiscoveryError(RuntimeError):
    """A shipped capability cannot be discovered without ambiguity."""


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    """One active, first-party skill discovered from a release tree."""

    capability_id: str
    name: str
    description: str
    source_path: str


@dataclass(frozen=True, slots=True)
class McpServerCandidate:
    capability_id: str
    server_name: str
    source_path: str
    tool_count: int
    example_tools: tuple[str, ...]
    tools: tuple[str, ...]
    has_feature_status: bool


@dataclass(frozen=True, slots=True)
class ScheduledAutomationCandidate:
    capability_id: str
    automation_label: str
    cadence: str
    source_paths: tuple[str, ...]
    installer_path: str
    program_target: str
    run_at_load: bool


@dataclass(frozen=True, slots=True)
class SystemEngineCandidate:
    capability_id: str
    availability: str
    source_paths: tuple[str, ...]
    component_count: int
    example_components: tuple[str, ...]


def _frontmatter_scalar(raw_value: str, *, context: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as error:
            raise LensDiscoveryError(f"{context} is not a valid quoted scalar") from error
        if not isinstance(parsed, str):
            raise LensDiscoveryError(f"{context} must be text")
        value = parsed
    if not value:
        raise LensDiscoveryError(f"{context} must be non-empty")
    if CONTROL.search(value):
        raise LensDiscoveryError(f"{context} contains control characters")
    return value


def _skill_frontmatter(path: Path, *, skill_id: str) -> tuple[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise LensDiscoveryError(f"cannot read active skill {path}: {error}") from error
    if not text.startswith("---\n"):
        raise LensDiscoveryError(f"active skill {path} has no frontmatter")

    fields: dict[str, str] = {}
    for line in text.splitlines()[1:]:
        if line == "---":
            break
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        if key in {"name", "description"}:
            if key in fields:
                raise LensDiscoveryError(f"active skill {path} repeats {key}")
            fields[key] = _frontmatter_scalar(raw_value, context=f"active skill {path} {key}")
    else:
        raise LensDiscoveryError(f"active skill {path} has unclosed frontmatter")

    if "name" not in fields:
        raise LensDiscoveryError(f"active skill {path} has no name")
    if "description" not in fields:
        raise LensDiscoveryError(f"active skill {path} has no description")
    if fields["name"] != skill_id:
        raise LensDiscoveryError(
            f"active skill {path} name {fields['name']!r} does not match its directory {skill_id!r}"
        )
    return fields["name"], fields["description"]


def discover_active_skills(release_root: Path) -> tuple[SkillCandidate, ...]:
    """Discover direct, active, first-party skill payloads in a release tree."""

    root = release_root.resolve(strict=True)
    skills_root = root / ".claude" / "skills"
    if skills_root.is_symlink() or not skills_root.is_dir():
        raise LensDiscoveryError(f"active skills directory is missing or unsafe: {skills_root}")

    candidates: list[SkillCandidate] = []
    for directory in sorted(skills_root.iterdir(), key=lambda path: path.name):
        skill_id = directory.name
        if skill_id == "_available" or skill_id.startswith("anthropic-"):
            continue
        if directory.is_symlink():
            raise LensDiscoveryError(f"active skill directory is missing or unsafe: {directory}")
        if not directory.is_dir():
            continue
        if SKILL_ID.fullmatch(skill_id) is None:
            raise LensDiscoveryError(f"active skill directory is not kebab-case: {skill_id!r}")

        payload = directory / "SKILL.md"
        if payload.is_symlink():
            raise LensDiscoveryError(f"active skill payload is missing or not a regular file: {payload}")
        if not payload.exists():
            continue
        if not payload.is_file():
            raise LensDiscoveryError(f"active skill payload is missing or not a regular file: {payload}")
        name, description = _skill_frontmatter(payload, skill_id=skill_id)
        candidates.append(
            SkillCandidate(
                capability_id=skill_id,
                name=name,
                description=description,
                source_path=f".claude/skills/{skill_id}/SKILL.md",
            )
        )
    return tuple(candidates)


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword_string(call: ast.Call, keyword: str) -> str | None:
    for item in call.keywords:
        if item.arg == keyword:
            return _string(item.value)
    return None


def _literal_tool_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return {value for item in node.elts if (value := _string(item)) and TOOL_NAME.fullmatch(value)}
    value = _string(node)
    return {value} if value is not None and TOOL_NAME.fullmatch(value) else set()


def _dispatch_tool_names(compare: ast.Compare) -> set[str]:
    names: set[str] = set()
    operands = [compare.left, *compare.comparators]
    for index, operator in enumerate(compare.ops):
        left = operands[index]
        right = operands[index + 1]
        left_is_name = isinstance(left, ast.Name) and left.id == "name"
        right_is_name = isinstance(right, ast.Name) and right.id == "name"
        if isinstance(operator, ast.Eq):
            if left_is_name:
                names.update(_literal_tool_names(right))
            elif right_is_name:
                names.update(_literal_tool_names(left))
        elif isinstance(operator, ast.In) and left_is_name:
            names.update(_literal_tool_names(right))
    return names


def _is_list_tools_handler(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr == "list_tools"
        for decorator in node.decorator_list
    )


def discover_mcp_server_source(release_root: Path, path: Path) -> McpServerCandidate:
    """Parse one MCP server using the shared architecture/Lens rules."""

    root = release_root.resolve(strict=True)
    relative = path.relative_to(root).as_posix()
    try:
        path = require_release_file(root, relative, context=f"MCP server {relative}")
    except SkillSourceError as error:
        raise LensDiscoveryError(str(error)) from error
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative)
    except (OSError, UnicodeError, SyntaxError) as error:
        raise LensDiscoveryError(f"cannot parse MCP server {relative}: {error}") from error

    server_names: list[str] = []
    registered_tools: set[str] = set()
    dispatched_tools: set[str] = set()
    has_list_tools = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_name = _call_name(node)
            if call_name == "Server" and node.args:
                if (server_name := _string(node.args[0])) is not None:
                    server_names.append(server_name)
            elif call_name == "Tool":
                tool_name = _keyword_string(node, "name")
                if tool_name is None and node.args:
                    tool_name = _string(node.args[0])
                if tool_name is not None and TOOL_NAME.fullmatch(tool_name):
                    registered_tools.add(tool_name)
        elif isinstance(node, ast.Compare):
            dispatched_tools.update(_dispatch_tool_names(node))
        if _is_list_tools_handler(node):
            has_list_tools = True

    if len(server_names) != 1:
        raise LensDiscoveryError(
            f"expected exactly one literal Server name in {relative}; found {sorted(server_names)}"
        )
    server_name = server_names[0]
    if not server_name.startswith("dex-"):
        raise LensDiscoveryError(f"MCP server {relative} does not use a dex- server name")
    if not has_list_tools:
        raise LensDiscoveryError(f"MCP server {relative} has no list-tools handler")
    tools = tuple(sorted(registered_tools | dispatched_tools))
    if not tools:
        raise LensDiscoveryError(f"MCP server {relative} exposes no literal tools")
    return McpServerCandidate(
        capability_id=server_name,
        server_name=server_name,
        source_path=relative,
        tool_count=len(tools),
        example_tools=tools[:5],
        tools=tools,
        has_feature_status="feature_status" in source,
    )


def mcp_server_sources(release_root: Path) -> tuple[Path, ...]:
    """Return every reviewed MCP server source in a release tree."""

    root = release_root.resolve(strict=True)
    sources = {
        path
        for pattern in MCP_SERVER_GLOBS
        for path in root.glob(pattern)
        if path.is_file()
    }
    return tuple(sorted(sources, key=lambda path: path.relative_to(root).as_posix()))


def discover_mcp_servers(release_root: Path) -> tuple[McpServerCandidate, ...]:
    """Discover the reviewed Core MCP boundary and its literal exposed tools."""

    root = release_root.resolve(strict=True)
    candidates = [
        discover_mcp_server_source(root, path)
        for path in mcp_server_sources(root)
    ]
    return tuple(sorted(candidates, key=lambda item: (item.server_name, item.source_path)))


AUTOMATION_INSTALLERS = {
    ".scripts/com.dex.changelog-checker.plist": ".scripts/install-learning-automation.sh",
    ".scripts/com.dex.learning-review.plist": ".scripts/install-learning-automation.sh",
    ".scripts/com.dex.smoke-nightly.plist.template": ".scripts/install-smoke-automation.sh",
    ".scripts/meeting-intel/com.dex.meeting-intel.plist.template": ".scripts/meeting-intel/install-automation.sh",
}


def _automation_cadence(payload: dict[str, object], *, source: str) -> str:
    suffix = "; also at load" if payload.get("RunAtLoad") is True else ""
    if type(interval := payload.get("StartInterval")) is int and interval > 0:
        if interval % 3600 == 0:
            amount = interval // 3600
            unit = "hour" if amount == 1 else "hours"
        elif interval % 60 == 0:
            amount = interval // 60
            unit = "minute" if amount == 1 else "minutes"
        else:
            amount = interval
            unit = "second" if amount == 1 else "seconds"
        return f"every {amount} {unit}{suffix}"
    calendar = payload.get("StartCalendarInterval")
    if isinstance(calendar, dict) and set(calendar) <= {"Hour", "Minute"}:
        hour = calendar.get("Hour")
        minute = calendar.get("Minute", 0)
        if type(hour) is int and 0 <= hour <= 23 and type(minute) is int and 0 <= minute <= 59:
            return f"daily at {hour:02d}:{minute:02d}{suffix}"
    raise LensDiscoveryError(f"scheduled automation {source} has an unsupported cadence")


def discover_scheduled_automations(release_root: Path) -> tuple[ScheduledAutomationCandidate, ...]:
    """Discover the four shipped plist jobs and the configurable backup job."""

    root = release_root.resolve(strict=True)
    candidates: list[ScheduledAutomationCandidate] = []
    for source, installer in AUTOMATION_INSTALLERS.items():
        try:
            path = require_release_file(root, source, context=f"scheduled automation source {source}")
            require_release_file(root, installer, context=f"scheduled automation installer {installer}")
        except SkillSourceError as error:
            raise LensDiscoveryError(str(error)) from error
        try:
            with path.open("rb") as handle:
                payload = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException) as error:
            raise LensDiscoveryError(f"cannot parse scheduled automation {source}: {error}") from error
        label = payload.get("Label")
        arguments = payload.get("ProgramArguments")
        if not isinstance(label, str) or not label.startswith("com.dex."):
            raise LensDiscoveryError(f"scheduled automation {source} has no com.dex label")
        if not isinstance(arguments, list) or not arguments or not all(isinstance(item, str) for item in arguments):
            raise LensDiscoveryError(f"scheduled automation {source} has no literal program target")
        candidates.append(
            ScheduledAutomationCandidate(
                capability_id=f"dex-{label.removeprefix('com.dex.').replace('.', '-')}",
                automation_label=label,
                cadence=_automation_cadence(payload, source=source),
                source_paths=(source, installer),
                installer_path=installer,
                program_target=arguments[-1],
                run_at_load=payload.get("RunAtLoad") is True,
            )
        )

    backup_installer = "core/backup/install_backup_job.py"
    backup_target = "core/backup/backup_vault.py"
    for relative in (backup_installer, backup_target):
        try:
            require_release_file(root, relative, context=f"backup automation source {relative}")
        except SkillSourceError as error:
            raise LensDiscoveryError(str(error)) from error
    candidates.append(
        ScheduledAutomationCandidate(
            capability_id="dex-vault-backup",
            automation_label="com.dex.vault-backup",
            cadence="daily at a user-selected time",
            source_paths=(backup_installer, backup_target),
            installer_path=backup_installer,
            program_target=backup_target,
            run_at_load=False,
        )
    )
    return tuple(sorted(candidates, key=lambda item: item.capability_id))


def _safe_files(root: Path, paths: list[Path], *, capability_id: str) -> tuple[str, ...]:
    result = []
    seen: set[str] = set()
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        if relative in seen:
            raise LensDiscoveryError(f"system engine {capability_id} repeats component {relative}")
        seen.add(relative)
        try:
            require_release_file(root, relative, context=f"system engine {capability_id} component")
        except SkillSourceError as error:
            raise LensDiscoveryError(str(error)) from error
        result.append(relative)
    if not result:
        raise LensDiscoveryError(f"system engine {capability_id} resolved no components")
    return tuple(result)


def discover_system_engines(release_root: Path) -> tuple[SystemEngineCandidate, ...]:
    """Resolve the publisher-reviewed system-engine groups."""

    root = release_root.resolve(strict=True)
    groups = {
        "connection-manager-engine": (
            "parked",
            [
                path
                for path in (root / "core/integrations/connection-manager").rglob("*")
                if path.is_file()
                and path.suffix in {".cjs", ".js"}
                and ".test." not in path.name
                and ".child." not in path.name
            ],
        ),
        "entity-temperature-engine": (
            "active",
            list((root / "core/entity_engine").glob("*.py")),
        ),
        "proactive-promise-engine": (
            "active",
            [root / "core/health/promises.py", root / "core/tests/test_health_promises.py"],
        ),
        "ritual-intelligence-engine": (
            "parked",
            list((root / "core/ritual_intelligence").glob("*.py")),
        ),
        "session-hook-orchestration": (
            "active",
            [
                path
                for path in (root / ".claude/hooks").rglob("*")
                if path.is_file() and "tests" not in path.relative_to(root / ".claude/hooks").parts
            ],
        ),
    }
    candidates = []
    for capability_id, (availability, paths) in groups.items():
        sources = _safe_files(root, paths, capability_id=capability_id)
        candidates.append(
            SystemEngineCandidate(
                capability_id=capability_id,
                availability=availability,
                source_paths=sources,
                component_count=len(sources),
                example_components=sources[:5],
            )
        )
    return tuple(sorted(candidates, key=lambda item: item.capability_id))
