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


RewindPhase = Literal["ready", "publishing", "recovery", "completed"]


@dataclass(frozen=True)
class FileIdentity:
    device: int
    inode: int
    mode: int
    links: int
    uid: int
    gid: int
    size: int

    @classmethod
    def from_metadata(cls, metadata: os.stat_result) -> "FileIdentity":
        return cls(
            metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink,
            metadata.st_uid, metadata.st_gid, metadata.st_size,
        )

    @classmethod
    def parse(cls, value: object, *, optional: bool = False) -> "FileIdentity | None":
        if value is None and optional:
            return None
        if not isinstance(value, list) or len(value) != 7 or not all(isinstance(item, int) for item in value):
            raise OSError("invalid credential journal file identity")
        identity = cls(*value)
        if min(identity.device, identity.inode, identity.mode, identity.links, identity.uid, identity.gid, identity.size) < 0:
            raise OSError("invalid credential journal file identity")
        return identity

    def json(self) -> list[int]:
        return [self.device, self.inode, self.mode, self.links, self.uid, self.gid, self.size]


@dataclass(frozen=True)
class CredentialImage:
    data: bytes
    mode: int
    uid: int
    gid: int
    identity: FileIdentity | None = None

    @classmethod
    def parse_preimage(cls, value: object, *, optional: bool = False) -> "CredentialImage | None":
        if value is None and optional:
            return None
        if not isinstance(value, dict) or set(value) != {"bytes_hex", "sha256", "mode", "uid", "gid"}:
            raise OSError("invalid credential journal preimage")
        try:
            image = cls(
                bytes.fromhex(value["bytes_hex"]), int(value["mode"]),
                int(value["uid"]), int(value["gid"]),
            )
        except (TypeError, ValueError) as error:
            raise OSError("invalid credential journal preimage") from error
        if (
            _hash(image.data) != value["sha256"]
            or not 0 <= image.mode <= 0o777
            or min(image.uid, image.gid) < 0
            or not _owner_restorable(image.owner)
        ):
            raise OSError("invalid credential journal preimage")
        return image

    @property
    def owner(self) -> tuple[int, int]:
        return self.uid, self.gid

    def preimage_json(self) -> dict[str, object]:
        return {
            "bytes_hex": self.data.hex(), "sha256": _hash(self.data), "mode": self.mode,
            "uid": self.uid, "gid": self.gid,
        }

    def with_identity(self, metadata: os.stat_result) -> "CredentialImage":
        identity = FileIdentity.from_metadata(metadata)
        if (
            stat.S_IMODE(identity.mode) != self.mode
            or identity.uid != self.uid
            or identity.gid != self.gid
            or identity.size != len(self.data)
            or identity.links != 1
        ):
            raise OSError("credential journal postimage identity mismatch")
        return CredentialImage(self.data, self.mode, self.uid, self.gid, identity)

    def same_contents(self, other: "CredentialImage | None") -> bool:
        return other is not None and (
            self.data, self.mode, self.uid, self.gid
        ) == (
            other.data, other.mode, other.uid, other.gid
        )


@dataclass
class CredentialTarget:
    name: Literal["config", "env"]
    parent_parts: tuple[str, ...]
    filename: str
    preimage: CredentialImage | None
    postimage: CredentialImage

    AUTHORITIES = {
        "config": (("System", "integrations"), "config.yaml"),
        "env": ((), ".env"),
    }

    @classmethod
    def create(
        cls,
        name: Literal["config", "env"],
        preimage: CredentialImage | None,
        postimage: CredentialImage,
    ) -> "CredentialTarget":
        parent_parts, filename = cls.AUTHORITIES[name]
        return cls(name, parent_parts, filename, preimage, postimage)

    def __post_init__(self) -> None:
        authority = self.AUTHORITIES.get(self.name)
        if authority != (self.parent_parts, self.filename):
            raise OSError("invalid credential journal target authority")
        if self.name == "config" and self.preimage is None:
            raise OSError("credential journal requires a config preimage")
        if self.name == "env" and self.postimage.mode != 0o600:
            raise OSError("credential journal requires a restrictive env postimage")


