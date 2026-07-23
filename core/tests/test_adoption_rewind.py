"""C3 adoption rewind: exact acknowledgement, drift refusal, and recovery."""

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
from core.lifecycle.engine import (
    AdoptionReceipt,
    AdoptionRewindError,
    RewindReceipt,
    canonical_adoption_receipt_bytes,
    canonical_rewind_receipt_bytes,
    execute_adoption,
    load_adoption_receipt,
    rewind_acknowledgement_token,
    rewind_adoption,
)
from core.tests.test_adoption_transaction import _preview
from core.transaction.engine import PlanEntry, Transaction

REPO_ROOT = Path(__file__).resolve().parents[2]
OLD = b"before adoption\r\nwith exact bytes\x00"
NEW = b"after adoption\n"
CREATED = b"created by adoption\n"
EXISTING_PATH = "README.md"
CREATED_PATH = ".claude/skills/created/SKILL.md"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _tx_directories(vault: Path) -> list[Path]:
    tx_root = vault / "System/.dex/tx"
    return sorted(path for path in tx_root.iterdir() if path.is_dir())


def _committed_adoption(tmp_path: Path) -> tuple[Path, AdoptionReceipt]:
    vault = tmp_path / "vault"
    vault.mkdir()
    existing = vault / EXISTING_PATH
    existing.write_bytes(OLD)
    os.chmod(existing, 0o640)
    transaction = Transaction.begin(
        vault,
        [
            PlanEntry(EXISTING_PATH, NEW, mode=0o644),
            PlanEntry(CREATED_PATH, CREATED, mode=0o600),
        ],
    )
    result = transaction.run()
    receipt = AdoptionReceipt.from_dict(
        {
            "receipt_version": 1,
            "items_adopted": ["alpha"],
            "files_written": [
                {
                    "item_id": "alpha",
                    "path": CREATED_PATH,
                    "sha256": _sha256(CREATED),
                    "byte_size": len(CREATED),
                },
                {
                    "item_id": "alpha",
                    "path": EXISTING_PATH,
                    "sha256": _sha256(NEW),
                    "byte_size": len(NEW),
                },
            ],
            "transaction_id": result["tx_id"],
            "snapshot_ref": f"System/.dex/tx/{result['tx_id']}/snapshot",
            "catalog_sha256": "a" * 64,
            "inventory_sha256": "b" * 64,
            "preview_sha256": "c" * 64,
        }
    )
    return vault, receipt


def test_happy_rewind_restores_exact_bytes_and_mode_and_deletes_created_file(
    tmp_path: Path,
) -> None:
    vault, receipt = _committed_adoption(tmp_path)

    rewind_receipt = rewind_adoption(
        vault,
        receipt,
        rewind_acknowledgement_token(receipt),
    )

    assert (vault / EXISTING_PATH).read_bytes() == OLD
    assert stat.S_IMODE((vault / EXISTING_PATH).stat().st_mode) == 0o640
    assert not (vault / CREATED_PATH).exists()
    assert rewind_receipt.adoption_transaction_id == receipt.transaction_id
    assert rewind_receipt.rewind_transaction_id != receipt.transaction_id
    assert rewind_receipt.snapshot_ref == (
        f"System/.dex/tx/{rewind_receipt.rewind_transaction_id}/snapshot"
    )
    assert rewind_receipt.source_receipt_sha256 == hashlib.sha256(
        canonical_adoption_receipt_bytes(receipt)
    ).hexdigest()
    assert [entry.to_dict() for entry in rewind_receipt.files_restored] == [
        {
            "item_id": "alpha",
            "path": CREATED_PATH,
            "existed_before_adoption": False,
            "restored_sha256": None,
            "byte_size": None,
            "mode": None,
        },
        {
            "item_id": "alpha",
            "path": EXISTING_PATH,
            "existed_before_adoption": True,
            "restored_sha256": _sha256(OLD),
            "byte_size": len(OLD),
            "mode": 0o640,
        },
    ]
    assert RewindReceipt.from_dict(rewind_receipt.to_dict()) == rewind_receipt
    assert canonical_rewind_receipt_bytes(rewind_receipt).endswith(b"\n")


