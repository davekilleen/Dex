"""Canonical, read-only previews for explicit conflict resolution."""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core.lifecycle.inventory import InventoryReport
from core.lifecycle.model import HEX_SHA256, ITEM_ID, SEMVER, ReleaseCatalog
from core.lifecycle.plan import AdoptionPlan, PlannedAction, ReasonCode
from core.lifecycle.preview import _requested_inventory_sha256

RESOLUTION_PREVIEW_VERSION = 1
STRATEGIES = ("take-theirs", "keep-both")
SOURCES = ("release", "preserved")
PayloadLoader = Callable[[str], bytes]
CurrentBytesLoader = Callable[[str], bytes]
_SKILL_PATH = re.compile(r"^\.claude/skills/([^/]+)/(.+)$")


class ConflictResolutionPreviewError(ValueError):
    """A conflict-resolution preview cannot be proved exactly and safely."""


def _refuse(message: str) -> ConflictResolutionPreviewError:
    return ConflictResolutionPreviewError(
        f"conflict resolution preview refused: {message}"
    )


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise _refuse(f"{context} must be an object with string field names")
    return value


def _closed_fields(
    value: Mapping[str, Any], *, required: set[str], context: str
) -> None:
    missing = required - set(value)
    unknown = set(value) - required
    if missing:
        raise _refuse(
            f"{context} is missing required fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise _refuse(
            f"{context} has unknown fields: {', '.join(sorted(unknown))}"
        )


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
        raise _refuse(
            f"{context} cannot be serialized canonically: {error}"
        ) from error


@dataclass(frozen=True)
class ResolutionWrite:
    path: str
    new_sha256: str
    byte_size: int
    source: str

    @classmethod
    def from_dict(cls, raw: object) -> "ResolutionWrite":
        value = _mapping(raw, "resolution write")
        _closed_fields(
            value,
            required={"path", "new_sha256", "byte_size", "source"},
            context="resolution write",
        )
        byte_size = value["byte_size"]
        if type(byte_size) is not int or byte_size < 0:
            raise _refuse(
                "resolution write byte_size must be a non-negative integer"
            )
        source = _string(value["source"], "resolution write source")
        if source not in SOURCES:
            raise _refuse(f"resolution write source must be one of {SOURCES}")
        return cls(
            _relative_path(value["path"], "resolution write path"),
            _sha256(value["new_sha256"], "resolution write new_sha256"),
            byte_size,
            source,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "new_sha256": self.new_sha256,
            "byte_size": self.byte_size,
            "source": self.source,
        }


@dataclass(frozen=True)
class ResolutionItem:
    item_id: str
    item_version: str
    strategy: str
    writes: tuple[ResolutionWrite, ...]

    @classmethod
    def from_dict(cls, raw: object) -> "ResolutionItem":
        value = _mapping(raw, "resolution item")
        _closed_fields(
            value,
            required={"item_id", "item_version", "strategy", "writes"},
            context="resolution item",
        )
        item_id = _item_id(value["item_id"], "resolution item_id")
        strategy = _string(
            value["strategy"], f"resolution item {item_id} strategy"
        )
        if strategy not in STRATEGIES:
            raise _refuse(
                f"resolution item {item_id} strategy must be one of {STRATEGIES}"
            )
        if not isinstance(value["writes"], list) or not value["writes"]:
            raise _refuse(f"resolution item {item_id} needs at least one write")
        writes = tuple(
            ResolutionWrite.from_dict(write) for write in value["writes"]
        )
        if writes != tuple(sorted(writes, key=lambda write: write.path)):
            raise _refuse(
                f"resolution item {item_id} writes must be sorted by path"
            )
        if len({write.path for write in writes}) != len(writes):
            raise _refuse(f"resolution item {item_id} repeats a write path")
        if strategy == "take-theirs" and any(
            write.source != "release" for write in writes
        ):
            raise _refuse(
                f"resolution item {item_id} take-theirs writes must come from release"
            )
        if strategy == "keep-both" and not any(
            write.source == "preserved" for write in writes
        ):
            raise _refuse(
                f"resolution item {item_id} keep-both needs a preserved write"
            )
        return cls(
            item_id,
            _version(
                value["item_version"], f"resolution item {item_id} version"
            ),
            strategy,
            writes,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "item_version": self.item_version,
            "strategy": self.strategy,
            "writes": [write.to_dict() for write in self.writes],
        }


