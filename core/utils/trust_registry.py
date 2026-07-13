"""Fail-closed trust registry and snapshots for user-owned local MCP servers."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

REGISTRY_RELATIVE = Path("System/trusted-mcps.yaml")
MAX_REGISTRY_BYTES = 64 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
ENTRY_KEYS = frozenset({"file", "sha256"})


class TrustRegistryError(ValueError):
    """A trust declaration or no-follow filesystem operation was refused."""


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise TrustRegistryError("registry mapping keys must be scalar") from exc
        if duplicate:
            raise TrustRegistryError(f"registry contains duplicate key {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True)
class TrustedMcpEntry:
    """The exact identity a user blessed for recurring startup checks."""

    name: str
    file: str
    sha256: str


@dataclass(frozen=True)
class TrustedMcpRegistry:
    """Loaded registry state; invalid registries deliberately expose no entries."""

    entries: Mapping[str, TrustedMcpEntry]
    present: bool
    invalid_reason: str | None = None


@dataclass(frozen=True)
class TrustedMcpSnapshot:
    """A decision plus the only script path recurring checks may execute."""

    trusted: bool
    detail: str
    snapshot_path: Path | None = None
    sha256: str | None = None


def normalize_vault_relative(value: object) -> str:
    """Return one normalized POSIX vault-relative path or reject it."""
    if not isinstance(value, str) or not value.strip() or "\\" in value:
        raise TrustRegistryError("file must be a non-empty vault-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise TrustRegistryError(f"unsafe vault-relative path {value!r}")
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts:
        raise TrustRegistryError("file must name a vault-relative file")
    return PurePosixPath(*parts).as_posix()


def _configured_relative(vault_root: Path, argument: str) -> str:
    if "\\" in argument:
        raise TrustRegistryError("configured script path must use a vault path")
    argument_path = Path(argument)
    if argument_path.is_absolute():
        lexical_root = Path(os.path.abspath(vault_root))
        lexical_argument = Path(os.path.abspath(argument_path))
        try:
            argument_path = lexical_argument.relative_to(lexical_root)
        except ValueError as exc:
            raise TrustRegistryError("configured script path is outside the vault") from exc
    return normalize_vault_relative(argument_path.as_posix())


def _open_component_file(
    root: Path,
    relative: Path,
    *,
    label: str,
) -> tuple[int, os.stat_result]:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise TrustRegistryError("safe no-follow file reads are unavailable")
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | no_follow | directory_flag | close_on_exec
    file_flags = os.O_RDONLY | no_follow | close_on_exec
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = os.open(root, directory_flags)
        for part in relative.parts[:-1]:
            component_stat = os.stat(part, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISLNK(component_stat.st_mode):
                raise TrustRegistryError(f"{label} path contains a symlink")
            if not stat.S_ISDIR(component_stat.st_mode):
                raise TrustRegistryError(f"{label} path contains a non-directory component")
            child_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        final_stat = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(final_stat.st_mode):
            raise TrustRegistryError(f"{label} is symlinked")
        file_fd = os.open(relative.name, file_flags, dir_fd=directory_fd)
        opened_stat = os.fstat(file_fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise TrustRegistryError(f"{label} is not a regular file")
        if (opened_stat.st_dev, opened_stat.st_ino) != (final_stat.st_dev, final_stat.st_ino):
            raise TrustRegistryError(f"{label} changed while it was opened")
        return file_fd, opened_stat
    except FileNotFoundError as exc:
        if file_fd is not None:
            os.close(file_fd)
        raise TrustRegistryError(f"{label} is missing") from exc
    except OSError as exc:
        if file_fd is not None:
            os.close(file_fd)
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise TrustRegistryError(f"{label} path contains a symlink") from exc
        raise TrustRegistryError(f"{label} could not be opened safely: {exc}") from exc
    except TrustRegistryError:
        if file_fd is not None:
            os.close(file_fd)
        raise
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _read_fd(fd: int, *, maximum: int | None = None) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if maximum is not None and size > maximum:
            raise TrustRegistryError("registry is larger than 64KB")


def _parse_registry(content: bytes) -> dict[str, TrustedMcpEntry]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrustRegistryError("registry is not valid UTF-8") from exc
    try:
        if any(getattr(event, "anchor", None) is not None for event in yaml.parse(text)):
            raise TrustRegistryError("registry contains YAML anchors or aliases")
        parsed: Any = yaml.load(text, Loader=_UniqueKeyLoader)
    except TrustRegistryError:
        raise
    except yaml.YAMLError as exc:
        raise TrustRegistryError(f"registry YAML is invalid: {exc}") from exc

    if not isinstance(parsed, Mapping) or set(parsed) != {"trusted_mcps"}:
        raise TrustRegistryError("registry must be a mapping containing only trusted_mcps")
    raw_entries = parsed["trusted_mcps"]
    if not isinstance(raw_entries, Mapping):
        raise TrustRegistryError("trusted_mcps must be a mapping")

    entries: dict[str, TrustedMcpEntry] = {}
    for name, raw_entry in raw_entries.items():
        if not isinstance(name, str) or not name.startswith("custom-") or not name.strip():
            raise TrustRegistryError("trusted MCP names must be non-empty custom-* names")
        if not isinstance(raw_entry, Mapping):
            raise TrustRegistryError(f"{name}: registry entry must be a mapping")
        unknown = set(raw_entry) - ENTRY_KEYS
        if unknown:
            rendered = ", ".join(sorted(str(key) for key in unknown))
            raise TrustRegistryError(f"{name}: unknown key(s): {rendered}")
        if set(raw_entry) != ENTRY_KEYS:
            raise TrustRegistryError(f"{name}: registry entry requires file and sha256")
        normalized = normalize_vault_relative(raw_entry["file"])
        digest = raw_entry["sha256"]
        if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
            raise TrustRegistryError(f"{name}: sha256 must be 64 lowercase hexadecimal characters")
        entries[name] = TrustedMcpEntry(name=name, file=normalized, sha256=digest)
    return entries


def load_trusted_mcp_registry(vault_root: Path) -> TrustedMcpRegistry:
    """Load the user-owned registry; any rejection makes all entries unavailable."""
    path = vault_root / REGISTRY_RELATIVE
    if not path.exists() and not path.is_symlink():
        return TrustedMcpRegistry(entries={}, present=False)
    descriptor: int | None = None
    try:
        descriptor, opened_stat = _open_component_file(
            vault_root,
            REGISTRY_RELATIVE,
            label=REGISTRY_RELATIVE.as_posix(),
        )
        if opened_stat.st_size > MAX_REGISTRY_BYTES:
            raise TrustRegistryError("registry is larger than 64KB")
        entries = _parse_registry(_read_fd(descriptor, maximum=MAX_REGISTRY_BYTES))
    except TrustRegistryError as exc:
        return TrustedMcpRegistry(entries={}, present=True, invalid_reason=str(exc))
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return TrustedMcpRegistry(entries=entries, present=True)


def _local_python_relative(
    vault_root: Path,
    entry: object,
) -> str:
    if not isinstance(entry, Mapping):
        raise TrustRegistryError("only local Python MCP entries can be blessed")
    if entry.get("type") in {"http", "sse", "streamable-http"} or "url" in entry:
        raise TrustRegistryError("only local Python MCP entries can be blessed; remote entries stay structural-only")
    command = entry.get("command")
    if not isinstance(command, str) or os.path.abspath(command) != os.path.abspath(sys.executable):
        raise TrustRegistryError("only local Python MCP entries using the trusted interpreter can be blessed")
    args = entry.get("args")
    if (
        not isinstance(args, list)
        or len(args) != 1
        or not isinstance(args[0], str)
        or args[0].startswith("-")
        or Path(args[0]).suffix != ".py"
    ):
        raise TrustRegistryError("local Python entries require exactly one .py argument and no flags")
    return _configured_relative(vault_root, args[0])


def snapshot_trusted_mcp(
    vault_root: Path,
    name: str,
    entry: object,
    registry: TrustedMcpRegistry,
    snapshot_root: Path,
    *,
    after_open: Callable[[int], None] | None = None,
) -> TrustedMcpSnapshot:
    """Bind config identity and copy the blessed bytes from one open descriptor."""
    if registry.invalid_reason is not None:
        return TrustedMcpSnapshot(
            False,
            f"trusted MCP registry is invalid ({registry.invalid_reason})",
        )
    trusted_entry = registry.entries.get(name)
    if trusted_entry is None:
        return TrustedMcpSnapshot(False, "not registered under the same name")
    try:
        configured_relative = _local_python_relative(vault_root, entry)
    except TrustRegistryError as exc:
        return TrustedMcpSnapshot(False, str(exc))
    if configured_relative != trusted_entry.file:
        return TrustedMcpSnapshot(
            False,
            f"configured file does not match blessed file {trusted_entry.file}",
        )

    descriptor: int | None = None
    destination_fd: int | None = None
    destination: Path | None = None
    try:
        descriptor, _opened_stat = _open_component_file(
            vault_root,
            Path(trusted_entry.file),
            label=f"{trusted_entry.file} file",
        )
        if after_open is not None:
            after_open(descriptor)
        digest = hashlib.sha256()
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        actual_hash = digest.hexdigest()
        if actual_hash != trusted_entry.sha256:
            return TrustedMcpSnapshot(
                False,
                "changed since you blessed it (content differs) — re-bless via /create-mcp "
                "or edit System/trusted-mcps.yaml",
                sha256=actual_hash,
            )

        snapshot_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        destination = snapshot_root / f"{safe_name}-{actual_hash}.py"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        destination_fd = os.open(destination, flags, 0o400)
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                view = view[written:]
        os.fsync(destination_fd)
        os.fchmod(destination_fd, 0o400)
    except TrustRegistryError as exc:
        if destination is not None:
            destination.unlink(missing_ok=True)
        return TrustedMcpSnapshot(False, str(exc))
    except OSError as exc:
        if destination is not None:
            destination.unlink(missing_ok=True)
        return TrustedMcpSnapshot(False, f"trusted script snapshot failed: {exc}")
    finally:
        if destination_fd is not None:
            os.close(destination_fd)
        if descriptor is not None:
            os.close(descriptor)

    return TrustedMcpSnapshot(
        True,
        "trusted local Python snapshot is ready",
        snapshot_path=destination,
        sha256=actual_hash,
    )