def test_rewind_refuses_all_drift_and_names_exact_paths(tmp_path: Path) -> None:
    vault, receipt = _committed_adoption(tmp_path)
    (vault / EXISTING_PATH).write_bytes(b"user edit\n")
    (vault / CREATED_PATH).write_bytes(b"another user edit\n")

    with pytest.raises(AdoptionRewindError) as raised:
        rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))

    assert str(raised.value) == (
        "rewind refused: files changed after adoption and were left untouched: "
        f"{CREATED_PATH}, {EXISTING_PATH}. Keep those edits or restore the adopted "
        "bytes, then request a new rewind."
    )
    assert len(_tx_directories(vault)) == 1
    assert (vault / EXISTING_PATH).read_bytes() == b"user edit\n"
    assert (vault / CREATED_PATH).read_bytes() == b"another user edit\n"


def test_rewind_catches_drift_immediately_before_snapshot_and_restores_the_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.lifecycle import engine as rewind_engine

    vault, receipt = _committed_adoption(tmp_path)
    target = vault / EXISTING_PATH
    real_begin = Transaction.begin

    def begin_then_race(vault_root: Path, plan: list[PlanEntry]):
        transaction = real_begin(vault_root, plan)
        target.write_bytes(b"edit won immediately before rewind snapshot\n")
        return transaction

    monkeypatch.setattr(rewind_engine.Transaction, "begin", begin_then_race)

    with pytest.raises(AdoptionRewindError, match=EXISTING_PATH):
        rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))

    assert target.read_bytes() == b"edit won immediately before rewind snapshot\n"
    assert (vault / CREATED_PATH).read_bytes() == CREATED


@pytest.mark.parametrize("token", [None, "0" * 64])
def test_rewind_refuses_missing_or_wrong_acknowledgement_token(
    tmp_path: Path, token: str | None
) -> None:
    vault, receipt = _committed_adoption(tmp_path)

    with pytest.raises(AdoptionRewindError, match="acknowledgement token"):
        rewind_adoption(vault, receipt, token)

    assert len(_tx_directories(vault)) == 1
    assert (vault / EXISTING_PATH).read_bytes() == NEW
    assert (vault / CREATED_PATH).read_bytes() == CREATED


def test_acknowledgement_token_is_bound_to_exact_id_and_sorted_paths(
    tmp_path: Path,
) -> None:
    _vault, receipt = _committed_adoption(tmp_path)
    expected_payload = {
        "rewind": receipt.transaction_id,
        "files": sorted([CREATED_PATH, EXISTING_PATH]),
    }
    expected = hashlib.sha256(
        (
            json.dumps(expected_payload, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    ).hexdigest()

    assert rewind_acknowledgement_token(receipt) == expected
    changed = receipt.to_dict()
    changed["transaction_id"] = "20260721T235959-deadbeef"
    changed["snapshot_ref"] = "System/.dex/tx/20260721T235959-deadbeef/snapshot"
    assert rewind_acknowledgement_token(AdoptionReceipt.from_dict(changed)) != expected


def test_rewind_refuses_when_adoption_snapshot_was_pruned(tmp_path: Path) -> None:
    vault, receipt = _committed_adoption(tmp_path)
    snapshot = vault / receipt.snapshot_ref
    for path in sorted(snapshot.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    snapshot.rmdir()

    with pytest.raises(
        AdoptionRewindError,
        match=r"keep-last-3 retention.*can no longer be rewound",
    ):
        rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))

    assert len(_tx_directories(vault)) == 1
    assert (vault / EXISTING_PATH).read_bytes() == NEW


def test_rewind_verifies_snapshot_blob_before_starting_transaction(tmp_path: Path) -> None:
    vault, receipt = _committed_adoption(tmp_path)
    snapshot_blob = vault / receipt.snapshot_ref / "000000.bin"
    snapshot_blob.write_bytes(b"tampered snapshot bytes")

    with pytest.raises(AdoptionRewindError, match=r"snapshot.*damaged"):
        rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))

    assert len(_tx_directories(vault)) == 1
    assert (vault / EXISTING_PATH).read_bytes() == NEW
    assert (vault / CREATED_PATH).read_bytes() == CREATED