@dataclass(frozen=True)
class ConflictResolutionPreview:
    resolution_preview_version: int
    catalog_sha256: str
    inventory_sha256: str
    items: tuple[ResolutionItem, ...]

    @classmethod
    def from_dict(cls, raw: object) -> "ConflictResolutionPreview":
        value = _mapping(raw, "conflict resolution preview")
        _closed_fields(
            value,
            required={
                "resolution_preview_version",
                "catalog_sha256",
                "inventory_sha256",
                "items",
            },
            context="conflict resolution preview",
        )
        if (
            type(value["resolution_preview_version"]) is not int
            or value["resolution_preview_version"] != RESOLUTION_PREVIEW_VERSION
        ):
            raise _refuse(
                "resolution_preview_version must be exactly "
                f"{RESOLUTION_PREVIEW_VERSION}"
            )
        if not isinstance(value["items"], list) or not value["items"]:
            raise _refuse("conflict resolution preview needs at least one item")
        items = tuple(ResolutionItem.from_dict(item) for item in value["items"])
        if items != tuple(sorted(items, key=lambda item: item.item_id)):
            raise _refuse(
                "conflict resolution preview items must be sorted by item_id"
            )
        if len({item.item_id for item in items}) != len(items):
            raise _refuse("conflict resolution preview repeats an item_id")
        all_paths = [write.path for item in items for write in item.writes]
        if len(set(all_paths)) != len(all_paths):
            raise _refuse(
                "conflict resolution preview assigns one path to multiple items"
            )
        return cls(
            RESOLUTION_PREVIEW_VERSION,
            _sha256(
                value["catalog_sha256"],
                "conflict resolution preview catalog_sha256",
            ),
            _sha256(
                value["inventory_sha256"],
                "conflict resolution preview inventory_sha256",
            ),
            items,
        )

    @property
    def sha256(self) -> str:
        """The approval token for these exact canonical preview bytes."""
        return hashlib.sha256(
            canonical_conflict_resolution_preview_bytes(self)
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "resolution_preview_version": self.resolution_preview_version,
            "catalog_sha256": self.catalog_sha256,
            "inventory_sha256": self.inventory_sha256,
            "items": [item.to_dict() for item in self.items],
        }


def sidecar_path(canonical_path: str) -> str:
    """Return the skills-only ``-custom`` preservation path."""
    path = _relative_path(canonical_path, "canonical path")
    match = _SKILL_PATH.fullmatch(path)
    if match is None:
        raise _refuse(
            f"keep-both is skills-only; {path} is not under "
            ".claude/skills/{name}/"
        )
    name, rest = match.groups()
    return f".claude/skills/{name}-custom/{rest}"


def _load_bytes(
    loader: Callable[[str], bytes],
    path: str,
    *,
    context: str,
) -> bytes:
    try:
        payload = loader(path)
    except Exception as error:
        raise _refuse(f"{context} {path} could not be loaded: {error}") from error
    if not isinstance(payload, bytes):
        raise _refuse(f"{context} {path} loader must return bytes")
    return payload


