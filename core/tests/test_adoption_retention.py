"""C3 read-only reporting for the transaction snapshot retention budget."""

from __future__ import annotations

from pathlib import Path

from core.lifecycle import retention
from core.transaction.engine import PlanEntry, Transaction


def _disk_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def test_retention_report_counts_bytes_and_only_committed_snapshots(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    for index in range(2):
        Transaction.begin(
            vault,
            [
                PlanEntry(
                    "System/.installed-files.manifest",
                    f"manifest {index}\n".encode(),
                )
            ],
        ).run()
    unfinished = vault / "System/.dex/tx/99999999T999999-deadbeef/snapshot"
    unfinished.mkdir(parents=True)
    (unfinished / "orphan.bin").write_bytes(b"orphan bytes")
    tx_root = vault / "System/.dex/tx"

    report = retention.compute_retention_report(vault)

    assert report.total_bytes == _disk_bytes(tx_root)
    assert report.committed_snapshot_count == 2
    assert report.warning is False


def test_retention_warning_uses_patchable_two_gib_threshold_and_never_blocks(
    tmp_path: Path, monkeypatch
) -> None:
    vault = tmp_path / "vault"
    payload = vault / "System/.dex/tx/uncommitted/small.bin"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"1234567")
    monkeypatch.setattr(retention, "RETENTION_WARNING_BYTES", 6)

    report = retention.compute_retention_report(vault)

    assert report.total_bytes == 7
    assert report.warning is True
    assert report.warning_threshold_bytes == 6

    monkeypatch.setattr(retention, "RETENTION_WARNING_BYTES", 7)
    assert retention.compute_retention_report(vault).warning is False


def test_retention_report_is_zero_for_vault_without_transaction_state(
    tmp_path: Path,
) -> None:
    report = retention.compute_retention_report(tmp_path / "vault")

    assert report.total_bytes == 0
    assert report.committed_snapshot_count == 0
    assert report.warning is False
    assert report.warning_threshold_bytes == 2 * 1024**3
