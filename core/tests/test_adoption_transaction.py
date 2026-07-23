"""C1 catalog adoption: approved previews, one transaction, exact recovery."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from core import portable_contract
from core.lifecycle.catalog import canonical_catalog_bytes, with_catalog_identity
from core.lifecycle.engine import (
    AdoptionExecutionError,
    AdoptionReceipt,
    canonical_adoption_receipt_bytes,
    execute_adoption,
)
from core.lifecycle.inventory import build_inventory
from core.lifecycle.model import ReleaseCatalog
from core.lifecycle.plan import build_adoption_plan
from core.lifecycle.preview import (
    AdoptionPreview,
    AdoptionPreviewError,
    build_adoption_preview,
    canonical_adoption_preview_bytes,
)
from core.tests.lifecycle_test_helpers import SOURCE_COMMIT, write_file, write_manifest
from core.transaction.engine import Transaction

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = "System/.release-catalog.json"


def _document(manifest: bytes, payloads: dict[str, dict[str, bytes]]) -> dict[str, object]:
    items = []
    for item_id, files in sorted(payloads.items()):
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
                    for path, content in sorted(files.items())
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
                "version": "1.64.0",
                "channel": "release",
                "immutable_distribution_tag": "dist/release/v1.64.0-0123456",
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


def _setup(tmp_path: Path, item_ids: tuple[str, ...] = ("alpha", "beta")):
    vault = tmp_path / "vault"
    vault.mkdir()
    payloads = {
        item_id: {
            f".claude/skills/{item_id}/SKILL.md": f"# {item_id}\n".encode()
        }
        for item_id in item_ids
    }
    paths = [path for files in payloads.values() for path in files]
    manifest = write_manifest(vault, paths)
    document = _document(manifest, payloads)
    catalog = ReleaseCatalog.from_dict(document)
    write_file(vault, CATALOG_PATH, canonical_catalog_bytes(document))
    flat_payloads = {
        path: content for files in payloads.values() for path, content in files.items()
    }
    for path, content in flat_payloads.items():
        write_file(vault, path, content)
    inventory = build_inventory(vault, catalog=catalog)
    plan = build_adoption_plan(catalog, inventory)

    def loader(path: str) -> bytes:
        return flat_payloads[path]

    return vault, document, catalog, inventory, plan, loader


def _preview(tmp_path: Path, requested: tuple[str, ...] = ("alpha",)):
    vault, document, catalog, inventory, plan, loader = _setup(tmp_path)
    preview = build_adoption_preview(
        catalog,
        inventory,
        plan,
        requested,
        loader,
    )
    return vault, document, preview, loader


def _tx_directories(vault: Path) -> list[Path]:
    tx_root = vault / "System/.dex/tx"
    return sorted(path for path in tx_root.iterdir() if path.is_dir()) if tx_root.exists() else []


def test_preview_is_canonical_payload_bound_and_requested_order_independent(
    tmp_path: Path,
) -> None:
    vault, _document_value, catalog, inventory, plan, loader = _setup(tmp_path)
    calls: list[str] = []

    def recording_loader(path: str) -> bytes:
        calls.append(path)
        return loader(path)

    reversed_preview = build_adoption_preview(
        catalog, inventory, plan, ("beta", "alpha"), recording_loader
    )
    ordered_preview = build_adoption_preview(
        catalog, inventory, plan, ("alpha", "beta"), loader
    )

    assert reversed_preview == ordered_preview
    assert canonical_adoption_preview_bytes(reversed_preview) == (
        canonical_adoption_preview_bytes(ordered_preview)
    )
    assert reversed_preview.sha256 == hashlib.sha256(
        canonical_adoption_preview_bytes(reversed_preview)
    ).hexdigest()
    assert calls == [
        ".claude/skills/alpha/SKILL.md",
        ".claude/skills/beta/SKILL.md",
    ]
    assert AdoptionPreview.from_dict(reversed_preview.to_dict()) == reversed_preview
    assert vault.is_dir()


def test_preview_rejects_non_adopt_item_and_names_its_action(tmp_path: Path) -> None:
    vault, _document_value, catalog, _inventory, _plan, loader = _setup(tmp_path)
    write_file(vault, ".claude/skills/beta/SKILL.md", b"user changed this\n")
    inventory = build_inventory(vault, catalog=catalog)
    plan = build_adoption_plan(catalog, inventory)

    with pytest.raises(AdoptionPreviewError, match=r"beta.*conflict"):
        build_adoption_preview(catalog, inventory, plan, ("beta",), loader)


def test_preview_refuses_payload_bytes_that_do_not_match_catalog(tmp_path: Path) -> None:
    _vault, _document_value, catalog, inventory, plan, _loader = _setup(tmp_path)

    with pytest.raises(AdoptionPreviewError, match=r"alpha.*payload.*sha256"):
        build_adoption_preview(
            catalog,
            inventory,
            plan,
            ("alpha",),
            lambda _path: b"substituted bytes\n",
        )


def test_single_item_happy_path_returns_exact_rewind_receipt(tmp_path: Path) -> None:
    vault, _document_value, preview, loader = _preview(tmp_path)
    target = vault / ".claude/skills/alpha/SKILL.md"
    os.chmod(target, 0o600)

    receipt = execute_adoption(vault, preview, preview.sha256, loader)

    assert receipt.items_adopted == ("alpha",)
    assert [(entry.path, entry.sha256, entry.byte_size) for entry in receipt.files_written] == [
        (
            ".claude/skills/alpha/SKILL.md",
            hashlib.sha256(b"# alpha\n").hexdigest(),
            len(b"# alpha\n"),
        )
    ]
    assert receipt.catalog_sha256 == preview.catalog_sha256
    assert receipt.inventory_sha256 == preview.inventory_sha256
    assert receipt.preview_sha256 == preview.sha256
    assert receipt.transaction_id
    assert receipt.snapshot_ref == (
        f"System/.dex/tx/{receipt.transaction_id}/snapshot"
    )
    snapshot = vault / receipt.snapshot_ref
    assert snapshot.is_dir()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["relative"] for entry in manifest["entries"]] == [
        ".claude/skills/alpha/SKILL.md"
    ]
    # PreviewWrite documents this fixed, intentionally token-independent side effect.
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_multi_item_happy_path_uses_one_transaction_and_sorted_writes(
    tmp_path: Path,
) -> None:
    vault, _document_value, catalog, inventory, plan, loader = _setup(tmp_path)
    preview = build_adoption_preview(
        catalog, inventory, plan, ("beta", "alpha"), loader
    )

    receipt = execute_adoption(vault, preview, preview.sha256, loader)

    assert receipt.items_adopted == ("alpha", "beta")
    assert [entry.path for entry in receipt.files_written] == [
        ".claude/skills/alpha/SKILL.md",
        ".claude/skills/beta/SKILL.md",
    ]
    assert len(_tx_directories(vault)) == 1


def test_wrong_approval_token_refuses_before_payload_or_transaction_write(
    tmp_path: Path,
) -> None:
    vault, _document_value, preview, _loader = _preview(tmp_path)
    calls: list[str] = []

    with pytest.raises(AdoptionExecutionError, match="approval token"):
        execute_adoption(
            vault,
            preview,
            "0" * 64,
            lambda path: calls.append(path) or b"never",
        )

    assert calls == []
    assert _tx_directories(vault) == []


def test_self_consistent_but_stale_preview_refuses_on_inventory_rebuild(
    tmp_path: Path,
) -> None:
    vault, _document_value, preview, loader = _preview(tmp_path)
    forged_raw = preview.to_dict()
    forged_raw["inventory_sha256"] = "f" * 64
    forged = AdoptionPreview.from_dict(forged_raw)

    with pytest.raises(AdoptionExecutionError, match="inventory changed since preview"):
        execute_adoption(vault, forged, forged.sha256, loader)

    assert _tx_directories(vault) == []


def test_requested_file_drift_changes_plan_and_refuses_without_transaction_write(
    tmp_path: Path,
) -> None:
    vault, _document_value, preview, loader = _preview(tmp_path)
    write_file(vault, ".claude/skills/alpha/SKILL.md", b"changed after approval\n")

    with pytest.raises(
        AdoptionExecutionError,
        match=r"alpha.*action changed.*conflict",
    ):
        execute_adoption(vault, preview, preview.sha256, loader)

    assert _tx_directories(vault) == []
    assert (vault / ".claude/skills/alpha/SKILL.md").read_bytes() == (
        b"changed after approval\n"
    )


def test_drift_after_rebuild_is_detected_from_snapshot_and_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.lifecycle import engine as adoption_engine

    vault, _document_value, preview, loader = _preview(tmp_path)
    target = vault / ".claude/skills/alpha/SKILL.md"
    real_begin = Transaction.begin

    def begin_then_race(vault_root: Path, entries):
        transaction = real_begin(vault_root, entries)
        target.write_bytes(b"external writer won the race\n")
        return transaction

    monkeypatch.setattr(adoption_engine.Transaction, "begin", begin_then_race)

    with pytest.raises(AdoptionExecutionError, match="changed after final preview rebuild"):
        execute_adoption(vault, preview, preview.sha256, loader)

    assert target.read_bytes() == b"external writer won the race\n"
    transaction_dir = _tx_directories(vault)[0]
    events = (transaction_dir / "journal.jsonl").read_text(encoding="utf-8")
    assert '"event":"ROLLED-BACK"' in events


def test_post_snapshot_writer_is_currently_overwritten_and_adoption_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pin the residual window documented by verify_approval_binding.

    Together with the pre-snapshot drift test above, this makes moving either
    boundary require an explicit test and documentation update.
    """
    from core.transaction import engine as transaction_engine

    vault, _document_value, preview, loader = _preview(tmp_path)
    target = vault / ".claude/skills/alpha/SKILL.md"
    race_was_injected = False

    def inject_writer_at_test_seam(seam: str) -> None:
        nonlocal race_was_injected
        if seam == "after-snapshot":
            target.write_bytes(b"saved after snapshot capture\n")
            race_was_injected = True

    monkeypatch.setattr(transaction_engine, "_stop_seam", inject_writer_at_test_seam)

    receipt = execute_adoption(vault, preview, preview.sha256, loader)

    assert race_was_injected is True
    assert target.read_bytes() == b"# alpha\n"
    transaction_dir = vault / receipt.snapshot_ref
    assert transaction_dir.is_dir()
    events = (transaction_dir.parent / "journal.jsonl").read_text(encoding="utf-8")
    assert '"event":"COMMITTED"' in events
    assert '"event":"ROLLED-BACK"' not in events


