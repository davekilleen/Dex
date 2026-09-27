"""Phase 2: checked-in LF fixtures become CRLF in the test, then repair."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.lifecycle.bridge import _canonical, _well_formed_activation
from core.lifecycle.byte_mode import (
    FINDING_CRLF_TAIL,
    FINDING_LEDGER_CRLF,
    MARKER_RELATIVE,
    apply,
    detect,
)
from core.lifecycle.engine import load_adoption_receipt
from core.tests.byte_mode_helpers import FIXTURE_DIR, TX_ID, crlf_variant

pytestmark = pytest.mark.windows_supported


def _read_lf_fixture(name: str) -> bytes:
    raw = (FIXTURE_DIR / name).read_bytes()
    assert b"\r\n" not in raw
    return raw


def test_checked_in_fixtures_are_lf_and_repair_as_crlf_variants(tmp_path: Path) -> None:
    activation = _read_lf_fixture("activation.crlf.json")
    receipt = _read_lf_fixture("receipt.crlf.json")
    event = _read_lf_fixture("event.crlf.json")

    vault = tmp_path / "vault"
    (vault / "System/.dex/lifecycle").mkdir(parents=True)
    (vault / "System/.dex/adoptions").mkdir(parents=True)
    (vault / "System/.dex/ledger/events").mkdir(parents=True)
    (vault / "System/.dex/lifecycle/activation.json").write_bytes(crlf_variant(activation))
    (vault / "System/.dex/adoptions" / f"{TX_ID}.receipt.json").write_bytes(
        crlf_variant(receipt)
    )
    (vault / "System/.dex/ledger/events/00000001-install-registered.json").write_bytes(
        crlf_variant(event)
    )

    blocked = detect(vault)
    assert any(finding.finding == FINDING_LEDGER_CRLF for finding in blocked.blocking)
    assert any(finding.finding == FINDING_CRLF_TAIL for finding in blocked.findings)

    (vault / "System/.dex/ledger/events/00000001-install-registered.json").unlink()
    report = detect(vault)
    assert report.blocking == []
    assert {finding.finding for finding in report.findings} == {FINDING_CRLF_TAIL}

    apply(vault)

    rewritten = (vault / "System/.dex/lifecycle/activation.json")
    assert not rewritten.exists()
    loaded = load_adoption_receipt(vault, TX_ID)
    assert loaded.inventory_sha256 == "d" * 64
    assert (vault / "System/.dex/adoptions" / f"{TX_ID}.receipt.json").read_bytes() == receipt
    assert (vault / MARKER_RELATIVE).is_file()
    assert _well_formed_activation(activation) is not None
    assert activation == _canonical(_well_formed_activation(activation) or {})
