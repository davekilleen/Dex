"""Pure, deterministic adoption planning over read-only lifecycle evidence."""

from __future__ import annotations

import json
import posixpath
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from core.lifecycle.customizations import CustomizationReport, Divergence
from core.lifecycle.inventory import InventoryEntry, InventoryReport
from core.lifecycle.model import (
    HEX_SHA256,
    ITEM_ID,
    SEMVER,
    AdoptionState,
    CatalogItem,
    ReleaseCatalog,
)

PLAN_VERSION = 1


class AdoptionPlanError(ValueError):
    """The requested or serialized plan cannot be interpreted safely."""


def _unknown(message: str) -> AdoptionPlanError:
    return AdoptionPlanError(f"adoption plan is UNKNOWN: {message}")


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _unknown(f"{context} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise _unknown(f"{context} has a non-string field name")
    return value


def _closed_fields(value: Mapping[str, Any], *, required: set[str], context: str) -> None:
    fields = set(value)
    missing = required - fields
    extra = fields - required
    if missing:
        raise _unknown(f"{context} is missing required fields: {', '.join(sorted(missing))}")
    if extra:
        raise _unknown(f"{context} has unknown fields: {', '.join(sorted(extra))}")


def _string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise _unknown(f"{context} must be a non-empty string")
    return value


def _item_id(value: object, context: str) -> str:
    candidate = _string(value, context)
    if ITEM_ID.fullmatch(candidate) is None:
        raise _unknown(f"{context} is not a canonical item id")
    return candidate


def _version(value: object, context: str) -> str:
    candidate = _string(value, context)
    if SEMVER.fullmatch(candidate) is None:
        raise _unknown(f"{context} is not strict SemVer")
    return candidate


def _sha256(value: object, context: str) -> str:
    candidate = _string(value, context)
    if HEX_SHA256.fullmatch(candidate) is None:
        raise _unknown(f"{context} must be a lowercase sha256 digest")
    return candidate


def _relative_path(value: object, context: str) -> str:
    candidate = _string(value, context)
    if "\\" in candidate or candidate.startswith("/") or any(ord(char) < 32 for char in candidate):
        raise _unknown(f"{context} must be a release-relative POSIX path")
    normalized = posixpath.normpath(candidate)
    if normalized != candidate or normalized in ("", ".", "..") or normalized.startswith("../"):
        raise _unknown(f"{context} is not a canonical release-relative path")
    return candidate


class PlannedAction(str, Enum):
    ADOPT = "adopt"
    ALREADY_ADOPTED = "already-adopted"
    SKIP_HELD_BACK = "skip-held-back"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class ReasonCode(str, Enum):
    HELD_BACK_BY_USER = "held-back-by-user"
    ADOPTION_RECEIPT_ADOPTED = "adoption-receipt-adopted"
    ADOPTION_RECEIPT_INCOMPLETE = "adoption-receipt-incomplete"
    ADOPTION_RECEIPT_CONFLICT = "adoption-receipt-conflict"
    ADOPTION_RECEIPT_NOT_ADOPTED = "adoption-receipt-not-adopted"
    RELEASE_FILES_MODIFIED = "release-files-modified"
    RELEASE_FILES_MISSING = "release-files-missing"
    RELEASE_FILES_UNKNOWN = "release-files-unknown"
    RELEASE_FILES_READY = "release-files-ready"


@dataclass(frozen=True)
class PlanReason:
    code: ReasonCode
    paths: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, raw: object) -> "PlanReason":
        value = _mapping(raw, "adoption plan reason")
        _closed_fields(value, required={"code", "paths"}, context="adoption plan reason")
        try:
            code = ReasonCode(_string(value["code"], "adoption plan reason code"))
        except ValueError as error:
            raise _unknown("adoption plan reason has an unknown code") from error
        if not isinstance(value["paths"], list):
            raise _unknown("adoption plan reason paths must be an array")
        paths = tuple(
            _relative_path(path, "adoption plan reason path") for path in value["paths"]
        )
        if paths != tuple(sorted(set(paths))):
            raise _unknown("adoption plan reason paths must be sorted and unique")
        path_reason_codes = {
            ReasonCode.RELEASE_FILES_MODIFIED,
            ReasonCode.RELEASE_FILES_MISSING,
            ReasonCode.RELEASE_FILES_UNKNOWN,
            ReasonCode.RELEASE_FILES_READY,
        }
        if (code in path_reason_codes) != bool(paths):
            raise _unknown("adoption plan reason path shape disagrees with its code")
        return cls(code, paths)

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code.value, "paths": list(self.paths)}


@dataclass(frozen=True)
class ItemEvidence:
    """Evidence already isolated to one catalog item."""

    inventory_entries: tuple[InventoryEntry, ...]
    divergences: tuple[Divergence, ...]