@dataclass
class CredentialJournal:
    config: CredentialTarget
    env: CredentialTarget
    _phase: RewindPhase = "ready"

    TOP_LEVEL_KEYS = frozenset({"schema_version", "config", "env", "postimages", "rewind"})
    POSTIMAGE_KEYS = frozenset(
        {
            "config_bytes_hex", "config_sha256", "config_mode", "config_uid", "config_gid",
            "config_identity", "env_bytes_hex", "env_sha256", "env_mode", "env_uid", "env_gid",
            "env_identity",
        }
    )
    PHASES = frozenset({"ready", "publishing", "recovery", "completed"})

    def __post_init__(self) -> None:
        if self.config.name != "config" or self.env.name != "env" or self._phase not in self.PHASES:
            raise OSError("invalid credential journal model")

    @classmethod
    def create(
        cls,
        *,
        config_preimage: CredentialImage,
        env_preimage: CredentialImage | None,
        config_postimage: CredentialImage,
        env_postimage: CredentialImage,
    ) -> "CredentialJournal":
        return cls(
            CredentialTarget.create("config", config_preimage, config_postimage),
            CredentialTarget.create("env", env_preimage, env_postimage),
        )

    @classmethod
    def parse(cls, raw: bytes) -> "CredentialJournal":
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise OSError("invalid credential journal") from error
        if not isinstance(value, dict) or set(value) != cls.TOP_LEVEL_KEYS or value.get("schema_version") != 1:
            raise OSError("invalid credential journal")
        rewind = value.get("rewind")
        if not isinstance(rewind, dict) or set(rewind) != {"phase"} or rewind.get("phase") not in cls.PHASES:
            raise OSError("invalid credential rewind phase")
        postimages = value.get("postimages")
        if not isinstance(postimages, dict) or set(postimages) != cls.POSTIMAGE_KEYS:
            raise OSError("invalid credential journal postimages")
        config_pre = CredentialImage.parse_preimage(value.get("config"))
        env_pre = CredentialImage.parse_preimage(value.get("env"), optional=True)
        if config_pre is None:  # pragma: no cover - nonoptional parser already rejects this
            raise OSError("invalid credential journal config preimage")
        config_post = cls._parse_postimage(postimages, "config")
        env_post = cls._parse_postimage(postimages, "env")
        return cls(
            CredentialTarget.create("config", config_pre, config_post),
            CredentialTarget.create("env", env_pre, env_post),
            rewind["phase"],
        )

    @staticmethod
    def _parse_postimage(value: dict[str, object], name: str) -> CredentialImage:
        try:
            data = bytes.fromhex(value[f"{name}_bytes_hex"])
            image = CredentialImage(
                data, int(value[f"{name}_mode"]), int(value[f"{name}_uid"]),
                int(value[f"{name}_gid"]),
                FileIdentity.parse(value[f"{name}_identity"], optional=True),
            )
        except (TypeError, ValueError) as error:
            raise OSError("invalid credential journal postimages") from error
        if (
            _hash(data) != value[f"{name}_sha256"]
            or not 0 <= image.mode <= 0o777
            or min(image.uid, image.gid) < 0
            or not _owner_restorable(image.owner)
            or (image.identity is not None and (
                stat.S_IMODE(image.identity.mode) != image.mode
                or image.identity.uid != image.uid
                or image.identity.gid != image.gid
                or image.identity.size != len(image.data)
                or image.identity.links != 1
            ))
        ):
            raise OSError("invalid credential journal postimages")
        return image

    @property
    def targets(self) -> tuple[CredentialTarget, CredentialTarget]:
        return self.config, self.env

    @property
    def phase(self) -> RewindPhase:
        return self._phase

    @property
    def fully_published(self) -> bool:
        return all(target.postimage.identity is not None for target in self.targets)

    def target(self, name: Literal["config", "env"]) -> CredentialTarget:
        return self.config if name == "config" else self.env

    def record_postimage(self, name: Literal["config", "env"], metadata: os.stat_result) -> None:
        target = self.target(name)
        target.postimage = target.postimage.with_identity(metadata)

    def begin_publication(self) -> None:
        self._transition("ready", "publishing")

    def begin_recovery(self) -> None:
        self._transition("publishing", "recovery")

    def finish_recovery(self) -> None:
        self._transition("recovery", "ready")

    def complete(self) -> None:
        self._transition("publishing", "completed")

    def _transition(self, expected: RewindPhase, target: RewindPhase) -> None:
        if self._phase != expected:
            raise OSError("invalid credential rewind transition")
        self._phase = target

    def serialize(self) -> bytes:
        postimages: dict[str, object] = {}
        for target in self.targets:
            image = target.postimage
            postimages.update(
                {
                    f"{target.name}_bytes_hex": image.data.hex(),
                    f"{target.name}_sha256": _hash(image.data),
                    f"{target.name}_mode": image.mode,
                    f"{target.name}_uid": image.uid,
                    f"{target.name}_gid": image.gid,
                    f"{target.name}_identity": image.identity.json() if image.identity else None,
                }
            )
        value = {
            "schema_version": 1,
            "config": self.config.preimage.preimage_json() if self.config.preimage else None,
            "env": self.env.preimage.preimage_json() if self.env.preimage else None,
            "postimages": postimages,
            "rewind": {"phase": self._phase},
        }
        return (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")


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


def _store_credential_journal(directory: int, name: str, journal: CredentialJournal) -> None:
    _atomic_replace_at(directory, name, journal.serialize(), 0o600)


def _record_postimage(
    vault_root: Path,
    journal_name: str,
    journal: CredentialJournal,
    name: Literal["config", "env"],
    metadata: os.stat_result,
) -> None:
    journal.record_postimage(name, metadata)
    descriptor = _open_directory_chain(vault_root, ("System", ".dex", "adoption", "credential-journals"))
    try:
        _store_credential_journal(descriptor, journal_name, journal)
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
    config_preimage = CredentialImage(
        config_raw, stat.S_IMODE(config_snapshot_metadata.st_mode),
        config_snapshot_metadata.st_uid, config_snapshot_metadata.st_gid,
    )
    env_preimage = (
        None
        if env_raw is None or env_metadata is None
        else CredentialImage(
            env_raw, stat.S_IMODE(env_metadata.st_mode), env_metadata.st_uid, env_metadata.st_gid,
        )
    )
    env_owner = env_preimage.owner if env_preimage else config_preimage.owner
    if hasattr(os, "getuid") and hasattr(os, "getgid"):
        env_owner = os.getuid(), os.getgid()
    journal = CredentialJournal.create(
        config_preimage=config_preimage,
        env_preimage=env_preimage,
        config_postimage=CredentialImage(expected_config, config_preimage.mode, *config_preimage.owner),
        env_postimage=CredentialImage(expected_env, 0o600, *env_owner),
    )
    try:
        journal_descriptor = _open_directory_chain(
            vault_root, ("System", ".dex", "adoption", "credential-journals")
        )
        try:
            descriptor = os.open(
                journal_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=journal_descriptor
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(journal.serialize())
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(journal_descriptor)
            if CredentialJournal.parse(_read_at(journal_descriptor, journal_name)).serialize() != journal.serialize():
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
                vault_root, journal_name, journal, "env", metadata
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
            journal.config.preimage.mode,
            before_publish=lambda metadata: _record_postimage(
                vault_root, journal_name, journal, "config", metadata
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


def _owner_restorable(owner: tuple[int, int]) -> bool:
    if not all(hasattr(os, name) for name in ("geteuid", "getegid", "getgroups")):
        return True
    effective_uid = os.geteuid()
    if effective_uid == 0:
        return True
    return owner[0] == effective_uid and owner[1] in {os.getegid(), *os.getgroups()}


@dataclass
class _OpenedCredentialTarget:
    target: CredentialTarget
    parent: int

    def close(self) -> None:
        os.close(self.parent)


def _open_credential_targets(
    vault_root: Path, journal: CredentialJournal
) -> tuple[_OpenedCredentialTarget, _OpenedCredentialTarget]:
    opened: list[_OpenedCredentialTarget] = []
    try:
        for target in journal.targets:
            opened.append(
                _OpenedCredentialTarget(
                    target, _open_directory_chain(vault_root, target.parent_parts)
                )
            )
    except BaseException:
        for item in reversed(opened):
            item.close()
        raise
    return opened[0], opened[1]


def _require_image(
    opened: _OpenedCredentialTarget,
    image: CredentialImage,
    *,
    require_identity: bool = False,
) -> None:
    data, metadata = _read_at_with_metadata(opened.parent, opened.target.filename)
    if (
        data != image.data
        or stat.S_IMODE(metadata.st_mode) != image.mode
        or (metadata.st_uid, metadata.st_gid) != image.owner
        or (
            require_identity
            and (
                image.identity is None
                or FileIdentity.from_metadata(metadata) != image.identity
            )
        )
    ):
        raise OSError("credential rewind requires an unchanged migration-owned postimage")


def _publish_image(opened: _OpenedCredentialTarget, image: CredentialImage) -> None:
    _atomic_replace_at(
        opened.parent,
        opened.target.filename,
        image.data,
        image.mode,
        owner=image.owner,
    )


def _restore_rewind_postimages(opened_targets: tuple[_OpenedCredentialTarget, ...]) -> None:
    """Resolve an interrupted rewind back to the secret-safe migrated state."""
    for opened in opened_targets:
        target = opened.target
        try:
            current, metadata = _read_at_with_metadata(opened.parent, target.filename)
        except FileNotFoundError:
            if target.preimage is not None or target.name == "config":
                raise OSError("credential rewind recovery-required: target disappeared") from None
        else:
            current_image = CredentialImage(
                current,
                stat.S_IMODE(metadata.st_mode),
                metadata.st_uid,
                metadata.st_gid,
            )
            if (
                not current_image.same_contents(target.postimage)
                and not current_image.same_contents(target.preimage)
            ):
                raise OSError("credential rewind recovery-required: target changed independently")
            if current_image.same_contents(target.postimage):
                continue
        _publish_image(opened, target.postimage)


def _refresh_postimage_identities(opened_targets: tuple[_OpenedCredentialTarget, ...]) -> None:
    for opened in opened_targets:
        data, metadata = _read_at_with_metadata(opened.parent, opened.target.filename)
        image = opened.target.postimage
        if (
            data != image.data
            or stat.S_IMODE(metadata.st_mode) != image.mode
            or (metadata.st_uid, metadata.st_gid) != image.owner
        ):
            raise OSError("credential rewind recovery-required: postimage readback mismatch")
        opened.target.postimage = image.with_identity(metadata)


def _finish_incomplete_migration_rollback(
    opened_targets: tuple[_OpenedCredentialTarget, ...],
) -> None:
    """Restore migration preimages when publication never reached both targets."""
    for opened in opened_targets:
        target = opened.target
        if target.postimage.identity is not None:
            _require_image(opened, target.postimage, require_identity=True)
        elif target.preimage is None:
            try:
                os.stat(target.filename, dir_fd=opened.parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise OSError("credential migration rollback target appeared") from None
        else:
            _require_image(opened, target.preimage)
    # Local-only state is restored before tracked configuration.
    for opened in reversed(opened_targets):
        target = opened.target
        if target.postimage.identity is None:
            continue
        if target.preimage is None:
            os.unlink(target.filename, dir_fd=opened.parent)
            os.fsync(opened.parent)
        else:
            _publish_image(opened, target.preimage)


def _verify_completed_rewind(opened_targets: tuple[_OpenedCredentialTarget, ...]) -> None:
    for opened in opened_targets:
        preimage = opened.target.preimage
        if preimage is None:
            try:
                os.stat(opened.target.filename, dir_fd=opened.parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise OSError("credential rewind preimage changed after completion")
        _require_image(opened, preimage)


def _recover_rewind_publication(
    journal_parent: int,
    journal_name: str,
    journal: CredentialJournal,
    opened_targets: tuple[_OpenedCredentialTarget, ...],
) -> None:
    if journal.phase == "publishing":
        journal.begin_recovery()
        _store_credential_journal(journal_parent, journal_name, journal)
    elif journal.phase != "recovery":
        raise OSError("invalid credential rewind recovery phase")
    _restore_rewind_postimages(opened_targets)
    _refresh_postimage_identities(opened_targets)
    journal.finish_recovery()
    _store_credential_journal(journal_parent, journal_name, journal)


def rewind_credential_migration(vault_root: Path, journal_id: str) -> MigrationResult:
    if not re.fullmatch(r"[0-9a-f]{32}", journal_id):
        raise ValueError("invalid credential journal id")
    journal_name = f"{journal_id}.json"
    root_before = vault_root.lstat()
    journal_parent = _open_directory_chain(
        vault_root, ("System", ".dex", "adoption", "credential-journals")
    )
    opened_targets: tuple[_OpenedCredentialTarget, ...] = ()
    try:
        journal_raw, journal_metadata = _read_at_with_metadata(journal_parent, journal_name)
        if (
            stat.S_IMODE(journal_metadata.st_mode) != 0o600
            or not _owner_restorable((journal_metadata.st_uid, journal_metadata.st_gid))
        ):
            raise OSError("unsafe credential rewind journal authority")
        journal = CredentialJournal.parse(journal_raw)
        opened_targets = _open_credential_targets(vault_root, journal)
        env_root = next(item for item in opened_targets if item.target.name == "env")
        root_after = vault_root.lstat()
        opened_root = os.fstat(env_root.parent)
        root_identities = {
            (item.st_dev, item.st_ino, item.st_mode, item.st_uid, item.st_gid)
            for item in (root_before, root_after, opened_root)
        }
        if len(root_identities) != 1:
            raise OSError("credential rewind vault root identity changed")

        if not journal.fully_published:
            if journal.phase != "ready":
                raise OSError("incomplete credential migration has invalid rewind phase")
            _finish_incomplete_migration_rollback(opened_targets)
            return MigrationResult("rewound", journal_id)
        if journal.phase == "completed":
            _verify_completed_rewind(opened_targets)
            return MigrationResult("rewound", journal_id)
        if journal.phase in {"publishing", "recovery"}:
            _recover_rewind_publication(
                journal_parent, journal_name, journal, opened_targets
            )
        if journal.phase != "ready":
            raise OSError("invalid credential rewind phase")

        # Complete read-only prevalidation of both pinned targets precedes mutation.
        for opened in opened_targets:
            _require_image(opened, opened.target.postimage, require_identity=True)
        journal.begin_publication()
        _store_credential_journal(journal_parent, journal_name, journal)
        try:
            # Publish local-only state first; tracked raw YAML is the final boundary.
            for opened in reversed(opened_targets):
                _require_image(opened, opened.target.postimage, require_identity=True)
                preimage = opened.target.preimage
                if preimage is None:
                    os.unlink(opened.target.filename, dir_fd=opened.parent)
                    os.fsync(opened.parent)
                else:
                    _publish_image(opened, preimage)
            journal.complete()
            _store_credential_journal(journal_parent, journal_name, journal)
        except BaseException:
            _recover_rewind_publication(
                journal_parent, journal_name, journal, opened_targets
            )
            raise
    finally:
        for opened in reversed(opened_targets):
            opened.close()
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
