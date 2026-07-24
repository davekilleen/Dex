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

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from core import portable_contract
from core.lifecycle.catalog import load_catalog, load_catalog_payload_sources
from core.lifecycle.conflict import (
    ConflictResolutionPreview,
    build_conflict_resolution_preview,
)
from core.lifecycle.engine import (
    AdoptionReceipt,
    execute_adoption,
    execute_conflict_resolution,
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
from core.path_safety import unsafe_existing_parent
from core.transaction.engine import PlanEntry, PlanRejected, Transaction

api_version = "1.0.0"

_CATALOG_RELATIVE = "System/.release-catalog.json"
_PURPOSE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _envelope(**values: object) -> dict[str, object]:
    return {"api_version": api_version, **values}


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


def _transaction_preview_document(
    vault_root: str | Path,
    plan: Sequence[PlanEntry],
    *,
    purpose: str,
) -> dict[str, object]:
    """Build the private service-to-Transaction approval binding.

    This is deliberately outside the frozen public ABI.  It gives trusted
    in-repo callers such as Doctor one service-owned route for small repairs
    that are authorized by the portable contract but are not catalog items.
    """
    if _PURPOSE.fullmatch(purpose) is None:
        raise ValueError("transaction purpose must be a short lowercase identifier")
    if not plan:
        raise ValueError("transaction preview needs at least one write")
    root = Path(vault_root)
    writes: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in plan:
        if not isinstance(entry, PlanEntry) or entry.content is None:
            raise ValueError("private lifecycle transactions currently accept writes only")
        if entry.relative in seen:
            raise ValueError(f"transaction preview repeats path {entry.relative}")
        seen.add(entry.relative)
        unsafe = unsafe_existing_parent(root, entry.relative)
        if unsafe is not None:
            raise PlanRejected(f"{entry.relative}: {unsafe}")
        target = root / entry.relative
        verdict = portable_contract.update_write_verdict(
            entry.relative,
            exists=target.exists(),
        )
        if not verdict.allowed:
            raise PlanRejected(
                f"the ownership contract forbids writing: {entry.relative} [{verdict.action}]"
            )
        current: dict[str, object]
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise PlanRejected(f"{entry.relative}: existing target is not a regular file")
            raw = target.read_bytes()
            current = {
                "exists": True,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "mode": target.stat().st_mode & 0o777,
            }
        else:
            current = {"exists": False, "sha256": None, "mode": None}
        writes.append(
            {
                "path": entry.relative,
                "sha256": entry.sha256(),
                "byte_size": len(entry.content),
                "mode": entry.mode,
                "current": current,
            }
        )
    return {
        "purpose": purpose,
        "writes": sorted(writes, key=lambda write: str(write["path"])),
    }


def _preview_transaction(
    vault_root: str | Path,
    plan: Sequence[PlanEntry],
    *,
    purpose: str,
) -> dict[str, object]:
    """Preview a private, contract-authorized transaction without writing."""
    preview = _transaction_preview_document(vault_root, plan, purpose=purpose)
    return _envelope(
        preview=preview,
        approval_token=hashlib.sha256(_canonical(preview)).hexdigest(),
    )


def _tree_paths(root: Path, relative: Path) -> set[str]:
    target = root / relative
    if not target.exists() or target.is_symlink():
        return set()
    paths = {relative.as_posix()}
    if target.is_dir():
        paths.update(path.relative_to(root).as_posix() for path in target.rglob("*"))
    return paths


def _missing_ancestors(root: Path, relatives: Sequence[str]) -> set[str]:
    missing: set[str] = set()
    for relative in relatives:
        current = Path(relative).parent
        while current != Path("."):
            if not (root / current).exists():
                missing.add(current.as_posix())
            current = current.parent
    return missing


def _execute_approved_transaction(
    vault_root: str | Path,
    plan: Sequence[PlanEntry],
    *,
    purpose: str,
    approved_token: str,
) -> dict[str, object]:
    """Execute an exact private preview through the one Transaction engine."""
    root = Path(vault_root)
    rebuilt = _preview_transaction(root, plan, purpose=purpose)
    expected = rebuilt["approval_token"]
    if not isinstance(approved_token, str) or not hmac.compare_digest(
        approved_token,
        str(expected),
    ):
        raise PlanRejected("transaction approval token does not match the current preview")

    targets = [entry.relative for entry in plan]
    missing_ancestors = _missing_ancestors(
        root,
        [*targets, "System/.dex/tx/placeholder"],
    )
    tx_root_relative = Path("System/.dex/tx")
    tx_paths_before = _tree_paths(root, tx_root_relative)
    result = Transaction.begin(root, list(plan)).run()
    tx_paths_after = _tree_paths(root, tx_root_relative)
    declared_paths = (
        set(targets)
        | missing_ancestors
        | (tx_paths_before ^ tx_paths_after)
    )
    files_written = [
        {
            "path": entry.relative,
            "sha256": entry.sha256(),
            "byte_size": len(entry.content or b""),
            "mode": entry.mode,
        }
        for entry in sorted(plan, key=lambda candidate: candidate.relative)
    ]
    return _envelope(
        receipt={
            "purpose": purpose,
            "transaction_id": result["tx_id"],
            "snapshot_ref": str(result["snapshot_dir"]),
            "files_written": files_written,
            "declared_paths": sorted(declared_paths),
        }
    )


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
    sources = load_catalog_payload_sources(root)

    def load(relative: str) -> bytes:
        mapping = sources.get(relative)
        return bounded_read(root, relative if mapping is None else mapping.source_path)

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


def build_and_preview_conflict_resolution(
    vault_root: str | Path,
    release_root: str | Path,
    resolutions: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build exact conflict-resolution writes and their approval token."""
    _prepare(vault_root, release_root)
    catalog, inventory, plan = _inventory_and_plan_models(vault_root)
    preview = build_conflict_resolution_preview(
        catalog,
        inventory,
        plan,
        resolutions,
        _release_payload_loader(release_root),
        lambda path: bounded_read(Path(vault_root), path),
    )
    return _envelope(preview=preview.to_dict(), approval_token=preview.sha256)


def execute_approved_conflict_resolution(
    vault_root: str | Path,
    release_root: str | Path,
    preview: ConflictResolutionPreview | Mapping[str, object],
    approved_token: str,
) -> dict[str, object]:
    """Execute one exactly approved conflict-resolution preview."""
    _prepare(vault_root, release_root)
    modeled = (
        preview
        if isinstance(preview, ConflictResolutionPreview)
        else ConflictResolutionPreview.from_dict(preview)
    )
    receipt = execute_conflict_resolution(
        Path(vault_root),
        modeled,
        approved_token,
        _release_payload_loader(release_root),
        lambda path: bounded_read(Path(vault_root), path),
    )
    return _envelope(
        receipt=receipt.to_dict(),
        rewind_acknowledgement_token=rewind_acknowledgement_token(receipt),
    )


__all__ = [
    "api_version",
    "build_inventory_and_plan",
    "build_and_preview_adoption",
    "execute_approved_adoption",
    "rewind_adoption_by_receipt",
    "read_lifecycle_state",
    "build_and_preview_conflict_resolution",
    "execute_approved_conflict_resolution",
]
