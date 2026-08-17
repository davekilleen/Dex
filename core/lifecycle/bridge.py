"""One-release handoff from the legacy updater to the lifecycle engine."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.lifecycle.catalog import load_catalog
from core.lifecycle.filesystem import FilesystemInspectionError, bounded_read
from core.lifecycle.inventory import build_inventory
from core.lifecycle.model import HEX_SHA256, SEMVER
from core.path_safety import unsafe_existing_parent
from core.transaction.engine import Transaction
from core.transaction.fsync import fsync_directory
from core.transaction.journal import PREVIOUS_SCHEMA_VERSION, SCHEMA_VERSION

BRIDGE_CONTRACT_VERSION = 1
ACTIVATION_VERSION = 1
BRIDGE_RELEASE_RELATIVE = Path("core/lifecycle/catalog/bridge-release.json")
ACTIVATION_RELATIVE = Path("System/.dex/lifecycle/activation.json")
CATALOG_RELATIVE = Path("System/.release-catalog.json")
COMPATIBLE_ACTIVATION_API_VERSIONS = frozenset({"1.2.0", "1.3.0", "1.4.0"})


class BridgeError(RuntimeError):
    """The bridge declaration or recovery boundary is unsafe."""


class BridgeActivationError(BridgeError):
    """The read-then-record activation could not be proved or persisted."""


@dataclass(frozen=True)
class JournalCompatibility:
    current_schema: int
    previous_schema: int
    minimum_resumable_schema: int
    incompatible_action: str


@dataclass(frozen=True)
class BridgeRelease:
    bridge_contract_version: int
    release_version: str
    transaction_journal: JournalCompatibility


def _strict_json(raw: bytes, context: str) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise BridgeError(f"{context} repeats field {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except BridgeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BridgeError(f"{context} is not strict JSON: {error}") from error


def _closed(raw: object, fields: set[str], context: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
        raise BridgeError(f"{context} must be an object")
    missing = fields - set(raw)
    unknown = set(raw) - fields
    if missing or unknown:
        raise BridgeError(
            f"{context} fields disagree (missing={sorted(missing)}, unknown={sorted(unknown)})"
        )
    return raw


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def load_bridge_release(release_root: str | Path) -> BridgeRelease:
    """Load the shipped declaration and bind it to Transaction.resume's window."""
    try:
        raw = bounded_read(Path(release_root), BRIDGE_RELEASE_RELATIVE.as_posix())
    except FilesystemInspectionError as error:
        raise BridgeError(f"bridge release declaration is unavailable: {error}") from error
    value = _closed(
        _strict_json(raw, "bridge release declaration"),
        {"bridge_contract_version", "release_version", "transaction_journal"},
        "bridge release declaration",
    )
    if type(value["bridge_contract_version"]) is not int or value["bridge_contract_version"] != 1:
        raise BridgeError("bridge release declaration has an unsupported contract version")
    release_version = value["release_version"]
    if not isinstance(release_version, str) or SEMVER.fullmatch(release_version) is None:
        raise BridgeError("bridge release version is not strict SemVer")
    journal = _closed(
        value["transaction_journal"],
        {
            "current_schema",
            "previous_schema",
            "minimum_resumable_schema",
            "incompatible_action",
        },
        "bridge journal compatibility",
    )
    for field in ("current_schema", "previous_schema", "minimum_resumable_schema"):
        if type(journal[field]) is not int:
            raise BridgeError(f"bridge journal compatibility {field} must be an integer")
    if not isinstance(journal["incompatible_action"], str):
        raise BridgeError("bridge journal compatibility incompatible_action must be a string")
    compatibility = JournalCompatibility(
        journal["current_schema"],
        journal["previous_schema"],
        journal["minimum_resumable_schema"],
        journal["incompatible_action"],
    )
    expected = JournalCompatibility(
        SCHEMA_VERSION,
        PREVIOUS_SCHEMA_VERSION,
        PREVIOUS_SCHEMA_VERSION,
        "rollback-only",
    )
    if compatibility != expected:
        raise BridgeError(
            "bridge journal compatibility disagrees with Transaction.resume's current+previous window"
        )
    if raw != _canonical(
        {
            "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
            "release_version": release_version,
            "transaction_journal": {
                "current_schema": compatibility.current_schema,
                "previous_schema": compatibility.previous_schema,
                "minimum_resumable_schema": compatibility.minimum_resumable_schema,
                "incompatible_action": compatibility.incompatible_action,
            },
        }
    ):
        raise BridgeError("bridge release declaration is not canonical JSON")
    return BridgeRelease(BRIDGE_CONTRACT_VERSION, release_version, compatibility)


