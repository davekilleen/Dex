"""Canonical, read-only previews for explicitly requested catalog adoption."""

from __future__ import annotations

import hashlib
import json
import posixpath
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.lifecycle.inventory import InventoryReport
from core.lifecycle.model import HEX_SHA256, ITEM_ID, SEMVER, ReleaseCatalog
from core.lifecycle.plan import AdoptionPlan, PlannedAction

PREVIEW_VERSION = 1
PayloadLoader = Callable[[str], bytes]


class AdoptionPreviewError(ValueError):
    """An adoption preview cannot be proved exactly and safely."""


def _refuse(message: str) -> AdoptionPreviewError:
    return AdoptionPreviewError(f"adoption preview refused: {message}")


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


def _item_id(value: object, context: str) -> str:
    item_id = _string(value, context)
    if ITEM_ID.fullmatch(item_id) is None:
        raise _refuse(f"{context} is not a canonical item id")
    return item_id


def _version(value: object, context: str) -> str:
    version = _string(value, context)
    if SEMVER.fullmatch(version) is None:
        raise _refuse(f"{context} is not strict SemVer")
    return version


def _relative_path(value: object, context: str) -> str:
    path = _string(value, context)
    if "\\" in path or path.startswith("/") or any(ord(char) < 32 for char in path):
        raise _refuse(f"{context} must be a release-relative POSIX path")
    normalized = posixpath.normpath(path)
    if normalized != path or normalized in ("", ".", "..") or normalized.startswith("../"):
        raise _refuse(f"{context} is not a canonical release-relative path")
    return path


def _canonical_bytes(value: object, context: str) -> bytes:
    try:
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
    except (TypeError, ValueError) as error:
        raise _refuse(f"{context} cannot be serialized canonically: {error}") from error


@dataclass(frozen=True)
class PreviewWrite:
    """Approved content bytes for one adoption write, intentionally without mode.

    The catalog carries no file mode, so the preview and approval token do not
    encode one. Adoption always writes with the transaction default ``0o644``;
    normalizing a stock-content file from a user-restricted mode such as
    ``0o600`` to ``0o644`` is an intentional fixed side effect.
    """

    path: str
    new_sha256: str
    byte_size: int

    @classmethod
    def from_dict(cls, raw: object) -> "PreviewWrite":
        value = _mapping(raw, "preview write")
        _closed_fields(
            value,
            required={"path", "new_sha256", "byte_size"},
            context="preview write",
        )
        byte_size = value["byte_size"]
        if type(byte_size) is not int or byte_size < 0:
            raise _refuse("preview write byte_size must be a non-negative integer")
        return cls(
            _relative_path(value["path"], "preview write path"),
            _sha256(value["new_sha256"], "preview write new_sha256"),
            byte_size,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "new_sha256": self.new_sha256,
            "byte_size": self.byte_size,
        }


@dataclass(frozen=True)
class PreviewItem:
    item_id: str
    item_version: str
    action: str
    writes: tuple[PreviewWrite, ...]

    @classmethod
    def from_dict(cls, raw: object) -> "PreviewItem":
        value = _mapping(raw, "preview item")
        _closed_fields(
            value,
            required={"item_id", "item_version", "action", "writes"},
            context="preview item",
        )
        item_id = _item_id(value["item_id"], "preview item_id")
        action = _string(value["action"], f"preview item {item_id} action")
        if action != PlannedAction.ADOPT.value:
            raise _refuse(f"preview item {item_id} action must be adopt")
        if not isinstance(value["writes"], list) or not value["writes"]:
            raise _refuse(f"preview item {item_id} needs at least one write")
        writes = tuple(PreviewWrite.from_dict(write) for write in value["writes"])
        if writes != tuple(sorted(writes, key=lambda write: write.path)):
            raise _refuse(f"preview item {item_id} writes must be sorted by path")
        if len({write.path for write in writes}) != len(writes):
            raise _refuse(f"preview item {item_id} repeats a write path")
        return cls(
            item_id,
            _version(value["item_version"], f"preview item {item_id} version"),
            action,
            writes,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "item_version": self.item_version,
            "action": self.action,
            "writes": [write.to_dict() for write in self.writes],
        }


@dataclass(frozen=True)
class AdoptionPreview:
    preview_version: int
    catalog_sha256: str
    inventory_sha256: str
    items: tuple[PreviewItem, ...]

    @classmethod
    def from_dict(cls, raw: object) -> "AdoptionPreview":
        value = _mapping(raw, "adoption preview")
        _closed_fields(
            value,
            required={"preview_version", "catalog_sha256", "inventory_sha256", "items"},
            context="adoption preview",
        )
        if type(value["preview_version"]) is not int or value["preview_version"] != PREVIEW_VERSION:
            raise _refuse(f"preview_version must be exactly {PREVIEW_VERSION}")
        if not isinstance(value["items"], list) or not value["items"]:
            raise _refuse("adoption preview needs at least one item")
        items = tuple(PreviewItem.from_dict(item) for item in value["items"])
        if items != tuple(sorted(items, key=lambda item: item.item_id)):
            raise _refuse("adoption preview items must be sorted by item_id")
        if len({item.item_id for item in items}) != len(items):
            raise _refuse("adoption preview repeats an item_id")
        all_paths = [write.path for item in items for write in item.writes]
        if len(set(all_paths)) != len(all_paths):
            raise _refuse("adoption preview assigns one path to multiple items")
        return cls(
            PREVIEW_VERSION,
            _sha256(value["catalog_sha256"], "adoption preview catalog_sha256"),
            _sha256(value["inventory_sha256"], "adoption preview inventory_sha256"),
            items,
        )

    @property
    def sha256(self) -> str:
        """The approval token for these exact canonical preview bytes."""
        return hashlib.sha256(canonical_adoption_preview_bytes(self)).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "preview_version": self.preview_version,
            "catalog_sha256": self.catalog_sha256,
            "inventory_sha256": self.inventory_sha256,
            "items": [item.to_dict() for item in self.items],
        }


