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
from core.transaction.journal import PREVIOUS_SCHEMA_VERSION, SCHEMA_VERSION

BRIDGE_CONTRACT_VERSION = 1
ACTIVATION_VERSION = 1
BRIDGE_RELEASE_RELATIVE = Path("core/lifecycle/catalog/bridge-release.json")
ACTIVATION_RELATIVE = Path("System/.dex/lifecycle/activation.json")
CATALOG_RELATIVE = Path("System/.release-catalog.json")


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
        if value["api_version"] != api_version:
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


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
            _fsync_directory(directory.parent)
    return directory


def activate_vault(
    vault_root: str | Path,
    *,
    release_root: str | Path | None = None,
) -> dict[str, object]:
    """Read current vault state, then atomically record first-run activation.

    The inventory pass is read-only.  The only durable output is the runtime
    activation record (plus its same-directory temporary file during publish).
    """
    root = Path(vault_root)
    release = root if release_root is None else Path(release_root)
    bridge = load_bridge_release(release)
    target = root / ACTIVATION_RELATIVE
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file():
            raise BridgeActivationError("existing activation path is unsafe")
        try:
            return _validate_activation(target.read_bytes(), bridge)
        except OSError as error:
            raise BridgeActivationError(f"existing activation could not be read: {error}") from error

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
            existing = _validate_activation(target.read_bytes(), bridge)
            temporary.unlink()
            _fsync_directory(directory)
            return existing
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        _fsync_directory(directory)
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
    "load_bridge_release",
    "prepare_vault",
    "resume_bridge_transactions",
]
