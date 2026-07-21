"""Double-authorized catalog adoption through the transaction core only."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import posixpath
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.lifecycle.catalog import CatalogError, load_catalog
from core.lifecycle.inventory import build_inventory
from core.lifecycle.model import HEX_SHA256, ITEM_ID, ReleaseCatalog
from core.lifecycle.plan import (
    PLAN_VERSION,
    AdoptionPlan,
    PlannedAction,
    isolate_item_evidence,
    plan_catalog_item,
)
from core.lifecycle.preview import (
    AdoptionPreview,
    AdoptionPreviewError,
    PayloadLoader,
    build_adoption_preview,
    canonical_adoption_preview_bytes,
)
from core.transaction.engine import PlanEntry, PlanRejected, Transaction, TransactionError
from core.transaction.journal import Journal, JournalCorruptError
from core.transaction.snapshot import Snapshot, SnapshotEntry, SnapshotError

RECEIPT_VERSION = 1
REWIND_RECEIPT_VERSION = 1
CATALOG_RELATIVE = "System/.release-catalog.json"
ADOPTION_RECEIPTS_RELATIVE = Path("System") / ".dex" / "adoptions"
TRANSACTION_ID = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$")


class AdoptionExecutionError(RuntimeError):
    """Adoption refused or failed without a partial lifecycle result."""


class AdoptionReceiptPersistenceError(RuntimeError):
    """The adoption committed, but its convenience receipt was not persisted."""


class AdoptionRewindError(RuntimeError):
    """An adoption rewind was refused or failed without a partial result."""


class LifecycleLedgerPersistenceError(RuntimeError):
    """A committed lifecycle transaction was not recorded in the ledger.

    Callers must not blanket-catch this error: the filesystem transaction has
    already committed and the user must be told how to repair its ledger.
    """


def _refuse(message: str) -> AdoptionExecutionError:
    return AdoptionExecutionError(f"adoption refused: {message}")


def _rewind_refuse(message: str) -> AdoptionRewindError:
    return AdoptionRewindError(f"rewind refused: {message}")


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise _refuse(f"{context} must be an object with string field names")
    return value


def _closed_fields(value: Mapping[str, Any], *, required: set[str], context: str) -> None:
    missing = required - set(value)
    unknown = set(value) - required
    if missing:
        raise _refuse(f"{context} is missing required fields: {', '.join(sorted(missing))}")
    if unknown:
        raise _refuse(f"{context} has unknown fields: {', '.join(sorted(unknown))}")


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise _refuse(f"{context} must be a non-empty string")
    return value


def _sha256(value: object, context: str) -> str:
    digest = _string(value, context)
    if HEX_SHA256.fullmatch(digest) is None:
        raise _refuse(f"{context} must be a lowercase sha256 digest")
    return digest


def _relative_path(value: object, context: str) -> str:
    path = _string(value, context)
    if "\\" in path or path.startswith("/") or any(ord(char) < 32 for char in path):
        raise _refuse(f"{context} must be a relative POSIX path")
    normalized = posixpath.normpath(path)
    if normalized != path or normalized in ("", ".", "..") or normalized.startswith("../"):
        raise _refuse(f"{context} is not a canonical relative path")
    return path


@dataclass(frozen=True)
class ReceiptFile:
    item_id: str
    path: str
    sha256: str
    byte_size: int

    @classmethod
    def from_dict(cls, raw: object) -> "ReceiptFile":
        value = _mapping(raw, "adoption receipt file")
        _closed_fields(
            value,
            required={"item_id", "path", "sha256", "byte_size"},
            context="adoption receipt file",
        )
        item_id = _string(value["item_id"], "adoption receipt file item_id")
        if ITEM_ID.fullmatch(item_id) is None:
            raise _refuse("adoption receipt file item_id is not canonical")
        byte_size = value["byte_size"]
        if type(byte_size) is not int or byte_size < 0:
            raise _refuse("adoption receipt file byte_size must be a non-negative integer")
        return cls(
            item_id,
            _relative_path(value["path"], "adoption receipt file path"),
            _sha256(value["sha256"], "adoption receipt file sha256"),
            byte_size,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "path": self.path,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
        }


@dataclass(frozen=True)
class AdoptionReceipt:
    """Evidence of one committed adoption, with a short-lived rewind reference.

    The transaction core keeps only the newest three committed snapshots via
    ``_prune_committed(keep=3)``. ``snapshot_ref`` is therefore not durable:
    after three further committed transactions, its snapshot has been deleted.
    The future C3 rewind implementation must detect a missing/pruned snapshot
    and fail safe rather than attempting a partial rewind.
    """

    receipt_version: int
    items_adopted: tuple[str, ...]
    files_written: tuple[ReceiptFile, ...]
    transaction_id: str
    snapshot_ref: str
    catalog_sha256: str
    inventory_sha256: str
    preview_sha256: str

    @classmethod
    def from_dict(cls, raw: object) -> "AdoptionReceipt":
        value = _mapping(raw, "adoption receipt")
        _closed_fields(
            value,
            required={
                "receipt_version",
                "items_adopted",
                "files_written",
                "transaction_id",
                "snapshot_ref",
                "catalog_sha256",
                "inventory_sha256",
                "preview_sha256",
            },
            context="adoption receipt",
        )
        if type(value["receipt_version"]) is not int or value["receipt_version"] != RECEIPT_VERSION:
            raise _refuse(f"receipt_version must be exactly {RECEIPT_VERSION}")
        if not isinstance(value["items_adopted"], list) or not value["items_adopted"]:
            raise _refuse("adoption receipt needs at least one adopted item")
        items = tuple(
            _string(item, "adoption receipt item") for item in value["items_adopted"]
        )
        if any(ITEM_ID.fullmatch(item) is None for item in items):
            raise _refuse("adoption receipt contains a non-canonical item id")
        if items != tuple(sorted(set(items))):
            raise _refuse("adoption receipt items must be sorted and unique")
        if not isinstance(value["files_written"], list) or not value["files_written"]:
            raise _refuse("adoption receipt needs at least one written file")
        files = tuple(ReceiptFile.from_dict(entry) for entry in value["files_written"])
        if files != tuple(sorted(files, key=lambda entry: (entry.path, entry.item_id))):
            raise _refuse("adoption receipt files must be sorted by path")
        if len({entry.path for entry in files}) != len(files):
            raise _refuse("adoption receipt repeats a written path")
        if {entry.item_id for entry in files} - set(items):
            raise _refuse("adoption receipt file names an item that was not adopted")
        transaction_id = _string(value["transaction_id"], "adoption receipt transaction_id")
        if TRANSACTION_ID.fullmatch(transaction_id) is None:
            raise _refuse("adoption receipt transaction_id is not canonical")
        # This validates the reference shape, not its lifetime. The transaction
        # core prunes all but the newest three committed snapshots, so C3 rewind
        # must treat a missing snapshot_ref as a safe refusal.
        snapshot_ref = _relative_path(value["snapshot_ref"], "adoption receipt snapshot_ref")
        expected_snapshot = f"System/.dex/tx/{transaction_id}/snapshot"
        if snapshot_ref != expected_snapshot:
            raise _refuse("adoption receipt snapshot_ref does not match its transaction_id")
        return cls(
            RECEIPT_VERSION,
            items,
            files,
            transaction_id,
            snapshot_ref,
            _sha256(value["catalog_sha256"], "adoption receipt catalog_sha256"),
            _sha256(value["inventory_sha256"], "adoption receipt inventory_sha256"),
            _sha256(value["preview_sha256"], "adoption receipt preview_sha256"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "receipt_version": self.receipt_version,
            "items_adopted": list(self.items_adopted),
            "files_written": [entry.to_dict() for entry in self.files_written],
            "transaction_id": self.transaction_id,
            "snapshot_ref": self.snapshot_ref,
            "catalog_sha256": self.catalog_sha256,
            "inventory_sha256": self.inventory_sha256,
            "preview_sha256": self.preview_sha256,
        }


def canonical_adoption_receipt_bytes(receipt: AdoptionReceipt) -> bytes:
    if not isinstance(receipt, AdoptionReceipt):
        raise _refuse("receipt must be an AdoptionReceipt")
    try:
        return (
            json.dumps(
                receipt.to_dict(),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise _refuse(f"receipt cannot be serialized canonically: {error}") from error


@dataclass(frozen=True)
class RewindReceiptFile:
    """The exact pre-adoption state restored for one adopted path."""

    item_id: str
    path: str
    existed_before_adoption: bool
    restored_sha256: str | None
    byte_size: int | None
    mode: int | None

    @classmethod
    def from_dict(cls, raw: object) -> "RewindReceiptFile":
        value = _mapping(raw, "rewind receipt file")
        _closed_fields(
            value,
            required={
                "item_id",
                "path",
                "existed_before_adoption",
                "restored_sha256",
                "byte_size",
                "mode",
            },
            context="rewind receipt file",
        )
        item_id = _string(value["item_id"], "rewind receipt file item_id")
        if ITEM_ID.fullmatch(item_id) is None:
            raise _refuse("rewind receipt file item_id is not canonical")
        existed = value["existed_before_adoption"]
        if type(existed) is not bool:
            raise _refuse("rewind receipt file existed_before_adoption must be a boolean")
        if existed:
            digest = _sha256(
                value["restored_sha256"], "rewind receipt file restored_sha256"
            )
            byte_size = value["byte_size"]
            mode = value["mode"]
            if type(byte_size) is not int or byte_size < 0:
                raise _refuse(
                    "rewind receipt file byte_size must be a non-negative integer"
                )
            if type(mode) is not int or mode < 0 or mode > 0o777:
                raise _refuse("rewind receipt file mode must be permission bits up to 0o777")
        else:
            if any(
                value[field] is not None
                for field in ("restored_sha256", "byte_size", "mode")
            ):
                raise _refuse(
                    "rewind receipt file absent state needs null hash, size, and mode"
                )
            digest = None
            byte_size = None
            mode = None
        return cls(
            item_id,
            _relative_path(value["path"], "rewind receipt file path"),
            existed,
            digest,
            byte_size,
            mode,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "path": self.path,
            "existed_before_adoption": self.existed_before_adoption,
            "restored_sha256": self.restored_sha256,
            "byte_size": self.byte_size,
            "mode": self.mode,
        }


@dataclass(frozen=True)
class RewindReceipt:
    """Strict evidence that one adoption was rewound in a new transaction."""

    rewind_receipt_version: int
    adoption_transaction_id: str
    rewind_transaction_id: str
    snapshot_ref: str
    source_receipt_sha256: str
    files_restored: tuple[RewindReceiptFile, ...]

    @classmethod
    def from_dict(cls, raw: object) -> "RewindReceipt":
        value = _mapping(raw, "rewind receipt")
        _closed_fields(
            value,
            required={
                "rewind_receipt_version",
                "adoption_transaction_id",
                "rewind_transaction_id",
                "snapshot_ref",
                "source_receipt_sha256",
                "files_restored",
            },
            context="rewind receipt",
        )
        if (
            type(value["rewind_receipt_version"]) is not int
            or value["rewind_receipt_version"] != REWIND_RECEIPT_VERSION
        ):
            raise _refuse(
                f"rewind_receipt_version must be exactly {REWIND_RECEIPT_VERSION}"
            )
        adoption_id = _string(
            value["adoption_transaction_id"],
            "rewind receipt adoption_transaction_id",
        )
        rewind_id = _string(
            value["rewind_transaction_id"], "rewind receipt rewind_transaction_id"
        )
        if TRANSACTION_ID.fullmatch(adoption_id) is None:
            raise _refuse("rewind receipt adoption_transaction_id is not canonical")
        if TRANSACTION_ID.fullmatch(rewind_id) is None:
            raise _refuse("rewind receipt rewind_transaction_id is not canonical")
        if adoption_id == rewind_id:
            raise _refuse("rewind receipt transaction ids must be distinct")
        snapshot_ref = _relative_path(
            value["snapshot_ref"], "rewind receipt snapshot_ref"
        )
        if snapshot_ref != f"System/.dex/tx/{rewind_id}/snapshot":
            raise _refuse(
                "rewind receipt snapshot_ref does not match its rewind_transaction_id"
            )
        raw_files = value["files_restored"]
        if not isinstance(raw_files, list) or not raw_files:
            raise _refuse("rewind receipt needs at least one restored file")
        files = tuple(RewindReceiptFile.from_dict(entry) for entry in raw_files)
        if files != tuple(sorted(files, key=lambda entry: (entry.path, entry.item_id))):
            raise _refuse("rewind receipt files must be sorted by path")
        if len({entry.path for entry in files}) != len(files):
            raise _refuse("rewind receipt repeats a restored path")
        return cls(
            REWIND_RECEIPT_VERSION,
            adoption_id,
            rewind_id,
            snapshot_ref,
            _sha256(
                value["source_receipt_sha256"],
                "rewind receipt source_receipt_sha256",
            ),
            files,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "rewind_receipt_version": self.rewind_receipt_version,
            "adoption_transaction_id": self.adoption_transaction_id,
            "rewind_transaction_id": self.rewind_transaction_id,
            "snapshot_ref": self.snapshot_ref,
            "source_receipt_sha256": self.source_receipt_sha256,
            "files_restored": [entry.to_dict() for entry in self.files_restored],
        }


def canonical_rewind_receipt_bytes(receipt: RewindReceipt) -> bytes:
    if not isinstance(receipt, RewindReceipt):
        raise _rewind_refuse("rewind receipt must be a RewindReceipt")
    try:
        validated = RewindReceipt.from_dict(receipt.to_dict())
        return (
            json.dumps(
                validated.to_dict(),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except AdoptionExecutionError as error:
        raise _rewind_refuse(str(error).removeprefix("adoption refused: ")) from error
    except (TypeError, ValueError) as error:
        raise _rewind_refuse(
            f"rewind receipt cannot be serialized canonically: {error}"
        ) from error


def _validated_adoption_receipt(raw: object) -> AdoptionReceipt:
    try:
        document = raw.to_dict() if isinstance(raw, AdoptionReceipt) else raw
        return AdoptionReceipt.from_dict(document)
    except AdoptionExecutionError as error:
        raise _rewind_refuse(
            f"receipt is invalid: {str(error).removeprefix('adoption refused: ')}"
        ) from error
    except (AttributeError, TypeError, ValueError) as error:
        raise _rewind_refuse(f"receipt is invalid: {error}") from error


def rewind_acknowledgement_token(receipt: object) -> str:
    """Bind rewind acknowledgement to the exact adoption id and sorted paths."""
    validated = _validated_adoption_receipt(receipt)
    payload = {
        "rewind": validated.transaction_id,
        "files": sorted(entry.path for entry in validated.files_written),
    }
    canonical = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _receipt_path(vault_root: Path, transaction_id: str) -> Path:
    if TRANSACTION_ID.fullmatch(transaction_id) is None:
        raise _rewind_refuse("receipt transaction_id is not canonical")
    return (
        Path(vault_root)
        / ADOPTION_RECEIPTS_RELATIVE
        / f"{transaction_id}.receipt.json"
    )


def _persist_adoption_receipt(vault_root: Path, receipt: AdoptionReceipt) -> None:
    """Atomically persist post-commit runtime evidence.

    This deliberately happens after the adoption transaction commits because
    the receipt describes that outcome. A process crash between COMMITTED and
    this write leaves a committed-but-unreceipted adoption; the fsynced
    transaction journal remains the authority for what happened.
    """
    target = _receipt_path(vault_root, receipt.transaction_id)
    root = Path(vault_root)
    directory = target.parent
    for component in (root / "System", root / "System/.dex", directory):
        if component.is_symlink() or (component.exists() and not component.is_dir()):
            raise AdoptionReceiptPersistenceError(
                f"adoption {receipt.transaction_id} committed, but its receipt path "
                f"is unsafe: {component}"
            )
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    temporary = directory / (
        f".{target.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    )
    data = canonical_adoption_receipt_bytes(receipt)
    descriptor = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
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


def load_adoption_receipt(vault_root: Path, transaction_id: str) -> AdoptionReceipt:
    """Load one canonical persisted receipt through the strict receipt parser."""
    path = _receipt_path(vault_root, transaction_id)
    if path.is_symlink() or not path.is_file():
        raise _rewind_refuse(f"receipt file is missing or unsafe: {path}")
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
        receipt = AdoptionReceipt.from_dict(document)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _rewind_refuse(f"receipt file is unreadable: {error}") from error
    except AdoptionExecutionError as error:
        raise _rewind_refuse(
            f"receipt file is invalid: {str(error).removeprefix('adoption refused: ')}"
        ) from error
    if receipt.transaction_id != transaction_id:
        raise _rewind_refuse("receipt file transaction_id does not match its filename")
    if not hmac.compare_digest(raw, canonical_adoption_receipt_bytes(receipt)):
        raise _rewind_refuse("receipt file is valid JSON but not canonical")
    return receipt


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _current_adopted_modes(
    root: Path, receipt: AdoptionReceipt
) -> tuple[dict[str, int], tuple[str, ...]]:
    modes: dict[str, int] = {}
    drifted: list[str] = []
    for entry in receipt.files_written:
        target = root / entry.path
        if target.is_symlink() or not target.is_file():
            drifted.append(entry.path)
            continue
        digest, size = _sha256_file(target)
        if digest != entry.sha256 or size != entry.byte_size:
            drifted.append(entry.path)
            continue
        modes[entry.path] = target.stat().st_mode & 0o777
    return modes, tuple(sorted(drifted))


def _drift_refusal(drifted: tuple[str, ...]) -> AdoptionRewindError:
    return _rewind_refuse(
        "files changed after adoption and were left untouched: "
        f"{', '.join(drifted)}. Keep those edits or restore the adopted bytes, "
        "then request a new rewind."
    )


def _verify_adoption_commit(root: Path, receipt: AdoptionReceipt) -> None:
    journal = (root / receipt.snapshot_ref).parent / "journal.jsonl"
    try:
        entries = Journal(journal).read()
    except JournalCorruptError as error:
        raise _rewind_refuse(
            "the adoption transaction journal is damaged; no files were changed"
        ) from error
    events = [entry.event for entry in entries]
    begins = [entry for entry in entries if entry.event == "BEGIN"]
    if (
        events.count("COMMITTED") != 1
        or "ROLLED-BACK" in events
        or len(begins) != 1
        or begins[0].payload.get("tx_id") != receipt.transaction_id
    ):
        raise _rewind_refuse(
            "the receipt does not point to a verifiably committed adoption; "
            "no files were changed"
        )


def _snapshot_rewind_plan(
    root: Path,
    receipt: AdoptionReceipt,
    current_modes: dict[str, int],
) -> tuple[list[PlanEntry], tuple[RewindReceiptFile, ...]]:
    snapshot_root = root / receipt.snapshot_ref
    manifest_path = snapshot_root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise _rewind_refuse(
            "the adoption snapshot manifest is damaged; no files were changed"
        )
    snapshot = Snapshot(snapshot_root)
    try:
        manifest = snapshot.read_manifest()
    except (SnapshotError, KeyError, TypeError, ValueError) as error:
        raise _rewind_refuse(
            f"the adoption snapshot manifest is damaged; no files were changed ({error})"
        ) from error

    receipt_by_path = {entry.path: entry for entry in receipt.files_written}
    try:
        manifest_paths = [
            _relative_path(entry.relative, "adoption snapshot path")
            for entry in manifest
        ]
    except (AdoptionExecutionError, AttributeError, TypeError, ValueError) as error:
        raise _rewind_refuse(
            f"the adoption snapshot manifest is damaged; no files were changed ({error})"
        ) from error
    if (
        len(manifest_paths) != len(set(manifest_paths))
        or set(manifest_paths) != set(receipt_by_path)
    ):
        raise _rewind_refuse(
            "the adoption snapshot does not exactly match the receipt; no files were changed"
        )

    plan: list[PlanEntry] = []
    restored: list[RewindReceiptFile] = []
    for index, snapshot_entry in enumerate(manifest):
        receipt_file = receipt_by_path[snapshot_entry.relative]
        if type(snapshot_entry.existed) is not bool:
            raise _rewind_refuse(
                f"the adoption snapshot is damaged for {snapshot_entry.relative}; "
                "no files were changed"
            )
        if snapshot_entry.existed:
            if not _valid_existing_snapshot_entry(snapshot_entry):
                raise _rewind_refuse(
                    f"the adoption snapshot is damaged for {snapshot_entry.relative}; "
                    "no files were changed"
                )
            blob = snapshot_root / f"{index:06d}.bin"
            if blob.is_symlink() or not blob.is_file():
                raise _rewind_refuse(
                    f"the adoption snapshot is damaged for {snapshot_entry.relative}; "
                    "no files were changed"
                )
            content = blob.read_bytes()
            if (
                len(content) != snapshot_entry.size
                or hashlib.sha256(content).hexdigest() != snapshot_entry.sha256
            ):
                raise _rewind_refuse(
                    f"the adoption snapshot is damaged for {snapshot_entry.relative}; "
                    "no files were changed"
                )
            plan.append(
                PlanEntry(snapshot_entry.relative, content, mode=snapshot_entry.mode)
            )
            restored.append(
                RewindReceiptFile(
                    receipt_file.item_id,
                    snapshot_entry.relative,
                    True,
                    snapshot_entry.sha256,
                    snapshot_entry.size,
                    snapshot_entry.mode,
                )
            )
        else:
            if any(
                value is not None
                for value in (
                    snapshot_entry.mode,
                    snapshot_entry.sha256,
                    snapshot_entry.size,
                )
            ):
                raise _rewind_refuse(
                    f"the adoption snapshot is damaged for {snapshot_entry.relative}; "
                    "no files were changed"
                )
            plan.append(
                PlanEntry(
                    snapshot_entry.relative,
                    None,
                    mode=current_modes[snapshot_entry.relative],
                    expected_current_sha256=receipt_file.sha256,
                )
            )
            restored.append(
                RewindReceiptFile(
                    receipt_file.item_id,
                    snapshot_entry.relative,
                    False,
                    None,
                    None,
                    None,
                )
            )
    return plan, tuple(sorted(restored, key=lambda entry: (entry.path, entry.item_id)))


def _valid_existing_snapshot_entry(entry: SnapshotEntry) -> bool:
    return bool(
        type(entry.relative) is str
        and entry.relative
        and type(entry.mode) is int
        and 0 <= entry.mode <= 0o777
        and type(entry.sha256) is str
        and HEX_SHA256.fullmatch(entry.sha256)
        and type(entry.size) is int
        and entry.size >= 0
    )


def rewind_adoption(
    vault_root: Path,
    receipt: object,
    acknowledgement_token: str | None = None,
) -> RewindReceipt:
    """Restore one adoption's pre-state through a new crash-safe transaction."""
    validated = _validated_adoption_receipt(receipt)
    root = Path(vault_root)

    current_modes, drifted = _current_adopted_modes(root, validated)
    if drifted:
        raise _drift_refusal(drifted)

    expected_token = rewind_acknowledgement_token(validated)
    if not isinstance(acknowledgement_token, str) or not hmac.compare_digest(
        acknowledgement_token, expected_token
    ):
        raise _rewind_refuse(
            "acknowledgement token does not match the exact adoption id and file list; "
            "show the rewind preview again and retry"
        )

    snapshot_root = root / validated.snapshot_ref
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        raise _rewind_refuse(
            "the adoption snapshot is no longer available under keep-last-3 retention; "
            "this adoption can no longer be rewound"
        )
    _verify_adoption_commit(root, validated)
    plan, restored = _snapshot_rewind_plan(root, validated, current_modes)

    try:
        transaction = Transaction.begin(root, plan)

        def verify_no_late_drift() -> None:
            """Bind the rewind to the state captured by its transaction.

            This closes drift between the initial hash pass and snapshot
            capture: rollback restores those later user bytes. As in C1, the
            trusted transaction core cannot detect a non-transaction writer
            that ignores the mutation lock after snapshot capture and races a
            write PlanEntry's atomic replace; that inherited residual window
            remains documented rather than hidden.
            """
            captured = {
                entry.relative: entry for entry in transaction.snapshot.read_manifest()
            }
            late_drift = tuple(
                sorted(
                    entry.path
                    for entry in validated.files_written
                    if entry.path not in captured
                    or not captured[entry.path].existed
                    or captured[entry.path].sha256 != entry.sha256
                    or captured[entry.path].size != entry.byte_size
                )
            )
            if late_drift:
                raise _drift_refusal(late_drift)

        result = transaction.run(before_commit=verify_no_late_drift)
    except PlanRejected as error:
        raise _rewind_refuse(
            f"the ownership contract rejected the complete rewind: {error}"
        ) from error
    except (SnapshotError, TransactionError) as error:
        raise _rewind_refuse(
            f"the rewind transaction could not complete safely: {error}"
        ) from error

    rewind_transaction_id = result["tx_id"]
    rewind_receipt = RewindReceipt.from_dict(
        {
            "rewind_receipt_version": REWIND_RECEIPT_VERSION,
            "adoption_transaction_id": validated.transaction_id,
            "rewind_transaction_id": rewind_transaction_id,
            "snapshot_ref": (
                f"System/.dex/tx/{rewind_transaction_id}/snapshot"
            ),
            "source_receipt_sha256": hashlib.sha256(
                canonical_adoption_receipt_bytes(validated)
            ).hexdigest(),
            "files_restored": [entry.to_dict() for entry in restored],
        }
    )
    # Boundary: the rewind transaction is already COMMITTED.  The transaction
    # journal is authoritative, so a later ledger failure is reported loudly
    # but must never trigger an attempted rollback of the committed rewind.
    try:
        from core.lifecycle.ledger import LedgerError, record_rewind

        record_rewind(root, rewind_receipt)
    except (LedgerError, OSError) as error:
        raise LifecycleLedgerPersistenceError(
            f"rewind {rewind_transaction_id} committed, but its lifecycle ledger refresh "
            f"did not complete; its event may already be durable and the transaction journal "
            f"is authoritative: {error}. Run 'python3 -m core.lifecycle.cli --vault-root "
            f"{root} rebuild-state' to repair the lifecycle ledger"
        ) from error
    return rewind_receipt


