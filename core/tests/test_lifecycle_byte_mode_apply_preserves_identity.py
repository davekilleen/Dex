"""Phase 2: apply keeps receipt identity and recorded digest strings."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.lifecycle.bridge import _canonical
from core.lifecycle.byte_mode import MARKER_RELATIVE, apply, detect, load_marker
from core.lifecycle.engine import AdoptionReceipt, load_adoption_receipt
from core.tests.byte_mode_helpers import (
    TX_ID,
    crlf_variant,
    receipt_bytes,
    sample_receipt,
    write_receipt,
)

pytestmark = pytest.mark.windows_supported


def test_apply_preserves_receipt_identity_and_inventory_digest(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    original = sample_receipt()
    original_bytes = receipt_bytes()
    inventory_before = original.inventory_sha256
    path = write_receipt(vault, crlf_variant(original_bytes))

    result = apply(vault)

    loaded = load_adoption_receipt(vault, TX_ID)
    assert loaded == original
    assert loaded.inventory_sha256 == inventory_before
    assert loaded.inventory_sha256.encode("ascii") == inventory_before.encode("ascii")
    assert path.read_bytes() == original_bytes

    marker = load_marker(vault)
    assert marker is not None
    marker_path = vault / MARKER_RELATIVE
    assert marker_path.read_bytes() == _canonical(marker)

    quarantine = vault / str(result["quarantine"])
    manifest = (quarantine / "manifest.json").read_bytes()
    assert b"sha256_before" in manifest
    quarantined = quarantine / "System/.dex/adoptions" / f"{TX_ID}.receipt.json"
    assert quarantined.read_bytes() == crlf_variant(original_bytes)

    actions = result["actions"]
    assert len(actions) == 1
    assert actions[0]["document_identity_unchanged"] is True
    assert actions[0]["previous_bytes_sha256"]
    assert actions[0]["new_bytes_sha256"]
    assert actions[0]["previous_bytes_sha256"] != actions[0]["new_bytes_sha256"]

    report = detect(vault)
    assert report.findings == []
    assert report.blocking == []
