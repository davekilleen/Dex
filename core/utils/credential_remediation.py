"""Atomic local credential migration and deterministic remediation status."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from core.utils.integration_credentials import (
    LEGACY_CREDENTIAL_FIELDS,
    inspect_active_mcp_config,
    parse_env_assignments,
    update_vault_env,
    updated_env_bytes,
)
from core.utils.local_git import git_output
from core.utils.strict_yaml import load_yaml_bytes

MigrationState = Literal["not-needed", "migrated-local-config", "partial", "refused", "rewound"]
SecurityState = Literal["remediated", "rotation-pending", "unknown"]
ActiveResidualState = Literal["none", "proven-revoked", "unrevoked-or-unclassified"]
HistoryState = Literal["history-cleanup-pending", "history-clean", "history-scope-unknown"]

CAPABILITIES = (
    "regular-targets",
    "journal-readback",
    "same-directory-temp",
    "durability",
    "atomic-replace",
    "precommit-recheck",
    "replacement-readback",
    "rollback-readback",
    "no-follow-containment",
)
EVIDENCE_CODES = frozenset(
    {
        "old-key-revocation",
        "replacement-present",
        "replacement-health",
        "active-copy",
        "provider-binding",
        "provider-evidence",
    }
)
UNKNOWN_CAUSES = frozenset({"unsupported", "unavailable", "inconsistent", "active-residual-unclassified"})
SCOPE_CATEGORIES = frozenset(
    {
        "worktree",
        "index",
        "git-common-dir",
        "primary-object-db",
        "reachable-refs",
        "stashes",
        "tags",
        "selected-archives",
    }
)
EXCEPTIONS_FILE = Path(__file__).with_name("credential_migration_exceptions.json")
MAX_TRACKED_CONFIG_BYTES = 1024 * 1024


@dataclass(frozen=True)
class CapabilityResult:
    results: dict[str, bool]

    @property
    def authorized(self) -> bool:
        return set(self.results) == set(CAPABILITIES) and all(self.results.values())


@dataclass(frozen=True)
class MigrationResult:
    state: MigrationState
    journal_id: str | None = None
    failed_capabilities: tuple[str, ...] = ()
    active_residual_state: ActiveResidualState = "none"
    uninspected_scopes: tuple[str, ...] = ()
    uninspected_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class CredentialStatusCopy:
    migration: str
    security_and_current_config: str
    history: str


@dataclass(frozen=True)
class CredentialEvidence:
    """Typed evidence polarity for deterministic security-state rendering."""

    present: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()
    unknown_causes: tuple[str, ...] = ()

    def normalized(self) -> "CredentialEvidence":
        groups = tuple(tuple(sorted(set(group))) for group in (self.present, self.missing, self.unavailable))
        causes = tuple(sorted(set(self.unknown_causes)))
        if any(not set(group) <= EVIDENCE_CODES for group in groups) or not set(causes) <= UNKNOWN_CAUSES:
            raise ValueError("unknown credential evidence category")
        if set(groups[0]) & set(groups[1]) or set(groups[0]) & set(groups[2]) or set(groups[1]) & set(groups[2]):
            raise ValueError("credential evidence polarity cannot overlap")
        return CredentialEvidence(*groups, causes)


def _contained_regular(
    path: Path,
    root: Path,
    *,
    absent_ok: bool = False,
    writable_if_present: bool = False,
) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    try:
        parent = _open_directory_chain(root, relative.parts[:-1])
        try:
            metadata = os.stat(relative.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return absent_ok
        finally:
            os.close(parent)
    except OSError:
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_nlink == 1
        and (not writable_if_present or bool(metadata.st_mode & 0o222))
    )


def _open_directory_chain(root: Path, parts: tuple[str, ...], *, create: bool = False) -> int:
    """Open a vault-contained directory chain without following any component."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    try:
        for part in parts:
            if not part or part in {".", ".."} or "/" in part:
                raise OSError("unsafe contained directory component")
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, 0o700, dir_fd=descriptor)
                os.fsync(descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_at_with_metadata(
    directory: int, name: str, *, max_bytes: int | None = None
) -> tuple[bytes, os.stat_result]:
    descriptor = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory)
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        data = handle.read() if max_bytes is None else handle.read(max_bytes + 1)
        after = os.fstat(handle.fileno())
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or (max_bytes is not None and (before.st_size > max_bytes or len(data) > max_bytes))
        or (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size)
        or len(data) != before.st_size
    ):
        raise OSError("contained file identity changed")
    return data, before


