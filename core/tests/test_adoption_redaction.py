"""E1 redaction tests, including a red-when-removed gate proof."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.lifecycle.inventory import build_inventory
from core.lifecycle.secrets import RedactionViolation, assert_no_denied_metadata, redact_document
from core.tests.lifecycle_test_helpers import write_file, write_manifest


@pytest.mark.parametrize(
    "relative",
    [".env", ".ENV.LOCAL", "System/Credentials", "nested/private.PEM"],
)
def test_denied_paths_show_names_but_never_size_or_hash(tmp_path: Path, relative: str) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, relative, b"super-secret-value\n")
    write_manifest(vault, [relative])

    report = build_inventory(vault)
    record = next(entry.to_dict() for entry in report.entries if entry.actual_path == relative)

    assert record["path"] == relative
    assert record["redacted"] is True
    assert "size" not in record
    assert "sha256" not in record
    assert_no_denied_metadata(report.to_dict())


def test_e1_red_when_removed_proves_the_output_gate_is_load_bearing() -> None:
    unsafe_without_redaction = {
        "path": "System/credentials/provider-token.json",
        "size": 123,
        "sha256": "a" * 64,
    }

    with pytest.raises(RedactionViolation, match="forbidden metadata"):
        assert_no_denied_metadata(unsafe_without_redaction)

    safe = redact_document(unsafe_without_redaction)
    assert_no_denied_metadata(safe)
    assert safe == {
        "path": "System/credentials/provider-token.json",
        "redacted": True,
    }