@dataclass(frozen=True)
class AdoptionPlanItem:
    item_id: str
    item_version: str
    action: PlannedAction
    reasons: tuple[PlanReason, ...]

    @classmethod
    def from_dict(cls, raw: object) -> "AdoptionPlanItem":
        value = _mapping(raw, "adoption plan item")
        _closed_fields(
            value,
            required={"item_id", "item_version", "action", "reasons"},
            context="adoption plan item",
        )
        item_id = _item_id(value["item_id"], "adoption plan item_id")
        item_version = _version(value["item_version"], f"adoption plan item {item_id} version")
        try:
            action = PlannedAction(_string(value["action"], f"adoption plan item {item_id} action"))
        except ValueError as error:
            raise _unknown(f"adoption plan item {item_id} has an unknown action") from error
        if not isinstance(value["reasons"], list) or not value["reasons"]:
            raise _unknown(f"adoption plan item {item_id} needs at least one reason")
        reasons = tuple(PlanReason.from_dict(reason) for reason in value["reasons"])
        if reasons != tuple(sorted(set(reasons), key=lambda reason: (reason.code.value, reason.paths))):
            raise _unknown(f"adoption plan item {item_id} reasons must be sorted and unique")
        reason_codes = {reason.code for reason in reasons}
        required_codes = {
            PlannedAction.ADOPT: {ReasonCode.RELEASE_FILES_READY},
            PlannedAction.ALREADY_ADOPTED: {ReasonCode.ADOPTION_RECEIPT_ADOPTED},
            PlannedAction.SKIP_HELD_BACK: {ReasonCode.HELD_BACK_BY_USER},
            PlannedAction.CONFLICT: {
                ReasonCode.ADOPTION_RECEIPT_CONFLICT,
                ReasonCode.RELEASE_FILES_MODIFIED,
                ReasonCode.RELEASE_FILES_MISSING,
            },
            PlannedAction.UNKNOWN: {
                ReasonCode.ADOPTION_RECEIPT_INCOMPLETE,
                ReasonCode.RELEASE_FILES_UNKNOWN,
            },
        }
        allowed_codes = {
            PlannedAction.ADOPT: {
                ReasonCode.ADOPTION_RECEIPT_NOT_ADOPTED,
                ReasonCode.RELEASE_FILES_READY,
            },
            PlannedAction.ALREADY_ADOPTED: {ReasonCode.ADOPTION_RECEIPT_ADOPTED},
            PlannedAction.SKIP_HELD_BACK: {ReasonCode.HELD_BACK_BY_USER},
            PlannedAction.CONFLICT: {
                ReasonCode.ADOPTION_RECEIPT_CONFLICT,
                ReasonCode.ADOPTION_RECEIPT_NOT_ADOPTED,
                ReasonCode.RELEASE_FILES_MODIFIED,
                ReasonCode.RELEASE_FILES_MISSING,
                ReasonCode.RELEASE_FILES_UNKNOWN,
            },
            PlannedAction.UNKNOWN: {
                ReasonCode.ADOPTION_RECEIPT_INCOMPLETE,
                ReasonCode.ADOPTION_RECEIPT_NOT_ADOPTED,
                ReasonCode.RELEASE_FILES_UNKNOWN,
            },
        }
        if not reason_codes.intersection(required_codes[action]) or not reason_codes.issubset(
            allowed_codes[action]
        ):
            raise _unknown(f"adoption plan item {item_id} reasons disagree with its action")
        return cls(item_id, item_version, action, reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "item_version": self.item_version,
            "action": self.action.value,
            "reasons": [reason.to_dict() for reason in self.reasons],
        }


@dataclass(frozen=True)
class AdoptionPlan:
    plan_version: int
    release_version: str
    catalog_sha256: str
    items: tuple[AdoptionPlanItem, ...]

    @property
    def counts(self) -> dict[str, int]:
        observed = Counter(item.action.value for item in self.items)
        return {action.value: observed[action.value] for action in PlannedAction}

    @classmethod
    def from_dict(cls, raw: object) -> "AdoptionPlan":
        value = _mapping(raw, "adoption plan")
        _closed_fields(
            value,
            required={"plan_version", "release_version", "catalog_sha256", "items", "counts"},
            context="adoption plan",
        )
        if type(value["plan_version"]) is not int or value["plan_version"] != PLAN_VERSION:
            raise _unknown(f"plan_version must be exactly {PLAN_VERSION}")
        if not isinstance(value["items"], list):
            raise _unknown("adoption plan items must be an array")
        items = tuple(AdoptionPlanItem.from_dict(item) for item in value["items"])
        if items != tuple(sorted(items, key=lambda item: item.item_id)):
            raise _unknown("adoption plan items must be sorted by item_id")
        if len({item.item_id for item in items}) != len(items):
            raise _unknown("adoption plan repeats an item_id")
        plan = cls(
            PLAN_VERSION,
            _version(value["release_version"], "adoption plan release_version"),
            _sha256(value["catalog_sha256"], "adoption plan catalog_sha256"),
            items,
        )
        counts = _mapping(value["counts"], "adoption plan counts")
        expected_fields = {action.value for action in PlannedAction}
        _closed_fields(counts, required=expected_fields, context="adoption plan counts")
        if any(type(counts[action]) is not int or counts[action] < 0 for action in expected_fields):
            raise _unknown("adoption plan counts must be non-negative integers")
        if dict(counts) != plan.counts:
            raise _unknown("adoption plan counts disagree with its items")
        return plan

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_version": self.plan_version,
            "release_version": self.release_version,
            "catalog_sha256": self.catalog_sha256,
            "items": [item.to_dict() for item in self.items],
            "counts": self.counts,
        }


