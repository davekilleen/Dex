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
from typing import Literal

import yaml

from core.utils.integration_credentials import (
    LEGACY_CREDENTIAL_FIELDS,
    inspect_active_mcp_config,
    parse_env_assignments,
    update_vault_env,
)

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


def _contained_regular(path: Path, root: Path, *, absent_ok: bool = False) -> bool:
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
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


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


def _atomic_replace_at(directory: int, name: str, data: bytes, mode: int) -> None:
    temporary = f".{name}.{uuid.uuid4().hex}"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode, dir_fd=directory)
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
        actual, metadata = _read_at_with_metadata(directory, name)
        if actual != data or stat.S_IMODE(metadata.st_mode) != mode:
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
    results["regular-targets"] = _contained_regular(config, vault_root) and _contained_regular(
        env_file, vault_root, absent_ok=True
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
    text = raw.decode("utf-8")
    if re.search(r"(^|\n)[ \t]*(todoist|trello):[^\n]*[&*]|(^|\n)[ \t]*(api_key|token):[ \t]*[>|]", text):
        raise ValueError("aliases and multiline credential values are refused")
    # SafeLoader silently accepts duplicate keys; reject credential keys textually.
    for section in ("todoist", "trello"):
        block = re.search(rf"(?ms)^(?P<i>[ ]*){section}:\s*\n(?P<body>(?:(?P=i)[ ]+.*\n?)*)", text)
        if block:
            for key in ("api_key", "token", "api_key_env_var", "token_env_var"):
                if len(re.findall(rf"(?m)^\s+{key}\s*:", block.group("body"))) > 1:
                    raise ValueError("duplicate credential key")
    data = yaml.safe_load(text) or {}
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
    return current_raw == expected_raw and (
        current_metadata.st_dev,
        current_metadata.st_ino,
        current_metadata.st_size,
        stat.S_IMODE(current_metadata.st_mode),
    ) == (
        expected_metadata.st_dev,
        expected_metadata.st_ino,
        expected_metadata.st_size,
        stat.S_IMODE(expected_metadata.st_mode),
    )


def _env_storage_is_local_only(vault_root: Path) -> bool:
    """Require ignored, untracked .env in Git vaults; non-Git vaults remain supported."""
    from core.utils.safe_autosave import _git as safe_git

    git_marker = vault_root / ".git"
    try:
        git_metadata = git_marker.lstat()
    except FileNotFoundError:
        return True
    if not (stat.S_ISDIR(git_metadata.st_mode) or stat.S_ISREG(git_metadata.st_mode)):
        return False
    try:
        if safe_git(vault_root, "rev-parse", "--is-inside-work-tree").strip() != b"true":
            return False
    except RuntimeError:
        return False
    try:
        safe_git(vault_root, "ls-files", "--error-unmatch", "--", ".env")
    except RuntimeError:
        tracked = False
    else:
        tracked = True
    try:
        ignored = safe_git(vault_root, "check-ignore", "-q", "--", ".env") == b""
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
    except (UnicodeDecodeError, ValueError, yaml.YAMLError):
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
    journal_id = uuid.uuid4().hex
    journal_name = f"{journal_id}.json"
    record = {
        "schema_version": 1,
        "config": {
            "bytes_hex": config_raw.hex(),
            "sha256": _hash(config_raw),
            "mode": stat.S_IMODE(config_snapshot_metadata.st_mode),
        },
        "env": None
        if env_raw is None
        else {
            "bytes_hex": env_raw.hex(),
            "sha256": _hash(env_raw),
            "mode": stat.S_IMODE(env_metadata.st_mode),
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
        if config_bytes != config_raw or (
            config_metadata.st_dev,
            config_metadata.st_ino,
            config_metadata.st_size,
            stat.S_IMODE(config_metadata.st_mode),
        ) != (
            config_snapshot_metadata.st_dev,
            config_snapshot_metadata.st_ino,
            config_snapshot_metadata.st_size,
            stat.S_IMODE(config_snapshot_metadata.st_mode),
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
        update_vault_env(vault_root, values)
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
        _atomic_replace_at(config_descriptor, "config.yaml", expected_config, record["config"]["mode"])
    except Exception:
        rewind_credential_migration(vault_root, journal_id)
        return MigrationResult("refused", journal_id)
    finally:
        os.close(config_descriptor)
    return MigrationResult(
        "partial" if mcp_raw_residual else "migrated-local-config",
        journal_id,
        active_residual_state="unrevoked-or-unclassified" if mcp_raw_residual else "none",
    )


def rewind_credential_migration(vault_root: Path, journal_id: str) -> MigrationResult:
    if not re.fullmatch(r"[0-9a-f]{32}", journal_id):
        raise ValueError("invalid credential journal id")
    journal_descriptor = _open_directory_chain(
        vault_root, ("System", ".dex", "adoption", "credential-journals")
    )
    try:
        record = json.loads(_read_at(journal_descriptor, f"{journal_id}.json").decode("utf-8"))
    finally:
        os.close(journal_descriptor)
    for name, entry in (("config", record["config"]), ("env", record["env"])):
        parts = ("System", "integrations") if name == "config" else ()
        target = "config.yaml" if name == "config" else ".env"
        parent = _open_directory_chain(vault_root, parts)
        try:
            if entry is None:
                try:
                    os.unlink(target, dir_fd=parent)
                except FileNotFoundError:
                    pass
                os.fsync(parent)
                continue
            expected = bytes.fromhex(entry["bytes_hex"])
            if _hash(expected) != entry["sha256"]:
                raise OSError("credential rewind readback mismatch")
            _atomic_replace_at(parent, target, expected, entry["mode"])
        finally:
            os.close(parent)
    return MigrationResult("rewound", journal_id)


def render_credential_status(
    migration_state: MigrationState,
    security_state: SecurityState,
    active_residual_state: ActiveResidualState,
    history_hygiene_state: HistoryState,
    evidence_codes: tuple[str, ...] = (),
    uninspected_scope_categories: tuple[str, ...] = (),
) -> CredentialStatusCopy:
    evidence = tuple(sorted(set(evidence_codes)))
    scopes = tuple(sorted(set(uninspected_scope_categories)))
    if not set(evidence) <= EVIDENCE_CODES or not set(scopes) <= SCOPE_CATEGORIES:
        raise ValueError("unknown credential evidence category")
    if active_residual_state != "none" and migration_state != "partial":
        raise ValueError("raw MCP residual requires partial migration")
    if security_state == "remediated" and active_residual_state == "unrevoked-or-unclassified":
        raise ValueError("security cannot be fixed with a potentially usable residual")
    if active_residual_state == "proven-revoked" and "provider-binding" not in evidence:
        raise ValueError("proven residual requires provider binding evidence")
    required_remediation = {
        "old-key-revocation",
        "replacement-present",
        "replacement-health",
        "active-copy",
        "provider-binding",
    }
    if security_state == "remediated" and not required_remediation <= set(evidence):
        raise ValueError("remediated security requires complete bound rotation and replacement evidence")
    if history_hygiene_state == "history-clean" and scopes:
        raise ValueError("clean history cannot have uninspected scopes")
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
            + ", ".join(evidence)
            + "."
        )
    else:
        security = (
            "Dex cannot determine security because these evidence categories are unavailable or inconsistent: "
            + ", ".join(evidence)
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