def test_catalog_identity_drift_refuses_without_transaction_write(tmp_path: Path) -> None:
    vault, document, preview, loader = _preview(tmp_path)
    changed = json.loads(json.dumps(document))
    changed["release"]["version"] = "1.64.1"
    changed["release"]["immutable_distribution_tag"] = "dist/release/v1.64.1-0123456"
    changed = with_catalog_identity(changed)
    write_file(vault, CATALOG_PATH, canonical_catalog_bytes(changed))

    with pytest.raises(AdoptionExecutionError, match="catalog changed since preview"):
        execute_adoption(vault, preview, preview.sha256, loader)

    assert _tx_directories(vault) == []


def test_e6_non_requested_item_state_does_not_change_preview_or_execution(
    tmp_path: Path,
) -> None:
    vault, _document_value, catalog, inventory, plan, loader = _setup(tmp_path)
    before = build_adoption_preview(catalog, inventory, plan, ("alpha",), loader)
    write_file(vault, ".claude/skills/beta/SKILL.md", b"beta held back elsewhere\n")
    after_inventory = build_inventory(vault, catalog=catalog)
    after_plan = build_adoption_plan(catalog, after_inventory, held_back={"beta"})
    after = build_adoption_preview(
        catalog, after_inventory, after_plan, ("alpha",), loader
    )

    assert canonical_adoption_preview_bytes(after) == canonical_adoption_preview_bytes(before)
    receipt = execute_adoption(vault, before, before.sha256, loader)
    assert receipt.items_adopted == ("alpha",)
    assert (vault / ".claude/skills/beta/SKILL.md").read_bytes() == (
        b"beta held back elsewhere\n"
    )


