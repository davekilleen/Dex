"""Lane C protected customization-capsule creation and recovery journeys."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from core import portable_contract
from core.customization_migration.capsule import (
    CAPSULE_ROOT,
    CapsuleError,
    abandon_capsule,
    create_capsule,
    preview_capsule,
    read_capsule_status,
    validate_capsule,
)
from core.customization_migration.state import MigrationState
from core.tests.lifecycle_test_helpers import write_file, write_manifest
from core.tests.test_customization_assessment import (
    SHIPPED_SKILL,
    _install_verified_catalog,
    _linked_customized_vault,
)
from core.transaction.engine import Transaction
from core.transaction.lock import LockBusyError, acquire_owned_lock

REPO_ROOT = Path(__file__).resolve().parents[2]


def _manifest_only_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, SHIPPED_SKILL, b"modified without verified catalog\n")
    write_manifest(vault, [SHIPPED_SKILL])
    return vault


def _capsule_dir(vault: Path, capsule_id: str) -> Path:
    return vault / CAPSULE_ROOT / capsule_id


def _file_modes(root: Path) -> tuple[dict[str, int], dict[str, int]]:
    directories: dict[str, int] = {}
    files: dict[str, int] = {}
    for candidate in root.rglob("*"):
        relative = candidate.relative_to(root).as_posix()
        mode = stat.S_IMODE(candidate.lstat().st_mode)
        if candidate.is_dir():
            directories[relative] = mode
        else:
            files[relative] = mode
    return directories, files


def _source_bytes(vault: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for relative in (
        SHIPPED_SKILL,
        ".scripts/custom-plan.py",
        "System/folder-paths.yaml",
        "System/.installed-files.manifest",
        "System/.release-catalog.json",
    ):
        target = vault / relative
        if target.is_file():
            result[relative] = target.read_bytes()
    return result


def test_preview_refuses_manifest_only_unknown_assessment(tmp_path: Path) -> None:
    vault = _manifest_only_vault(tmp_path)

    with pytest.raises(CapsuleError, match="VERIFIED assessment"):
        preview_capsule(vault)

    assert not (vault / CAPSULE_ROOT).exists()


def test_preview_create_validate_and_status_happy_path(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)

    preview = preview_capsule(vault, clock=lambda: 1_750_000_000)
    receipt = create_capsule(vault, preview, preview.preview_sha256)
    capsule = _capsule_dir(vault, preview.capsule_id)

    assert capsule.is_dir()
    assert (capsule / "manifest.json").read_bytes() == (
        preview.manifest.canonical_manifest_bytes()
    )
    assert json.loads((capsule / "manifest.json").read_bytes()) == (
        preview.manifest.to_dict()
    )
    assert (capsule / "receipts/capsule.json").read_bytes() == receipt.canonical_bytes()
    directories, files = _file_modes(capsule)
    assert stat.S_IMODE((vault / CAPSULE_ROOT).stat().st_mode) == 0o700
    assert stat.S_IMODE(capsule.stat().st_mode) == 0o700
    assert directories
    assert files
    assert set(directories.values()) == {0o700}
    assert set(files.values()) == {0o600}
    assert set(directories) == {"blobs", "evidence", "receipts"}
    for directory in ("blobs", "evidence", "receipts"):
        assert stat.S_IMODE((capsule / directory).stat().st_mode) == 0o700
    assert (capsule / "journal.jsonl").is_file()
    capsule_files = [candidate for candidate in capsule.rglob("*") if candidate.is_file()]
    assert receipt.file_count == len(capsule_files)
    assert receipt.byte_count == sum(candidate.stat().st_size for candidate in capsule_files)

    for source in preview.blob_sources:
        assert (vault / source.blob_path).read_bytes() == (
            vault / source.source_path
        ).read_bytes()
        assert hashlib.sha256((vault / source.blob_path).read_bytes()).hexdigest() == (
            Path(source.blob_path).name
        )

    assert validate_capsule(vault, preview.capsule_id).status == "OK"
    status = read_capsule_status(vault)
    assert status.capsules == (
        type(status.capsules[0])(
            preview.capsule_id,
            MigrationState.CAPSULE_CREATED,
        ),
    )


def test_embedded_secret_is_finding_only_and_bytes_never_enter_capsule(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    canary = b"sk-CAPSULELEAKCANARY1234567890"
    write_file(
        vault,
        ".scripts/secret-helper.py",
        b'API_KEY = "' + canary + b'"\n',
    )

    preview = preview_capsule(vault, clock=lambda: 1_750_000_000)
    create_capsule(vault, preview, preview.preview_sha256)
    capsule = _capsule_dir(vault, preview.capsule_id)
    all_capsule_bytes = b"".join(
        candidate.read_bytes()
        for candidate in capsule.rglob("*")
        if candidate.is_file()
    )
    exclusions = json.loads(
        (capsule / "evidence/exclusions.json").read_text(encoding="utf-8")
    )

    assert canary not in all_capsule_bytes
    assert {
        (item["path"], item["reason"]) for item in exclusions["items"]
    } == {(".scripts/secret-helper.py", "embedded-secret")}
    assert exclusions["restricted_findings"][0]["source_paths"] == [
        ".scripts/secret-helper.py"
    ]
    assert not (capsule / "blobs").exists()


def test_source_drift_refuses_before_any_capsule_write(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault, clock=lambda: 1_750_000_000)
    (vault / ".scripts/custom-plan.py").write_bytes(b"user changed this\n")

    with pytest.raises(CapsuleError, match="drifted after capsule preview"):
        create_capsule(vault, preview, preview.preview_sha256)

    assert not _capsule_dir(vault, preview.capsule_id).exists()


def test_preview_digest_mismatch_refuses_before_write(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault, clock=lambda: 1_750_000_000)

    with pytest.raises(CapsuleError, match="preview digest mismatch"):
        create_capsule(vault, preview, "0" * 64)

    assert not _capsule_dir(vault, preview.capsule_id).exists()


def test_blob_tamper_is_broken_with_exact_path(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault, clock=lambda: 1_750_000_000)
    create_capsule(vault, preview, preview.preview_sha256)
    blob = _capsule_dir(vault, preview.capsule_id) / "blobs" / (
        preview.blob_sources[0].sha256
    )
    blob.write_bytes(b"tampered")

    result = validate_capsule(vault, preview.capsule_id)

    assert result.status == "BROKEN"
    assert f"blobs/{blob.name}" in result.mismatches


def test_corrupt_journal_projects_recovery_required(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault, clock=lambda: 1_750_000_000)
    create_capsule(vault, preview, preview.preview_sha256)
    journal = _capsule_dir(vault, preview.capsule_id) / "journal.jsonl"
    journal.write_bytes(journal.read_bytes() + b"{garbage")

    status = read_capsule_status(vault)

    assert status.capsules[0].state is MigrationState.RECOVERY_REQUIRED


def test_abandonment_appends_event_and_preserves_evidence(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault, clock=lambda: 1_750_000_000)
    create_capsule(vault, preview, preview.preview_sha256)
    capsule = _capsule_dir(vault, preview.capsule_id)
    evidence_before = {
        path.relative_to(capsule).as_posix(): path.read_bytes()
        for path in (capsule / "evidence").iterdir()
    }

    abandon_capsule(vault, preview.capsule_id)

    assert read_capsule_status(vault).capsules[0].state is MigrationState.ABANDONED
    assert {
        path.relative_to(capsule).as_posix(): path.read_bytes()
        for path in (capsule / "evidence").iterdir()
    } == evidence_before
    assert b'"event":"abandoned"' in (capsule / "journal.jsonl").read_bytes()


@pytest.mark.parametrize(
    "seam",
    (
        "after-begin",
        "after-snapshot",
        "mid-apply:0",
        "after-apply",
        "after-verify",
        "after-commit-record",
    ),
)
def test_create_fault_injection_resumes_to_absent_recovery_or_full_capsule(
    seam: str,
    tmp_path: Path,
) -> None:
    vault = _linked_customized_vault(tmp_path)
    source_before = _source_bytes(vault)
    script = (
        "from pathlib import Path\n"
        "from core.customization_migration.capsule import preview_capsule,create_capsule\n"
        "vault=Path(__import__('sys').argv[1])\n"
        "preview=preview_capsule(vault,clock=lambda:1750000000)\n"
        "create_capsule(vault,preview,preview.preview_sha256)\n"
    )
    environment = os.environ.copy()
    environment["DEX_TX_TEST_STOP_AFTER"] = seam
    environment["PYTHONPATH"] = str(REPO_ROOT)

    child = subprocess.run(
        [sys.executable, "-c", script, str(vault)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert child.returncode == 137

    Transaction.resume(vault)

    assert _source_bytes(vault) == source_before
    status = read_capsule_status(vault)
    assert all(
        item.state
        in {
            MigrationState.CAPSULE_CREATED,
            MigrationState.RECOVERY_REQUIRED,
        }
        for item in status.capsules
    )
    for item in status.capsules:
        if item.state is MigrationState.CAPSULE_CREATED:
            assert validate_capsule(vault, item.capsule_id).status == "OK"


@pytest.mark.parametrize(
    "seam",
    (
        "capsule-after-layout",
        "capsule-mid-finalize",
    ),
)
def test_create_capsule_finalize_crash_resumes_to_absent_capsule(
    seam: str,
    tmp_path: Path,
) -> None:
    vault = _linked_customized_vault(tmp_path)
    source_before = _source_bytes(vault)
    capsule_id_path = tmp_path / "capsule-id.txt"
    script = (
        "from pathlib import Path\n"
        "from core.customization_migration.capsule import preview_capsule,create_capsule\n"
        "vault=Path(__import__('sys').argv[1])\n"
        "capsule_id_path=Path(__import__('sys').argv[2])\n"
        "preview=preview_capsule(vault,clock=lambda:1750000000)\n"
        "capsule_id_path.write_text(preview.capsule_id,encoding='utf-8')\n"
        "create_capsule(vault,preview,preview.preview_sha256)\n"
    )
    environment = os.environ.copy()
    environment["DEX_TX_TEST_STOP_AFTER"] = seam
    environment["PYTHONPATH"] = str(REPO_ROOT)

    child = subprocess.run(
        [sys.executable, "-c", script, str(vault), str(capsule_id_path)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert child.returncode == 137
    capsule_id = capsule_id_path.read_text(encoding="utf-8")

    Transaction.resume(vault)

    assert _source_bytes(vault) == source_before
    capsule_root = vault / CAPSULE_ROOT
    assert not capsule_root.exists() or not (capsule_root / capsule_id).exists()


def test_create_refuses_while_single_writer_lock_is_held(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault, clock=lambda: 1_750_000_000)
    release = acquire_owned_lock(vault, "test-owner")
    try:
        with pytest.raises(LockBusyError):
            create_capsule(vault, preview, preview.preview_sha256)
    finally:
        release()

    assert not _capsule_dir(vault, preview.capsule_id).exists()


def test_capsule_path_is_gitignored_and_distribution_excluded() -> None:
    path = f"{CAPSULE_ROOT}/cap-0123456789abcdef/manifest.json"
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=REPO_ROOT,
    )
    distignore = (REPO_ROOT / ".distignore").read_text(encoding="utf-8").splitlines()

    assert ignored.returncode == 0
    assert CAPSULE_ROOT + "/" in distignore
    assert portable_contract.resolve(path).ownership == "runtime"


def test_capsule_root_and_write_authority_prefix_cannot_drift() -> None:
    assert portable_contract.CUSTOMIZATION_MIGRATION_SEAM_PREFIXES == (
        CAPSULE_ROOT + "/",
    )
