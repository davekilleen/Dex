"""D-GATE: one hostile-vault adoption journey with observed-write proof."""

from __future__ import annotations

import hashlib
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from core.lifecycle.catalog import (
    CatalogError,
    canonical_catalog_bytes,
    load_catalog,
    with_catalog_identity,
)
from core.lifecycle.engine import (
    execute_adoption,
    rewind_acknowledgement_token,
    rewind_adoption,
)
from core.lifecycle.inventory import build_inventory
from core.lifecycle.ledger import (
    LedgerError,
    project_state,
    read_events,
    record_holdback,
    register_install,
    repair_state,
)
from core.lifecycle.model import AdoptionState, ReleaseCatalog
from core.lifecycle.plan import build_adoption_plan
from core.lifecycle.preview import build_adoption_preview
from core.lifecycle.sqlite_snapshot import detect_sync_folder
from core.tests.vault_observed_writes import (
    assert_observed_writes,
    snapshot_vault,
)
from core.transaction.engine import PlanEntry, PlanRejected, Transaction
from core.transaction.snapshot import SnapshotError
from core.utils import doctor

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
SOURCE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
CATALOG_PATH = "System/.release-catalog.json"
LEGACY_CATALOG_PATH = "core/lifecycle/catalog/release.json"

PAYLOADS = {
    "linked-dir": b"# must not traverse a linked directory\n",
    "modified-stock": b"# release-owned stock\n",
    "safe-new": b"# safely adopted\nOwner: journey@example.com\n",
    "symlink-file": b"# must not replace a symlink\n",
    "user-wins": b"# catalog seed that must not replace user content\n",
}

