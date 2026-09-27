"""Phase 2: detect reports an exact trailing-CRLF finding per record class."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.lifecycle.bridge import _canonical
from core.lifecycle.byte_mode import (
    ACTION_BLOCKED,
    ACTION_BYTES_NORMALISED,
    ACTION_RE_RECORDED,
    FINDING_CRLF_TAIL,
    FINDING_LEDGER_CRLF,
    FINDING_UNEXPLAINED,
    detect,
)
from core.tests.byte_mode_helpers import (
    activation_bytes,
    crlf_variant,
    event_bytes,
    interior_crlf_variant,
    receipt_bytes,
    sample_activation,
    sample_receipt,
    topology_bytes,
    write_activation,
    write_ledger_event,
    write_receipt,
    write_topology_receipt,
)

pytestmark = pytest.mark.windows_supported


def test_detects_crlf_tail_on_each_record_class(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_activation(vault, crlf_variant(activation_bytes()))
    write_receipt(vault, crlf_variant(receipt_bytes()))
    write_topology_receipt(vault, crlf_variant(topology_bytes()))
    write_ledger_event(vault, crlf_variant(event_bytes()))

    report = detect(vault)

    by_record = {finding.record: finding for finding in report.findings}
    assert set(by_record) == {
        "System/.dex/lifecycle/activation.json",
        "System/.dex/adoptions/20260128T120000-abcd1234.receipt.json",
        "System/.dex/topology-migrations/20260128T120000-abcd1234.receipt.json",
    }
    assert by_record["System/.dex/lifecycle/activation.json"].finding == FINDING_CRLF_TAIL
    assert by_record["System/.dex/lifecycle/activation.json"].action == ACTION_RE_RECORDED
    assert by_record[
        "System/.dex/adoptions/20260128T120000-abcd1234.receipt.json"
    ].finding == FINDING_CRLF_TAIL
    assert by_record[
        "System/.dex/adoptions/20260128T120000-abcd1234.receipt.json"
    ].action == ACTION_BYTES_NORMALISED
    assert by_record[
        "System/.dex/topology-migrations/20260128T120000-abcd1234.receipt.json"
    ].finding == FINDING_CRLF_TAIL
    assert len(report.blocking) == 1
    assert report.blocking[0].finding == FINDING_LEDGER_CRLF
    assert report.blocking[0].action == ACTION_BLOCKED
    assert "dex-doctor" in (report.blocking[0].reason or "")


def test_interior_crlf_and_changed_field_are_blocking(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_activation(vault, interior_crlf_variant(activation_bytes()))
    report = detect(vault)
    assert report.findings == []
    assert len(report.blocking) == 1
    assert report.blocking[0].finding == FINDING_UNEXPLAINED

    vault2 = tmp_path / "vault2"
    vault2.mkdir()
    changed = dict(sample_activation())
    changed["baseline_inventory_sha256"] = "1" * 64
    write_activation(vault2, _canonical(changed) + b" extra")
    report2 = detect(vault2)
    assert report2.findings == []
    assert report2.blocking[0].finding == FINDING_UNEXPLAINED

    vault3 = tmp_path / "vault3"
    vault3.mkdir()
    receipt = sample_receipt()
    write_receipt(vault3, interior_crlf_variant(receipt_bytes()))
    report3 = detect(vault3)
    assert report3.findings == []
    assert report3.blocking[0].finding == FINDING_UNEXPLAINED


def test_canonical_records_are_not_findings(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_activation(vault, activation_bytes())
    write_receipt(vault, receipt_bytes())
    write_topology_receipt(vault, topology_bytes())
    write_ledger_event(vault, event_bytes())

    report = detect(vault)
    assert report.findings == []
    assert report.blocking == []
    assert report.state == "binary"