def test_e6_execution_does_not_hash_non_requested_item_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.lifecycle import inventory as inventory_module

    vault, _document_value, catalog, inventory, plan, loader = _setup(tmp_path)
    preview = build_adoption_preview(catalog, inventory, plan, ("alpha",), loader)
    original_sha256_file = inventory_module.sha256_file

    def requested_only(root: Path, relative: str, *, max_bytes: int) -> str:
        if relative == ".claude/skills/beta/SKILL.md":
            raise AssertionError("execution read a non-requested item payload")
        return original_sha256_file(root, relative, max_bytes=max_bytes)

    monkeypatch.setattr(inventory_module, "sha256_file", requested_only)

    receipt = execute_adoption(vault, preview, preview.sha256, loader)

    assert receipt.items_adopted == ("alpha",)


def test_contract_refusal_aborts_the_whole_adoption_without_skipping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, _document_value, catalog, inventory, plan, loader = _setup(tmp_path)
    preview = build_adoption_preview(
        catalog, inventory, plan, ("alpha", "beta"), loader
    )
    original = portable_contract.update_write_verdict

    def refuse_alpha(path: str, *, exists: bool):
        if path == ".claude/skills/alpha/SKILL.md":
            return portable_contract.WriteVerdict(
                path, False, "deny", "brain", "adversarial-test"
            )
        return original(path, exists=exists)

    monkeypatch.setattr(portable_contract, "update_write_verdict", refuse_alpha)

    with pytest.raises(AdoptionExecutionError, match=r"ownership contract.*alpha"):
        execute_adoption(vault, preview, preview.sha256, loader)

    assert _tx_directories(vault) == []
    assert (vault / ".claude/skills/alpha/SKILL.md").read_bytes() == b"# alpha\n"
    assert (vault / ".claude/skills/beta/SKILL.md").read_bytes() == b"# beta\n"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: raw.update({"surprise": True}),
        lambda raw: raw.update({"preview_version": True}),
        lambda raw: raw["items"][0].update({"action": "conflict"}),
        lambda raw: raw["items"][0]["writes"][0].update({"path": "../escape"}),
        lambda raw: raw["items"][0]["writes"][0].update({"byte_size": -1}),
        lambda raw: raw["items"].append(dict(raw["items"][0])),
    ],
)
def test_preview_parser_fails_closed_on_ambiguous_documents(
    tmp_path: Path, mutation
) -> None:
    _vault, _document_value, preview, _loader = _preview(tmp_path)
    raw = json.loads(json.dumps(preview.to_dict()))
    mutation(raw)

    with pytest.raises(AdoptionPreviewError, match="refused"):
        AdoptionPreview.from_dict(raw)


