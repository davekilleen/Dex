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
import os
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from core import portable_contract
from core.customization_migration.registration import mcp_registration_snippet
from core.lifecycle.catalog import load_catalog, load_catalog_payload_sources
from core.lifecycle.conflict import (
    ConflictResolutionPreview,
    build_conflict_resolution_preview,
)
from core.lifecycle.engine import (
    AdoptionReceipt,
    TopologyMigrationError,
    build_topology_migration_preview,
    execute_adoption,
    execute_conflict_resolution,
    execute_topology_migration,
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

api_version = "1.4.0"

_CATALOG_RELATIVE = "System/.release-catalog.json"
_PURPOSE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_ARCHIVE_RELATIVE = ".dex/pre-split-archive.git"
_ARCHIVE_RECEIPTS_RELATIVE = "System/.dex/archive-removals"
_MCP_CONFIG_RELATIVE = ".mcp.json"
_MCP_REGISTRATION_NAME = "customization-migration-mcp"
_ONBOARDING_PROFILE_RELATIVE = "System/user-profile.yaml"
_REBUILD_TRANSACTION_PATH = re.compile(
    r"^System/\.dex/customization-migrations/cap-[0-9a-f]{16}/(?:"
    r"receipts/(?:capsule|activation|rewind)\.json|"
    r"verification/prop-[0-9a-f]{16}\.json|"
    r"candidates/prop-[0-9a-f]{16}/staging/receipt\.json"
    r")$"
)


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
    operation: str = "update",
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
        if not isinstance(entry, PlanEntry):
            raise ValueError("private lifecycle transactions require PlanEntry values")
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
            operation=operation,
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
                "action": entry.operation,
                "sha256": entry.sha256(),
                "byte_size": len(entry.content) if entry.content is not None else 0,
                "mode": entry.mode,
                "current": current,
            }
        )
    preview = {
        "purpose": purpose,
        "writes": sorted(writes, key=lambda write: str(write["path"])),
    }
    if operation != "update":
        preview["operation"] = operation
    return preview


def _preview_transaction(
    vault_root: str | Path,
    plan: Sequence[PlanEntry],
    *,
    purpose: str,
    operation: str = "update",
) -> dict[str, object]:
    """Preview a private, contract-authorized transaction without writing."""
    preview = _transaction_preview_document(
        vault_root,
        plan,
        purpose=purpose,
        operation=operation,
    )
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
    operation: str = "update",
    before_commit: Callable[[], None] | None = None,
) -> dict[str, object]:
    """Execute an exact private preview through the one Transaction engine."""
    root = Path(vault_root)
    rebuilt = _preview_transaction(
        root,
        plan,
        purpose=purpose,
        operation=operation,
    )
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
    result = Transaction.begin(root, list(plan), operation=operation).run(
        before_commit=before_commit
    )
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


