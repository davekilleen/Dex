"""C-1-honest shipped-state divergence tests."""

from __future__ import annotations

from pathlib import Path

from core.lifecycle.inventory import build_inventory
from core.tests.lifecycle_test_helpers import catalog_for, write_file, write_manifest


def test_diff_reports_modified_missing_and_unprovable_separately(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, "core/modified.py", b"local edit\n")
    write_file(vault, "core/unproven.py", b"some bytes\n")
    manifest = write_manifest(vault, ["core/modified.py", "core/unproven.py", "core/missing.py"])
    catalog = catalog_for(
        manifest,
        {
            "core/modified.py": b"release bytes\n",
            "core/missing.py": b"release bytes\n",
        },
    )

    report = build_inventory(vault, catalog=catalog)
    by_path = {entry.actual_path: entry for entry in report.entries}

    assert by_path["core/modified.py"].release_state == "stock-modified"
    assert by_path["core/missing.py"].release_state == "stock-missing"
    assert by_path["core/unproven.py"].release_state == "unknown"
    assert report.customizations.state == "DIVERGED"
    assert {entry.state for entry in report.customizations.divergences} == {
        "stock-modified",
        "stock-missing",
        "unknown",
    }


def test_windows_crlf_manifest_still_proves_release_identity(tmp_path: Path) -> None:
    """Issue #256 defense in depth: an existing Windows checkout keeps its
    CRLF manifest until the .gitattributes rule re-checks it out. Release
    identity must still verify from that working copy — canonicality parsing
    and the catalog binding both tolerate the CRLF form of the exact
    released manifest, and nothing else."""
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, "core/feature.py", b"release bytes\n")
    manifest = write_manifest(vault, ["core/feature.py"])
    catalog = catalog_for(manifest, {"core/feature.py": b"release bytes\n"})
    # Rewrite the manifest on disk the way core.autocrlf=true checks it out.
    target = vault / "System/.installed-files.manifest"
    target.write_bytes(manifest.replace(b"\n", b"\r\n"))

    report = build_inventory(vault, catalog=catalog)
    by_path = {entry.actual_path: entry for entry in report.entries}

    assert report.baseline.identity_state == "VERIFIED"
    assert by_path["core/feature.py"].release_state == "stock-unmodified"


def test_manifest_only_never_claims_release_owned_file_is_clean(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, "core/feature.py", b"bytes without a hash authority\n")
    write_manifest(vault, ["core/feature.py"])

    report = build_inventory(vault)
    feature = next(entry for entry in report.entries if entry.actual_path == "core/feature.py")

    assert report.baseline.identity_state == "MANIFEST_ONLY"
    assert feature.release_state == "unknown"
    assert report.customizations.state == "UNKNOWN"
