"""Where Archives and Resources live, and which top-level folders are known.

Filing automations should call locate_vault_folders before creating folders.
The safety gate uses the same map so a new top-level folder is refused.
This module stays dependency-free so the portable plugin can vendor it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

DEFAULT_ARCHIVES = "07-Archives"
DEFAULT_RESOURCES = "06-Resources"
FOLDER_MAP_RELATIVE = "System/folder-paths.yaml"
MAX_FOLDER_MAP_BYTES = 256 * 1024
FOLDER_KEY = re.compile(r"^[a-z][a-z0-9_]*$")

# Known Dex top-level folders that setup and everyday flows may create.
KNOWN_TOP_LEVEL = frozenset(
    {
        "00-Inbox",
        "01-Quarter_Goals",
        "02-Week_Priorities",
        "03-Tasks",
        "04-Projects",
        "05-Areas",
        "06-Resources",
        "07-Archives",
        "System",
    }
)
KNOWN_DOT_TOP_LEVEL = frozenset(
    {
        ".agents",
        ".claude",
        ".cursor",
        ".git",
        ".github",
        ".obsidian",
        ".scripts",
        ".venv",
    }
)
MKDIR_COMMAND = re.compile(
    r"(?:^|[;&|\n]|&&|\|\|)\s*mkdir\b(?P<args>[^;&|\n]*)",
    re.IGNORECASE,
)
CURL_COMMAND = re.compile(
    r"(?:^|[;&|\n]|&&|\|\|)\s*curl\b(?P<args>[^;&|\n]*)",
    re.IGNORECASE,
)
CP_MV_COMMAND = re.compile(
    r"(?:^|[;&|\n]|&&|\|\|)\s*(?:cp|mv)\b(?P<args>[^;&|\n]*)",
    re.IGNORECASE,
)


def locate_vault_folders(vault: Path) -> dict[str, Any]:
    """Return the real Archives and Resources folders for *vault*."""
    locations = read_folder_locations(vault)
    archives = locations["archives"]
    resources = locations["resources"]
    return {
        "success": True,
        "archives": archives,
        "resources": resources,
        "message": (
            f"Archives live in {archives}. "
            f"Reference material lives in {resources}. "
            "Do not create a new top-level folder for either."
        ),
    }


def new_top_level_folder_reason(
    vault: Path,
    path: str,
    *,
    as_directory: bool = False,
) -> str | None:
    """Explain why *path* would invent a new top-level folder, or None."""
    name = planned_new_top_level(vault, path, as_directory=as_directory)
    if name is None:
        return None
    locations = locate_vault_folders(vault)
    return (
        f"Blocked: that would create a new top-level folder named {name}. "
        f"Archives live in {locations['archives']} and reference material "
        f"lives in {locations['resources']}. Call locate_vault_folders to "
        "see the real paths."
    )


def planned_new_top_level(
    vault: Path,
    path: str,
    *,
    as_directory: bool = False,
) -> str | None:
    """Return the new top-level folder *path* would create, or None."""
    parts = _vault_relative_parts(vault, path)
    if not parts:
        return None
    if not as_directory and len(parts) == 1:
        return None
    first = parts[0]
    if first in {".", ".."}:
        return None
    allowed = {name.casefold() for name in allowed_top_level_names(vault)}
    if first.casefold() in allowed:
        return None
    return first


def allowed_top_level_names(vault: Path) -> frozenset[str]:
    """Known, remapped, and already-present top-level folder names."""
    names = set(KNOWN_TOP_LEVEL)
    names.update(KNOWN_DOT_TOP_LEVEL)
    names.update(read_folder_locations(vault)["extra_top_level"])
    try:
        for child in Path(vault).iterdir():
            if child.is_dir():
                names.add(child.name)
    except OSError:
        pass
    return frozenset(names)


def read_folder_locations(vault: Path) -> dict[str, Any]:
    """Read Archives/Resources paths and remapped top-level names."""
    archives = DEFAULT_ARCHIVES
    resources = DEFAULT_RESOURCES
    extra: set[str] = set()
    payload = _read_folder_map(vault)
    if payload:
        mapped_archives = payload.get("archives")
        mapped_resources = payload.get("resources")
        if isinstance(mapped_archives, str) and mapped_archives.strip():
            archives = _normalize_relative(mapped_archives) or archives
        if isinstance(mapped_resources, str) and mapped_resources.strip():
            resources = _normalize_relative(mapped_resources) or resources
        for value in payload.values():
            if not isinstance(value, str):
                continue
            normalized = _normalize_relative(value)
            if normalized:
                extra.add(normalized.split("/", 1)[0])
    extra.update(archives.split("/", 1)[:1])
    extra.update(resources.split("/", 1)[:1])
    return {
        "archives": archives,
        "resources": resources,
        "extra_top_level": tuple(sorted(extra)),
    }


def mkdir_targets(command: str) -> list[str]:
    """Return directory operands of mkdir invocations in *command*."""
    targets: list[str] = []
    for match in MKDIR_COMMAND.finditer(command):
        skip_next = False
        for token in _tokenize(match.group("args")):
            if skip_next:
                skip_next = False
                continue
            if token in {"-m", "--mode"}:
                skip_next = True
                continue
            if token == "--" or token.startswith("-"):
                continue
            targets.append(token)
    return targets


def shell_write_targets(command: str) -> list[str]:
    """Return easily parsed shell write destinations in *command*.

    Covers ``curl -o/--output/--output-dir``, ``cp``/``mv`` destinations
    (including ``-tDIR``), and ``>``/``>>``/``>|``/``>!`` redirects. This is
    not a shell parser: quoted simple forms are read; indirection, python
    one-liners, and unknown flags are skipped.
    """
    targets: list[str] = []
    for match in CURL_COMMAND.finditer(command):
        targets.extend(_curl_output_targets(match.group("args")))
    for match in CP_MV_COMMAND.finditer(command):
        targets.extend(_cp_mv_destinations(match.group("args")))
    targets.extend(_redirect_targets(command))
    return targets


def _vault_relative_parts(vault: Path, candidate: str) -> tuple[str, ...] | None:
    if not candidate or not isinstance(candidate, str):
        return None
    try:
        if candidate.startswith("~/"):
            expanded = Path.home() / candidate[2:]
        elif candidate.startswith("$HOME/"):
            expanded = Path.home() / candidate[6:]
        else:
            expanded = Path(candidate)
        root = Path(vault).resolve()
        resolved = expanded.resolve() if expanded.is_absolute() else (root / expanded).resolve()
        relative = resolved.relative_to(root)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return relative.parts


def _read_folder_map(vault: Path) -> dict[str, str] | None:
    path = Path(vault) / FOLDER_MAP_RELATIVE
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        return _parse_flat_folder_map(raw)
    except ValueError:
        return None


def _parse_flat_folder_map(raw: bytes) -> dict[str, str]:
    """Parse the contract's deliberately flat ``semantic: path`` YAML form."""
    if len(raw) > MAX_FOLDER_MAP_BYTES:
        raise ValueError("folder map exceeds its configured byte bound")
    result: dict[str, str] = {}
    for line_number, raw_line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in raw_line or ":" not in line or any(token in line for token in ("&", "*", "<<")):
            raise ValueError(f"folder map line {line_number} is not a flat scalar mapping")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if FOLDER_KEY.fullmatch(key) is None or key in result:
            raise ValueError(f"folder map line {line_number} has an invalid or duplicate key")
        if value.startswith('"'):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError(f"folder map line {line_number} has an invalid quoted path") from error
            if not isinstance(parsed, str):
                raise ValueError(f"folder map line {line_number} path must be a string")
            value = parsed
        elif value.startswith("'"):
            if len(value) < 2 or not value.endswith("'"):
                raise ValueError(f"folder map line {line_number} has an invalid quoted path")
            value = value[1:-1].replace("''", "'")
        else:
            value = value.split(" #", 1)[0].rstrip()
            if not value or value[0] in "[{!":
                raise ValueError(f"folder map line {line_number} path must be a scalar string")
        result[key] = value
    return result


