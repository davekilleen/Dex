"""Phase 2: ledger events with a trailing CRLF are detected and never rewritten."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.lifecycle.byte_mode import (
    FINDING_LEDGER_CRLF,
    ByteModeBlocked,
    apply,
    detect,
)
from core.tests.byte_mode_helpers import (
    crlf_variant,
    event_bytes,
    receipt_bytes,
    write_ledger_event,
    write_receipt,
)

pytestmark = pytest.mark.windows_supported


def test_ledger_crlf_is_blocked_and_not_rewritten(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    crlf_event = crlf_variant(event_bytes())
    path = write_ledger_event(vault, crlf_event)
    write_receipt(vault, crlf_variant(receipt_bytes()))

    report = detect(vault)
    assert any(finding.finding == FINDING_LEDGER_CRLF for finding in report.blocking)
    assert all(finding.record != path.relative_to(vault).as_posix() for finding in report.findings)

    with pytest.raises(ByteModeBlocked, match="cannot safely repair"):
        apply(vault)

    assert path.read_bytes() == crlf_event
    assert (vault / "System/.dex/adoptions").exists()
    receipt = next((vault / "System/.dex/adoptions").glob("*.receipt.json"))
    assert receipt.read_bytes() == crlf_variant(receipt_bytes())
    assert not (vault / "System/.dex/lifecycle/byte-mode.json").exists()
