"""Strict local credential authority for Todoist and Trello integrations."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.utils.strict_yaml import load_yaml_bytes

_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_NAME_BYTES = re.compile(rb"^[A-Z][A-Z0-9_]*$")
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
MAX_ENV_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class ActiveConfigInspection:
    data: bytes | None
    inspected: bool
    reason: str | None = None


@dataclass(frozen=True)
class EnvAuthorityInspection:
    valid: bool
    reason: str | None = None
    repair: str | None = None


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev, value.st_ino, value.st_mode, value.st_nlink, value.st_uid,
        value.st_gid, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
    )


def inspect_active_mcp_config(vault_root: Path) -> ActiveConfigInspection:
    """Read active MCP config once without following or trusting aliases."""
    path = vault_root / ".mcp.json"
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return ActiveConfigInspection(b"", True)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size > MAX_ACTIVE_CONFIG_BYTES
        or metadata.st_mode & 0o444 == 0
    ):
        return ActiveConfigInspection(None, False, "unsafe-active-config")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            opened = os.fstat(descriptor)
            data = os.read(descriptor, MAX_ACTIVE_CONFIG_BYTES + 1)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        current = path.lstat()
    except OSError:
        return ActiveConfigInspection(None, False, "unreadable-active-config")
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or len(data) != opened.st_size
        or len(data) > MAX_ACTIVE_CONFIG_BYTES
        or len({_identity(item) for item in (metadata, opened, after, current)}) != 1
    ):
        return ActiveConfigInspection(None, False, "active-config-identity-change")
    return ActiveConfigInspection(data, True)


_MCP_REFERENCE_TEMPLATE = re.compile(r"\$\{[A-Z_][A-Z0-9_]*\}|<[^>]*>")


def mcp_value_is_reference(value: str) -> bool:
    """A ``.mcp.json`` value is a safe *reference* only if it is exactly a ``${VAR}``
    environment reference or a ``<placeholder>`` — never a raw literal."""
    return bool(_MCP_REFERENCE_TEMPLATE.fullmatch(value))


def _document_has_raw_residual(node: Any, key_names: frozenset[str]) -> bool:
    if isinstance(node, dict):
        for key, value in node.items():
            if (
                isinstance(key, str)
                and key in key_names
                and isinstance(value, str)
                and value
                and not mcp_value_is_reference(value)
            ):
                return True
            if _document_has_raw_residual(value, key_names):
                return True
        return False
    if isinstance(node, list):
        return any(_document_has_raw_residual(item, key_names) for item in node)
    return False


def active_mcp_raw_residual(raw: bytes, key_names: frozenset[str]) -> bool:
    """Structurally detect a live raw credential in ``.mcp.json``.

    JSON-parses the document — so an escaped key name (``\\u0054ODOIST_API_KEY``) decodes
    to its real name before comparison — then walks it, flagging any string value under a
    credential key name that is not a bare ``${VAR}`` / ``<placeholder>`` reference. This
    replaces a byte-level regex that both excluded any value starting with ``$``/``<``/``{``
    and never saw escaped key names. Empty/whitespace (no active config) is clean.

    Fails closed for the ambiguous case: a non-empty but unparseable document raises
    ``ValueError`` so the caller can surface the scope as UNKNOWN (never silently clean),
    rather than being asserted either clean or definitely-residual.
    """
    if not raw.strip():
        return False
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("unparseable active mcp config") from error
    return _document_has_raw_residual(document, key_names)


def mcp_credential_key_names(config_raw: bytes | None) -> frozenset[str]:
    """Key names whose ``.mcp.json`` values are treated as credentials: the canonical
    env-var names, the raw YAML field names (``api_key``/``token``), and any custom
    env-var names configured via ``api_key_env_var``/``token_env_var``. Fails safe — on
    any config parse problem the canonical + literal set is still returned (never fewer).
    """
    names = {env_name for env_name, _ in LEGACY_CREDENTIAL_FIELDS.values()} | {"api_key", "token"}
    if not config_raw:
        return frozenset(names)
    try:
        document = load_yaml_bytes(config_raw, max_bytes=MAX_ACTIVE_CONFIG_BYTES)
    except (ValueError, UnicodeDecodeError):
        return frozenset(names)
    if isinstance(document, dict):
        for (service, _key), (_env_name, ref_name) in LEGACY_CREDENTIAL_FIELDS.items():
            settings = document.get(service)
            if isinstance(settings, dict):
                configured = settings.get(ref_name)
                if isinstance(configured, str) and _NAME.fullmatch(configured):
                    names.add(configured)
    return frozenset(names)


def _decode_env_value(raw: bytes, number: int) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"invalid UTF-8 .env value on line {number}") from error
    if text.startswith('"'):
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid quoted .env value on line {number}") from error
        if not isinstance(value, str):
            raise ValueError(f"invalid quoted .env value on line {number}")
        return value
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise ValueError(f"invalid quoted .env value on line {number}")
        return text[1:-1]
    return text


def serialize_env_value(value: str) -> bytes:
    """Serialize an exact scalar using canonical JSON string escaping."""
    if not value or any(character in value for character in "\r\n\x00"):
        raise ValueError("invalid .env value")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def parse_env_assignments(raw: bytes) -> dict[str, str]:
    """Parse the strict lossless dotenv subset used by all credential paths."""
    values: dict[str, str] = {}
    for number, raw_line in enumerate(raw.splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith(b"#"):
            continue
        line = raw_line[7:] if raw_line.startswith(b"export ") else raw_line
        if b"=" not in line:
            raise ValueError(f"invalid .env assignment on line {number}")
        name_raw, value_raw = line.split(b"=", 1)
        name_raw = name_raw.strip()
        if not _NAME_BYTES.fullmatch(name_raw):
            raise ValueError(f"invalid or duplicate .env name on line {number}")
        name = name_raw.decode("ascii")
        if name in values:
            raise ValueError(f"invalid or duplicate .env name on line {number}")
        values[name] = _decode_env_value(value_raw, number)
    return values


def updated_env_bytes(original: bytes, updates: dict[str, str]) -> bytes:
    """Build the canonical lossless dotenv postimage without writing it."""
    if any(not _NAME.fullmatch(name) for name in updates):
        raise ValueError("invalid .env update")
    encoded = {name: serialize_env_value(value) for name, value in updates.items()}
    parse_env_assignments(original)
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    remaining = dict(encoded)
    output: list[bytes] = []
    for line in original.splitlines():
        match = re.match(rb"(?:export )?([A-Z][A-Z0-9_]*)=", line)
        if match and match.group(1).decode("ascii") in remaining:
            name = match.group(1).decode("ascii")
            output.append(name.encode("ascii") + b"=" + remaining.pop(name))
        else:
            output.append(line)
    output.extend(name.encode("ascii") + b"=" + value for name, value in sorted(remaining.items()))
    expected = newline.join(output) + (newline if output else b"")
    if len(expected) > MAX_ENV_BYTES:
        raise ValueError("vault .env exceeds the local credential bound")
    return expected


def _open_vault(vault_root: Path) -> tuple[int, os.stat_result]:
    if (
        not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
        or os.open not in os.supports_dir_fd
        or os.stat not in os.supports_dir_fd
    ):
        raise OSError("descriptor-relative no-follow .env authority is unavailable")
    descriptor = os.open(vault_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise OSError("vault root is not a directory")
    return descriptor, metadata


def _verify_vault_current(vault_root: Path, expected: os.stat_result) -> None:
    current = vault_root.lstat()
    if (current.st_dev, current.st_ino, current.st_mode, current.st_uid, current.st_gid) != (
        expected.st_dev,
        expected.st_ino,
        expected.st_mode,
        expected.st_uid,
        expected.st_gid,
    ):
        raise OSError("vault root identity changed")


def _validate_env_metadata(metadata: os.stat_result) -> None:
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError("vault .env must be one regular file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError("vault .env must have owner-only 0600 permissions")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise ValueError("vault .env must be owned by the current user")
    if metadata.st_size > MAX_ENV_BYTES:
        raise ValueError("vault .env exceeds the local credential bound")


def _read_env_at(root_fd: int) -> tuple[bytes, os.stat_result]:
    before = os.stat(".env", dir_fd=root_fd, follow_symlinks=False)
    _validate_env_metadata(before)
    descriptor = os.open(".env", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
    try:
        opened = os.fstat(descriptor)
        _validate_env_metadata(opened)
        chunks: list[bytes] = []
        remaining = MAX_ENV_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    current = os.stat(".env", dir_fd=root_fd, follow_symlinks=False)
    if len(raw) != opened.st_size or len(raw) > MAX_ENV_BYTES or len({_identity(x) for x in (before, opened, after, current)}) != 1:
        raise OSError("vault .env identity changed during read")
    return raw, opened


def read_vault_env(vault_root: Path) -> dict[str, str]:
    """Parse `.env` through a pinned vault descriptor and closed file authority."""
    root_fd, root_metadata = _open_vault(vault_root)
    try:
        try:
            raw, _ = _read_env_at(root_fd)
        except FileNotFoundError:
            return {}
        _verify_vault_current(vault_root, root_metadata)
    finally:
        os.close(root_fd)
    return parse_env_assignments(raw)


def inspect_vault_env_authority(vault_root: Path) -> EnvAuthorityInspection:
    """Return a redacted, repairable finding for the local `.env` authority."""
    try:
        read_vault_env(vault_root)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        detail = str(error)
        reason = (
            "permissions" if "0600" in detail
            else "ownership" if "owned" in detail
            else "unsafe-file-authority"
        )
        repair = (
            "Set vault .env to owner-only mode 0600 and ensure it is owned by the current user; "
            "replace symlinks or hard links with one regular local file."
        )
        return EnvAuthorityInspection(False, reason, repair)
    return EnvAuthorityInspection(True)


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


def update_vault_env(
    vault_root: Path,
    updates: dict[str, str],
    *,
    before_publish: Callable[[os.stat_result], None] | None = None,
) -> None:
    """Atomically update exact names through one pinned vault descriptor."""
    root_fd, root_metadata = _open_vault(vault_root)
    temporary = f".env.{secrets.token_hex(16)}.tmp"
    try:
        try:
            original, original_metadata = _read_env_at(root_fd)
        except FileNotFoundError:
            original, original_metadata = b"", None
        existing = parse_env_assignments(original)
        expected = updated_env_bytes(original, updates)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=root_fd,
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(expected)
                handle.flush()
                os.fsync(descriptor)
            staged_metadata = os.fstat(descriptor)
            _validate_env_metadata(staged_metadata)
            if before_publish is not None:
                before_publish(staged_metadata)
        finally:
            os.close(descriptor)
        if original_metadata is None:
            try:
                os.stat(".env", dir_fd=root_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise OSError("vault .env appeared during update")
        elif _identity(os.stat(".env", dir_fd=root_fd, follow_symlinks=False)) != _identity(original_metadata):
            raise OSError("vault .env changed during update")
        _verify_vault_current(vault_root, root_metadata)
        os.replace(temporary, ".env", src_dir_fd=root_fd, dst_dir_fd=root_fd)
        os.fsync(root_fd)
        raw, _ = _read_env_at(root_fd)
        if raw != expected or parse_env_assignments(raw) != {**existing, **updates}:
            raise OSError("vault .env readback mismatch")
        _verify_vault_current(vault_root, root_metadata)
    finally:
        try:
            os.unlink(temporary, dir_fd=root_fd)
        except FileNotFoundError:
            pass
        os.close(root_fd)