def _normalize_relative(value: str) -> str | None:
    collapsed = value.replace("\\", "/").strip().strip("/")
    if not collapsed or collapsed.startswith("/") or any(part in {"", ".", ".."} for part in collapsed.split("/")):
        return None
    return collapsed


_CURL_NOARG_SHORT = frozenset("sSiIkLvqn#gGjf")


def _short_cluster_output_path(token: str) -> str | None:
    """Return the attached PATH for ``-o`` / ``-sSo`` clusters, or None.

    Scans short-option letters left to right. No-arg letters may precede a
    terminating ``o``. ``-socks5`` is not an output cluster (see the caller).
    """
    if not token.startswith("-") or token.startswith("--"):
        return None
    body = token[1:]
    index = 0
    while index < len(body) and body[index] in _CURL_NOARG_SHORT:
        index += 1
    if index >= len(body) or body[index] != "o":
        return None
    return body[index + 1 :]


def _curl_filename_is_relative(name: str) -> bool:
    """True when a curl ``-o`` path is cwd-relative, not absolute or home/env."""
    if not name or name.startswith(("/", "\\", "~", "$")):
        return False
    try:
        return not Path(name).is_absolute()
    except (OSError, TypeError, ValueError):
        return True


def _curl_output_targets(args: str) -> list[str]:
    tokens = _tokenize(args)
    targets: list[str] = []
    output_dir: str | None = None
    skip_next = False
    for index, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        if token == "--output-dir":
            if index + 1 < len(tokens) and tokens[index + 1] not in {"", "-"}:
                output_dir = tokens[index + 1]
            skip_next = True
            continue
        if token.startswith("--output-dir="):
            value = token.split("=", 1)[1]
            if value and value != "-":
                output_dir = value
            continue
        if token in {"-O", "--remote-name", "--remote-name-all"}:
            continue
        if token in {"-o", "--output"}:
            if index + 1 < len(tokens) and tokens[index + 1] not in {"", "-"}:
                targets.append(tokens[index + 1])
            skip_next = True
            continue
        if token.startswith("--output="):
            value = token.split("=", 1)[1]
            if value and value != "-":
                targets.append(value)
            continue
        if token.startswith("--"):
            continue
        if token.startswith("-socks"):
            continue
        attached = _short_cluster_output_path(token)
        if attached is None:
            continue
        if attached and attached != "-":
            targets.append(attached)
            continue
        if attached == "":
            if index + 1 < len(tokens) and tokens[index + 1] not in {"", "-"}:
                targets.append(tokens[index + 1])
            skip_next = True
    if output_dir:
        combined = [output_dir]
        for target in targets:
            if _curl_filename_is_relative(target):
                combined.append(f"{output_dir.rstrip('/\\')}/{target}")
            else:
                combined.append(target)
        return combined
    return targets