def isolate_item_evidence(
    item: CatalogItem,
    inventory: InventoryReport,
    customizations: CustomizationReport,
) -> ItemEvidence:
    """Partition shared reports before planning so later items cannot influence this one."""
    paths = {catalog_file.path for catalog_file in item.files}
    entries = tuple(
        sorted(
            (entry for entry in inventory.entries if entry.canonical_path in paths),
            key=lambda entry: (entry.canonical_path, entry.actual_path, entry.kind),
        )
    )
    divergences = tuple(
        sorted(
            (entry for entry in customizations.divergences if entry.canonical_path in paths),
            key=lambda entry: (entry.canonical_path, entry.path, entry.state),
        )
    )
    return ItemEvidence(entries, divergences)


def _reason(code: ReasonCode, paths: set[str] | tuple[str, ...] = ()) -> PlanReason:
    return PlanReason(code, tuple(sorted(set(paths))))


def _ordered_reasons(reasons: list[PlanReason]) -> tuple[PlanReason, ...]:
    return tuple(sorted(set(reasons), key=lambda reason: (reason.code.value, reason.paths)))


def plan_catalog_item(
    item: CatalogItem,
    evidence: ItemEvidence,
    *,
    adoption_state: AdoptionState | None = None,
    held_back: bool = False,
) -> AdoptionPlanItem:
    """Plan exactly one item; no other item's state or action is an input."""
    if adoption_state is not None and not isinstance(adoption_state, AdoptionState):
        raise _unknown(f"adoption state for {item.id} must be an AdoptionState")
    if type(held_back) is not bool:
        raise _unknown(f"held_back for {item.id} must be a boolean")
    if held_back:
        return AdoptionPlanItem(
            item.id,
            item.version,
            PlannedAction.SKIP_HELD_BACK,
            (_reason(ReasonCode.HELD_BACK_BY_USER),),
        )
    if adoption_state is AdoptionState.ADOPTED:
        return AdoptionPlanItem(
            item.id,
            item.version,
            PlannedAction.ALREADY_ADOPTED,
            (_reason(ReasonCode.ADOPTION_RECEIPT_ADOPTED),),
        )
    if adoption_state in {
        AdoptionState.HELD_FOR_REVIEW,
        AdoptionState.CUSTOMIZATION_REVIEW_REQUIRED,
    }:
        return AdoptionPlanItem(
            item.id,
            item.version,
            PlannedAction.CONFLICT,
            (_reason(ReasonCode.ADOPTION_RECEIPT_CONFLICT),),
        )
    if adoption_state in {
        AdoptionState.APPLIED,
        AdoptionState.EXTERNAL_RECONCILIATION_PENDING,
        AdoptionState.NEEDS_RECHECK,
    }:
        return AdoptionPlanItem(
            item.id,
            item.version,
            PlannedAction.UNKNOWN,
            (_reason(ReasonCode.ADOPTION_RECEIPT_INCOMPLETE),),
        )

    item_paths = {catalog_file.path for catalog_file in item.files}
    by_path: dict[str, list[InventoryEntry]] = {path: [] for path in item_paths}
    for entry in evidence.inventory_entries:
        if entry.canonical_path not in item_paths:
            raise _unknown(f"item evidence for {item.id} includes another item's inventory path")
        by_path[entry.canonical_path].append(entry)
    conflict_paths: dict[ReasonCode, set[str]] = {
        ReasonCode.RELEASE_FILES_MODIFIED: set(),
        ReasonCode.RELEASE_FILES_MISSING: set(),
    }
    safely_creatable: set[str] = set()
    unknown_paths: set[str] = set()
    for path, entries in by_path.items():
        if len(entries) != 1:
            unknown_paths.add(path)
            continue
        state = entries[0].release_state
        if state == "stock-modified":
            conflict_paths[ReasonCode.RELEASE_FILES_MODIFIED].add(path)
        elif state == "stock-missing":
            if entries[0].write_allowed:
                safely_creatable.add(path)
            else:
                conflict_paths[ReasonCode.RELEASE_FILES_MISSING].add(path)
        elif state != "stock-unmodified":
            unknown_paths.add(path)
    for divergence in evidence.divergences:
        if divergence.canonical_path not in item_paths:
            raise _unknown(f"item evidence for {item.id} includes another item's divergence")
        if divergence.state == "stock-modified":
            conflict_paths[ReasonCode.RELEASE_FILES_MODIFIED].add(divergence.canonical_path)
        elif divergence.state == "stock-missing":
            if divergence.canonical_path not in safely_creatable:
                conflict_paths[ReasonCode.RELEASE_FILES_MISSING].add(
                    divergence.canonical_path
                )
        else:
            unknown_paths.add(divergence.canonical_path)

    reasons: list[PlanReason] = []
    if adoption_state in {
        AdoptionState.REWOUND,
        AdoptionState.SKIPPED_BY_USER,
        AdoptionState.FAILED_ROLLED_BACK,
    }:
        reasons.append(_reason(ReasonCode.ADOPTION_RECEIPT_NOT_ADOPTED))
    reasons.extend(
        _reason(code, paths)
        for code, paths in conflict_paths.items()
        if paths
    )
    if unknown_paths:
        reasons.append(_reason(ReasonCode.RELEASE_FILES_UNKNOWN, unknown_paths))
    if any(conflict_paths.values()):
        action = PlannedAction.CONFLICT
    elif unknown_paths:
        action = PlannedAction.UNKNOWN
    else:
        action = PlannedAction.ADOPT
        reasons.append(_reason(ReasonCode.RELEASE_FILES_READY, item_paths))
    return AdoptionPlanItem(item.id, item.version, action, _ordered_reasons(reasons))