def _validate_activation(raw: bytes, bridge: BridgeRelease) -> dict[str, object]:
    try:
        value = _closed(
            _strict_json(raw, "existing activation"),
            {
                "activation_version",
                "api_version",
                "bridge_release_version",
                "baseline_inventory_sha256",
            },
            "existing activation",
        )
        from core.lifecycle.service import api_version

        if type(value["activation_version"]) is not int or value["activation_version"] != 1:
            raise BridgeActivationError("existing activation has an unsupported version")
        if value["api_version"] not in {
            api_version,
            *COMPATIBLE_ACTIVATION_API_VERSIONS,
        }:
            raise BridgeActivationError("existing activation belongs to another lifecycle API")
        if value["bridge_release_version"] != bridge.release_version:
            raise BridgeActivationError("existing activation belongs to another bridge release")
        digest = value["baseline_inventory_sha256"]
        if not isinstance(digest, str) or HEX_SHA256.fullmatch(digest) is None:
            raise BridgeActivationError("existing activation has an invalid inventory hash")
        document = dict(value)
        if raw != _canonical(document):
            raise BridgeActivationError("existing activation is not canonical JSON")
        return document
    except BridgeActivationError:
        raise
    except BridgeError as error:
        raise BridgeActivationError(f"existing activation is invalid: {error}") from error


def _well_formed_activation(raw: bytes) -> dict[str, object] | None:
    """Return the parsed record when it is structurally a routine activation.

    "Routine" means the closed four-field shape in canonical bytes with a
    supported activation version, a string API version, a strict-SemVer
    release, and a hex inventory digest.  Anything else returns ``None`` so
    callers keep treating it as fail-closed evidence rather than staleness.
    """
    try:
        value = _closed(
            _strict_json(raw, "existing activation"),
            {
                "activation_version",
                "api_version",
                "bridge_release_version",
                "baseline_inventory_sha256",
            },
            "existing activation",
        )
    except BridgeError:
        return None
    recorded = value["bridge_release_version"]
    digest = value["baseline_inventory_sha256"]
    if (
        type(value["activation_version"]) is int
        and value["activation_version"] == ACTIVATION_VERSION
        and isinstance(value["api_version"], str)
        and isinstance(recorded, str)
        and SEMVER.fullmatch(recorded) is not None
        and isinstance(digest, str)
        and HEX_SHA256.fullmatch(digest) is not None
        and raw == _canonical(dict(value))
    ):
        return dict(value)
    return None


def _stale_activation(raw: bytes, bridge: BridgeRelease) -> bool:
    """True when the record is a well-formed activation for a different bridge release.

    A delivered release rewrites the shipped bridge declaration, but the
    activation record is runtime state no release may write, so after every
    update the existing record still references the prior release. That
    staleness is routine, not evidence of tampering; activation re-records
    the baseline exactly as a first run would. Anything structurally invalid
    stays refused.
    """
    document = _well_formed_activation(raw)
    return document is not None and document["bridge_release_version"] != bridge.release_version


def discard_superseded_activation(
    vault_root: str | Path,
    installed_release_version: str,
) -> bool:
    """Best-effort, post-commit removal of a record another release left behind.

    Called by the release-apply paths after their transaction has committed a
    release identified by ``installed_release_version``.  The engine executing
    an update is the *previous* release's code, so it must never interpret the
    newly installed release's declarations (a future release may change the
    bridge contract, the journal schema, or the activation API surface) and it
    must never stamp its own ``api_version`` onto a record naming the new
    release.  Removing the superseded record avoids both: an absent record
    means "activate on next use" to every historic and future engine, and the
    next gated operation re-records the baseline with the newly installed
    code, which validates its own formats.

    This is tidy-up, never a gate: it runs outside the transaction, removes
    only a well-formed record naming a different release, leaves anything
    unreadable, malformed, or unsafe in place for the fail-closed activation
    path to judge, and never raises — a byte-verified committed update must
    not be failed (or rolled back) because its paperwork could not be cleared.
    ``activate_vault``'s stale-record re-recording remains the safety net.
    Returns ``True`` only when a record was removed.
    """
    try:
        if (
            not isinstance(installed_release_version, str)
            or SEMVER.fullmatch(installed_release_version) is None
        ):
            return False
        target = Path(vault_root) / ACTIVATION_RELATIVE
        if target.is_symlink() or not target.is_file():
            return False
        document = _well_formed_activation(target.read_bytes())
        if document is None or document["bridge_release_version"] == installed_release_version:
            return False
        target.unlink()
        fsync_directory(target.parent)
        return True
    except Exception:  # noqa: BLE001 - tidy-up must never fail a committed update
        return False


