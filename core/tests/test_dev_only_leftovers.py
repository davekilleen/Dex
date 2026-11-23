"""DEX-277: by-design exclusions and leftover developer files must not dead-end updates."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core import portable_contract
from core.customization_migration.model import (
    EXCLUSION_REASONS,
    exclusion_guidance,
)
from core.customization_migration.service import assess
from core.customization_migration.tidy import (
    apply_tidy_dev_leftovers,
    preview_tidy_dev_leftovers,
    restore_dev_leftovers,
)
from core.dev_only import (
    CONTRACT_TIDY_PATTERNS,
    TIDY_DEV_LEFTOVERS_DRY_RUN,
    parse_distignore_patterns,
)
from core.lifecycle.catalog import canonical_catalog_bytes, with_catalog_identity
from core.tests.lifecycle_test_helpers import SOURCE_COMMIT, write_file, write_manifest
from core.tests.test_customization_assessment import (
    SHIPPED_BYTES,
    SHIPPED_SKILL,
    _install_verified_catalog,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOCK = datetime(2026, 11, 23, 15, 30, 11, tzinfo=timezone.utc)
DEV_PATTERNS = (
    ".github/",
    "core/tests/",
    "scripts/",
)


def _install_catalog(vault: Path, *, patterns: tuple[str, ...] | None) -> None:
    write_file(vault, SHIPPED_SKILL, SHIPPED_BYTES)
    manifest = write_manifest(vault, [SHIPPED_SKILL])
    release: dict[str, object] = {
        "version": "1.73.0",
        "channel": "release",
        "immutable_distribution_tag_pattern": "dist/release/v1.73.0-<release-commit-prefix>",
        "source_commit": SOURCE_COMMIT,
        "manifest": {
            "path": "System/.installed-files.manifest",
            "sha256": hashlib.sha256(manifest).hexdigest(),
        },
    }
    if patterns is not None:
        release["dev_only_patterns"] = list(sorted(set(patterns)))
    document = with_catalog_identity(
        {
            "catalog_version": 2,
            "release": release,
            "items": [
                {
                    "id": "daily-plan",
                    "kind": "skill",
                    "version": "1.0.0",
                    "files": [
                        {
                            "path": SHIPPED_SKILL,
                            "sha256": hashlib.sha256(SHIPPED_BYTES).hexdigest(),
                            "ownership_class": "brain",
                        }
                    ],
                    "dependencies": [],
                    "capabilities": [],
                    "rewind": {
                        "acknowledgement_required": True,
                        "token": "rewind:daily-plan@1.0.0",
                    },
                }
            ],
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )
    write_file(
        vault,
        "System/.release-catalog.json",
        canonical_catalog_bytes(document),
    )


def _plant_leftovers(vault: Path) -> dict[str, bytes]:
    payloads = {
        "core/tests/test_x.py": b"print('leftover')\n",
        "scripts/build-release.sh": b"#!/bin/sh\necho leftover\n",
        ".github/workflows/a.yml": b"name: leftover\n",
    }
    for path, raw in payloads.items():
        write_file(vault, path, raw)
    return payloads


def test_assessment_ok_with_only_by_design_exclusions(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".venv/lib/site.py", b"x = 1\n")
    write_file(vault, ".claude/settings.json", b"{}\n")

    assessment = assess(vault)
    reasons = {(item.path, item.reason) for item in assessment.exclusions}

    assert (".venv", "dependency-tree-excluded") in reasons
    assert (".claude/settings.json", "restricted") in reasons
    assert assessment.completeness == "OK"
    assert assessment.incomplete_reasons == ()
    assert assessment.verdict == "OK"


def test_dev_only_leftovers_classified(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_catalog(vault, patterns=DEV_PATTERNS)
    _plant_leftovers(vault)

    assessment = assess(vault)
    leftovers = {
        item.path: item.reason
        for item in assessment.exclusions
        if item.reason == "dev-only-leftover"
    }

    assert set(leftovers) == {
        "core/tests/test_x.py",
        "scripts/build-release.sh",
        ".github/workflows/a.yml",
    }
    assert assessment.completeness == "OK"
    assert assessment.incomplete_reasons == ()


def test_unproved_non_dev_file_still_blocks(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_catalog(vault, patterns=DEV_PATTERNS)
    write_file(vault, "core/mystery.py", b"VALUE = 1\n")

    assessment = assess(vault)
    unproved = {
        item.path
        for item in assessment.exclusions
        if item.reason == "release-identity-unproved"
    }

    assert "core/mystery.py" in unproved
    assert assessment.completeness == "UNKNOWN"
    assert "assessment-exclusions" in assessment.incomplete_reasons


def test_guidance_never_dead_end() -> None:
    repair_commands = (
        "python3 -m core.update.reanchor_cli",
        TIDY_DEV_LEFTOVERS_DRY_RUN,
    )
    for anchor_state in ("verified", "absent", "rejected"):
        for reason in sorted(EXCLUSION_REASONS):
            text = exclusion_guidance(reason, anchor_state=anchor_state)
            if "Don't update" in text:
                assert any(command in text for command in repair_commands), (
                    reason,
                    anchor_state,
                    text,
                )
            if anchor_state == "verified":
                assert "Don't update until" not in text


def test_tidy_dev_leftovers_dry_run_and_apply(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_catalog(vault, patterns=DEV_PATTERNS)
    payloads = _plant_leftovers(vault)
    write_file(vault, "notes.md", b"leave me\n")
    original_skill = (vault / SHIPPED_SKILL).read_bytes()

    preview = preview_tidy_dev_leftovers(vault, clock=lambda: CLOCK)
    listed = [item["path"] for item in preview["files"]]
    assert listed == sorted(payloads)
    token = preview["preview_sha256"]
    assert isinstance(token, str) and len(token) == 64

    with pytest.raises(Exception) as wrong:
        apply_tidy_dev_leftovers(vault, "0" * 64, clock=lambda: CLOCK)
    assert "Nothing was moved" in str(wrong.value)
    for path, raw in payloads.items():
        assert (vault / path).read_bytes() == raw

    result = apply_tidy_dev_leftovers(vault, token, clock=lambda: CLOCK)
    assert result["moved"] == 3
    for path, raw in payloads.items():
        assert not (vault / path).exists()
        archived = vault / str(result["archive_dir"]) / path
        assert archived.read_bytes() == raw
    manifest = vault / str(result["archive_dir"]) / "manifest.json"
    assert manifest.is_file()
    assert (vault / "notes.md").read_bytes() == b"leave me\n"
    assert (vault / SHIPPED_SKILL).read_bytes() == original_skill

    restore = restore_dev_leftovers(vault, str(result["archive_dir"]))
    assert restore["restored"] == 3
    for path, raw in payloads.items():
        assert (vault / path).read_bytes() == raw
    assert not (vault / str(result["archive_dir"]) / "manifest.json").exists()
    assert (vault / "notes.md").read_bytes() == b"leave me\n"


def test_tidy_refuses_a_symlinked_leftover(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_catalog(vault, patterns=DEV_PATTERNS)
    write_file(vault, "core/tests/test_x.py", b"print('real')\n")
    (vault / "core/tests/link.py").symlink_to(vault / "core/tests/test_x.py")

    with pytest.raises(Exception) as linked:
        preview_tidy_dev_leftovers(vault, clock=lambda: CLOCK)
    assert "symlink" in str(linked.value).lower()
    assert (vault / "core/tests/test_x.py").read_bytes() == b"print('real')\n"


def test_old_catalog_without_dev_patterns(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    _plant_leftovers(vault)

    assessment = assess(vault)
    leftovers = {
        item.path
        for item in assessment.exclusions
        if item.reason == "dev-only-leftover"
    }
    unproved = {
        item.path
        for item in assessment.exclusions
        if item.reason == "release-identity-unproved"
    }

    assert leftovers == set()
    assert "core/tests/test_x.py" in unproved
    assert assessment.completeness == "UNKNOWN"


def test_contract_tidy_patterns_match_distignore_when_present() -> None:
    distignore = REPO_ROOT / ".distignore"
    if not distignore.is_file():
        return
    assert parse_distignore_patterns(distignore.read_text(encoding="utf-8")) == (
        CONTRACT_TIDY_PATTERNS
    )


def test_tidy_operation_allows_only_leftover_and_archive_paths() -> None:
    leftover = portable_contract.update_write_verdict(
        "core/tests/test_x.py",
        exists=True,
        operation="dev-leftover-tidy",
    )
    archive = portable_contract.update_write_verdict(
        "System/.dex/archive/dev-leftovers-20261123-153011/manifest.json",
        exists=False,
        operation="dev-leftover-tidy",
    )
    notes = portable_contract.update_write_verdict(
        "notes.md",
        exists=True,
        operation="dev-leftover-tidy",
    )

    assert leftover.allowed is True
    assert leftover.action == "write-dev-leftover-tidy"
    assert archive.allowed is True
    assert archive.action == "write-dev-leftover-tidy"
    assert notes.allowed is False
    assert notes.action == "outside-dev-leftover-tidy"


def test_stock_unmodified_shipped_file_is_not_a_customization(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)

    assessment = assess(vault)
    paths = {record.source_paths[0] for record in assessment.records}

    assert SHIPPED_SKILL not in paths
    assert assessment.completeness == "OK"
