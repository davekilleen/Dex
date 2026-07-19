"""Strict local credential authority for task integrations.

Todoist and Trello secrets are read only from the vault-root ``.env`` file.
The process environment, tracked settings, and MCP configuration are never
credential sources.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SERVICE_FIELDS = {
    "todoist": {"api_key": "api_key_env_var"},
    "trello": {"api_key": "api_key_env_var", "token": "token_env_var"},
}
LEGACY_CREDENTIAL_FIELDS = {
    ("todoist", "api_key"): ("TODOIST_API_KEY", "api_key_env_var"),
    ("trello", "api_key"): ("TRELLO_API_KEY", "api_key_env_var"),
    ("trello", "token"): ("TRELLO_TOKEN", "token_env_var"),
}
MAX_ACTIVE_CONFIG_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ActiveConfigInspection:
    data: bytes | None
    inspected: bool
    reason: str | None = None


def inspect_active_mcp_config(vault_root: Path) -> ActiveConfigInspection:
    """Read the active MCP config once without following or trusting aliases."""
    path = vault_root / ".mcp.json"
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return ActiveConfigInspection(b"", True)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > MAX_ACTIVE_CONFIG_BYTES:
        return ActiveConfigInspection(None, False, "unsafe-active-config")
    if metadata.st_mode & 0o444 == 0:
        return ActiveConfigInspection(None, False, "unreadable-active-config")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or (opened.st_dev, opened.st_ino, opened.st_size)
                != (metadata.st_dev, metadata.st_ino, metadata.st_size)
            ):
                return ActiveConfigInspection(None, False, "active-config-identity-change")
            data = os.read(descriptor, MAX_ACTIVE_CONFIG_BYTES + 1)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        return ActiveConfigInspection(None, False, "unreadable-active-config")
    try:
        current = path.lstat()
    except OSError:
        return ActiveConfigInspection(None, False, "active-config-identity-change")
    if (
        len(data) > MAX_ACTIVE_CONFIG_BYTES
        or len(data) != opened.st_size
        or (after.st_dev, after.st_ino, after.st_size) != (opened.st_dev, opened.st_ino, opened.st_size)
        or (current.st_dev, current.st_ino, current.st_size) != (opened.st_dev, opened.st_ino, opened.st_size)
    ):
        return ActiveConfigInspection(None, False, "active-config-identity-change")
    return ActiveConfigInspection(data, True)


def parse_env_assignments(raw: bytes) -> dict[str, str]:
    """Parse the one strict dotenv assignment subset used by all credential paths."""
    values: dict[str, str] = {}
    for number, raw_line in enumerate(raw.decode("utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"invalid .env assignment on line {number}")
        name, value = line.split("=", 1)
        name = name.strip()
        if not _NAME.fullmatch(name) or name in values:
            raise ValueError(f"invalid or duplicate .env name on line {number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif any(character in value for character in "\r\n"):
            raise ValueError(f"multiline .env value on line {number}")
        values[name] = value
    return values


def read_vault_env(vault_root: Path) -> dict[str, str]:
    """Parse a conservative dotenv subset without expanding ambient values."""
    path = vault_root / ".env"
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {}
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError("vault .env must be a regular file")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        raw = os.read(descriptor, 8 * 1024 * 1024 + 1)
    finally:
        os.close(descriptor)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("vault .env exceeds the local credential bound")
    return parse_env_assignments(raw)


def resolve_service_credentials(service: str, settings: dict[str, Any], vault_root: Path) -> dict[str, str]:
    """Resolve a supported service from references in tracked settings."""
    required = _SERVICE_FIELDS.get(service)
    if required is None:
        return {}
    env_values = read_vault_env(vault_root)
    resolved: dict[str, str] = {}
    for output_name, reference_name in required.items():
        reference = settings.get(reference_name)
        if not isinstance(reference, str) or not _NAME.fullmatch(reference):
            raise ValueError(f"{service}.{reference_name} must name a vault .env variable")
        value = env_values.get(reference)
        if not value:
            raise ValueError(f"vault .env does not define {reference}")
        resolved[output_name] = value
    return resolved


def update_vault_env(vault_root: Path, updates: dict[str, str]) -> None:
    """Atomically add or replace exact names while preserving unrelated lines."""
    for name, value in updates.items():
        if not _NAME.fullmatch(name) or not value or any(c in value for c in "\r\n"):
            raise ValueError("invalid .env update")
    path = vault_root / ".env"
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None and (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1):
        raise ValueError("vault .env must be a regular file")
    original = path.read_bytes() if metadata is not None else b""
    parse_env_assignments(original)
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    lines = original.splitlines()
    remaining = dict(updates)
    output: list[bytes] = []
    for line in lines:
        match = re.match(rb"\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", line)
        if match and match.group(1).decode() in remaining:
            name = match.group(1).decode()
            output.append(f"{name}={remaining.pop(name)}".encode())
        else:
            output.append(line)
    output.extend(f"{name}={value}".encode() for name, value in sorted(remaining.items()))
    expected = newline.join(output) + (newline if output else b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".env.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if path.read_bytes() != expected:
            raise OSError(".env readback mismatch")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