def _cp_mv_destinations(args: str) -> list[str]:
    tokens = _tokenize(args)
    destinations: list[str] = []
    operands: list[str] = []
    skip_next = False
    take_destination = False
    for token in tokens:
        if skip_next:
            if take_destination and token not in {"", "-"}:
                destinations.append(token)
            take_destination = False
            skip_next = False
            continue
        if token in {"-t", "--target-directory"}:
            skip_next = True
            take_destination = True
            continue
        if token.startswith("--target-directory="):
            value = token.split("=", 1)[1]
            if value and value != "-":
                destinations.append(value)
            continue
        if token.startswith("-t") and not token.startswith("--"):
            value = token[2:]
            if value and value != "-":
                destinations.append(value)
            continue
        if token == "--" or token.startswith("-"):
            continue
        operands.append(token)
    if not destinations and len(operands) >= 2:
        destinations.append(operands[-1])
    return destinations


def _redirect_targets(command: str) -> list[str]:
    """Return operands of unquoted ``>`` / ``>>`` redirects."""
    targets: list[str] = []
    quote: str | None = None
    index = 0
    length = len(command)
    while index < length:
        char = command[index]
        if quote is not None:
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'"}:
            quote = char
            index += 1
            continue
        if char == "<":
            index += 1
            continue
        if char != ">":
            index += 1
            continue
        index += 1
        if index < length and command[index] == ">":
            index += 1
        if index < length and command[index] in {"|", "!"}:
            index += 1
        while index < length and command[index].isspace():
            index += 1
        if index >= length:
            break
        if command[index] in {'"', "'"}:
            closer = command[index]
            index += 1
            start = index
            while index < length and command[index] != closer:
                index += 1
            token = command[start:index]
            if token:
                targets.append(token)
            if index < length:
                index += 1
            continue
        start = index
        while index < length and not command[index].isspace() and command[index] not in ";|&<>":
            index += 1
        token = command[start:index]
        if token and token not in {"-", "&1", "&2"}:
            targets.append(token)
    return targets


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in text:
        if quote is not None:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char.isspace():
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def iter_mkdir_targets(command: str) -> Iterable[str]:
    """Compatibility alias used by tests and the safety gate."""
    return mkdir_targets(command)
