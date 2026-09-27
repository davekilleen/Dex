"""Phase 2: pre-repair snapshots refuse restore on Windows, including crash recovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.lifecycle.engine import (
    AdoptionRewindError,
    rewind_acknowledgement_token,
    rewind_adoption,
)
from core.tests.test_adoption_rewind import CREATED_PATH, EXISTING_PATH, _committed_adoption
from core.transaction import byte_mode_flag
from core.transaction.byte_mode_flag import (
    HASH_READ_MODE_PRE_REPAIR,
    MESSAGE_REWIND_REFUSED,
    PreRepairRestoreRefused,
    flag_path,
    write_operation_flag,
)
from core.transaction.engine import PlanEntry, Transaction

pytestmark = pytest.mark.windows_supported


def _pre_repair_tx_dir(vault: Path, transaction_id: str) -> Path:
    """Simulate a snapshot taken before this code wrote a post-repair flag."""
    tx_dir = vault / "System/.dex/tx" / transaction_id
    existing = flag_path(tx_dir)
    if existing.is_file():
        existing.unlink()
    write_operation_flag(tx_dir, HASH_READ_MODE_PRE_REPAIR)
    return tx_dir


def test_rewind_adoption_refuses_pre_repair_snapshot_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, receipt = _committed_adoption(tmp_path)
    _pre_repair_tx_dir(vault, receipt.transaction_id)
    monkeypatch.setattr(byte_mode_flag, "windows_restore_guard_active", lambda: True)

    with pytest.raises(AdoptionRewindError, match="will not restore") as error:
        rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))

    assert MESSAGE_REWIND_REFUSED in str(error.value)
    assert (vault / EXISTING_PATH).read_bytes() == b"after adoption\n"
    assert (vault / CREATED_PATH).exists()


def test_rewind_adoption_proceeds_on_posix(tmp_path: Path) -> None:
    vault, receipt = _committed_adoption(tmp_path)
    _pre_repair_tx_dir(vault, receipt.transaction_id)
    if os.name == "nt":
        pytest.skip("this assertion is the POSIX path")

    rewind_adoption(vault, receipt, rewind_acknowledgement_token(receipt))

    assert (vault / EXISTING_PATH).read_bytes() == b"before adoption\r\nwith exact bytes\x00"
    assert not (vault / CREATED_PATH).exists()


def test_crash_recovery_rollback_refuses_pre_repair_snapshot_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    target = vault / "README.md"
    target.write_bytes(b"original\n")
    transaction = Transaction.begin(
        vault,
        [PlanEntry("README.md", b"changed\n", mode=0o644)],
        max_read_bytes_by_relative={"README.md": 4096},
    )
    transaction._snapshot_phase()
    existing = flag_path(transaction.tx_dir)
    if existing.is_file():
        existing.unlink()
    write_operation_flag(transaction.tx_dir, HASH_READ_MODE_PRE_REPAIR)
    monkeypatch.setattr(byte_mode_flag, "windows_restore_guard_active", lambda: True)

    with pytest.raises(PreRepairRestoreRefused, match="will not restore"):
        transaction.rollback()

    assert target.read_bytes() == b"original\n"
    assert flag_path(transaction.tx_dir).is_file()