def build_adoption_plan(
    catalog: ReleaseCatalog,
    inventory: InventoryReport,
    *,
    customizations: CustomizationReport | None = None,
    adoption_states: Mapping[str, AdoptionState] | None = None,
    held_back: set[str] | frozenset[str] = frozenset(),
) -> AdoptionPlan:
    """Build a read-only plan by invoking the pure per-item planner independently."""
    if not isinstance(catalog, ReleaseCatalog):
        raise _unknown("catalog must be a loaded ReleaseCatalog")
    if not isinstance(inventory, InventoryReport):
        raise _unknown("inventory must be an InventoryReport")
    customizations = inventory.customizations if customizations is None else customizations
    if not isinstance(customizations, CustomizationReport):
        raise _unknown("customizations must be a CustomizationReport")
    if not isinstance(held_back, (set, frozenset)) or not all(
        isinstance(item_id, str) for item_id in held_back
    ):
        raise _unknown("held_back must be a set of item ids")
    states = {} if adoption_states is None else adoption_states
    if not isinstance(states, Mapping) or not all(isinstance(item_id, str) for item_id in states):
        raise _unknown("adoption_states must map item ids to AdoptionState values")
    catalog_ids = {item.id for item in catalog.items}
    unknown_holdbacks = set(held_back) - catalog_ids
    if unknown_holdbacks:
        raise _unknown(f"unknown held-back item: {', '.join(sorted(unknown_holdbacks))}")
    unknown_states = set(states) - catalog_ids
    if unknown_states:
        raise _unknown(f"unknown adoption-state item: {', '.join(sorted(unknown_states))}")
    for item_id, state in states.items():
        if not isinstance(state, AdoptionState):
            raise _unknown(f"adoption state for {item_id} must be an AdoptionState")

    items = tuple(
        plan_catalog_item(
            item,
            isolate_item_evidence(item, inventory, customizations),
            adoption_state=states.get(item.id),
            held_back=item.id in held_back,
        )
        for item in sorted(catalog.items, key=lambda candidate: candidate.id)
    )
    return AdoptionPlan(
        PLAN_VERSION,
        catalog.release.version,
        catalog.integrity.catalog_sha256,
        items,
    )


def canonical_adoption_plan_bytes(plan: AdoptionPlan) -> bytes:
    """Stable JSON bytes for receipts and equality checks; contains no clock fields."""
    try:
        return (
            json.dumps(
                plan.to_dict(),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise _unknown(f"plan cannot be serialized canonically: {error}") from error


__all__ = [
    "AdoptionPlan",
    "AdoptionPlanError",
    "AdoptionPlanItem",
    "ItemEvidence",
    "PlanReason",
    "PlannedAction",
    "ReasonCode",
    "build_adoption_plan",
    "canonical_adoption_plan_bytes",
    "isolate_item_evidence",
    "plan_catalog_item",
]