def _requested_inventory_sha256(
    inventory: InventoryReport,
    item_paths: Mapping[str, frozenset[str]],
) -> str:
    """Hash only requested-item evidence, preserving B5/E6 isolation."""
    evidence_items = []
    for item_id, paths in sorted(item_paths.items()):
        entries = []
        for entry in inventory.entries:
            if entry.canonical_path not in paths:
                continue
            entries.append(
                {
                    "actual_path": entry.actual_path,
                    "canonical_path": entry.canonical_path,
                    "kind": entry.kind,
                    "release_state": entry.release_state,
                    "size": entry.size,
                    "sha256": entry.sha256,
                    "redacted": entry.redacted,
                }
            )
        entries.sort(
            key=lambda entry: (
                str(entry["canonical_path"]),
                str(entry["actual_path"]),
                str(entry["kind"]),
            )
        )
        divergences = [
            divergence.to_dict()
            for divergence in inventory.customizations.divergences
            if divergence.canonical_path in paths
        ]
        divergences.sort(
            key=lambda entry: (
                entry["canonical_path"],
                entry["path"],
                entry["state"],
            )
        )
        evidence_items.append(
            {"item_id": item_id, "entries": entries, "divergences": divergences}
        )
    evidence = {"inventory_evidence_version": 1, "items": evidence_items}
    return hashlib.sha256(_canonical_bytes(evidence, "requested inventory evidence")).hexdigest()


def build_adoption_preview(
    catalog: ReleaseCatalog,
    inventory: InventoryReport,
    plan: AdoptionPlan,
    requested_item_ids: Sequence[str],
    payload_loader: PayloadLoader,
) -> AdoptionPreview:
    """Build the exact, payload-verified writes a user may approve."""
    if not isinstance(catalog, ReleaseCatalog):
        raise _refuse("catalog must be a loaded ReleaseCatalog")
    if not isinstance(inventory, InventoryReport):
        raise _refuse("inventory must be an InventoryReport")
    if not isinstance(plan, AdoptionPlan):
        raise _refuse("plan must be an AdoptionPlan")
    if plan.catalog_sha256 != catalog.integrity.catalog_sha256:
        raise _refuse("plan catalog identity does not match the supplied catalog")
    if plan.release_version != catalog.release.version:
        raise _refuse("plan release version does not match the supplied catalog")
    if isinstance(requested_item_ids, (str, bytes)) or not isinstance(
        requested_item_ids, Sequence
    ):
        raise _refuse("requested item ids must be a sequence")
    if not requested_item_ids or not all(isinstance(item_id, str) for item_id in requested_item_ids):
        raise _refuse("at least one canonical requested item id is required")
    if not callable(payload_loader):
        raise _refuse("payload_loader must be callable")
    requested = tuple(sorted(requested_item_ids))
    if len(set(requested)) != len(requested):
        raise _refuse("requested item ids must be unique")

    catalog_by_id = {item.id: item for item in catalog.items}
    plan_by_id = {item.item_id: item for item in plan.items}
    unknown = set(requested) - set(catalog_by_id)
    if unknown:
        raise _refuse(f"unknown requested item: {', '.join(sorted(unknown))}")

    items: list[PreviewItem] = []
    item_paths: dict[str, frozenset[str]] = {}
    for item_id in requested:
        catalog_item = catalog_by_id[item_id]
        planned = plan_by_id.get(item_id)
        if planned is None:
            raise _refuse(f"requested item {item_id} is absent from the adoption plan")
        if planned.item_version != catalog_item.version:
            raise _refuse(f"requested item {item_id} version disagrees with the catalog")
        if planned.action is not PlannedAction.ADOPT:
            raise _refuse(
                f"requested item {item_id} has planned action {planned.action.value}; "
                "only adopt may be approved"
            )
        writes = []
        for catalog_file in sorted(catalog_item.files, key=lambda entry: entry.path):
            try:
                payload = payload_loader(catalog_file.path)
            except Exception as error:
                raise _refuse(
                    f"item {item_id} payload {catalog_file.path} could not be loaded: {error}"
                ) from error
            if not isinstance(payload, bytes):
                raise _refuse(
                    f"item {item_id} payload {catalog_file.path} loader must return bytes"
                )
            digest = hashlib.sha256(payload).hexdigest()
            if digest != catalog_file.sha256:
                raise _refuse(
                    f"item {item_id} payload {catalog_file.path} sha256 does not match the catalog"
                )
            writes.append(PreviewWrite(catalog_file.path, digest, len(payload)))
        item_paths[item_id] = frozenset(write.path for write in writes)
        items.append(
            PreviewItem(
                item_id,
                catalog_item.version,
                PlannedAction.ADOPT.value,
                tuple(writes),
            )
        )
    return AdoptionPreview(
        PREVIEW_VERSION,
        catalog.integrity.catalog_sha256,
        _requested_inventory_sha256(inventory, item_paths),
        tuple(items),
    )


def canonical_adoption_preview_bytes(preview: AdoptionPreview) -> bytes:
    if not isinstance(preview, AdoptionPreview):
        raise _refuse("preview must be an AdoptionPreview")
    return _canonical_bytes(preview.to_dict(), "adoption preview")


__all__ = [
    "AdoptionPreview",
    "AdoptionPreviewError",
    "PayloadLoader",
    "PreviewItem",
    "PreviewWrite",
    "build_adoption_preview",
    "canonical_adoption_preview_bytes",
]
