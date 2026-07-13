"""Fail-closed trust registry and snapshots for user-owned local MCP servers."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
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

    return _snapshot_local_python_file(
        vault_root,
        name,
        configured_relative,
        snapshot_root,
        expected_hash=trusted_entry.sha256,
        after_open=after_open,
    )


def snapshot_local_python_mcp(
    vault_root: Path,
    name: str,
    entry: object,
    snapshot_root: Path,
    *,
    after_open: Callable[[int], None] | None = None,
) -> TrustedMcpSnapshot:
    """Snapshot one structurally local Python MCP for an explicit one-off check."""
    try:
        configured_relative = _local_python_relative(vault_root, entry)
    except TrustRegistryError as exc:
        return TrustedMcpSnapshot(False, str(exc))
    return _snapshot_local_python_file(
        vault_root,
        name,
        configured_relative,
        snapshot_root,
        expected_hash=None,
        after_open=after_open,
    )


def _snapshot_local_python_file(
    vault_root: Path,
    name: str,
    configured_relative: str,
    snapshot_root: Path,
    *,
    expected_hash: str | None,
    after_open: Callable[[int], None] | None,
) -> TrustedMcpSnapshot:
    """Hash and copy a no-follow-opened script without returning to its live path."""
    descriptor: int | None = None
    destination_fd: int | None = None
    destination: Path | None = None
    try:
        descriptor, _opened_stat = _open_component_file(
            vault_root,
            Path(configured_relative),
            label=f"{configured_relative} file",
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
        if expected_hash is not None and actual_hash != expected_hash:
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


def _load_live_mcp_entry(vault_root: Path, name: str) -> object:
    descriptor: int | None = None
    try:
        descriptor, opened_stat = _open_component_file(
            vault_root,
            Path(".mcp.json"),
            label=".mcp.json",
        )
        if opened_stat.st_size > 1024 * 1024:
            raise TrustRegistryError(".mcp.json is larger than 1MB")
        try:
            config = json.loads(_read_fd(descriptor, maximum=1024 * 1024))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TrustRegistryError(f".mcp.json is invalid: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(config, Mapping) or not isinstance(config.get("mcpServers"), Mapping):
        raise TrustRegistryError(".mcp.json must contain an mcpServers mapping")
    if name not in config["mcpServers"]:
        raise TrustRegistryError(f".mcp.json has no entry named {name}")
    return config["mcpServers"][name]


def inspect_local_mcp(vault_root: Path, name: str) -> TrustedMcpEntry:
    """Return the securely opened local entry identity without executing or writing."""
    entry = _load_live_mcp_entry(vault_root, name)
    relative = _local_python_relative(vault_root, entry)
    with tempfile.TemporaryDirectory(prefix="dex-mcp-bless-") as temporary:
        snapshot = snapshot_local_python_mcp(
            vault_root,
            name,
            entry,
            Path(temporary),
        )
        if not snapshot.trusted or snapshot.sha256 is None:
            raise TrustRegistryError(snapshot.detail)
    return TrustedMcpEntry(name=name, file=relative, sha256=snapshot.sha256)


def bless_local_mcp(
    vault_root: Path,
    name: str,
    *,
    expected_sha256: str | None = None,
) -> TrustedMcpEntry:
    """Record explicit consent for one exact local Python entry and content hash."""
    inspected = inspect_local_mcp(vault_root, name)
    if expected_sha256 is not None and inspected.sha256 != expected_sha256:
        raise TrustRegistryError("file changed after the consent details were shown; inspect it again")
    registry = load_trusted_mcp_registry(vault_root)
    if registry.invalid_reason is not None:
        raise TrustRegistryError(f"trusted MCP registry is invalid ({registry.invalid_reason})")

    updated = {
        entry_name: {"file": trusted.file, "sha256": trusted.sha256}
        for entry_name, trusted in registry.entries.items()
    }
    updated[name] = {"file": inspected.file, "sha256": inspected.sha256}
    content = (
        "# User-owned trust registry. Dex updates preserve this file verbatim.\n"
        "# Each entry permits recurring startup checks for these exact bytes only.\n"
        + yaml.safe_dump({"trusted_mcps": updated}, sort_keys=True)
    )
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_REGISTRY_BYTES:
        raise TrustRegistryError("updated registry would be larger than 64KB")

    registry_path = vault_root / REGISTRY_RELATIVE
    if not registry.present:
        template = vault_root / "System/trusted-mcps.example.yaml"
        if template.is_symlink() or not template.is_file():
            raise TrustRegistryError("System/trusted-mcps.example.yaml template is unavailable")
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=registry_path.parent,
            prefix=".trusted-mcps.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o600)
        os.replace(temporary_path, registry_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return inspected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage explicit local MCP startup trust.")
    parser.add_argument("--vault", type=Path, default=Path.cwd())
    parser.add_argument("--bless-mcp", metavar="CUSTOM_NAME")
    parser.add_argument("--inspect-mcp", metavar="CUSTOM_NAME")
    parser.add_argument("--expected-sha256")
    args = parser.parse_args(argv)
    if (args.bless_mcp is None) == (args.inspect_mcp is None):
        parser.error("choose exactly one of --inspect-mcp or --bless-mcp")
    try:
        if args.inspect_mcp is not None:
            trusted = inspect_local_mcp(args.vault.resolve(), args.inspect_mcp)
        else:
            trusted = bless_local_mcp(
                args.vault.resolve(),
                args.bless_mcp,
                expected_sha256=args.expected_sha256,
            )
    except TrustRegistryError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    print(f"{'Blessed' if args.bless_mcp else 'Local Python entry'}: {trusted.name}")
    print(f"vault-relative path: {trusted.file}")
    print(f"sha256: {trusted.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
