"""Double-authorized catalog adoption through the transaction core only."""

from __future__ import annotations

import hmac
import json
import posixpath
import re
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

RECEIPT_VERSION = 1
CATALOG_RELATIVE = "System/.release-catalog.json"
TRANSACTION_ID = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{8}$")


class AdoptionExecutionError(RuntimeError):
    """Adoption refused or failed without a partial lifecycle result."""


def _refuse(message: str) -> AdoptionExecutionError:
    return AdoptionExecutionError(f"adoption refused: {message}")


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
    """Re-prove an approved preview, then execute all writes in one transaction."""
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
    return AdoptionReceipt(
        RECEIPT_VERSION,
        requested,
        files,
        transaction_id,
        f"System/.dex/tx/{transaction_id}/snapshot",
        rebuilt.catalog_sha256,
        rebuilt.inventory_sha256,
        rebuilt.sha256,
    )


__all__ = [
    "AdoptionExecutionError",
    "AdoptionReceipt",
    "ReceiptFile",
    "canonical_adoption_receipt_bytes",
    "execute_adoption",
]
