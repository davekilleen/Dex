"""Phase 2: rollback succeeds only when no newer update was recorded."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.lifecycle.byte_mode import (
    MESSAGE_ROLLBACK_REFUSED,
    ByteModeRollbackRefused,
    apply,
    rollback,
)
from core.tests.byte_mode_helpers import crlf_variant, receipt_bytes, write_receipt
from core.transaction.engine import PlanEntry, Transaction

pytestmark = pytest.mark.windows_supported


def test_rollback_restores_when_no_new_transaction(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    crlf = crlf_variant(receipt_bytes())
    path = write_receipt(vault, crlf)

    apply(vault)
    assert path.read_bytes() != crlf

    result = rollback(vault)

    assert path.read_bytes() == crlf
    assert result["restored"]
    assert not (vault / "System/.dex/lifecycle/byte-mode.json").exists()
    quarantine = vault / result["quarantine"]
    manifest = (quarantine / "manifest.json").read_bytes()
    assert b"rolled_back_at" in manifest


def test_rollback_refused_after_one_committed_transaction(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    crlf = crlf_variant(receipt_bytes())
    write_receipt(vault, crlf)
    apply(vault)

    (vault / "README.md").write_bytes(b"before\n")
    transaction = Transaction.begin(
        vault,
        [PlanEntry("README.md", b"after\n", mode=0o644)],
    )
    transaction.run()

    with pytest.raises(ByteModeRollbackRefused, match="cannot be undone") as error:
        rollback(vault)

    assert "byte-mode-quarantine" in str(error.value)
    assert MESSAGE_ROLLBACK_REFUSED.split("{")[0] in str(error.value)