def build_conflict_resolution_preview(
    catalog: ReleaseCatalog,
    inventory: InventoryReport,
    plan: AdoptionPlan,
    resolutions: Sequence[Mapping[str, object]],
    payload_loader: PayloadLoader,
    current_bytes_loader: CurrentBytesLoader,
) -> ConflictResolutionPreview:
    """Build exact, payload-verified writes for requested conflict choices."""
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
    if isinstance(resolutions, (str, bytes)) or not isinstance(
        resolutions, Sequence
    ):
        raise _refuse("resolutions must be a sequence")
    if not resolutions:
        raise _refuse("at least one conflict resolution is required")
    if not callable(payload_loader):
        raise _refuse("payload_loader must be callable")
    if not callable(current_bytes_loader):
        raise _refuse("current_bytes_loader must be callable")

    requested: list[tuple[str, str]] = []
    for index, raw in enumerate(resolutions):
        value = _mapping(raw, f"resolution {index}")
        _closed_fields(
            value,
            required={"item_id", "strategy"},
            context=f"resolution {index}",
        )
        item_id = _item_id(value["item_id"], f"resolution {index} item_id")
        strategy = _string(
            value["strategy"], f"resolution for {item_id} strategy"
        )
        if strategy not in STRATEGIES:
            raise _refuse(
                f"resolution for {item_id} strategy must be one of {STRATEGIES}"
            )
        requested.append((item_id, strategy))
    requested.sort()
    if len({item_id for item_id, _strategy in requested}) != len(requested):
        raise _refuse("resolution item_ids must be unique")

    catalog_by_id = {item.id: item for item in catalog.items}
    plan_by_id = {item.item_id: item for item in plan.items}
    unknown = {item_id for item_id, _strategy in requested} - set(catalog_by_id)
    if unknown:
        raise _refuse(f"unknown requested item: {', '.join(sorted(unknown))}")

    items: list[ResolutionItem] = []
    item_paths: dict[str, frozenset[str]] = {}
    for item_id, strategy in requested:
        catalog_item = catalog_by_id[item_id]
        planned = plan_by_id.get(item_id)
        if planned is None:
            raise _refuse(
                f"requested item {item_id} is absent from the adoption plan"
            )
        if planned.item_version != catalog_item.version:
            raise _refuse(
                f"requested item {item_id} version disagrees with the catalog"
            )
        if planned.action is not PlannedAction.CONFLICT:
            raise _refuse(
                f"requested item {item_id} has planned action "
                f"{planned.action.value}; only conflict may be resolved"
            )

        modified_paths = {
            path
            for reason in planned.reasons
            if reason.code is ReasonCode.RELEASE_FILES_MODIFIED
            for path in reason.paths
        }
        missing_paths = {
            path
            for reason in planned.reasons
            if reason.code is ReasonCode.RELEASE_FILES_MISSING
            for path in reason.paths
        }
        catalog_paths = frozenset(
            catalog_file.path for catalog_file in catalog_item.files
        )
        if not (modified_paths | missing_paths).issubset(catalog_paths):
            raise _refuse(
                f"requested item {item_id} conflict paths disagree with the catalog"
            )
        inventory_by_path = {
            entry.canonical_path: entry
            for entry in inventory.entries
            if entry.canonical_path in modified_paths
        }

        writes: list[ResolutionWrite] = []
        for catalog_file in sorted(
            catalog_item.files, key=lambda entry: entry.path
        ):
            payload = _load_bytes(
                payload_loader,
                catalog_file.path,
                context=f"item {item_id} release payload",
            )
            digest = hashlib.sha256(payload).hexdigest()
            if digest != catalog_file.sha256:
                raise _refuse(
                    f"item {item_id} payload {catalog_file.path} sha256 "
                    "does not match the catalog"
                )
            writes.append(
                ResolutionWrite(
                    catalog_file.path,
                    digest,
                    len(payload),
                    "release",
                )
            )

        if strategy == "keep-both":
            if not modified_paths:
                raise _refuse(
                    f"item {item_id} has nothing to preserve; choose take-theirs"
                )
            for canonical_path in sorted(modified_paths):
                preserved_path = sidecar_path(canonical_path)
                current = _load_bytes(
                    current_bytes_loader,
                    canonical_path,
                    context=f"item {item_id} current bytes",
                )
                current_digest = hashlib.sha256(current).hexdigest()
                evidence = inventory_by_path.get(canonical_path)
                if (
                    evidence is None
                    or evidence.kind != "file"
                    or evidence.release_state != "stock-modified"
                    or evidence.sha256 != current_digest
                    or evidence.size != len(current)
                ):
                    raise _refuse(
                        f"item {item_id} current bytes {canonical_path} "
                        "changed while the preview was being built"
                    )
                writes.append(
                    ResolutionWrite(
                        preserved_path,
                        current_digest,
                        len(current),
                        "preserved",
                    )
                )

        item_paths[item_id] = catalog_paths
        items.append(
            ResolutionItem(
                item_id,
                catalog_item.version,
                strategy,
                tuple(sorted(writes, key=lambda write: write.path)),
            )
        )

    preview = ConflictResolutionPreview(
        RESOLUTION_PREVIEW_VERSION,
        catalog.integrity.catalog_sha256,
        _requested_inventory_sha256(inventory, item_paths),
        tuple(items),
    )
    return ConflictResolutionPreview.from_dict(preview.to_dict())


def canonical_conflict_resolution_preview_bytes(
    preview: ConflictResolutionPreview,
) -> bytes:
    if not isinstance(preview, ConflictResolutionPreview):
        raise _refuse("preview must be a ConflictResolutionPreview")
    return _canonical_bytes(
        preview.to_dict(), "conflict resolution preview"
    )


__all__ = [
    "ConflictResolutionPreview",
    "ConflictResolutionPreviewError",
    "CurrentBytesLoader",
    "PayloadLoader",
    "RESOLUTION_PREVIEW_VERSION",
    "ResolutionItem",
    "ResolutionWrite",
    "SOURCES",
    "STRATEGIES",
    "build_conflict_resolution_preview",
    "canonical_conflict_resolution_preview_bytes",
    "sidecar_path",
]
