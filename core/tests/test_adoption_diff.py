"""C-1-honest shipped-state divergence tests."""

from __future__ import annotations

import hashlib
import json
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


def test_windows_crlf_checkout_still_proves_release_identity(tmp_path: Path) -> None:
    """Issue #256 defense in depth: an existing Windows checkout with Git's
    core.autocrlf=true carries EVERY tracked text file as CRLF — the
    manifest, tracked release files, and dormant catalog payload sources —
    until .gitattributes re-checks them out. Release identity must still
    verify from that working copy, dormant payloads must still resolve, and
    pristine files must classify stock-unmodified instead of flooding the
    report with false "you modified this" verdicts. Genuinely edited files
    must still be caught."""
    vault = tmp_path / "vault"
    vault.mkdir()

    tracked_lf = b"release bytes\nsecond line\n"
    edited_lf = b"the shipped bytes\n"
    dormant_lf = b"---\nname: dormant-skill\n---\nrelease payload\n"
    dormant_source = ".claude/skills/_available/sales/dormant/SKILL.md"
    dormant_target = ".claude/skills/dormant/SKILL.md"

    manifest = write_manifest(
        vault, ["core/feature.py", "core/edited.py", dormant_source]
    )
    catalog = catalog_for(
        manifest,
        {
            "core/feature.py": tracked_lf,
            "core/edited.py": edited_lf,
            dormant_target: dormant_lf,
        },
    )
    # Publisher fragment mapping the absent target to its dormant source,
    # exactly as core/lifecycle/catalog/official-capabilities.json does for
    # the optional capability skills.
    fragment = {
        "catalog_source_version": 1,
        "items": [
            {
                "files": [
                    {
                        "path": dormant_target,
                        "source_path": dormant_source,
                        "sha256": hashlib.sha256(dormant_lf).hexdigest(),
                        "byte_size": len(dormant_lf),
                    }
                ]
            }
        ],
    }
    write_file(
        vault,
        "core/lifecycle/catalog/official-capabilities.json",
        json.dumps(fragment).encode("utf-8"),
    )

    # Rewrite every text file on disk the way core.autocrlf=true checks out.
    def crlf(raw: bytes) -> bytes:
        return raw.replace(b"\n", b"\r\n")

    write_file(vault, "core/feature.py", crlf(tracked_lf))
    write_file(vault, dormant_source, crlf(dormant_lf))
    write_file(vault, "core/edited.py", crlf(b"a real user edit\n"))
    (vault / "System/.installed-files.manifest").write_bytes(crlf(manifest))

    report = build_inventory(vault, catalog=catalog)
    by_path = {entry.actual_path: entry for entry in report.entries}

    assert report.baseline.identity_state == "VERIFIED"
    assert not report.baseline.errors
    # Line-ending skew alone is never a user modification…
    assert by_path["core/feature.py"].release_state == "stock-unmodified"
    # …but genuinely different content still is, even in CRLF form.
    assert by_path["core/edited.py"].release_state == "stock-modified"
    modified = [
        entry
        for entry in report.customizations.divergences
        if entry.state == "stock-modified"
    ]
    assert [entry.canonical_path for entry in modified] == ["core/edited.py"]


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