_INTERRUPTED_WORKER = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from core.transaction.engine import PlanEntry, Transaction
vault = Path(sys.argv[1])
manifest = (vault / "System/.installed-files.manifest").read_bytes()
Transaction.begin(
    vault,
    [PlanEntry("System/.installed-files.manifest", manifest + b"interrupted-only\n")],
).run()
"""


def _write(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def _catalog_document(manifest: bytes) -> dict[str, object]:
    items = []
    for item_id, content in sorted(PAYLOADS.items()):
        path = f".claude/skills/{item_id}/SKILL.md"
        items.append(
            {
                "id": item_id,
                "kind": "skill",
                "version": "1.0.0",
                "files": [
                    {
                        "path": path,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "ownership_class": "brain",
                    }
                ],
                "dependencies": [],
                "capabilities": [],
                "rewind": {
                    "acknowledgement_required": True,
                    "token": f"rewind:{item_id}@1.0.0",
                },
            }
        )
    return with_catalog_identity(
        {
            "catalog_version": 1,
            "release": {
                "version": "1.67.0",
                "channel": "release",
                "immutable_distribution_tag": "dist/release/v1.67.0-0123456",
                "source_commit": SOURCE_COMMIT,
                "manifest": {
                    "path": "System/.installed-files.manifest",
                    "sha256": hashlib.sha256(manifest).hexdigest(),
                },
            },
            "items": items,
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )


def _hostile_vault(tmp_path: Path) -> tuple[Path, Path, ReleaseCatalog, bytes, Path, bytes]:
    sync_root = tmp_path / "Dropbox"
    (sync_root / ".dropbox").mkdir(parents=True)
    vault = sync_root / "Dex Vault – hostile"
    vault.mkdir(parents=True)
    outside = tmp_path / "outside-linked-skills"
    outside.mkdir()

    manifest_paths = sorted(
        f".claude/skills/{item_id}/SKILL.md" for item_id in PAYLOADS
    )
    manifest = "".join(f"{path}\n" for path in manifest_paths).encode()
    document = _catalog_document(manifest)
    catalog = ReleaseCatalog.from_dict(document)
    _write(vault / "System/.installed-files.manifest", manifest)
    _write(vault / CATALOG_PATH, canonical_catalog_bytes(document))
    _write(vault / LEGACY_CATALOG_PATH, b'{"catalog_version":')

    # Broken folder map: inventory must report UNKNOWN rather than guess.
    _write(vault / "System/folder-paths.yaml", b"projects: [not-a-flat-path]\n")

    # Two different user-owned conflicts: edited stock and a user-created file
    # at a path a catalog item wants. Both byte sequences must win.
    _write(
        vault / ".claude/skills/modified-stock/SKILL.md",
        b"# user's edited stock; preserve exactly\n",
        0o600,
    )
    _write(
        vault / ".claude/skills/user-wins/SKILL.md",
        b"# user's independently-created skill; preserve exactly\n",
    )

    # A catalog file replaced by a symlink and a catalog parent replaced by a
    # directory symlink. Neither target may be followed or replaced.
    symlink_source = vault / "00-Inbox/linked source.md"
    _write(symlink_source, b"linked source stays unchanged\n")
    file_link = vault / ".claude/skills/symlink-file/SKILL.md"
    file_link.parent.mkdir(parents=True)
    os.symlink(symlink_source, file_link)
    _write(outside / "SKILL.md", b"outside directory target stays unchanged\n")
    os.symlink(outside, vault / ".claude/skills/linked-dir")

    # Unicode, spaces, case-collision-prone names, zero bytes, and a seeded
    # few-megabyte file keep the fixture deterministic on every filesystem.
    _write(vault / "00-Inbox/naïve café – 東京 notes.md", "Olá 東京\n".encode())
    _write(vault / "00-Inbox/Case Collision Prone.md", b"upper\n")
    lower_case = vault / "00-Inbox/case collision prone.md"
    if not lower_case.exists():
        _write(lower_case, b"lower\n")
    _write(vault / "04-Resources/zero byte.bin", b"")
    seeded = random.Random(17_067)
    _write(vault / "04-Resources/huge-ish deterministic.bin", seeded.randbytes(3 << 20))

    # Stay near (but below) macOS's practical path limit without oversized
    # individual components.
    deep = vault / "04-Resources" / "near macOS path limit"
    depth = 0
    while len(os.fsencode(deep / "deep payload.md")) < 860:
        deep /= f"segment {depth:02d} – abcdefghijklmnopqrstuvwxyz"
        depth += 1
    _write(deep / "deep payload.md", b"deep and deterministic\n")

    # D1 hostile state: a committed historical event is tampered while the
    # valid terminal event's commitment is missing.
    register_install(vault, UUID("12345678-1234-4678-9234-567812345678"))
    record_holdback(vault, "legacy-item")
    first_event = vault / "System/.dex/ledger/events/00000001-install-registered.json"
    original_first_event = first_event.read_bytes()
    first_event.write_bytes(
        original_first_event.replace(b'"ledger_version":1', b'"ledger_version":9', 1)
    )
    (vault / "System/.dex/ledger/commitments/00000002.sha256").unlink()

    # Crash after BEGIN: the journal is interrupted but user-visible bytes have
    # not changed. Doctor must surface it and resume must converge it.
    process = subprocess.run(
        [sys.executable, "-c", _INTERRUPTED_WORKER, str(vault), str(REPO_ROOT)],
        env={**os.environ, "DEX_TX_TEST_STOP_AFTER": "after-begin"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert process.returncode == 137, process.stderr[-500:]
    return vault, outside, catalog, manifest, first_event, original_first_event


def _doctor_context(vault: Path, tmp_path: Path) -> doctor.DoctorContext:
    return doctor.DoctorContext(vault, vault, tmp_path / "home", NOW)


def _action_map(plan) -> dict[str, str]:
    return {item.item_id: item.action.value for item in plan.items}


def _created_ancestors(path: str, before: dict[str, object]) -> set[str]:
    ancestors: set[str] = set()
    current = Path(path).parent
    while current.as_posix() != ".":
        relative = current.as_posix()
        if relative not in before:
            ancestors.add(relative)
        current = current.parent
    return ancestors


def _transaction_paths(tx_id: str, *, writes_payload: bool, snapshot_blob: bool) -> set[str]:
    root = f"System/.dex/tx/{tx_id}"
    paths = {
        root,
        f"{root}/journal.jsonl",
        f"{root}/snapshot",
        f"{root}/snapshot/manifest.json",
        f"{root}/staged",
    }
    if writes_payload:
        paths.add(f"{root}/staged/000000.bin")
    if snapshot_blob:
        paths.add(f"{root}/snapshot/000000.bin")
    return paths


def test_messy_vault_adoption_journey(tmp_path: Path) -> None:
    vault, outside, catalog, manifest, first_event, original_first_event = _hostile_vault(
        tmp_path
    )
    outside_before = snapshot_vault(outside)

    # INVENTORY: without an explicit authority, the valid canonical catalog
    # and corrupt legacy candidate are ambiguous. The loader picks neither.
    before_inventory = snapshot_vault(vault)
    ambiguous = build_inventory(vault)
    assert ambiguous.baseline.identity_state == "MANIFEST_ONLY"
    assert ambiguous.baseline.errors == (
        "multiple installed release catalogs are present; identity is ambiguous",
    )
    assert load_catalog(vault / CATALOG_PATH, release_root=vault) == catalog
    with pytest.raises(CatalogError, match=r"UNKNOWN.*JSON cannot be parsed"):
        load_catalog(vault / LEGACY_CATALOG_PATH, release_root=vault)

    inventory = build_inventory(vault, catalog=catalog)
    assert inventory.baseline.identity_state == "VERIFIED"
    assert inventory.folder_map.state == "UNKNOWN"
    assert any("flat scalar" in error or "path must be" in error for error in inventory.errors)
    kinds = {entry.actual_path: entry.kind for entry in inventory.entries}
    assert kinds[".claude/skills/symlink-file/SKILL.md"] == "symlink"
    assert kinds[".claude/skills/linked-dir"] == "symlink"
    assert any(entry.actual_path.endswith("deep payload.md") for entry in inventory.entries)
    assert detect_sync_folder(vault) == "Dropbox"
    assert (vault / "04-Resources/zero byte.bin").stat().st_size == 0
    assert (vault / "04-Resources/huge-ish deterministic.bin").stat().st_size == 3 << 20
    assert_observed_writes(before_inventory, snapshot_vault(vault), set())

    before_transaction_refusal = snapshot_vault(vault)
    with pytest.raises(PlanRejected, match="symlinked parent"):
        Transaction.begin(
            vault,
            [
                PlanEntry(
                    ".claude/skills/linked-dir/SKILL.md",
                    b"transaction must never reach outside the vault\n",
                )
            ],
        ).run()
    assert_observed_writes(before_transaction_refusal, snapshot_vault(vault), set())
    assert snapshot_vault(outside) == outside_before

    # PLAN: only the genuinely absent path is adoptable. User bytes and both
    # symlink attacks are withheld from writes.
    before_plan = snapshot_vault(vault)
    plan = build_adoption_plan(catalog, inventory)
    assert _action_map(plan) == {
        "linked-dir": "unknown",
        "modified-stock": "conflict",
        "safe-new": "adopt",
        "symlink-file": "unknown",
        "user-wins": "conflict",
    }
    assert_observed_writes(before_plan, snapshot_vault(vault), set())

    # DOCTOR first refuses the tampered ledger exactly; repairing while the
    # committed event is still changed also refuses per D1.
    context = _doctor_context(vault, tmp_path)
    before_refusals = snapshot_vault(vault)
    refused = doctor.collect_adoption_report(context)
    assert refused.verdict == "UNKNOWN"
    recovery = refused.groups[3]
    assert recovery.ledger is not None
    assert "integrity hash" in recovery.ledger.detail or "unsupported ledger" in recovery.ledger.detail
    with pytest.raises(LedgerError, match=r"integrity hash|unsupported ledger"):
        repair_state(vault)
    assert_observed_writes(before_refusals, snapshot_vault(vault), set())

    # Restore the known event bytes, leaving only the valid missing terminal
    # commitment. D1 may now heal that incomplete publication. Resume then
    # rolls back the BEGIN-only transaction and is idempotent.
    before_recovery = snapshot_vault(vault)
    first_event.write_bytes(original_first_event)
    _state, repair_actions = repair_state(vault)
    assert repair_actions == ("completed publication commitment for valid event 2",)
    outcomes = Transaction.resume(vault)
    assert len(outcomes) == 1
    assert outcomes[0]["resumed"] is True
    assert outcomes[0]["committed"] is False
    assert Transaction.resume(vault) == []
    after_recovery = snapshot_vault(vault)
    interrupted_tx = outcomes[0]["tx_id"]
    assert_observed_writes(
        before_recovery,
        after_recovery,
        {
            "System/.dex/ledger/events/00000001-install-registered.json",
            "System/.dex/ledger/commitments/00000002.sha256",
            "System/.dex/mutation.lock",
            f"System/.dex/tx/{interrupted_tx}/journal.jsonl",
        },
    )
    assert (vault / "System/.installed-files.manifest").read_bytes() == manifest

    # The complete five-group collector now exposes safe, review, preserved,
    # recovery, and receipt authority without performing another write.
    before_doctor = snapshot_vault(vault)
    report = doctor.collect_adoption_report(context)
    assert_observed_writes(before_doctor, snapshot_vault(vault), set())
    assert [group.id for group in report.groups] == list(doctor.ADOPTION_GROUP_IDS)
    assert report.verdict == "UNKNOWN"
    assert report.groups[1].verdict == "UNKNOWN"
    assert [item.item_id for item in report.groups[0].items] == ["safe-new"]
    assert {item.item_id for item in report.groups[1].items} == {
        "linked-dir",
        "modified-stock",
        "symlink-file",
        "user-wins",
    }
    assert [item.item_id for item in report.groups[2].held_back_items] == ["legacy-item"]
    assert report.groups[3].count == 0
    assert report.groups[4].count == 0

    # PREVIEW + ADOPT: the approved preview names one file. The complete vault
    # diff must equal the target plus transaction, receipt, and ledger evidence
    # that the returned receipt identifies.
    before_preview = snapshot_vault(vault)
    preview = build_adoption_preview(
        catalog,
        inventory,
        plan,
        ("safe-new",),
        lambda path: PAYLOADS[path.split("/")[-2]],
    )
    assert [write.path for write in preview.items[0].writes] == [
        ".claude/skills/safe-new/SKILL.md"
    ]
    assert_observed_writes(before_preview, snapshot_vault(vault), set())
    before_adoption = snapshot_vault(vault)
    receipt = execute_adoption(
        vault,
        preview,
        preview.sha256,
        lambda path: PAYLOADS[path.split("/")[-2]],
    )
    after_adoption = snapshot_vault(vault)
    target = receipt.files_written[0].path
    declared_adoption = {
        target,
        f"System/.dex/adoptions/{receipt.transaction_id}.receipt.json",
        "System/.dex/ledger/events/00000003-adoption-recorded.json",
        "System/.dex/ledger/commitments/00000003.sha256",
        "System/.dex/ledger/state.json",
    }
    declared_adoption |= _created_ancestors(target, before_adoption)
    declared_adoption |= _created_ancestors(
        f"System/.dex/adoptions/{receipt.transaction_id}.receipt.json",
        before_adoption,
    )
    declared_adoption |= _transaction_paths(
        receipt.transaction_id,
        writes_payload=True,
        snapshot_blob=False,
    )
    assert_observed_writes(before_adoption, after_adoption, declared_adoption)
    adoption_event = read_events(vault)[-1]
    assert adoption_event["event_type"] == "adoption-recorded"
    assert adoption_event["payload"]["receipt"] == receipt.to_dict()

    # EFFECTIVE BEHAVIOR: bytes are live, the ledger makes the item adopted,
    # replanning suppresses a second adoption, and Doctor shows a rewindable receipt.
    before_effective_verification = snapshot_vault(vault)
    assert (vault / target).read_bytes() == PAYLOADS["safe-new"]
    state = project_state(vault)
    assert state["adopted"]["safe-new"]["tx_id"] == receipt.transaction_id
    adopted_plan = build_adoption_plan(
        catalog,
        build_inventory(vault, catalog=catalog),
        adoption_states={"safe-new": AdoptionState.ADOPTED},
    )
    assert _action_map(adopted_plan)["safe-new"] == "already-adopted"
    adopted_report = doctor.collect_adoption_report(context)
    assert adopted_report.groups[4].count == 1
    assert adopted_report.groups[4].receipts[0].rewindable is True
    assert_observed_writes(
        before_effective_verification,
        snapshot_vault(vault),
        set(),
    )

    # REWIND: one item returns to exact absence through another transaction.
    # Again, no path outside the receipt-derived set may change.
    before_rewind = snapshot_vault(vault)
    rewind = rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))
    after_rewind = snapshot_vault(vault)
    assert [(entry.item_id, entry.path, entry.existed_before_adoption) for entry in rewind.files_restored] == [
        ("safe-new", target, False)
    ]
    declared_rewind = {
        target,
        "System/.dex/ledger/events/00000004-rewind-recorded.json",
        "System/.dex/ledger/commitments/00000004.sha256",
        "System/.dex/ledger/state.json",
    }
    declared_rewind |= _transaction_paths(
        rewind.rewind_transaction_id,
        writes_payload=False,
        snapshot_blob=True,
    )
    assert_observed_writes(before_rewind, after_rewind, declared_rewind)
    rewind_event = read_events(vault)[-1]
    assert rewind_event["event_type"] == "rewind-recorded"
    assert rewind_event["payload"]["receipt"] == rewind.to_dict()
    assert not (vault / target).exists()

    # LEDGER VERIFY + E5: the full chain verifies, the item is no longer
    # adopted, and even the symlink targets outside the vault are byte-identical.
    before_ledger_verification = snapshot_vault(vault)
    events = read_events(vault)
    assert [event["event_type"] for event in events] == [
        "install-registered",
        "holdback-recorded",
        "adoption-recorded",
        "rewind-recorded",
    ]
    assert project_state(vault)["adopted"] == {}
    assert snapshot_vault(outside) == outside_before
    assert (vault / ".claude/skills/modified-stock/SKILL.md").read_bytes() == (
        b"# user's edited stock; preserve exactly\n"
    )
    assert (vault / ".claude/skills/user-wins/SKILL.md").read_bytes() == (
        b"# user's independently-created skill; preserve exactly\n"
    )
    assert (outside / "SKILL.md").read_bytes() == b"outside directory target stays unchanged\n"
    assert_observed_writes(
        before_ledger_verification,
        snapshot_vault(vault),
        set(),
    )

    # Recovery must apply the same ancestor rule. Simulate a parent becoming a
    # symlink after snapshot/apply but before rollback; resume may refuse, but
    # it must never restore bytes through that link into another directory.
    recovery_vault = tmp_path / "recovery-vault"
    recovery_target = recovery_vault / ".claude/skills/recovery-race/SKILL.md"
    _write(recovery_target, b"original recovery bytes\n")
    transaction = Transaction.begin(
        recovery_vault,
        [
            PlanEntry(
                ".claude/skills/recovery-race/SKILL.md",
                b"applied before interrupted rollback\n",
            )
        ],
    )
    transaction._snapshot_phase()
    transaction._apply_phase()
    real_parent = tmp_path / "detached-real-parent"
    recovery_target.parent.rename(real_parent)
    recovery_outside = tmp_path / "recovery-outside"
    recovery_outside.mkdir()
    _write(recovery_outside / "SKILL.md", b"outside recovery sentinel\n")
    os.symlink(recovery_outside, recovery_target.parent)

    with pytest.raises(SnapshotError, match="symlinked parent"):
        transaction.rollback()
    assert (recovery_outside / "SKILL.md").read_bytes() == b"outside recovery sentinel\n"