def test_receipt_serialization_is_strict_and_deterministic(tmp_path: Path) -> None:
    vault, _document_value, preview, loader = _preview(tmp_path)
    receipt = execute_adoption(vault, preview, preview.sha256, loader)

    canonical = canonical_adoption_receipt_bytes(receipt)

    assert canonical_adoption_receipt_bytes(receipt) == canonical
    assert AdoptionReceipt.from_dict(receipt.to_dict()) == receipt
    unknown = receipt.to_dict()
    unknown["surprise"] = True
    with pytest.raises(AdoptionExecutionError, match="unknown fields"):
        AdoptionReceipt.from_dict(unknown)
    nested_transaction = receipt.to_dict()
    nested_transaction["transaction_id"] = "nested/id"
    nested_transaction["snapshot_ref"] = "System/.dex/tx/nested/id/snapshot"
    with pytest.raises(AdoptionExecutionError, match="transaction_id"):
        AdoptionReceipt.from_dict(nested_transaction)


def test_receipt_snapshot_ref_expires_after_three_further_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.transaction import engine as transaction_engine

    vault, _document_value, preview, loader = _preview(tmp_path)
    timestamps = iter(
        (
            "20260721T000001-",
            "20260721T000002-",
            "20260721T000003-",
            "20260721T000004-",
        )
    )
    monkeypatch.setattr(
        transaction_engine.time,
        "strftime",
        lambda _format: next(timestamps),
    )

    receipts = [
        execute_adoption(vault, preview, preview.sha256, loader) for _ in range(4)
    ]

    assert not (vault / receipts[0].snapshot_ref).exists()
    assert all((vault / receipt.snapshot_ref).is_dir() for receipt in receipts[1:])