def _confirmed_onboarding_context(
    working_context: Mapping[str, object],
    calendar_source: Mapping[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    """Validate the closed, user-reviewed onboarding fields for persistence."""
    context_fields = (
        "role_focus",
        "current_work",
        "week_success",
        "quarter_outcome",
        "anything_else",
    )
    allowed_context = {*context_fields, "key_people"}
    if set(working_context) - allowed_context:
        raise PlanRejected("working context contains unsupported fields")
    context: dict[str, object] = {}
    for field in context_fields:
        value = working_context.get(field, "")
        if not isinstance(value, str):
            raise PlanRejected(f"working context {field} must be text")
        cleaned = value.strip()
        if cleaned:
            context[field] = cleaned
    people = working_context.get("key_people", [])
    if not isinstance(people, list) or len(people) > 5:
        raise PlanRejected("working context key_people must contain at most five people")
    normalized_people: list[dict[str, str]] = []
    for person in people:
        if not isinstance(person, Mapping) or set(person) - {"name", "relationship", "how_to_help"}:
            raise PlanRejected("working context people must contain name, relationship, and how_to_help")
        name = person.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PlanRejected("working context people need a name")
        normalized = {"name": name.strip()}
        for field in ("relationship", "how_to_help"):
            value = person.get(field, "")
            if not isinstance(value, str):
                raise PlanRejected(f"working context people {field} must be text")
            if value.strip():
                normalized[field] = value.strip()
        normalized_people.append(normalized)
    context["key_people"] = normalized_people
    if not context or (set(context) == {"key_people"} and not normalized_people):
        raise PlanRejected("working context needs at least one confirmed value")

    provider = calendar_source.get("provider")
    if provider == "none":
        if set(calendar_source) != {"provider"}:
            raise PlanRejected("an absent calendar source cannot include calendar details")
        return context, {"provider": "none"}
    if provider != "apple" or set(calendar_source) != {"provider", "work_calendar"}:
        raise PlanRejected("calendar source must be Apple Calendar or no calendar")
    calendar_name = calendar_source.get("work_calendar")
    if not isinstance(calendar_name, str) or not calendar_name.strip():
        raise PlanRejected("Apple Calendar needs a selected calendar name")
    return context, {"provider": "apple", "work_calendar": calendar_name.strip()}


def _onboarding_context_preview(
    vault_root: str | Path,
    working_context: Mapping[str, object],
    calendar_source: Mapping[str, object],
) -> tuple[dict[str, object], list[PlanEntry]]:
    """Build the exact profile mutation for confirmed onboarding context."""
    import yaml

    root = Path(vault_root)
    profile = root / _ONBOARDING_PROFILE_RELATIVE
    if profile.is_symlink() or not profile.is_file():
        raise PlanRejected("onboarding context requires a finalized regular user profile")
    original = profile.read_bytes()
    try:
        current = yaml.safe_load(original.decode("utf-8")) or {}
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise PlanRejected("user profile is not valid YAML") from error
    if not isinstance(current, dict):
        raise PlanRejected("user profile must be a YAML object")
    context, source = _confirmed_onboarding_context(working_context, calendar_source)
    updated = dict(current)
    updated["working_context"] = context
    updated["calendar"] = source
    plan = [
        PlanEntry(
            _ONBOARDING_PROFILE_RELATIVE,
            yaml.safe_dump(updated, sort_keys=False, allow_unicode=True).encode("utf-8"),
            mode=profile.stat().st_mode & 0o777,
            expected_current_sha256=hashlib.sha256(original).hexdigest(),
        )
    ]
    transaction = _transaction_preview_document(
        root,
        plan,
        purpose="onboarding-context",
        operation="onboarding-context",
    )
    return {
        "working_context": context,
        "calendar_source": source,
        "writes": transaction["writes"],
    }, plan


def build_and_preview_onboarding_context(
    vault_root: str | Path,
    working_context: Mapping[str, object],
    calendar_source: Mapping[str, object],
) -> dict[str, object]:
    """Show the confirmed onboarding profile update before writing anything."""
    preview, _plan = _onboarding_context_preview(vault_root, working_context, calendar_source)
    return _envelope(
        preview=preview,
        approval_token=hashlib.sha256(_canonical(preview)).hexdigest(),
    )


def execute_approved_onboarding_context(
    vault_root: str | Path,
    preview: Mapping[str, object],
    approved_token: str,
) -> dict[str, object]:
    """Write only the unchanged, confirmed onboarding context through Transaction."""
    if not isinstance(preview, Mapping):
        raise PlanRejected("onboarding context preview is malformed")
    working_context = preview.get("working_context")
    calendar_source = preview.get("calendar_source")
    if not isinstance(working_context, Mapping) or not isinstance(calendar_source, Mapping):
        raise PlanRejected("onboarding context preview is malformed")
    expected_preview, plan = _onboarding_context_preview(
        vault_root,
        working_context,
        calendar_source,
    )
    expected_bytes = _canonical(expected_preview)
    if (
        _canonical(dict(preview)) != expected_bytes
        or not isinstance(approved_token, str)
        or not hmac.compare_digest(approved_token, hashlib.sha256(expected_bytes).hexdigest())
    ):
        raise PlanRejected("onboarding context approval does not match the current exact preview")
    transaction = _preview_transaction(
        vault_root,
        plan,
        purpose="onboarding-context",
        operation="onboarding-context",
    )
    executed = _execute_approved_transaction(
        vault_root,
        plan,
        purpose="onboarding-context",
        operation="onboarding-context",
        approved_token=str(transaction["approval_token"]),
    )
    return _envelope(receipt=executed["receipt"])


def _missing_companies_default_plan(
    vault_root: str | Path,
) -> tuple[list[PlanEntry], dict[str, bool]]:
    """Build the exact compatibility plan and room-state summary."""
    import yaml

    from core.capabilities import render_missing_companies_compatibility_pin

    root = Path(vault_root)
    profile = root / "System/user-profile.yaml"
    if profile.is_symlink():
        raise PlanRejected("System/user-profile.yaml must not be a symlink")
    exists = profile.exists()
    if exists and not profile.is_file():
        raise PlanRejected("System/user-profile.yaml must be a regular file")
    original = profile.read_text(encoding="utf-8") if exists else ""
    rendered = render_missing_companies_compatibility_pin(original)
    if rendered is None:
        return [], {}

    before = yaml.safe_load(original) or {}
    after = yaml.safe_load(rendered) or {}
    before_capabilities = before.get("capabilities", {})
    after_capabilities = after.get("capabilities", {})
    states = {
        room: state["enabled"]
        for room, state in after_capabilities.items()
        if isinstance(state, Mapping)
        and isinstance(state.get("enabled"), bool)
        and (
            not isinstance(before_capabilities, Mapping)
            or before_capabilities.get(room) != state
        )
    }

    raw = original.encode("utf-8")
    return [
        PlanEntry(
            "System/user-profile.yaml",
            rendered.encode("utf-8"),
            mode=(profile.stat().st_mode & 0o777) if exists else 0o644,
            expected_current_sha256=(
                hashlib.sha256(raw).hexdigest() if exists else None
            ),
            expected_absent=not exists,
        )
    ], states


def _preview_missing_companies_default(
    vault_root: str | Path,
) -> dict[str, object]:
    """Preview the compatibility transaction without recovering or writing."""
    root = Path(vault_root)
    plan, states = _missing_companies_default_plan(root)
    if not plan:
        return _envelope(pinned=False, preview=None, states={})
    purpose = "companies-default-compatibility"
    operation = "capability-state"
    preview = _preview_transaction(
        root,
        plan,
        purpose=purpose,
        operation=operation,
    )
    return _envelope(pinned=True, preview=preview["preview"], states=states)


def _pin_missing_companies_default(vault_root: str | Path) -> dict[str, object]:
    """Recover first, then transactionally pin legacy Companies state."""
    root = Path(vault_root)
    Transaction.resume(root)
    plan, states = _missing_companies_default_plan(root)
    if not plan:
        return _envelope(pinned=False, receipt=None, states={})
    purpose = "companies-default-compatibility"
    operation = "capability-state"
    preview = _preview_transaction(
        root,
        plan,
        purpose=purpose,
        operation=operation,
    )
    executed = _execute_approved_transaction(
        root,
        plan,
        purpose=purpose,
        operation=operation,
        approved_token=str(preview["approval_token"]),
    )
    return _envelope(pinned=True, receipt=executed["receipt"], states=states)


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
    from core.lifecycle.bridge import BridgeActivationError, prepare_vault

    try:
        prepare_vault(vault_root, release_root=release_root)
    except BridgeActivationError:
        raise PlanRejected(
            "this Dex copy's update engine doesn't match its release information "
            "— run /dex-doctor"
        ) from None


def _archive_inventory(root: Path) -> dict[str, object]:
    archive = root / _ARCHIVE_RELATIVE
    if archive.is_symlink() or not archive.is_dir():
        raise PlanRejected("the pre-split archive is missing or is not a safe directory")
    digest = hashlib.sha256()
    size_bytes = 0
    file_count = 0
    for candidate in sorted(archive.rglob("*")):
        if candidate.is_symlink() or not candidate.is_file():
            if candidate.is_symlink():
                raise PlanRejected("the pre-split archive contains a symlink")
            continue
        relative = candidate.relative_to(archive).as_posix().encode("utf-8")
        raw = candidate.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
        size_bytes += len(raw)
        file_count += 1
    return {
        "archive_relative": _ARCHIVE_RELATIVE,
        "archive_sha256": digest.hexdigest(),
        "size_bytes": size_bytes,
        "file_count": file_count,
        "retention": "one full release cycle after conversion",
    }


def build_archive_removal_preview(vault_root: str | Path) -> dict[str, object]:
    """Offer, but never force, a reviewed removal of the old undo archive."""
    root = Path(vault_root)
    preview = _archive_inventory(root)
    return _envelope(
        preview=preview,
        approval_token=hashlib.sha256(_canonical(preview)).hexdigest(),
    )


def _write_archive_receipt(path: Path, receipt: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        handle.write(_canonical(receipt))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def execute_approved_archive_removal(
    vault_root: str | Path, approved_token: str
) -> dict[str, object]:
    """Remove the exact archive previewed by the user while holding the shared lock."""
    root = Path(vault_root)
    preview = _archive_inventory(root)
    expected = hashlib.sha256(_canonical(preview)).hexdigest()
    if not isinstance(approved_token, str) or not hmac.compare_digest(approved_token, expected):
        raise PlanRejected("archive-removal approval token does not match the current archive")

    transaction = Transaction.begin(root, [], allow_empty=True)
    archive = root / _ARCHIVE_RELATIVE
    quarantined = transaction.tx_dir / "removed-pre-split-archive.git"
    receipt_relative = f"{_ARCHIVE_RECEIPTS_RELATIVE}/{transaction.tx_id}.json"
    receipt_path = root / receipt_relative
    moved = False
    try:
        def remove_archive() -> None:
            nonlocal moved
            os.replace(archive, quarantined)
            moved = True
            receipt = {
                "receipt_version": 1,
                "transaction_id": transaction.tx_id,
                "archive_relative": _ARCHIVE_RELATIVE,
                "archive_sha256": preview["archive_sha256"],
                "size_bytes": preview["size_bytes"],
                "file_count": preview["file_count"],
                "retention": preview["retention"],
            }
            _write_archive_receipt(receipt_path, receipt)

        result = transaction.run(before_commit=remove_archive)
    except BaseException:
        if moved and quarantined.exists() and not archive.exists():
            os.replace(quarantined, archive)
        receipt_path.unlink(missing_ok=True)
        raise
    shutil.rmtree(quarantined)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["receipt_relative"] = receipt_relative
    receipt["committed"] = bool(result["committed"])
    _write_archive_receipt(receipt_path, receipt)
    return _envelope(receipt=receipt)


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


def _bound_release_plan(root: Path, entries: Sequence[PlanEntry]) -> list[PlanEntry]:
    """Bind every delivered-release write to the bytes the user previewed."""
    bound: list[PlanEntry] = []
    for entry in entries:
        target = root / entry.relative
        if target.exists() or target.is_symlink():
            if target.is_symlink() or not target.is_file():
                raise PlanRejected(f"{entry.relative}: existing target is not a regular file")
            raw = target.read_bytes()
            bound.append(
                PlanEntry(
                    entry.relative,
                    entry.content,
                    entry.mode,
                    expected_current_sha256=hashlib.sha256(raw).hexdigest(),
                )
            )
            continue
        if entry.content is None:
            raise PlanRejected(f"{entry.relative}: delivered-release deletion target disappeared")
        bound.append(
            PlanEntry(
                entry.relative,
                entry.content,
                entry.mode,
                expected_absent=True,
            )
        )
    return bound


def _closed_release_identity(value: Mapping[str, object]) -> dict[str, str]:
    required = {"tag", "tag_object", "commit", "tree", "version", "channel"}
    if set(value) != required or not all(isinstance(value[key], str) for key in required):
        raise PlanRejected("delivered release identity is malformed")
    return {key: str(value[key]) for key in sorted(required)}


def _delivered_release_preview(
    vault_root: str | Path,
    release_identity: Mapping[str, object],
) -> tuple[dict[str, object], list[PlanEntry], object, str]:
    """Rebuild the exact delivery preview from immutable fetched bytes."""
    from core.update import apply_update

    root = Path(vault_root).resolve()
    identity = _closed_release_identity(release_identity)
    release = apply_update.verify_release_ref(
        root,
        tag=identity["tag"],
        tag_object=identity["tag_object"],
        commit=identity["commit"],
        tree=identity["tree"],
    )
    if apply_update._release_identity(release) != identity:
        raise PlanRejected("delivered release identity changed during verification")
    previous_commit = apply_update.validated_release_apply_context(root, release)
    plan = _bound_release_plan(root, apply_update.build_update_plan(root, release).entries)
    transaction = _transaction_preview_document(
        root,
        plan,
        purpose="delivered-release",
    )
    preview: dict[str, object] = {
        "release": identity,
        "previous_commit": previous_commit,
        "writes": transaction["writes"],
    }
    return preview, plan, release, previous_commit


def deliver_latest_release(vault_root: str | Path) -> dict[str, object]:
    """Fetch and re-prove a release, without a vault-content transaction."""
    from core.update.apply_update import deliver_latest_release as deliver

    return _envelope(**deliver(Path(vault_root)))


def build_and_preview_delivered_release(
    vault_root: str | Path,
    release: Mapping[str, object],
) -> dict[str, object]:
    """Render the exact immutable delivered release before asking for approval."""
    preview, _plan, _verified, _previous = _delivered_release_preview(vault_root, release)
    return _envelope(
        preview=preview,
        approval_token=hashlib.sha256(_canonical(preview)).hexdigest(),
    )


def execute_approved_delivered_release(
    vault_root: str | Path,
    preview: Mapping[str, object],
    approved_token: str,
) -> dict[str, object]:
    """Apply only the unchanged delivered-release preview through Transaction."""
    from core.update import apply_update

    if not isinstance(preview, Mapping) or set(preview) != {
        "release",
        "previous_commit",
        "writes",
    }:
        raise PlanRejected("delivered-release preview is malformed")
    if not isinstance(preview["release"], Mapping):
        raise PlanRejected("delivered-release preview is missing its release identity")
    try:
        expected_preview, plan, release, previous_commit = _delivered_release_preview(
            vault_root,
            preview["release"],
        )
        supplied_bytes = _canonical(dict(preview))
    except (TypeError, ValueError) as error:
        raise PlanRejected("delivered-release preview is not canonical JSON") from error
    expected_bytes = _canonical(expected_preview)
    expected_token = hashlib.sha256(expected_bytes).hexdigest()
    if not hmac.compare_digest(supplied_bytes, expected_bytes) or not isinstance(
        approved_token, str
    ) or not hmac.compare_digest(approved_token, expected_token):
        raise PlanRejected("delivered-release approval does not match the current exact preview")

    transaction_token = _preview_transaction(
        vault_root,
        plan,
        purpose="delivered-release",
    )["approval_token"]
    executed = _execute_approved_transaction(
        vault_root,
        plan,
        purpose="delivered-release",
        approved_token=str(transaction_token),
        before_commit=lambda: apply_update._finalize_release_metadata(
            Path(vault_root).resolve(), release, previous_commit
        ),
    )
    # Post-commit tidy-up (issue #433): the runtime activation record still
    # names the release that just executed this update, which would refuse
    # every gated operation until repaired.  The record is removed — never
    # rewritten — because this (old) engine must not interpret the newly
    # installed release's declarations or stamp its own api_version onto a
    # record naming the new release; the next gated operation re-records the
    # baseline with the newly installed code.  Removal is deliberately outside
    # the transaction and best-effort: a byte-verified committed update is
    # never failed because tidy-up could not run, and activate_vault's
    # stale-record re-recording remains the safety net.
    from core.lifecycle.bridge import ACTIVATION_RELATIVE, discard_superseded_activation

    receipt = executed["receipt"]
    identity = expected_preview["release"]
    assert isinstance(identity, Mapping)
    if discard_superseded_activation(Path(vault_root).resolve(), str(identity["version"])):
        declared = receipt.get("declared_paths")
        if isinstance(declared, list):
            receipt["declared_paths"] = sorted({*declared, ACTIVATION_RELATIVE.as_posix()})
    return _envelope(receipt=receipt, release=expected_preview["release"])


def _mcp_registration_preview(
    vault_root: str | Path,
) -> tuple[dict[str, object] | None, list[PlanEntry]]:
    """Build the one explicitly approved, add-only MCP registration write."""
    root = Path(vault_root).resolve()
    target = root / _MCP_CONFIG_RELATIVE
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise PlanRejected(".mcp.json must be a regular file")
    try:
        existing = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    except json.JSONDecodeError as error:
        raise PlanRejected("MCP configuration must contain valid JSON") from error
    if not isinstance(existing, dict):
        raise PlanRejected("MCP configuration must contain a JSON object")
    servers = existing.get("mcpServers")
    if servers is None:
        servers = {}
    if not isinstance(servers, dict):
        raise PlanRejected("MCP configuration must contain an mcpServers object")
    registration = mcp_registration_snippet().get(_MCP_REGISTRATION_NAME)
    if not isinstance(registration, dict):
        raise PlanRejected("the shipped MCP registration is missing or malformed")
    if _MCP_REGISTRATION_NAME in servers:
        return None, []

    rendered = json.loads(json.dumps(registration).replace("{{VAULT_PATH}}", str(root)))
    if os.name == "nt":
        rendered = json.loads(
            json.dumps(rendered).replace(".venv/bin/python", ".venv/Scripts/python.exe")
        )
    updated = dict(existing)
    updated_servers = dict(servers)
    updated_servers[_MCP_REGISTRATION_NAME] = rendered
    updated["mcpServers"] = updated_servers
    content = (json.dumps(updated, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    current = target.read_bytes() if target.exists() else None
    plan = [
        PlanEntry(
            _MCP_CONFIG_RELATIVE,
            content,
            mode=(target.stat().st_mode & 0o777) if target.exists() else 0o600,
            expected_current_sha256=(hashlib.sha256(current).hexdigest() if current else None),
            expected_absent=not target.exists(),
        )
    ]
    transaction = _transaction_preview_document(
        root,
        plan,
        purpose="mcp-registration",
        operation="mcp-registration",
    )
    preview = {
        "registration": {
            "config_path": _MCP_CONFIG_RELATIVE,
            "server_name": _MCP_REGISTRATION_NAME,
            "action": "add-only",
        },
        "writes": transaction["writes"],
    }
    return preview, plan


def build_and_preview_mcp_registration(vault_root: str | Path) -> dict[str, object]:
    """Show the exact missing Dex MCP registration before any configuration write."""
    preview, _plan = _mcp_registration_preview(vault_root)
    if preview is None:
        return _envelope(needed=False, preview=None, approval_token=None)
    return _envelope(
        needed=True,
        preview=preview,
        approval_token=hashlib.sha256(_canonical(preview)).hexdigest(),
    )


def execute_approved_mcp_registration(
    vault_root: str | Path,
    preview: Mapping[str, object],
    approved_token: str,
) -> dict[str, object]:
    """Add only the exact previewed Dex registration through one transaction."""
    try:
        expected_preview, plan = _mcp_registration_preview(vault_root)
        supplied = _canonical(dict(preview))
    except (TypeError, ValueError) as error:
        raise PlanRejected("MCP registration preview is not canonical JSON") from error
    if expected_preview is None:
        raise PlanRejected("the customization migration MCP registration is already present")
    expected = _canonical(expected_preview)
    token = hashlib.sha256(expected).hexdigest()
    if not isinstance(approved_token, str) or not hmac.compare_digest(supplied, expected) or not hmac.compare_digest(approved_token, token):
        raise PlanRejected("MCP registration approval does not match the current exact preview")
    transaction = _preview_transaction(
        vault_root,
        plan,
        purpose="mcp-registration",
        operation="mcp-registration",
    )
    executed = _execute_approved_transaction(
        vault_root,
        plan,
        purpose="mcp-registration",
        operation="mcp-registration",
        approved_token=str(transaction["approval_token"]),
    )
    return _envelope(receipt=executed["receipt"])


def deliver_and_apply_latest_release(vault_root: str | Path) -> dict[str, object]:
    """Safe v1.3 bridge: never apply a release that was not previewed."""
    del vault_root
    return _envelope(
        status="not-delivered",
        evidence={
            "status": "deprecated",
            "reason": "use-deliver-preview-execute",
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


def build_and_preview_topology_migration(
    vault_root: str | Path,
) -> dict[str, object]:
    """Detect topology and preview the one-time split without converting it."""
    topology, preview, approval_token = build_topology_migration_preview(
        Path(vault_root)
    )
    return _envelope(
        topology=topology,
        preview=preview,
        approval_token=approval_token,
    )


def execute_approved_topology_migration(
    vault_root: str | Path,
    preview: Mapping[str, object],
    approved_token: str,
) -> dict[str, object]:
    """Execute an exactly approved split and return its durable receipt."""
    receipt, receipt_path = execute_topology_migration(
        Path(vault_root),
        preview,
        approved_token,
    )
    return _envelope(receipt=receipt, receipt_path=receipt_path)


def execute_approved_rebuild_capsule(
    vault_root: str | Path,
    preview: object,
    approved_token: str,
) -> dict[str, object]:
    """Create the exact approved customization Capsule through the lifecycle door."""
    from core.customization_migration.capsule import create_capsule

    receipt = create_capsule(Path(vault_root), preview, approved_token)
    return _envelope(receipt=receipt.to_dict())


def execute_approved_rebuild_staging(
    vault_root: str | Path,
    preview: object,
    approved_token: str,
) -> dict[str, object]:
    """Stage the exact approved rebuild candidate through the lifecycle door."""
    from core.customization_migration.staging import stage_candidate

    receipt = stage_candidate(Path(vault_root), preview, approved_token)
    return _envelope(receipt=receipt.to_dict())


def execute_approved_rebuild_verification(
    vault_root: str | Path,
    capsule_id: str,
    proposal_id: str,
    report: object,
    approved_token: str,
) -> dict[str, object]:
    """Seal one exact approved verification report through the lifecycle door."""
    from core.customization_migration.staging import load_staged_candidate
    from core.customization_migration.verification import (
        VerificationError,
        VerificationReport,
        write_verification_report,
    )

    if type(report) is not VerificationReport:
        raise TypeError("report must be VerificationReport")
    _candidate, staging_receipt, _staging = load_staged_candidate(
        Path(vault_root),
        capsule_id,
        proposal_id,
    )
    expected_token = hashlib.sha256(
        _canonical(
            {
                "capsule_id": capsule_id,
                "proposal_id": proposal_id,
                "staging_receipt_sha256": hashlib.sha256(
                    staging_receipt.canonical_bytes()
                ).hexdigest(),
                "report_sha256": hashlib.sha256(
                    report.canonical_bytes()
                ).hexdigest(),
            }
        )
    ).hexdigest()
    if not isinstance(approved_token, str) or not hmac.compare_digest(
        approved_token,
        expected_token,
    ):
        raise VerificationError(
            "verification confirmation token does not match staging"
        )
    receipt = write_verification_report(
        Path(vault_root),
        capsule_id,
        proposal_id,
        report,
    )
    return _envelope(receipt=receipt.to_dict())


def execute_approved_rebuild_activation(
    vault_root: str | Path,
    preview: object,
    approved_token: str,
) -> dict[str, object]:
    """Activate the exact approved rebuild and return its rewind acknowledgement."""
    from core.customization_migration import activation

    root = Path(vault_root)
    receipt = activation.activate(root, preview, approved_token)
    return _envelope(
        receipt=receipt.to_dict(),
        rewind_acknowledgement_token=(
            activation._rewind_acknowledgement_token(receipt)
        ),
    )


def rewind_rebuild_activation_by_receipt(
    vault_root: str | Path,
    receipt: object,
    acknowledgement_token: str,
) -> dict[str, object]:
    """Rewind one rebuild activation identified by its exact receipt."""
    from core.customization_migration.activation import (
        ActivationReceipt,
        rewind,
    )

    modeled = (
        receipt
        if isinstance(receipt, ActivationReceipt)
        else ActivationReceipt.from_dict(receipt)
    )
    rewind_receipt = rewind(
        Path(vault_root),
        modeled,
        acknowledgement_token,
    )
    return _envelope(rewind_receipt=rewind_receipt.to_dict())


def abandon_rebuild_capsule(
    vault_root: str | Path,
    capsule_id: str,
) -> dict[str, object]:
    """Append one rebuild Capsule abandonment event through the lifecycle door."""
    from core.customization_migration.capsule import abandon_capsule

    abandon_capsule(Path(vault_root), capsule_id)
    return _envelope(capsule_id=capsule_id, abandoned=True)


def _rebuild_transaction_ids(root: Path) -> frozenset[str]:
    from core.transaction.engine import TX_ROOT_RELATIVE
    from core.transaction.journal import Journal, JournalCorruptError

    tx_root = root / TX_ROOT_RELATIVE
    if not tx_root.is_dir() or tx_root.is_symlink():
        return frozenset()
    transaction_ids: set[str] = set()
    for tx_dir in sorted(tx_root.iterdir(), key=lambda path: path.name):
        if not tx_dir.is_dir() or tx_dir.is_symlink():
            continue
        try:
            entries = Journal(tx_dir / "journal.jsonl").read()
        except JournalCorruptError:
            continue
        events = {entry.event for entry in entries}
        if not entries or events & {"COMMITTED", "ROLLED-BACK"}:
            continue
        begin = next((entry for entry in entries if entry.event == "BEGIN"), None)
        if begin is None or begin.payload.get("operation") != "customization-migration":
            continue
        plan = begin.payload.get("plan")
        if not isinstance(plan, list):
            continue
        relatives = (
            item.get("relative")
            for item in plan
            if isinstance(item, Mapping)
        )
        if any(
            isinstance(relative, str)
            and _REBUILD_TRANSACTION_PATH.fullmatch(relative) is not None
            for relative in relatives
        ):
            transaction_ids.add(tx_dir.name)
    return frozenset(transaction_ids)


def recover_rebuild_transactions(
    vault_root: str | Path,
) -> dict[str, object]:
    """Converge every interrupted rebuild transaction through the lifecycle door."""
    root = Path(vault_root)
    outcomes = Transaction.resume(
        root,
        transaction_ids=_rebuild_transaction_ids(root),
    )
    return _envelope(outcomes=outcomes)


__all__ = [
    "api_version",
    "build_inventory_and_plan",
    "build_and_preview_adoption",
    "execute_approved_adoption",
    "rewind_adoption_by_receipt",
    "read_lifecycle_state",
    "deliver_latest_release",
    "build_and_preview_delivered_release",
    "execute_approved_delivered_release",
    "build_and_preview_mcp_registration",
    "execute_approved_mcp_registration",
    "build_and_preview_onboarding_context",
    "execute_approved_onboarding_context",
    "deliver_and_apply_latest_release",
    "build_and_preview_conflict_resolution",
    "execute_approved_conflict_resolution",
    "build_archive_removal_preview",
    "execute_approved_archive_removal",
    "build_and_preview_topology_migration",
    "execute_approved_topology_migration",
    "execute_approved_rebuild_capsule",
    "execute_approved_rebuild_staging",
    "execute_approved_rebuild_verification",
    "execute_approved_rebuild_activation",
    "rewind_rebuild_activation_by_receipt",
    "abandon_rebuild_capsule",
    "recover_rebuild_transactions",
    "TopologyMigrationError",
]