def test_rewind_fails_closed_on_malformed_snapshot_manifest(tmp_path: Path) -> None:
    vault, receipt = _committed_adoption(tmp_path)
    manifest_path = vault / receipt.snapshot_ref / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"][0]["relative"] = [EXISTING_PATH]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(AdoptionRewindError, match=r"snapshot manifest is damaged"):
        rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))

    assert len(_tx_directories(vault)) == 1
    assert (vault / EXISTING_PATH).read_bytes() == NEW
    assert (vault / CREATED_PATH).read_bytes() == CREATED


def test_rewind_strictly_revalidates_receipt_input(tmp_path: Path) -> None:
    vault, receipt = _committed_adoption(tmp_path)
    malformed = receipt.to_dict()
    malformed["unexpected"] = True

    with pytest.raises(AdoptionRewindError, match=r"receipt is invalid.*unknown fields"):
        rewind_adoption(vault, malformed, "0" * 64)

    assert len(_tx_directories(vault)) == 1


def test_ownership_contract_refusal_aborts_the_whole_rewind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, receipt = _committed_adoption(tmp_path)
    original = portable_contract.update_write_verdict

    def refuse_existing(path: str, *, exists: bool):
        if path == EXISTING_PATH:
            return portable_contract.WriteVerdict(
                path, False, "deny", "brain", "adversarial-test"
            )
        return original(path, exists=exists)

    monkeypatch.setattr(portable_contract, "update_write_verdict", refuse_existing)

    with pytest.raises(AdoptionRewindError, match=r"ownership contract.*README"):
        rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))

    assert len(_tx_directories(vault)) == 1
    assert (vault / EXISTING_PATH).read_bytes() == NEW
    assert (vault / CREATED_PATH).read_bytes() == CREATED


def test_successful_adoption_persists_canonical_loadable_receipt(tmp_path: Path) -> None:
    vault, _document, preview, loader = _preview(tmp_path)

    receipt = execute_adoption(vault, preview, preview.sha256, loader)

    receipt_path = (
        vault
        / "System/.dex/adoptions"
        / f"{receipt.transaction_id}.receipt.json"
    )
    assert receipt_path.read_bytes() == canonical_adoption_receipt_bytes(receipt)
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert load_adoption_receipt(vault, receipt.transaction_id) == receipt
    assert portable_contract.resolve(str(receipt_path.relative_to(vault))).ownership == (
        "runtime"
    )

    receipt_path.write_bytes(receipt_path.read_bytes().replace(b"\n", b" \n", 1))
    with pytest.raises(AdoptionRewindError, match="not canonical"):
        load_adoption_receipt(vault, receipt.transaction_id)


_REWIND_FAULT_WORKER = r"""
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[3])

from core.lifecycle.engine import (
    AdoptionReceipt,
    rewind_acknowledgement_token,
    rewind_adoption,
)

vault = Path(sys.argv[1])
receipt = AdoptionReceipt.from_dict(json.loads(Path(sys.argv[2]).read_text()))
rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))
"""


def test_crash_during_rewind_converges_via_transaction_resume(tmp_path: Path) -> None:
    vault, receipt = _committed_adoption(tmp_path)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(canonical_adoption_receipt_bytes(receipt))
    env = dict(os.environ, DEX_TX_TEST_STOP_AFTER="mid-apply:0")

    process = subprocess.run(
        [
            sys.executable,
            "-c",
            _REWIND_FAULT_WORKER,
            str(vault),
            str(receipt_path),
            str(REPO_ROOT),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert process.returncode == 137, process.stderr[-500:]
    outcomes = Transaction.resume(vault)
    assert len(outcomes) == 1
    assert outcomes[0]["resumed"] is True
    assert (vault / EXISTING_PATH).read_bytes() == NEW
    assert stat.S_IMODE((vault / EXISTING_PATH).stat().st_mode) == 0o644
    assert (vault / CREATED_PATH).read_bytes() == CREATED
    assert stat.S_IMODE((vault / CREATED_PATH).stat().st_mode) == 0o600