def _rebuild_requested_plan(catalog, inventory, requested: tuple[str, ...]) -> AdoptionPlan:
    by_id = {item.id: item for item in catalog.items}
    rebuilt_items = []
    for item_id in requested:
        item = by_id.get(item_id)
        if item is None:
            raise _refuse(f"requested item {item_id} is no longer in the catalog")
        planned = plan_catalog_item(
            item,
            isolate_item_evidence(item, inventory, inventory.customizations),
        )
        if planned.action is not PlannedAction.ADOPT:
            raise _refuse(
                f"item {item_id} planned action changed from adopt to "
                f"{planned.action.value} since preview; review the current plan"
            )
        rebuilt_items.append(planned)
    return AdoptionPlan(
        PLAN_VERSION,
        catalog.release.version,
        catalog.integrity.catalog_sha256,
        tuple(rebuilt_items),
    )


def _catalog_inventory_scope(
    catalog: ReleaseCatalog, requested: tuple[str, ...]
) -> ReleaseCatalog:
    """Keep full identity while inventory hashes payloads for requested items only."""
    by_id = {item.id: item for item in catalog.items}
    missing = set(requested) - set(by_id)
    if missing:
        raise _refuse(f"requested item is no longer in the catalog: {', '.join(sorted(missing))}")
    return ReleaseCatalog(
        catalog.catalog_version,
        catalog.release,
        tuple(by_id[item_id] for item_id in requested),
        catalog.integrity,
    )