def _read_at(directory: int, name: str) -> bytes:
    return _read_at_with_metadata(directory, name)[0]


def _read_contained(
    root: Path, relative: Path, *, max_bytes: int | None = None
) -> tuple[bytes, os.stat_result]:
    parent = _open_directory_chain(root, relative.parts[:-1])
    try:
        return _read_at_with_metadata(parent, relative.name, max_bytes=max_bytes)
    finally:
        os.close(parent)


def _atomic_replace_at(
    directory: int,
    name: str,
    data: bytes,
    mode: int,
    *,
    before_publish: Callable[[os.stat_result], None] | None = None,
    owner: tuple[int, int] | None = None,
) -> None:
    temporary = f".{name}.{uuid.uuid4().hex}"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode, dir_fd=directory)
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            if owner is not None and hasattr(os, "fchown"):
                os.fchown(handle.fileno(), *owner)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            if before_publish is not None:
                before_publish(os.fstat(handle.fileno()))
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
        actual, metadata = _read_at_with_metadata(directory, name)
        if (
            actual != data
            or stat.S_IMODE(metadata.st_mode) != mode
            or (owner is not None and (metadata.st_uid, metadata.st_gid) != owner)
        ):
            raise OSError("credential replacement readback mismatch")
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def _read_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        return handle.read()


def probe_atomic_migration(vault_root: Path, journal_dir: Path) -> CapabilityResult:
    """Exercise the exact local primitives; platform labels never participate."""
    results = {name: False for name in CAPABILITIES}
    config = vault_root / "System" / "integrations" / "config.yaml"
    env_file = vault_root / ".env"
    results["regular-targets"] = _contained_regular(
        config,
        vault_root,
        writable_if_present=True,
    ) and _contained_regular(
        env_file,
        vault_root,
        absent_ok=True,
        writable_if_present=True,
    )
    try:
        relative_journal = journal_dir.relative_to(vault_root)
        journal_descriptor = _open_directory_chain(vault_root, relative_journal.parts, create=True)
    except (OSError, ValueError):
        return CapabilityResult(results)
    results["no-follow-containment"] = results["regular-targets"]
    probe = f".capability-{uuid.uuid4().hex}"
    replacement = probe + ".replacement"
    rollback = probe + ".rollback"
    try:
        for name, data in ((probe, b"before"), (replacement, b"after")):
            descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=journal_descriptor)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        probe_stat = os.stat(probe, dir_fd=journal_descriptor, follow_symlinks=False)
        replacement_stat = os.stat(replacement, dir_fd=journal_descriptor, follow_symlinks=False)
        results["journal-readback"] = _read_at(journal_descriptor, probe) == b"before" and stat.S_IMODE(probe_stat.st_mode) == 0o600
        results["same-directory-temp"] = replacement_stat.st_dev == probe_stat.st_dev
        os.fsync(journal_descriptor)
        results["durability"] = True
        results["precommit-recheck"] = _read_at(journal_descriptor, probe) == b"before"
        os.replace(replacement, probe, src_dir_fd=journal_descriptor, dst_dir_fd=journal_descriptor)
        results["atomic-replace"] = _read_at(journal_descriptor, probe) == b"after"
        results["replacement-readback"] = _read_at(journal_descriptor, probe) == b"after"
        descriptor = os.open(rollback, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=journal_descriptor)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(b"before")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(rollback, probe, src_dir_fd=journal_descriptor, dst_dir_fd=journal_descriptor)
        results["rollback-readback"] = _read_at(journal_descriptor, probe) == b"before"
    except OSError:
        pass
    finally:
        for name in (probe, replacement, rollback):
            try:
                os.unlink(name, dir_fd=journal_descriptor)
            except FileNotFoundError:
                pass
        os.close(journal_descriptor)
    return CapabilityResult(results)


