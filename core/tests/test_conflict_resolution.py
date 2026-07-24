"""Conflict resolution: exact choices, atomic keep-both, and free rewind."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core.lifecycle.catalog import canonical_catalog_bytes
from core.lifecycle.conflict import (
    ConflictResolutionPreviewError,
    build_conflict_resolution_preview,
)
from core.lifecycle.engine import (
    AdoptionExecutionError,
    AdoptionReceipt,
    execute_conflict_resolution,
    rewind_acknowledgement_token,
    rewind_adoption,
)
from core.lifecycle.filesystem import bounded_read
from core.lifecycle.inventory import build_inventory
from core.lifecycle.model import ReleaseCatalog
from core.lifecycle.plan import PlannedAction, build_adoption_plan
from core.tests.lifecycle_test_helpers import write_file, write_manifest
from core.tests.test_adoption_transaction import _document, _setup

CANONICAL = ".claude/skills/alpha/SKILL.md"
SIDECAR = ".claude/skills/alpha-custom/SKILL.md"
RELEASE_BYTES = b"# alpha\n"
USER_BYTES = b"# alpha\n\nMy local instructions.\n"


def _current_loader(vault: Path):
    return lambda path: bounded_read(vault, path)


def _conflicted_preview(tmp_path: Path, strategy: str):
    vault, _document_value, catalog, _inventory, _plan, release_loader = _setup(
        tmp_path, item_ids=("alpha",)
    )
    write_file(vault, CANONICAL, USER_BYTES)
    inventory = build_inventory(vault, catalog=catalog)
    plan = build_adoption_plan(catalog, inventory)
    preview = build_conflict_resolution_preview(
        catalog,
        inventory,
        plan,
        [{"item_id": "alpha", "strategy": strategy}],
        release_loader,
        _current_loader(vault),
    )
    return vault, catalog, preview, release_loader


def _non_skill_conflict(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    canonical = ".claude/commands/alpha.md"
    payloads = {"alpha": {canonical: RELEASE_BYTES}}
    manifest_bytes = write_manifest(vault, [canonical])
    document = _document(manifest_bytes, payloads)
    catalog = ReleaseCatalog.from_dict(document)
    write_file(vault, "System/.release-catalog.json", canonical_catalog_bytes(document))
    write_file(vault, canonical, RELEASE_BYTES)

    def release_loader(path: str) -> bytes:
        return payloads["alpha"][path]

    write_file(vault, canonical, USER_BYTES)
    inventory = build_inventory(vault, catalog=catalog)
    plan = build_adoption_plan(catalog, inventory)
    return vault, catalog, inventory, plan, release_loader, canonical


def test_take_theirs_writes_release_and_rewind_restores_user_edit(tmp_path: Path) -> None:
    vault, _catalog, preview, release_loader = _conflicted_preview(
        tmp_path, "take-theirs"
    )

    receipt = execute_conflict_resolution(
        vault,
        preview,
        preview.sha256,
        release_loader,
        _current_loader(vault),
    )

    assert isinstance(receipt, AdoptionReceipt)
    assert (vault / CANONICAL).read_bytes() == RELEASE_BYTES
    assert receipt.items_adopted == ("alpha",)
    assert [
        (entry.item_id, entry.path, entry.sha256, entry.byte_size)
        for entry in receipt.files_written
    ] == [
        (
            "alpha",
            CANONICAL,
            hashlib.sha256(RELEASE_BYTES).hexdigest(),
            len(RELEASE_BYTES),
        )
    ]
    rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))
    assert (vault / CANONICAL).read_bytes() == USER_BYTES


def test_keep_both_writes_sidecar_and_rewind_removes_it(tmp_path: Path) -> None:
    vault, _catalog, preview, release_loader = _conflicted_preview(
        tmp_path, "keep-both"
    )

    receipt = execute_conflict_resolution(
        vault,
        preview,
        preview.sha256,
        release_loader,
        _current_loader(vault),
    )

    assert (vault / CANONICAL).read_bytes() == RELEASE_BYTES
    assert (vault / SIDECAR).read_bytes() == USER_BYTES
    assert [entry.path for entry in receipt.files_written] == sorted(
        [CANONICAL, SIDECAR]
    )

    rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))
    assert (vault / CANONICAL).read_bytes() == USER_BYTES
    assert not (vault / SIDECAR).exists()


def test_keep_both_refuses_existing_sidecar_without_partial_write(tmp_path: Path) -> None:
    vault, _catalog, preview, release_loader = _conflicted_preview(
        tmp_path, "keep-both"
    )
    existing_sidecar = b"# existing custom skill\n"
    write_file(vault, SIDECAR, existing_sidecar)

    with pytest.raises(AdoptionExecutionError, match=r"already have.*alpha-custom"):
        execute_conflict_resolution(
            vault,
            preview,
            preview.sha256,
            release_loader,
            _current_loader(vault),
        )

    assert (vault / CANONICAL).read_bytes() == USER_BYTES
    assert (vault / SIDECAR).read_bytes() == existing_sidecar


def test_execute_refuses_drift_after_preview_without_writing(tmp_path: Path) -> None:
    vault, _catalog, preview, release_loader = _conflicted_preview(
        tmp_path, "keep-both"
    )
    drifted = b"# changed again after preview\n"
    write_file(vault, CANONICAL, drifted)

    with pytest.raises(AdoptionExecutionError, match="inventory changed"):
        execute_conflict_resolution(
            vault,
            preview,
            preview.sha256,
            release_loader,
            _current_loader(vault),
        )

    assert (vault / CANONICAL).read_bytes() == drifted
    assert not (vault / SIDECAR).exists()


def test_preview_refuses_non_conflict_item(tmp_path: Path) -> None:
    _vault, _document_value, catalog, inventory, plan, release_loader = _setup(
        tmp_path, item_ids=("alpha",)
    )

    with pytest.raises(ConflictResolutionPreviewError, match=r"alpha.*adopt.*conflict"):
        build_conflict_resolution_preview(
            catalog,
            inventory,
            plan,
            [{"item_id": "alpha", "strategy": "take-theirs"}],
            release_loader,
            lambda _path: b"unused",
        )


def test_keep_both_refuses_non_skill_conflict_but_take_theirs_succeeds(
    tmp_path: Path,
) -> None:
    vault, catalog, inventory, plan, release_loader, canonical = _non_skill_conflict(
        tmp_path
    )

    with pytest.raises(ConflictResolutionPreviewError, match="skills-only"):
        build_conflict_resolution_preview(
            catalog,
            inventory,
            plan,
            [{"item_id": "alpha", "strategy": "keep-both"}],
            release_loader,
            _current_loader(vault),
        )

    preview = build_conflict_resolution_preview(
        catalog,
        inventory,
        plan,
        [{"item_id": "alpha", "strategy": "take-theirs"}],
        release_loader,
        _current_loader(vault),
    )
    execute_conflict_resolution(
        vault,
        preview,
        preview.sha256,
        release_loader,
        _current_loader(vault),
    )
    assert (vault / canonical).read_bytes() == RELEASE_BYTES


def test_deleted_shipped_file_is_adoptable_not_a_conflict(
    tmp_path: Path,
) -> None:
    """A deleted shipped file is restored by normal adoption, not conflict
    resolution. Conflict resolution is scoped to edited-in-place (stock-modified)
    files, so it refuses a non-conflict item."""
    vault, _document_value, catalog, _inventory, _plan, release_loader = _setup(
        tmp_path, item_ids=("alpha",)
    )
    (vault / CANONICAL).unlink()
    inventory = build_inventory(vault, catalog=catalog)
    plan = build_adoption_plan(catalog, inventory)
    # Deletion of a shipped (brain) file is re-adoptable, not a conflict.
    assert plan.items[0].action is PlannedAction.ADOPT

    for strategy in ("take-theirs", "keep-both"):
        with pytest.raises(ConflictResolutionPreviewError, match="only conflict"):
            build_conflict_resolution_preview(
                catalog,
                inventory,
                plan,
                [{"item_id": "alpha", "strategy": strategy}],
                release_loader,
                _current_loader(vault),
            )


def test_approval_token_mismatch_refuses_without_writing(tmp_path: Path) -> None:
    vault, _catalog, preview, release_loader = _conflicted_preview(
        tmp_path, "take-theirs"
    )

    with pytest.raises(AdoptionExecutionError, match="approval token"):
        execute_conflict_resolution(
            vault,
            preview,
            "0" * 64,
            release_loader,
            _current_loader(vault),
        )

    assert (vault / CANONICAL).read_bytes() == USER_BYTES