def execute_adoption(
    vault_root: Path,
    preview: AdoptionPreview,
    approved_token: str,
    payload_loader: PayloadLoader,
) -> AdoptionReceipt:
    """Re-prove an approved preview, execute it, then persist its receipt.

    Receipt persistence is intentionally after COMMITTED because the receipt
    records the transaction outcome. A crash in that narrow window leaves a
    committed-but-unreceipted adoption; the transaction journal remains the
    durable source of truth and no adoption bytes are rolled back or guessed.
    """
    if not isinstance(preview, AdoptionPreview):
        raise _refuse("preview must be an AdoptionPreview")
    if not isinstance(approved_token, str) or not hmac.compare_digest(
        approved_token, preview.sha256
    ):
        raise _refuse("approval token does not match the exact canonical preview")
    if not callable(payload_loader):
        raise _refuse("payload_loader must be callable")

    root = Path(vault_root)
    try:
        current_catalog = load_catalog(root / CATALOG_RELATIVE, release_root=root)
    except CatalogError as error:
        raise _refuse(f"current catalog could not be verified: {error}") from error
    if current_catalog.integrity.catalog_sha256 != preview.catalog_sha256:
        raise _refuse("catalog changed since preview; build and approve a fresh preview")

    requested = tuple(item.item_id for item in preview.items)
    current_inventory = build_inventory(
        root,
        catalog=_catalog_inventory_scope(current_catalog, requested),
    )
    current_plan = _rebuild_requested_plan(current_catalog, current_inventory, requested)
    payload_cache: dict[str, bytes] = {}

    def cached_loader(path: str) -> bytes:
        if path not in payload_cache:
            payload_cache[path] = payload_loader(path)
        return payload_cache[path]

    try:
        rebuilt = build_adoption_preview(
            current_catalog,
            current_inventory,
            current_plan,
            requested,
            cached_loader,
        )
    except AdoptionPreviewError as error:
        raise _refuse(f"current preview could not be rebuilt: {error}") from error
    if canonical_adoption_preview_bytes(rebuilt) != canonical_adoption_preview_bytes(preview):
        if rebuilt.inventory_sha256 != preview.inventory_sha256:
            raise _refuse(
                "requested file inventory changed since preview; build and approve a fresh preview"
            )
        raise _refuse("rebuilt preview differs from the approved preview; approve a fresh preview")

    entries = [
        PlanEntry(write.path, payload_cache[write.path])
        for item in rebuilt.items
        for write in item.writes
    ]

    try:
        transaction = Transaction.begin(root, entries)

        def verify_approval_binding() -> None:
            """Catch pre-snapshot drift, with one inherited residual window.

            If a target changes after the final preview rebuild but before
            snapshot capture, the snapshot records those newer bytes; comparing
            it with the approved catalog bytes catches the drift and rollback
            restores the newer bytes. A non-transaction writer that changes a
            target after snapshot capture but before ``_apply_one`` is not
            caught: apply overwrites the edit with the approved stock bytes,
            this comparison still sees snapshot(stock) == catalog, and the
            adoption commits. That sub-millisecond window is inherited from the
            trusted transaction core because write PlanEntry objects cannot set
            ``expected_current_sha256``.
            """
            if not hmac.compare_digest(approved_token, rebuilt.sha256):
                raise _refuse("approval binding changed before commit")
            snapshot_by_path = {
                entry.relative: entry for entry in transaction.snapshot.read_manifest()
            }
            for item in rebuilt.items:
                for write in item.writes:
                    captured = snapshot_by_path.get(write.path)
                    if (
                        captured is None
                        or not captured.existed
                        or captured.sha256 != write.new_sha256
                        or captured.size != write.byte_size
                    ):
                        raise _refuse(
                            f"requested file {write.path} changed after final preview rebuild; "
                            "the transaction will restore the newer bytes"
                        )

        result = transaction.run(before_commit=verify_approval_binding)
    except PlanRejected as error:
        raise _refuse(f"the ownership contract rejected the complete adoption: {error}") from error
    except TransactionError as error:
        raise _refuse(f"the transaction could not complete safely: {error}") from error

    files = tuple(
        sorted(
            (
                ReceiptFile(item.item_id, write.path, write.new_sha256, write.byte_size)
                for item in rebuilt.items
                for write in item.writes
            ),
            key=lambda entry: (entry.path, entry.item_id),
        )
    )
    transaction_id = result["tx_id"]
    receipt = AdoptionReceipt(
        RECEIPT_VERSION,
        requested,
        files,
        transaction_id,
        f"System/.dex/tx/{transaction_id}/snapshot",
        rebuilt.catalog_sha256,
        rebuilt.inventory_sha256,
        rebuilt.sha256,
    )
    try:
        _persist_adoption_receipt(root, receipt)
    except AdoptionReceiptPersistenceError:
        raise
    except (OSError, AdoptionExecutionError) as error:
        raise AdoptionReceiptPersistenceError(
            f"adoption {transaction_id} committed, but its receipt could not be "
            f"persisted; the transaction journal is authoritative: {error}"
        ) from error
    # Boundary: adoption and receipt persistence are already durable.  Ledger
    # projection is post-commit evidence; failure is loud and never rolls back
    # the transaction whose fsynced journal remains authoritative.
    try:
        from core.lifecycle.ledger import LedgerError, record_adoption

        record_adoption(
            root,
            receipt,
            {item.item_id: item.item_version for item in rebuilt.items},
        )
    except (LedgerError, OSError) as error:
        raise LifecycleLedgerPersistenceError(
            f"adoption {transaction_id} committed, but its lifecycle ledger refresh did not "
            f"complete; its event may already be durable and the transaction journal is "
            f"authoritative: {error}. Run 'python3 -m core.lifecycle.cli --vault-root "
            f"{root} rebuild-state' to repair the lifecycle ledger"
        ) from error
    return receipt


__all__ = [
    "AdoptionExecutionError",
    "AdoptionReceipt",
    "AdoptionReceiptPersistenceError",
    "AdoptionRewindError",
    "LifecycleLedgerPersistenceError",
    "ReceiptFile",
    "RewindReceipt",
    "RewindReceiptFile",
    "canonical_adoption_receipt_bytes",
    "canonical_rewind_receipt_bytes",
    "execute_adoption",
    "load_adoption_receipt",
    "rewind_acknowledgement_token",
    "rewind_adoption",
]