def _activation_directory(root: Path) -> Path:
    unsafe = unsafe_existing_parent(root, ACTIVATION_RELATIVE.as_posix())
    if unsafe is not None:
        raise BridgeActivationError(f"activation path is unsafe: {unsafe}")
    directory = root
    for component in ACTIVATION_RELATIVE.parts[:-1]:
        directory /= component
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise BridgeActivationError(f"activation path is unsafe: {directory}")
        if not directory.exists():
            directory.mkdir(mode=0o700)
            os.chmod(directory, 0o700)
            fsync_directory(directory.parent)
    return directory


def activate_vault(
    vault_root: str | Path,
    *,
    release_root: str | Path | None = None,
) -> dict[str, object]:
    """Read current vault state, then atomically record activation.

    The inventory pass is read-only.  The only durable output is the runtime
    activation record (plus its same-directory temporary file during publish).
    A well-formed record left behind by an earlier bridge release is re-recorded
    against the currently installed release rather than refused, so a delivered
    update never strands plan, state, adoption, or rewind operations.
    """
    root = Path(vault_root)
    release = root if release_root is None else Path(release_root)
    bridge = load_bridge_release(release)
    target = root / ACTIVATION_RELATIVE
    stale_record: bytes | None = None
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file():
            raise BridgeActivationError("existing activation path is unsafe")
        try:
            raw = target.read_bytes()
        except OSError as error:
            raise BridgeActivationError(f"existing activation could not be read: {error}") from error
        try:
            return _validate_activation(raw, bridge)
        except BridgeActivationError:
            if not _stale_activation(raw, bridge):
                raise
            stale_record = raw

    try:
        catalog = load_catalog(root / CATALOG_RELATIVE, release_root=root)
        if catalog.release.version != bridge.release_version:
            raise BridgeActivationError(
                "installed catalog release does not match the designated bridge release"
            )
        baseline_hash = build_inventory(root, catalog=catalog).to_dict()["inventory_sha256"]
    except BridgeActivationError:
        raise
    except Exception as error:  # noqa: BLE001 - translate the read-only proof boundary
        raise BridgeActivationError(f"baseline inventory could not be proved: {error}") from error
    assert isinstance(baseline_hash, str)
    from core.lifecycle.service import api_version

    document: dict[str, object] = {
        "activation_version": ACTIVATION_VERSION,
        "api_version": api_version,
        "bridge_release_version": bridge.release_version,
        "baseline_inventory_sha256": baseline_hash,
    }
    data = _canonical(document)
    directory = _activation_directory(root)
    temporary = directory / f".activation.json.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        view = memoryview(data)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        if target.exists() or target.is_symlink():
            current = target.read_bytes()
            if stale_record is None or current != stale_record:
                existing = _validate_activation(current, bridge)
                temporary.unlink()
                fsync_directory(directory)
                return existing
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        fsync_directory(directory)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return document


def resume_bridge_transactions(
    vault_root: str | Path,
    *,
    release_root: str | Path | None = None,
) -> list[dict]:
    """Converge bridge-release transactions using the declared resume window."""
    root = Path(vault_root)
    load_bridge_release(root if release_root is None else release_root)
    return Transaction.resume(root)


def prepare_vault(
    vault_root: str | Path,
    *,
    release_root: str | Path | None = None,
) -> dict[str, object]:
    """Recover any interrupted bridge transaction, then activate the vault."""
    root = Path(vault_root)
    release = root if release_root is None else Path(release_root)
    outcomes = resume_bridge_transactions(root, release_root=release)
    activation = activate_vault(root, release_root=release)
    return {"resume_outcomes": outcomes, "activation": activation}


__all__ = [
    "ACTIVATION_RELATIVE",
    "BRIDGE_RELEASE_RELATIVE",
    "BridgeActivationError",
    "BridgeError",
    "BridgeRelease",
    "JournalCompatibility",
    "activate_vault",
    "discard_superseded_activation",
    "load_bridge_release",
    "prepare_vault",
    "resume_bridge_transactions",
]
