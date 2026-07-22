"""Frozen public lifecycle API (v1).

This module is the sole sanctioned lifecycle entry point for Phase E callers.
Changing a frozen function signature or JSON shape requires an API version bump
and a compatibility bridge for callers on the preceding version.

The facade deliberately contains no lifecycle policy.  Read operations compose
the existing catalog, inventory, planning, ledger, and retention functions;
mutations delegate to :mod:`core.lifecycle.engine`, which in turn delegates to
the transaction and portable-contract layers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from core.lifecycle.catalog import load_catalog
from core.lifecycle.engine import (
    AdoptionReceipt,
    execute_adoption,
    rewind_acknowledgement_token,
    rewind_adoption,
)
from core.lifecycle.filesystem import bounded_read
from core.lifecycle.inventory import build_inventory
from core.lifecycle.ledger import project_state
from core.lifecycle.model import AdoptionState
from core.lifecycle.plan import build_adoption_plan
from core.lifecycle.preview import AdoptionPreview, build_adoption_preview
from core.lifecycle.retention import compute_retention_report

api_version = "1.0.0"

_CATALOG_RELATIVE = "System/.release-catalog.json"


def _envelope(**values: object) -> dict[str, object]:
    return {"api_version": api_version, **values}


def _inventory_and_plan_models(vault_root: str | Path):
    root = Path(vault_root)
    catalog = load_catalog(root / _CATALOG_RELATIVE, release_root=root)
    inventory = build_inventory(root, catalog=catalog)
    ledger = project_state(root)
    adopted = ledger["adopted"]
    held_back = ledger["held_back"]
    assert isinstance(adopted, dict)
    assert isinstance(held_back, list)
    plan = build_adoption_plan(
        catalog,
        inventory,
        adoption_states={item_id: AdoptionState.ADOPTED for item_id in adopted},
        held_back=frozenset(held_back),
    )
    return catalog, inventory, plan


def _release_payload_loader(release_root: str | Path):
    root = Path(release_root)

    def load(relative: str) -> bytes:
        return bounded_read(root, relative)

    return load


def _prepare(vault_root: str | Path, release_root: str | Path | None = None) -> None:
    from core.lifecycle.bridge import prepare_vault

    prepare_vault(vault_root, release_root=release_root)


def build_inventory_and_plan(vault_root: str | Path) -> dict[str, object]:
    """Return the current verified inventory and ledger-aware adoption plan."""
    _prepare(vault_root)
    _catalog, inventory, plan = _inventory_and_plan_models(vault_root)
    return _envelope(inventory=inventory.to_dict(), plan=plan.to_dict())


def build_and_preview_adoption(
    vault_root: str | Path,
    release_root: str | Path,
    requested_item_ids: Sequence[str],
) -> dict[str, object]:
    """Build the exact preview and approval token for requested catalog items."""
    _prepare(vault_root, release_root)
    catalog, inventory, plan = _inventory_and_plan_models(vault_root)
    preview = build_adoption_preview(
        catalog,
        inventory,
        plan,
        requested_item_ids,
        _release_payload_loader(release_root),
    )
    return _envelope(preview=preview.to_dict(), approval_token=preview.sha256)


def execute_approved_adoption(
    vault_root: str | Path,
    release_root: str | Path,
    preview: AdoptionPreview | Mapping[str, object],
    approved_token: str,
) -> dict[str, object]:
    """Execute one exactly approved preview and return its durable receipt."""
    _prepare(vault_root, release_root)
    modeled = preview if isinstance(preview, AdoptionPreview) else AdoptionPreview.from_dict(preview)
    receipt = execute_adoption(
        Path(vault_root),
        modeled,
        approved_token,
        _release_payload_loader(release_root),
    )
    return _envelope(
        receipt=receipt.to_dict(),
        rewind_acknowledgement_token=rewind_acknowledgement_token(receipt),
    )


def rewind_adoption_by_receipt(
    vault_root: str | Path,
    receipt: AdoptionReceipt | Mapping[str, object],
    acknowledgement_token: str,
) -> dict[str, object]:
    """Rewind the adoption identified by an exact receipt and acknowledgement."""
    _prepare(vault_root)
    rewind_receipt = rewind_adoption(
        Path(vault_root),
        receipt,
        acknowledgement_token,
    )
    return _envelope(rewind_receipt=rewind_receipt.to_dict())


def read_lifecycle_state(vault_root: str | Path) -> dict[str, object]:
    """Return verified ledger state and the advisory snapshot-retention report."""
    root = Path(vault_root)
    _prepare(root)
    retention = compute_retention_report(root)
    return _envelope(
        ledger_state=project_state(root),
        retention={
            "total_bytes": retention.total_bytes,
            "committed_snapshot_count": retention.committed_snapshot_count,
            "warning": retention.warning,
            "warning_threshold_bytes": retention.warning_threshold_bytes,
        },
    )


__all__ = [
    "api_version",
    "build_inventory_and_plan",
    "build_and_preview_adoption",
    "execute_approved_adoption",
    "rewind_adoption_by_receipt",
    "read_lifecycle_state",
]
