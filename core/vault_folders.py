"""Where Archives and Resources live, and which top-level folders are known.

Filing automations should call locate_vault_folders before creating folders.
The safety gate uses the same map so a new top-level folder is refused.
This module stays dependency-free so the portable plugin can vendor it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ShellWriteParse:
    """Write destinations the parser could name, plus whether anything was unknown.

    ``unresolved`` means the command used an option, redirect, or form that is
    not on the positive allowlist. Callers must refuse the whole command.
    """

    targets: tuple[str, ...]
    unresolved: bool


def parse_shell_writes(command: str) -> ShellWriteParse:
    """Parse curl/cp/mv/redirect write destinations, failing closed on unknowns."""
    targets: list[str] = []
    unresolved = False
    for match in CURL_COMMAND.finditer(command):
        parsed = _parse_curl_output(match.group("args"))
        targets.extend(parsed.targets)
        unresolved = unresolved or parsed.unresolved
    for match in CP_MV_COMMAND.finditer(command):
        parsed = _parse_cp_mv_destinations(match.group("args"))
        targets.extend(parsed.targets)
        unresolved = unresolved or parsed.unresolved
    parsed = _parse_redirects(command)
    targets.extend(parsed.targets)
    unresolved = unresolved or parsed.unresolved
    return ShellWriteParse(tuple(targets), unresolved)


def shell_write_targets(command: str) -> list[str]:
    """Return easily parsed shell write destinations in *command*.

    Covers understood ``curl -o/--output``, ``cp``/``mv`` destinations, and
    ``>``/``>>`` redirects. Unknown flags and operators are not guessed;
    ``parse_shell_writes`` reports those as ``unresolved``.
    """
    return list(parse_shell_writes(command).targets)


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
_CURL_NOARG_LONG = frozenset(
    {
        "--silent",
        "--show-error",
        "--fail",
        "--location",
        "--compressed",
        "--head",
        "--get",
    }
)
_CP_NOARG_SHORT = frozenset("afinprvR")


def _classify_curl_short(token: str) -> tuple[str, str] | None:
    """Return ``('none', '')`` or ``('out', attached)`` for a known short cluster.

    Attached is empty when the path is the next token. Unknown letters, ``-O``,
    and a single no-arg letter plus ``o`` plus remainder (``-socks5``) are None.
    """
    if not token.startswith("-") or token.startswith("--") or len(token) < 2:
        return None
    body = token[1:]
    if body[0] == "o":
        return ("out", body[1:])
    index = 0
    while index < len(body) and body[index] in _CURL_NOARG_SHORT:
        index += 1
    if index == len(body):
        return ("none", "")
    if body[index] != "o":
        return None
    attached = body[index + 1 :]
    if attached == "":
        return ("out", "")
    # Combined attached path is the documented ``-sSoPATH`` form: two or more
    # no-arg letters, then ``o``, then the path. One letter plus ``o`` plus
    # remainder is not a unique parse against unknown options.
    if index >= 2:
        return ("out", attached)
    return None


def _take_output_path(tokens: list[str], index: int) -> tuple[str | None, bool, bool]:
    """Return (path, skip_next, unresolved) for a flag that takes an output path."""
    if index + 1 >= len(tokens):
        return (None, False, True)
    value = tokens[index + 1]
    if value == "-":
        return (None, True, False)
    if not value:
        return (None, True, True)
    return (value, True, False)


def _parse_curl_output(args: str) -> ShellWriteParse:
    tokens = _tokenize(args)
    targets: list[str] = []
    unresolved = False
    skip_next = False
    end_of_options = False
    for index, token in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        if end_of_options or not token.startswith("-") or token == "-":
            continue
        if token == "--":
            end_of_options = True
            continue
        if token in {"-o", "--output"}:
            path, skip_next, missing = _take_output_path(tokens, index)
            if path:
                targets.append(path)
            unresolved = unresolved or missing
            continue
        if token.startswith("--output="):
            value = token.split("=", 1)[1]
            if value and value != "-":
                targets.append(value)
            elif value != "-":
                unresolved = True
            continue
        if token in _CURL_NOARG_LONG:
            continue
        if token.startswith("--"):
            unresolved = True
            continue
        classified = _classify_curl_short(token)
        if classified is None:
            unresolved = True
            continue
        kind, attached = classified
        if kind == "none":
            continue
        if attached:
            if attached != "-":
                targets.append(attached)
            continue
        path, skip_next, missing = _take_output_path(tokens, index)
        if path:
            targets.append(path)
        unresolved = unresolved or missing
    return ShellWriteParse(tuple(targets), unresolved)


def _curl_output_targets(args: str) -> list[str]:
    return list(_parse_curl_output(args).targets)


def _parse_cp_mv_destinations(args: str) -> ShellWriteParse:
    tokens = _tokenize(args)
    destinations: list[str] = []
    operands: list[str] = []
    unresolved = False
    skip_next = False
    take_destination = False
    end_of_options = False
    for token in tokens:
        if skip_next:
            if take_destination:
                if token and token != "-":
                    destinations.append(token)
                else:
                    unresolved = True
            take_destination = False
            skip_next = False
            continue
        if end_of_options:
            operands.append(token)
            continue
        if token == "--":
            end_of_options = True
            continue
        if token in {"-t", "--target-directory"}:
            skip_next = True
            take_destination = True
            continue
        if token.startswith("--target-directory="):
            value = token.split("=", 1)[1]
            if value and value != "-":
                destinations.append(value)
            else:
                unresolved = True
            continue
        if token.startswith("--"):
            unresolved = True
            continue
        if token.startswith("-t"):
            unresolved = True
            continue
        if token.startswith("-"):
            body = token[1:]
            if body and all(char in _CP_NOARG_SHORT for char in body):
                continue
            unresolved = True
            continue
        operands.append(token)
    if take_destination:
        unresolved = True
    if not destinations and len(operands) >= 2:
        destinations.append(operands[-1])
    return ShellWriteParse(tuple(destinations), unresolved)


def _skip_redirect_destination(command: str, index: int) -> int:
    length = len(command)
    while index < length and command[index].isspace():
        index += 1
    if index >= length:
        return index
    if command[index] in {'"', "'"}:
        closer = command[index]
        index += 1
        while index < length and command[index] != closer:
            index += 1
        if index < length:
            index += 1
        return index
    while index < length and not command[index].isspace() and command[index] not in ";|&<>":
        index += 1
    return index


def _read_redirect_destination(command: str, index: int) -> tuple[int, str | None]:
    length = len(command)
    while index < length and command[index].isspace():
        index += 1
    if index >= length:
        return (index, None)
    if command[index] in {'"', "'"}:
        closer = command[index]
        index += 1
        start = index
        while index < length and command[index] != closer:
            index += 1
        token = command[start:index]
        if index < length:
            index += 1
        return (index, token or None)
    start = index
    while index < length and not command[index].isspace() and command[index] not in ";|&<>":
        index += 1
    token = command[start:index]
    if token and token not in {"-", "&1", "&2"}:
        return (index, token)
    return (index, None)


def _parse_redirects(command: str) -> ShellWriteParse:
    """Parse unquoted ``>`` / ``>>`` destinations; unknown redirect forms fail closed."""
    targets: list[str] = []
    unresolved = False
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
        prev = command[index - 1] if index > 0 else ""
        if prev == "&" or prev.isdigit():
            unresolved = True
            index += 1
            if index < length and command[index] == ">":
                index += 1
            if index < length and command[index] in {"|", "!"}:
                index += 1
            index = _skip_redirect_destination(command, index)
            continue
        index += 1
        if index < length and command[index] == ">":
            index += 1
        if index < length and command[index] in {"|", "!"}:
            unresolved = True
            index += 1
            index = _skip_redirect_destination(command, index)
            continue
        index, token = _read_redirect_destination(command, index)
        if token:
            targets.append(token)
        else:
            unresolved = True
    return ShellWriteParse(tuple(targets), unresolved)


def _cp_mv_destinations(args: str) -> list[str]:
    return list(_parse_cp_mv_destinations(args).targets)


def _redirect_targets(command: str) -> list[str]:
    """Return operands of unquoted ``>`` / ``>>`` redirects."""
    return list(_parse_redirects(command).targets)


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
