"""Atomic local credential migration and deterministic remediation status."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
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
        path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.exists() and current.is_symlink():
            return False
    return (absent_ok and not path.exists() and path.parent.is_dir()) or (path.is_file() and not path.is_symlink())


def _read_nofollow(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        return handle.read()


def _fsync_parent(path: Path) -> bool:
    try:
        descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True
    except OSError:
        return False


def probe_atomic_migration(vault_root: Path, journal_dir: Path) -> CapabilityResult:
    """Exercise the exact local primitives; platform labels never participate."""
    results = {name: False for name in CAPABILITIES}
    config = vault_root / "System" / "integrations" / "config.yaml"
    env_file = vault_root / ".env"
    journal_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(journal_dir, 0o700)
    results["regular-targets"] = _contained_regular(config, vault_root) and _contained_regular(
        env_file, vault_root, absent_ok=True
    )
    results["no-follow-containment"] = (
        results["regular-targets"] and journal_dir.is_dir() and not journal_dir.is_symlink()
    )
    probe = journal_dir / f".capability-{uuid.uuid4().hex}"
    replacement = probe.with_name(probe.name + ".replacement")
    try:
        probe.write_bytes(b"before")
        os.chmod(probe, 0o600)
        with probe.open("rb") as handle:
            os.fsync(handle.fileno())
        results["journal-readback"] = probe.read_bytes() == b"before" and stat.S_IMODE(probe.stat().st_mode) == 0o600
        replacement.write_bytes(b"after")
        results["same-directory-temp"] = (
            replacement.parent == probe.parent and replacement.stat().st_dev == probe.stat().st_dev
        )
        with replacement.open("rb") as handle:
            os.fsync(handle.fileno())
        results["durability"] = _fsync_parent(replacement)
        before = probe.stat()
        results["precommit-recheck"] = probe.read_bytes() == b"before" and before.st_mode == probe.stat().st_mode
        os.replace(replacement, probe)
        results["atomic-replace"] = probe.read_bytes() == b"after" and not replacement.exists()
        results["replacement-readback"] = probe.read_bytes() == b"after"
        rollback = probe.with_name(probe.name + ".rollback")
        rollback.write_bytes(b"before")
        os.replace(rollback, probe)
        results["rollback-readback"] = probe.read_bytes() == b"before"
    except OSError:
        pass
    finally:
        for path in (probe, replacement, probe.with_name(probe.name + ".rollback")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    return CapabilityResult(results)


def _legacy_values(raw: bytes) -> tuple[dict[str, str], dict[str, str]]:
    text = raw.decode("utf-8")
    if re.search(r"(^|\n)[ \t]*(todoist|trello):[^\n]*[&*]|(^|\n)[ \t]*(api_key|token):[ \t]*[>|]", text):
        raise ValueError("aliases and multiline credential values are refused")
    # SafeLoader silently accepts duplicate keys; reject credential keys textually.
    for section in ("todoist", "trello"):
        block = re.search(rf"(?ms)^(?P<i>[ ]*){section}:\s*\n(?P<body>(?:(?P=i)[ ]+.*\n?)*)", text)
        if block:
            for key in ("api_key", "token"):
                if len(re.findall(rf"(?m)^\s+{key}\s*:", block.group("body"))) > 1:
                    raise ValueError("duplicate credential key")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError("integration config must be an object")
    values: dict[str, str] = {}
    refs: dict[str, str] = {}
    for (service, key), (env_name, ref_name) in LEGACY_CREDENTIAL_FIELDS.items():
        settings = data.get(service)
        if not isinstance(settings, dict) or key not in settings:
            continue
        value = settings[key]
        if not isinstance(value, str) or not value or "\n" in value:
            raise ValueError("legacy credential must be an unambiguous scalar")
        values[env_name] = value
        refs[f"{service}.{key}"] = ref_name
    return values, refs


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
    config = vault_root / "System" / "integrations" / "config.yaml"
    config_raw = _read_nofollow(config)
    try:
        values, refs = _legacy_values(config_raw)
    except (UnicodeDecodeError, ValueError, yaml.YAMLError):
        return MigrationResult("refused")
    mcp = inspect_active_mcp_config(vault_root)
    if not mcp.inspected:
        return MigrationResult(
            "refused" if values else "partial",
            active_residual_state="unrevoked-or-unclassified",
            uninspected_scopes=("worktree",),
            uninspected_reasons=(mcp.reason or "unsafe-active-config",),
        )
    mcp_raw = mcp.data or b""
    mcp_raw_residual = any(value.encode() in mcp_raw for value in values.values()) or bool(
        re.search(rb'"(?:TODOIST_API_KEY|TRELLO_API_KEY|TRELLO_TOKEN)"\s*:\s*"[^"$<{][^"]*"', mcp_raw)
    )
    if not values:
        return MigrationResult(
            "partial" if mcp_raw_residual else "not-needed",
            active_residual_state="unrevoked-or-unclassified" if mcp_raw_residual else "none",
        )
    journal_dir = vault_root / "System" / ".dex" / "adoption" / "credential-journals"
    capability = probe_atomic_migration(vault_root, journal_dir)
    if not capability.authorized:
        return MigrationResult(
            "refused", failed_capabilities=tuple(sorted(k for k, v in capability.results.items() if not v))
        )
    env_path = vault_root / ".env"
    env_raw = _read_nofollow(env_path) if env_path.exists() else None
    if env_raw:
        existing_values = parse_env_assignments(env_raw)
        for name, value in values.items():
            if name in existing_values and existing_values[name] != value:
                return MigrationResult("refused")
    expected_config = _replace_yaml_credentials(config_raw, refs)
    journal_id = uuid.uuid4().hex
    journal = journal_dir / f"{journal_id}.json"
    record = {
        "schema_version": 1,
        "config": {
            "bytes_hex": config_raw.hex(),
            "sha256": _hash(config_raw),
            "mode": stat.S_IMODE(config.stat().st_mode),
        },
        "env": None
        if env_raw is None
        else {"bytes_hex": env_raw.hex(), "sha256": _hash(env_raw), "mode": stat.S_IMODE(env_path.stat().st_mode)},
    }
    descriptor = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if not _fsync_parent(journal) or json.loads(_read_nofollow(journal).decode("utf-8")) != record:
        return MigrationResult("refused")
    config_before = (config.stat().st_ino, _hash(_read_nofollow(config)), stat.S_IMODE(config.stat().st_mode))
    try:
        update_vault_env(vault_root, values)
        if (config.stat().st_ino, _hash(_read_nofollow(config)), stat.S_IMODE(config.stat().st_mode)) != config_before:
            raise OSError("config changed during migration")
        fd, temporary = tempfile.mkstemp(prefix=".config.yaml.", dir=config.parent)
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), record["config"]["mode"])
            handle.write(expected_config)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, config)
        if not _fsync_parent(config) or _read_nofollow(config) != expected_config:
            raise OSError("config readback mismatch")
    except Exception:
        rewind_credential_migration(vault_root, journal_id)
        return MigrationResult("refused", journal_id)
    return MigrationResult(
        "partial" if mcp_raw_residual else "migrated-local-config",
        journal_id,
        active_residual_state="unrevoked-or-unclassified" if mcp_raw_residual else "none",
    )


def rewind_credential_migration(vault_root: Path, journal_id: str) -> MigrationResult:
    journal = vault_root / "System" / ".dex" / "adoption" / "credential-journals" / f"{journal_id}.json"
    record = json.loads(_read_nofollow(journal).decode("utf-8"))
    for name, entry in (("config", record["config"]), ("env", record["env"])):
        path = vault_root / ("System/integrations/config.yaml" if name == "config" else ".env")
        if entry is None:
            path.unlink(missing_ok=True)
            continue
        expected = bytes.fromhex(entry["bytes_hex"])
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), entry["mode"])
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if not _fsync_parent(path) or _read_nofollow(path) != expected or _hash(expected) != entry["sha256"]:
            raise OSError("credential rewind readback mismatch")
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
        if active_residual_state == "proven-revoked":
            security += cleanup
    elif security_state == "rotation-pending" and active_residual_state == "unrevoked-or-unclassified":
        security = "An active `.mcp.json` value may still be usable. Security is not fixed; rotate/revoke it at the provider or remove it manually. Dex did not edit this file."
    elif security_state == "rotation-pending":
        security = (
            "Security is not fixed because these required rotation/replacement checks are incomplete: "
            + ", ".join(evidence)
            + "."
        )
        if active_residual_state == "proven-revoked":
            security += cleanup
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
        elif active_residual_state == "proven-revoked":
            security += cleanup
    history = {
        "history-cleanup-pending": "Copies remain in inspected local Git history. Cleaning them is optional privacy hygiene.",
        "history-clean": "The inspected history scopes are clean: no revoked copies were found.",
        "history-scope-unknown": "These historical scope categories were not inspected: "
        + ", ".join(scopes)
        + ". Checking them is optional privacy hygiene, not a current-danger warning.",
    }[history_hygiene_state]
    return CredentialStatusCopy(migration, security, history)