_FAULT_WORKER = r"""
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[3])

from core.lifecycle.engine import execute_adoption
from core.lifecycle.preview import AdoptionPreview

vault = Path(sys.argv[1])
preview = AdoptionPreview.from_dict(json.loads(Path(sys.argv[2]).read_text()))
payloads = {
    ".claude/skills/alpha/SKILL.md": b"# alpha\n",
    ".claude/skills/beta/SKILL.md": b"# beta\n",
}
execute_adoption(vault, preview, preview.sha256, payloads.__getitem__)
"""


@pytest.mark.parametrize(
    "seam",
    [
        "after-begin",
        "after-snapshot",
        "mid-apply:0",
        "mid-apply:1",
        "after-apply",
        "after-verify",
        "before-finalize",
        "after-commit-record",
    ],
)
def test_e9_adoption_crash_at_every_transaction_seam_converges(
    seam: str, tmp_path: Path
) -> None:
    vault, _document_value, catalog, inventory, plan, loader = _setup(tmp_path)
    preview = build_adoption_preview(
        catalog, inventory, plan, ("alpha", "beta"), loader
    )
    relatives = [
        ".claude/skills/alpha/SKILL.md",
        ".claude/skills/beta/SKILL.md",
    ]
    os.chmod(vault / relatives[0], 0o600)
    os.chmod(vault / relatives[1], 0o640)
    before = {
        relative: (
            (vault / relative).read_bytes(),
            stat.S_IMODE((vault / relative).stat().st_mode),
        )
        for relative in relatives
    }
    preview_path = tmp_path / "approved-preview.json"
    preview_path.write_bytes(canonical_adoption_preview_bytes(preview))
    env = dict(os.environ, DEX_TX_TEST_STOP_AFTER=seam)

    process = subprocess.run(
        [
            sys.executable,
            "-c",
            _FAULT_WORKER,
            str(vault),
            str(preview_path),
            str(REPO_ROOT),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert process.returncode == 137, (seam, process.stderr[-500:])
    outcomes = Transaction.resume(vault)
    after = {
        relative: (
            (vault / relative).read_bytes(),
            stat.S_IMODE((vault / relative).stat().st_mode),
        )
        for relative in relatives
    }
    if seam == "after-commit-record":
        assert after == {
            ".claude/skills/alpha/SKILL.md": (b"# alpha\n", 0o644),
            ".claude/skills/beta/SKILL.md": (b"# beta\n", 0o644),
        }
        assert outcomes == []
    else:
        assert after == before, seam
        assert len(outcomes) == 1
        assert outcomes[0]["resumed"] is True