def _legacy_values(raw: bytes) -> tuple[dict[str, str], dict[str, str], frozenset[str]]:
    data = load_yaml_bytes(raw, max_bytes=MAX_TRACKED_CONFIG_BYTES) or {}
    if not isinstance(data, dict):
        raise ValueError("integration config must be an object")
    values: dict[str, str] = {}
    refs: dict[str, str] = {}
    env_names = {env_name for env_name, _ in LEGACY_CREDENTIAL_FIELDS.values()}
    for (service, key), (env_name, ref_name) in LEGACY_CREDENTIAL_FIELDS.items():
        settings = data.get(service)
        if settings is None:
            continue
        if not isinstance(settings, dict):
            raise ValueError("integration settings must be an object")
        if ref_name in settings:
            configured_name = settings[ref_name]
            if not isinstance(configured_name, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", configured_name):
                raise ValueError("credential environment reference must be an uppercase variable name")
            env_names.add(configured_name)
        if key in settings:
            value = settings[key]
            if not isinstance(value, str) or not value or "\n" in value:
                raise ValueError("legacy credential must be an unambiguous scalar")
            values[env_name] = value
            refs[f"{service}.{key}"] = ref_name
    return values, refs, frozenset(env_names)


def _active_mcp_raw_residual(raw: bytes, env_names: frozenset[str], legacy_values: dict[str, str]) -> bool:
    if any(value.encode() in raw for value in legacy_values.values()):
        return True
    names = b"|".join(re.escape(name.encode()) for name in sorted(env_names))
    return bool(re.search(rb'"(?:' + names + rb')"\s*:\s*"[^"$<{][^"]*"', raw))


def _config_snapshot_unchanged(
    vault_root: Path,
    expected_raw: bytes,
    expected_metadata: os.stat_result,
) -> bool:
    try:
        current_raw, current_metadata = _read_contained(
            vault_root,
            Path("System/integrations/config.yaml"),
            max_bytes=MAX_TRACKED_CONFIG_BYTES,
        )
    except OSError:
        return False
    return _config_snapshot_matches(current_raw, current_metadata, expected_raw, expected_metadata)


def _config_snapshot_matches(
    raw: bytes,
    metadata: os.stat_result,
    expected_raw: bytes,
    expected_metadata: os.stat_result,
) -> bool:
    return raw == expected_raw and (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        stat.S_IMODE(metadata.st_mode),
    ) == (
        expected_metadata.st_dev,
        expected_metadata.st_ino,
        expected_metadata.st_size,
        stat.S_IMODE(expected_metadata.st_mode),
    )


def _env_storage_is_local_only(vault_root: Path) -> bool:
    """Require ignored, untracked .env in Git vaults; non-Git vaults remain supported."""
    git_marker = vault_root / ".git"
    try:
        git_metadata = git_marker.lstat()
    except FileNotFoundError:
        return True
    if not (stat.S_ISDIR(git_metadata.st_mode) or stat.S_ISREG(git_metadata.st_mode)):
        return False
    try:
        if git_output(vault_root, "rev-parse", "--is-inside-work-tree", profile="read-only").strip() != b"true":
            return False
    except RuntimeError:
        return False
    try:
        git_output(vault_root, "ls-files", "--error-unmatch", "--", ".env", profile="read-only")
    except RuntimeError:
        tracked = False
    else:
        tracked = True
    try:
        ignored = git_output(vault_root, "check-ignore", "-q", "--", ".env", profile="read-only") == b""
    except RuntimeError:
        ignored = False
    return ignored and not tracked


def _replace_yaml_credentials(raw: bytes, refs: dict[str, str]) -> bytes:
    text = raw.decode("utf-8")
    for dotted, ref_name in refs.items():
        section, key = dotted.split(".")
        pattern = rf"(?ms)(^[ ]*{section}:\s*\n(?:(?:[ ]+.*\n)*?))([ ]+){key}:([^\r\n]*)(\r?\n|$)"
        text, count = re.subn(
            pattern,
            rf"\1\2{ref_name}: {LEGACY_CREDENTIAL_FIELDS[(section, key)][0]}\4",
            text,
            count=1,
        )
        if count != 1:
            raise ValueError("could not preserve legacy YAML structure")
    return text.encode("utf-8")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _postimage_identity(metadata: os.stat_result) -> list[int]:
    return [
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_size,
    ]


def _record_postimage(
    vault_root: Path,
    journal_name: str,
    record: dict[str, object],
    name: str,
    metadata: os.stat_result,
) -> None:
    postimages = record["postimages"]
    if not isinstance(postimages, dict):
        raise OSError("invalid credential journal postimage state")
    postimages[f"{name}_identity"] = _postimage_identity(metadata)
    descriptor = _open_directory_chain(vault_root, ("System", ".dex", "adoption", "credential-journals"))
    try:
        _atomic_replace_at(descriptor, journal_name, (json.dumps(record, sort_keys=True) + "\n").encode(), 0o600)
    finally:
        os.close(descriptor)


def _validate_exception_registry() -> None:
    """Fail closed until a separately implemented exact exception matcher is shipped."""
    try:
        payload = json.loads(_read_nofollow(EXCEPTIONS_FILE).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("credential migration exception registry is unavailable") from error
    if payload != {"schema_version": 1, "exceptions": []}:
        raise ValueError("credential migration exception registry contains unsupported authority")


def migrate_legacy_credentials(vault_root: Path) -> MigrationResult:
    try:
        _validate_exception_registry()
    except ValueError:
        return MigrationResult("refused")
    try:
        config_raw, config_metadata = _read_contained(
            vault_root,
            Path("System/integrations/config.yaml"),
            max_bytes=MAX_TRACKED_CONFIG_BYTES,
        )
    except OSError:
        return MigrationResult("refused")
    config_snapshot_metadata = config_metadata
    try:
        values, refs, env_names = _legacy_values(config_raw)
    except (UnicodeDecodeError, ValueError):
        return MigrationResult("refused")
    mcp = inspect_active_mcp_config(vault_root)
    if not _config_snapshot_unchanged(vault_root, config_raw, config_snapshot_metadata):
        return MigrationResult(
            "refused" if values else "partial",
            active_residual_state="unrevoked-or-unclassified",
            uninspected_scopes=("worktree",),
            uninspected_reasons=("integration-config-identity-change",),
        )
    if not mcp.inspected:
        return MigrationResult(
            "refused" if values else "partial",
            active_residual_state="unrevoked-or-unclassified",
            uninspected_scopes=("worktree",),
            uninspected_reasons=(mcp.reason or "unsafe-active-config",),
        )
    mcp_raw = mcp.data or b""
    mcp_raw_residual = _active_mcp_raw_residual(mcp_raw, env_names, values)
    if not values:
        return MigrationResult(
            "partial" if mcp_raw_residual else "not-needed",
            active_residual_state="unrevoked-or-unclassified" if mcp_raw_residual else "none",
        )
    if not _env_storage_is_local_only(vault_root):
        return MigrationResult("refused")
    journal_dir = vault_root / "System" / ".dex" / "adoption" / "credential-journals"
    capability = probe_atomic_migration(vault_root, journal_dir)
    if not capability.authorized:
        return MigrationResult(
            "refused", failed_capabilities=tuple(sorted(k for k, v in capability.results.items() if not v))
        )
    try:
        env_raw, env_metadata = _read_contained(vault_root, Path(".env"))
    except FileNotFoundError:
        env_raw = None
        env_metadata = None
    except OSError:
        return MigrationResult("refused")
    if env_raw:
        existing_values = parse_env_assignments(env_raw)
        for name, value in values.items():
            if name in existing_values and existing_values[name] != value:
                return MigrationResult("refused")
    expected_config = _replace_yaml_credentials(config_raw, refs)
    expected_env = updated_env_bytes(env_raw or b"", values)
    journal_id = uuid.uuid4().hex
    journal_name = f"{journal_id}.json"
    record = {
        "schema_version": 1,
        "config": {
            "bytes_hex": config_raw.hex(),
            "sha256": _hash(config_raw),
            "mode": stat.S_IMODE(config_snapshot_metadata.st_mode),
            "uid": config_snapshot_metadata.st_uid,
            "gid": config_snapshot_metadata.st_gid,
        },
        "env": None
        if env_raw is None
        else {
            "bytes_hex": env_raw.hex(),
            "sha256": _hash(env_raw),
            "mode": stat.S_IMODE(env_metadata.st_mode),
            "uid": env_metadata.st_uid,
            "gid": env_metadata.st_gid,
        },
        "postimages": {
            "config_sha256": _hash(expected_config),
            "config_bytes_hex": expected_config.hex(),
            "config_mode": stat.S_IMODE(config_snapshot_metadata.st_mode),
            "env_sha256": _hash(expected_env),
            "env_bytes_hex": expected_env.hex(),
            "env_mode": 0o600,
        },
    }
    try:
        journal_descriptor = _open_directory_chain(
            vault_root, ("System", ".dex", "adoption", "credential-journals")
        )
        try:
            descriptor = os.open(
                journal_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=journal_descriptor
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(journal_descriptor)
            if json.loads(_read_at(journal_descriptor, journal_name).decode("utf-8")) != record:
                return MigrationResult("refused")
        finally:
            os.close(journal_descriptor)
    except OSError:
        return MigrationResult("refused")
    config_descriptor = None
    try:
        config_descriptor = _open_directory_chain(vault_root, ("System", "integrations"))
        config_bytes, config_metadata = _read_at_with_metadata(config_descriptor, "config.yaml")
        if not _config_snapshot_matches(
            config_bytes,
            config_metadata,
            config_raw,
            config_snapshot_metadata,
        ):
            raise OSError("config changed after migration inspection")
        config_before = (
            config_metadata.st_ino,
            _hash(config_bytes),
            stat.S_IMODE(config_metadata.st_mode),
        )
    except OSError:
        if config_descriptor is not None:
            os.close(config_descriptor)
        return MigrationResult("refused", journal_id)
    try:
        update_vault_env(
            vault_root,
            values,
            before_publish=lambda metadata: _record_postimage(
                vault_root, journal_name, record, "env", metadata
            ),
        )
        current_bytes, current = _read_at_with_metadata(config_descriptor, "config.yaml")
        if (current.st_ino, _hash(current_bytes), stat.S_IMODE(current.st_mode)) != config_before:
            raise OSError("config changed during migration")
        current_parent = _open_directory_chain(vault_root, ("System", "integrations"))
        try:
            if (os.fstat(current_parent).st_dev, os.fstat(current_parent).st_ino) != (
                os.fstat(config_descriptor).st_dev,
                os.fstat(config_descriptor).st_ino,
            ):
                raise OSError("config parent changed during migration")
        finally:
            os.close(current_parent)
        _atomic_replace_at(
            config_descriptor,
            "config.yaml",
            expected_config,
            record["config"]["mode"],
            before_publish=lambda metadata: _record_postimage(
                vault_root, journal_name, record, "config", metadata
            ),
        )
    except BaseException as error:
        rewind_credential_migration(vault_root, journal_id)
        if not isinstance(error, Exception):
            raise
        return MigrationResult("refused", journal_id)
    finally:
        os.close(config_descriptor)
    return MigrationResult(
        "partial" if mcp_raw_residual else "migrated-local-config",
        journal_id,
        active_residual_state="unrevoked-or-unclassified" if mcp_raw_residual else "none",
    )


def _journal_image(entry: object, *, optional: bool = False) -> tuple[bytes, int, tuple[int, int]] | None:
    if entry is None and optional:
        return None
    if not isinstance(entry, dict) or set(entry) != {"bytes_hex", "sha256", "mode", "uid", "gid"}:
        raise OSError("invalid credential journal preimage")
    try:
        data = bytes.fromhex(entry["bytes_hex"])
        mode = int(entry["mode"])
        owner = (int(entry["uid"]), int(entry["gid"]))
    except (TypeError, ValueError) as error:
        raise OSError("invalid credential journal preimage") from error
    if (
        _hash(data) != entry["sha256"]
        or not 0 <= mode <= 0o777
        or min(owner) < 0
        or not _owner_restorable(owner)
    ):
        raise OSError("invalid credential journal preimage")
    return data, mode, owner


def _owner_restorable(owner: tuple[int, int]) -> bool:
    if not all(hasattr(os, name) for name in ("geteuid", "getegid", "getgroups")):
        return True
    effective_uid = os.geteuid()
    if effective_uid == 0:
        return True
    return owner[0] == effective_uid and owner[1] in {os.getegid(), *os.getgroups()}


def _rewind_images(record: object) -> dict[str, tuple[bytes, int, tuple[int, int]] | None]:
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise OSError("invalid credential journal")
    config_pre = _journal_image(record.get("config"))
    env_pre = _journal_image(record.get("env"), optional=True)
    postimages = record.get("postimages")
    if not isinstance(postimages, dict):
        raise OSError("invalid credential journal postimages")
    try:
        config_post = bytes.fromhex(postimages["config_bytes_hex"])
        env_post = bytes.fromhex(postimages["env_bytes_hex"])
        config_mode = int(postimages["config_mode"])
        env_mode = int(postimages["env_mode"])
        config_identity = postimages.get("config_identity")
        env_identity = postimages.get("env_identity")
    except (KeyError, TypeError, ValueError) as error:
        raise OSError("invalid credential journal postimages") from error
    if (
        _hash(config_post) != postimages.get("config_sha256")
        or _hash(env_post) != postimages.get("env_sha256")
        or (config_identity is not None and (not isinstance(config_identity, list) or len(config_identity) != 7))
        or (env_identity is not None and (not isinstance(env_identity, list) or len(env_identity) != 7))
        or (config_identity is not None and config_mode != stat.S_IMODE(config_identity[2]))
        or env_mode != 0o600
        or (env_identity is not None and env_mode != stat.S_IMODE(env_identity[2]))
    ):
        raise OSError("invalid credential journal postimages")
    assert config_pre is not None
    config_owner = (
        (config_identity[4], config_identity[5])
        if config_identity is not None
        else config_pre[2]
    )
    env_owner = (
        (env_identity[4], env_identity[5])
        if env_identity is not None
        else (env_pre[2] if env_pre is not None else config_pre[2])
    )
    return {
        "config_pre": config_pre,
        "env_pre": env_pre,
        "config_post": (config_post, config_mode, config_owner),
        "env_post": (env_post, env_mode, env_owner),
    }


def _require_image(
    parent: int,
    target: str,
    image: tuple[bytes, int, tuple[int, int]],
    *,
    identity: object | None = None,
) -> None:
    data, metadata = _read_at_with_metadata(parent, target)
    expected, mode, owner = image
    if (
        data != expected
        or stat.S_IMODE(metadata.st_mode) != mode
        or (metadata.st_uid, metadata.st_gid) != owner
        or (identity is not None and _postimage_identity(metadata) != identity)
    ):
        raise OSError("credential rewind requires an unchanged migration-owned postimage")


def _store_rewind_journal(directory: int, name: str, record: dict[str, object]) -> None:
    _atomic_replace_at(directory, name, (json.dumps(record, sort_keys=True) + "\n").encode(), 0o600)


def _restore_rewind_postimages(
    config_parent: int,
    env_parent: int,
    images: dict[str, tuple[bytes, int, tuple[int, int]] | None],
) -> None:
    """Resolve an interrupted rewind back to the secret-safe migrated state."""
    for name, parent, target in (
        ("config", config_parent, "config.yaml"),
        ("env", env_parent, ".env"),
    ):
        post = images[f"{name}_post"]
        pre = images[f"{name}_pre"]
        assert post is not None
        try:
            current, metadata = _read_at_with_metadata(parent, target)
        except FileNotFoundError:
            if pre is not None or name == "config":
                raise OSError("credential rewind recovery-required: target disappeared") from None
        else:
            current_image = (current, stat.S_IMODE(metadata.st_mode), (metadata.st_uid, metadata.st_gid))
            if current_image != post and (pre is None or current_image != pre):
                raise OSError("credential rewind recovery-required: target changed independently")
            if current_image == post:
                continue
        _atomic_replace_at(parent, target, post[0], post[1], owner=post[2])


def _refresh_postimage_identities(
    config_parent: int,
    env_parent: int,
    images: dict[str, tuple[bytes, int, tuple[int, int]] | None],
    postimages: dict[str, object],
) -> None:
    for name, parent, target in (
        ("config", config_parent, "config.yaml"),
        ("env", env_parent, ".env"),
    ):
        post = images[f"{name}_post"]
        assert post is not None
        data, metadata = _read_at_with_metadata(parent, target)
        if (
            data != post[0]
            or stat.S_IMODE(metadata.st_mode) != post[1]
            or (metadata.st_uid, metadata.st_gid) != post[2]
        ):
            raise OSError("credential rewind recovery-required: postimage readback mismatch")
        postimages[f"{name}_identity"] = _postimage_identity(metadata)


def _finish_incomplete_migration_rollback(
    config_parent: int,
    env_parent: int,
    images: dict[str, tuple[bytes, int, tuple[int, int]] | None],
    postimages: dict[str, object],
) -> None:
    """Restore migration preimages when publication never reached both targets."""
    config_pre = images["config_pre"]
    env_pre = images["env_pre"]
    config_post = images["config_post"]
    env_post = images["env_post"]
    assert config_pre is not None and config_post is not None and env_post is not None
    for name, parent, target, pre, post in (
        ("config", config_parent, "config.yaml", config_pre, config_post),
        ("env", env_parent, ".env", env_pre, env_post),
    ):
        identity = postimages.get(f"{name}_identity")
        if identity is not None:
            _require_image(parent, target, post, identity=identity)
        elif pre is None:
            try:
                os.stat(target, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise OSError("credential migration rollback target appeared") from None
        else:
            _require_image(parent, target, pre)
    if postimages.get("env_identity") is not None:
        if env_pre is None:
            os.unlink(".env", dir_fd=env_parent)
            os.fsync(env_parent)
        else:
            _atomic_replace_at(env_parent, ".env", env_pre[0], env_pre[1], owner=env_pre[2])
    if postimages.get("config_identity") is not None:
        _atomic_replace_at(
            config_parent, "config.yaml", config_pre[0], config_pre[1], owner=config_pre[2]
        )


def rewind_credential_migration(vault_root: Path, journal_id: str) -> MigrationResult:
    if not re.fullmatch(r"[0-9a-f]{32}", journal_id):
        raise ValueError("invalid credential journal id")
    journal_name = f"{journal_id}.json"
    root_before = vault_root.lstat()
    journal_parent = _open_directory_chain(
        vault_root, ("System", ".dex", "adoption", "credential-journals")
    )
    try:
        config_parent = _open_directory_chain(vault_root, ("System", "integrations"))
    except BaseException:
        os.close(journal_parent)
        raise
    try:
        env_parent = _open_directory_chain(vault_root, ())
    except BaseException:
        os.close(config_parent)
        os.close(journal_parent)
        raise
    try:
        root_after = vault_root.lstat()
        opened_root = os.fstat(env_parent)
        root_identities = {
            (item.st_dev, item.st_ino, item.st_mode, item.st_uid, item.st_gid)
            for item in (root_before, root_after, opened_root)
        }
        if len(root_identities) != 1:
            raise OSError("credential rewind vault root identity changed")
        journal_raw, journal_metadata = _read_at_with_metadata(journal_parent, journal_name)
        if (
            stat.S_IMODE(journal_metadata.st_mode) != 0o600
            or not _owner_restorable((journal_metadata.st_uid, journal_metadata.st_gid))
        ):
            raise OSError("unsafe credential rewind journal authority")
        record = json.loads(journal_raw.decode("utf-8"))
        images = _rewind_images(record)
        postimages = record["postimages"]
        assert isinstance(postimages, dict)
        if postimages.get("config_identity") is None or postimages.get("env_identity") is None:
            _finish_incomplete_migration_rollback(config_parent, env_parent, images, postimages)
            return MigrationResult("rewound", journal_id)
        if record.get("rewind") == {"phase": "rewound"}:
            config_pre = images["config_pre"]
            assert config_pre is not None
            _require_image(config_parent, "config.yaml", config_pre)
            env_pre = images["env_pre"]
            if env_pre is None:
                try:
                    os.stat(".env", dir_fd=env_parent, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise OSError("credential rewind preimage changed after completion") from None
            else:
                _require_image(env_parent, ".env", env_pre)
            return MigrationResult("rewound", journal_id)
        if record.get("rewind") == {"phase": "publishing"}:
            _restore_rewind_postimages(config_parent, env_parent, images)
            _refresh_postimage_identities(
                config_parent, env_parent, images, postimages
            )
            record["rewind"] = {"phase": "ready"}
            _store_rewind_journal(journal_parent, journal_name, record)
        elif record.get("rewind") not in (None, {"phase": "ready"}):
            raise OSError("invalid credential rewind phase")

        config_post = images["config_post"]
        env_post = images["env_post"]
        assert config_post is not None and env_post is not None
        # Complete read-only prevalidation of both pinned targets precedes any target mutation.
        _require_image(
            config_parent, "config.yaml", config_post, identity=postimages["config_identity"]
        )
        _require_image(env_parent, ".env", env_post, identity=postimages["env_identity"])
        config_pre = images["config_pre"]
        assert config_pre is not None
        env_pre = images["env_pre"]
        record["rewind"] = {"phase": "publishing"}
        _store_rewind_journal(journal_parent, journal_name, record)
        try:
            # Publish local-only state first; tracked raw YAML is the final boundary.
            _require_image(env_parent, ".env", env_post, identity=postimages["env_identity"])
            if env_pre is None:
                os.unlink(".env", dir_fd=env_parent)
                os.fsync(env_parent)
            else:
                _atomic_replace_at(env_parent, ".env", env_pre[0], env_pre[1], owner=env_pre[2])
            _require_image(
                config_parent, "config.yaml", config_post, identity=postimages["config_identity"]
            )
            _atomic_replace_at(
                config_parent, "config.yaml", config_pre[0], config_pre[1], owner=config_pre[2]
            )
            record["rewind"] = {"phase": "rewound"}
            _store_rewind_journal(journal_parent, journal_name, record)
        except BaseException:
            _restore_rewind_postimages(config_parent, env_parent, images)
            _refresh_postimage_identities(
                config_parent, env_parent, images, postimages
            )
            record["rewind"] = {"phase": "ready"}
            _store_rewind_journal(journal_parent, journal_name, record)
            raise
    finally:
        os.close(env_parent)
        os.close(config_parent)
        os.close(journal_parent)
    return MigrationResult("rewound", journal_id)


def render_credential_status(
    migration_state: MigrationState,
    security_state: SecurityState,
    active_residual_state: ActiveResidualState,
    history_hygiene_state: HistoryState,
    evidence_codes: tuple[str, ...] | CredentialEvidence = (),
    uninspected_scope_categories: tuple[str, ...] = (),
) -> CredentialStatusCopy:
    if isinstance(evidence_codes, CredentialEvidence):
        typed_evidence = evidence_codes.normalized()
    else:
        legacy = tuple(sorted(set(evidence_codes)))
        typed_evidence = CredentialEvidence(
            present=legacy if security_state == "remediated" else (),
            missing=legacy if security_state == "rotation-pending" else (),
            unavailable=legacy if security_state == "unknown" else (),
            unknown_causes=("unavailable",) if security_state == "unknown" and legacy else (),
        ).normalized()
    present = typed_evidence.present
    missing = typed_evidence.missing
    unavailable = typed_evidence.unavailable
    scopes = tuple(sorted(set(uninspected_scope_categories)))
    if not set(scopes) <= SCOPE_CATEGORIES:
        raise ValueError("unknown credential evidence category")
    if active_residual_state != "none" and migration_state != "partial":
        raise ValueError("raw MCP residual requires partial migration")
    if security_state == "remediated" and active_residual_state == "unrevoked-or-unclassified":
        raise ValueError("security cannot be fixed with a potentially usable residual")
    if active_residual_state == "proven-revoked" and "provider-binding" not in present:
        raise ValueError("proven residual requires provider binding evidence")
    required_remediation = {
        "old-key-revocation",
        "replacement-present",
        "replacement-health",
        "active-copy",
        "provider-binding",
    }
    if security_state == "remediated" and (
        not required_remediation <= set(present) or missing or unavailable or typed_evidence.unknown_causes
    ):
        raise ValueError("remediated security requires complete bound rotation and replacement evidence")
    residual_supplies_pending_reason = active_residual_state == "unrevoked-or-unclassified"
    if security_state == "rotation-pending" and (
        present or unavailable or typed_evidence.unknown_causes or (not missing and not residual_supplies_pending_reason)
    ):
        raise ValueError("rotation-pending security requires incomplete evidence or an active residual")
    if security_state == "unknown" and (
        present or missing or not unavailable or not typed_evidence.unknown_causes
    ):
        raise ValueError("unknown security requires unavailable or inconsistent evidence")
    if history_hygiene_state != "history-scope-unknown" and scopes:
        raise ValueError("uninspected scopes require unknown history")
    if history_hygiene_state == "history-scope-unknown" and not scopes:
        raise ValueError("unknown history requires named scopes")
    migration = {
        "not-needed": "No legacy local credential migration was needed.",
        "migrated-local-config": "Local configuration was migrated to vault .env references. This does not prove the old key was rotated.",
        "partial": "Local credential migration is partial; setup cleanup remains incomplete.",
        "refused": "Dex refused local credential migration because its safety preconditions were not proven.",
        "rewound": "Dex restored the exact local configuration preimages. Provider credential validity was not changed.",
    }[migration_state]
    cleanup = " Setup cleanup is incomplete because `.mcp.json` still contains the revoked value; remove it manually to complete local-config cleanup. Dex did not edit this file."
    if security_state == "remediated":
        security = "Your old key was rotated and is no longer usable. Security is fixed."
    elif security_state == "rotation-pending" and active_residual_state == "unrevoked-or-unclassified":
        security = "An active `.mcp.json` value may still be usable. Security is not fixed; rotate/revoke it at the provider or remove it manually. Dex did not edit this file."
    elif security_state == "rotation-pending":
        security = (
            "Security is not fixed because these required rotation/replacement checks are incomplete: "
            + ", ".join(missing)
            + "."
        )
    else:
        security = (
            "Dex cannot determine security because these evidence categories are unavailable or inconsistent: "
            + ", ".join(unavailable)
            + "."
        )
        if active_residual_state == "unrevoked-or-unclassified":
            security += (
                " Dex cannot determine whether the active `.mcp.json` value remains usable. Dex did not edit this file."
            )
    if active_residual_state == "proven-revoked":
        security += cleanup
    history = {
        "history-cleanup-pending": "Copies remain in inspected local Git history. Cleaning them is optional privacy hygiene.",
        "history-clean": "The inspected history scopes are clean: no revoked copies were found.",
        "history-scope-unknown": "These historical scope categories were not inspected: "
        + ", ".join(scopes)
        + ". Checking them is optional privacy hygiene, not a current-danger warning.",
    }[history_hygiene_state]
    return CredentialStatusCopy(migration, security, history)
