"""Lane F private staging journeys."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from core.customization_migration.capsule import (
    CAPSULE_ROOT,
    create_capsule,
    preview_capsule,
)
from core.customization_migration.planning import (
    CandidateFile,
    DependencyRemapping,
    DependencyResolution,
    Disposition,
    DispositionPlanItem,
    RegenerationCandidate,
)
from core.customization_migration.staging import (
    StagingError,
    preview_staging,
    read_staging_status,
    stage_candidate,
    validate_staging,
)
from core.customization_migration.state import MigrationState
from core.tests.test_customization_assessment import _linked_customized_vault
from core.transaction.engine import Transaction

PROPOSAL_ID = "prop-0123456789abcdef"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _candidate_with_capsule(tmp_path: Path) -> tuple[Path, RegenerationCandidate]:
    vault = _linked_customized_vault(tmp_path)
    capsule_preview = preview_capsule(vault, clock=lambda: 1_750_000_000)
    create_capsule(vault, capsule_preview, capsule_preview.preview_sha256)
    assessment = capsule_preview.assessment
    digest = hashlib.sha256(assessment.canonical_assessment_bytes()).hexdigest()
    record = next(
        item
        for item in assessment.records
        if any(edge.source_path in item.source_paths for edge in assessment.edges)
    )
    owned_edges = tuple(
        edge for edge in assessment.edges if edge.source_path in record.source_paths
    )
    dispositions = tuple(
        sorted(
            (
                DispositionPlanItem(
                    item.customization_id,
                    Disposition.REWRITE
                    if item.customization_id == record.customization_id
                    else Disposition.KEEP_DISABLED,
                    digest,
                    evidence_edge_ids=(owned_edges[0].edge_id,)
                    if item.customization_id == record.customization_id
                    else (),
                )
                for item in assessment.records
            ),
            key=lambda item: item.customization_id,
        )
    )
    candidate = RegenerationCandidate(
        schema_version=0,
        proposal_id=PROPOSAL_ID,
        capsule_id=capsule_preview.capsule_id,
        evidence_digest=digest,
        dispositions=dispositions,
        files=(
            CandidateFile.create(
                "CLAUDE-custom.md",
                b"# Migrated customization\n",
                (record.customization_id,),
            ),
        ),
        dependency_remappings=tuple(
            DependencyRemapping(edge.edge_id, DependencyResolution.PRESERVE)
            for edge in owned_edges
        ),
        behaviour_contracts=(),
        declared_requirements=(),
        confidence=100,
        unresolved_questions=(),
        shim_expiries=(),
    )
    return vault, candidate


def _non_lifecycle_bytes(vault: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in vault.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(vault).as_posix()
        if relative.startswith(CAPSULE_ROOT + "/"):
            continue
        if relative.startswith("System/.dex/tx/"):
            continue
        result[relative] = path.read_bytes()
    return result


def test_stage_places_content_addressed_candidate_only_inside_capsule(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    outside_before = _non_lifecycle_bytes(vault)

    preview = preview_staging(vault, candidate.capsule_id, candidate)
    receipt = stage_candidate(vault, preview, preview.preview_sha256)

    staging = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
    )
    blob = staging / "files" / candidate.files[0].sha256
    assert blob.read_bytes() == candidate.files[0].content
    assert stat.S_IMODE(blob.stat().st_mode) == 0o600
    assert stat.S_IMODE(staging.stat().st_mode) == 0o700
    assert {
        stat.S_IMODE(path.stat().st_mode)
        for path in (
            staging.parent.parent,
            staging.parent,
            staging,
            staging / "files",
        )
    } == {0o700}
    assert {
        stat.S_IMODE(path.stat().st_mode)
        for path in staging.rglob("*")
        if path.is_file()
    } == {0o600}
    assert json.loads((staging / "manifest.json").read_bytes()) == candidate.to_dict()
    assert (staging / "receipt.json").read_bytes() == receipt.canonical_bytes()
    assert receipt.capsule_id == candidate.capsule_id
    assert receipt.proposal_id == candidate.proposal_id
    assert receipt.staged_file_count == 1
    assert receipt.staged_byte_count == len(candidate.files[0].content)
    assert validate_staging(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    ).status == "OK"
    assert read_staging_status(vault, candidate.capsule_id).proposals[0].state is (
        MigrationState.REGENERATION_STAGED
    )
    assert not (vault / candidate.files[0].target_path).exists()
    assert _non_lifecycle_bytes(vault) == outside_before


def test_accepted_candidate_without_generated_files_stages_closed_metadata(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    generated_id = candidate.files[0].customization_ids[0]
    candidate = replace(
        candidate,
        dispositions=tuple(
            replace(
                item,
                disposition=Disposition.MANUAL_REVIEW,
                evidence_edge_ids=(),
            )
            if item.customization_id == generated_id
            else item
            for item in candidate.dispositions
        ),
        files=(),
        dependency_remappings=(),
    )

    preview = preview_staging(vault, candidate.capsule_id, candidate)
    receipt = stage_candidate(vault, preview, preview.preview_sha256)

    assert receipt.staged_file_count == 0
    assert receipt.staged_byte_count == 0
    assert validate_staging(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    ).status == "OK"


def test_candidate_capsule_digest_drift_refuses_without_writing(tmp_path: Path) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    before = {
        path.relative_to(vault).as_posix(): path.read_bytes()
        for path in vault.rglob("*")
        if path.is_file()
    }
    drifted = replace(candidate, evidence_digest="0" * 64)

    with pytest.raises(StagingError, match="evidence digest"):
        preview_staging(vault, candidate.capsule_id, drifted)

    assert {
        path.relative_to(vault).as_posix(): path.read_bytes()
        for path in vault.rglob("*")
        if path.is_file()
    } == before


def test_staging_preview_digest_mismatch_refuses_before_write(tmp_path: Path) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    staging = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
    )

    with pytest.raises(StagingError, match="preview digest mismatch"):
        stage_candidate(vault, preview, "0" * 64)

    assert not staging.exists()
    assert not (vault / candidate.files[0].target_path).exists()


def test_restaging_same_proposal_refuses_without_clobber(tmp_path: Path) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    stage_candidate(vault, preview, preview.preview_sha256)
    staging = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
    )
    before = {
        path.relative_to(staging).as_posix(): path.read_bytes()
        for path in staging.rglob("*")
        if path.is_file()
    }

    with pytest.raises(StagingError, match="already exists"):
        stage_candidate(vault, preview, preview.preview_sha256)

    assert {
        path.relative_to(staging).as_posix(): path.read_bytes()
        for path in staging.rglob("*")
        if path.is_file()
    } == before


def test_existing_staging_artifact_refuses_without_clobber(tmp_path: Path) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    competing = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "manifest.json"
    )
    competing.parent.mkdir(parents=True, exist_ok=True)
    competing.write_bytes(b"competing private artifact\n")

    with pytest.raises(StagingError, match="already exists"):
        stage_candidate(vault, preview, preview.preview_sha256)

    assert competing.read_bytes() == b"competing private artifact\n"
    assert not (vault / candidate.files[0].target_path).exists()


def test_existing_empty_staging_directory_is_not_adopted(tmp_path: Path) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    staging = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
    )
    staging.mkdir(parents=True)

    with pytest.raises(StagingError, match="already exists"):
        stage_candidate(vault, preview, preview.preview_sha256)

    assert staging.is_dir()
    assert list(staging.iterdir()) == []


def test_capsule_drift_after_transaction_begin_rolls_staging_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    evidence = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "evidence"
        / "environment.json"
    )
    original_snapshot = Transaction._snapshot_phase

    def drift_capsule_then_snapshot(transaction: Transaction) -> None:
        evidence.write_bytes(evidence.read_bytes() + b" ")
        original_snapshot(transaction)

    monkeypatch.setattr(
        Transaction,
        "_snapshot_phase",
        drift_capsule_then_snapshot,
    )

    with pytest.raises(StagingError, match="capsule"):
        stage_candidate(vault, preview, preview.preview_sha256)

    staging = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
    )
    assert not staging.exists()


def test_validate_staging_reports_missing_unknown_and_tamper_broken(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)

    missing = validate_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert missing.status == "UNKNOWN"
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    stage_candidate(vault, preview, preview.preview_sha256)
    blob = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "files"
        / candidate.files[0].sha256
    )
    blob.write_bytes(b"tampered staged bytes\n")

    broken = validate_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert broken.status == "BROKEN"
    assert broken.mismatches == (f"files/{candidate.files[0].sha256}",)


@pytest.mark.parametrize("kind", ("directory", "symlink"))
def test_validate_staging_rejects_undeclared_tree_entries(
    kind: str,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    stage_candidate(vault, preview, preview.preview_sha256)
    staging = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
    )
    unexpected = staging / "unexpected"
    if kind == "directory":
        unexpected.mkdir()
    else:
        unexpected.symlink_to(staging / "manifest.json")

    validation = validate_staging(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )

    assert validation.status == "BROKEN"
    assert validation.mismatches == ("unexpected",)


def test_incomplete_staging_journal_is_unknown_not_ok(tmp_path: Path) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    stage_candidate(vault, preview, preview.preview_sha256)
    journal = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "journal.jsonl"
    )
    journal.write_bytes(
        b'{"event":"regeneration-proposed","schema_version":0}\n'
    )

    validation = validate_staging(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )

    assert validation.status == "UNKNOWN"
    assert validation.mismatches == ("journal.jsonl:incomplete",)


def test_symlinked_capsule_parent_cannot_validate_private_staging(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    stage_candidate(vault, preview, preview.preview_sha256)
    migration_root = vault / CAPSULE_ROOT
    moved_root = migration_root.with_name("customization-migrations-moved")
    migration_root.rename(moved_root)
    migration_root.symlink_to(moved_root, target_is_directory=True)

    validation = validate_staging(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )

    assert validation.status == "BROKEN"


def test_malformed_staging_journal_projects_recovery_required(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    stage_candidate(vault, preview, preview.preview_sha256)
    journal = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "journal.jsonl"
    )
    journal.write_bytes(journal.read_bytes() + b"{garbage")

    status = read_staging_status(vault, candidate.capsule_id)

    assert status.proposals[0].state is MigrationState.RECOVERY_REQUIRED


@pytest.mark.parametrize(
    "seam",
    (
        "after-begin",
        "after-snapshot",
        "mid-apply:0",
        "mid-apply:1",
        "mid-apply:2",
        "mid-apply:3",
        "after-apply",
        "after-verify",
        "before-finalize",
        "staging-after-layout",
        "staging-mid-finalize",
    ),
)
def test_staging_crash_resumes_to_absent_without_live_changes(
    seam: str,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    outside_before = _non_lifecycle_bytes(vault)
    candidate_path = tmp_path / "candidate.pickle"
    candidate_path.write_bytes(pickle.dumps(candidate))
    script = (
        "from pathlib import Path\n"
        "import pickle,sys\n"
        "from core.customization_migration.staging import "
        "preview_staging,stage_candidate\n"
        "vault=Path(sys.argv[1])\n"
        "candidate=pickle.loads(Path(sys.argv[2]).read_bytes())\n"
        "preview=preview_staging(vault,candidate.capsule_id,candidate)\n"
        "stage_candidate(vault,preview,preview.preview_sha256)\n"
    )
    environment = dict(os.environ)
    environment["DEX_TX_TEST_STOP_AFTER"] = seam
    environment["PYTHONPATH"] = str(REPO_ROOT)

    child = subprocess.run(
        [sys.executable, "-c", script, str(vault), str(candidate_path)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert child.returncode == 137, (seam, child.stderr[-500:])
    Transaction.resume(vault)
    staging = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
    )
    assert not staging.exists()
    assert not (vault / candidate.files[0].target_path).exists()
    assert _non_lifecycle_bytes(vault) == outside_before
