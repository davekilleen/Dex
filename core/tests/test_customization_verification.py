"""Lane F conservative staged-candidate verification journeys."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import core.customization_migration.verification as verification_module
from core.customization_migration.behaviour import (
    BehaviouralContract,
    ContractProvenance,
    VerificationClass,
)
from core.customization_migration.capsule import CAPSULE_ROOT
from core.customization_migration.planning import (
    CandidateFile,
    DeclaredRequirement,
    DependencyRemapping,
    DependencyResolution,
    Disposition,
    RequirementKind,
)
from core.customization_migration.staging import (
    preview_staging,
    read_staging_status,
    stage_candidate,
    validate_staging,
)
from core.customization_migration.state import MigrationState
from core.customization_migration.verification import (
    VerificationError,
    verify_staging,
    write_verification_report,
)
from core.tests.test_customization_staging import (
    REPO_ROOT,
    _candidate_with_capsule,
    _non_lifecycle_bytes,
)
from core.transaction.engine import Transaction

_REGISTERED_STATIC_STATEMENT = (
    "The required static verification ladder proves the staged candidate's "
    "schema, paths, bytes, modes, dependency closure, syntax, release "
    "compatibility, trust requirements, and capsule isolation."
)


def _candidate_with_contract(
    tmp_path: Path,
    *,
    provenance: ContractProvenance = ContractProvenance.DETERMINISTIC,
    verification_class: VerificationClass = VerificationClass.STATIC,
    statement: str = _REGISTERED_STATIC_STATEMENT,
):
    vault, candidate = _candidate_with_capsule(tmp_path)
    customization_id = candidate.files[0].customization_ids[0]
    contract = BehaviouralContract.create(
        customization_id,
        statement,
        provenance,
        verification_class,
    )
    dispositions = tuple(
        replace(item, behaviour_contract_ids=(contract.contract_id,))
        if item.customization_id == customization_id
        else item
        for item in candidate.dispositions
    )
    return vault, replace(
        candidate,
        dispositions=dispositions,
        behaviour_contracts=(contract,),
    )


def _stage(vault: Path, candidate) -> None:
    preview = preview_staging(vault, candidate.capsule_id, candidate)
    stage_candidate(vault, preview, preview.preview_sha256)


def _capsule_bytes(vault: Path, capsule_id: str) -> dict[str, bytes]:
    capsule = vault / CAPSULE_ROOT / capsule_id
    return {
        path.relative_to(capsule).as_posix(): path.read_bytes()
        for path in capsule.rglob("*")
        if path.is_file()
    }


def test_clean_static_ladder_is_ok_and_deterministic_contract_is_verified(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    before = _non_lifecycle_bytes(vault)

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "OK"
    assert report.staging_id == candidate.proposal_id
    assert report.static_results[0].status == "OK"
    assert report.reported_verifications[0].status == "verified"
    assert tuple(
        check.name for check in report.static_results[0].checks
    ) == (
        "schema",
        "canonical-path",
        "ownership-authorization",
        "content-digest",
        "mode",
        "dependency-closure",
        "syntax",
        "target-release-compatibility",
        "trust-permission-delta",
        "private-staging",
    )
    assert report.staged_paths_private is True
    assert report.writes_confined_to_capsule is True
    assert _non_lifecycle_bytes(vault) == before
    assert not (vault / candidate.files[0].target_path).exists()


def test_tampered_staged_bytes_block_static_verification(tmp_path: Path) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    staged_blob = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "files"
        / candidate.files[0].sha256
    )
    staged_blob.write_bytes(b"tampered staged bytes\n")

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert report.static_results[0].status == "BLOCKED"
    assert any(
        check.name == "content-digest" and check.outcome == "fail"
        for check in report.static_results[0].checks
    )
    assert not (vault / candidate.files[0].target_path).exists()


def test_tampered_staging_receipt_blocks_static_verification(tmp_path: Path) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    receipt_path = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "receipt.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["staging_digest"] = "0" * 64
    receipt_path.write_text(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert any(
        check.name == "schema" and check.outcome == "fail"
        for check in report.static_results[0].checks
    )


def test_frozen_blocked_dependency_cannot_pass_static_closure(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    capsule = vault / CAPSULE_ROOT / candidate.capsule_id
    customizations = json.loads(
        (capsule / "evidence/customizations.json").read_text(encoding="utf-8")
    )
    dependencies = json.loads(
        (capsule / "evidence/dependencies.json").read_text(encoding="utf-8")
    )
    blocked_record = next(
        item
        for item in customizations["items"]
        if item["source_paths"] == ["System/folder-paths.yaml"]
    )
    blocked_edges = tuple(
        item["edge_id"]
        for item in dependencies["items"]
        if item["source_path"] == "System/folder-paths.yaml"
    )
    candidate = replace(
        candidate,
        dispositions=tuple(
            replace(
                item,
                disposition=Disposition.REWRITE,
                evidence_edge_ids=blocked_edges,
            )
            if item.customization_id == blocked_record["customization_id"]
            else replace(
                item,
                disposition=Disposition.MANUAL_REVIEW,
                evidence_edge_ids=(),
            )
            for item in candidate.dispositions
        ),
        files=(
            CandidateFile.create(
                "CLAUDE-custom.md",
                b"# Regenerated folder-map customization\n",
                (blocked_record["customization_id"],),
            ),
        ),
        dependency_remappings=tuple(
            DependencyRemapping(edge_id, DependencyResolution.PRESERVE)
            for edge_id in blocked_edges
        ),
    )
    _stage(vault, candidate)

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert any(
        check.name == "dependency-closure" and check.outcome == "fail"
        for check in report.static_results[0].checks
    )


def test_model_proposed_passing_check_is_never_reported_verified(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(
        tmp_path,
        provenance=ContractProvenance.MODEL_PROPOSED,
    )
    _stage(vault, candidate)

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert report.reported_verifications[0].outcome.outcome == "pass"
    assert report.reported_verifications[0].status == "model-claimed-pass"
    assert report.reported_verifications[0].status != "verified"


def test_candidate_cannot_self_label_arbitrary_contract_deterministic(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(
        tmp_path,
        provenance=ContractProvenance.DETERMINISTIC,
        statement="An arbitrary candidate-authored equivalence claim.",
    )
    _stage(vault, candidate)

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert report.reported_verifications[0].outcome.outcome == "pass"
    assert (
        report.reported_verifications[0].contract.provenance
        is ContractProvenance.MODEL_PROPOSED
    )
    assert report.reported_verifications[0].status == "model-claimed-pass"


@pytest.mark.parametrize(
    ("provenance", "expected_status", "expected_verdict"),
    (
        (
            ContractProvenance.MODEL_PROPOSED,
            "model-claimed-pass",
            "BLOCKED",
        ),
        (
            ContractProvenance.DETERMINISTIC,
            "model-claimed-pass",
            "BLOCKED",
        ),
    ),
)
def test_passing_fixture_respects_contract_provenance(
    provenance: ContractProvenance,
    expected_status: str,
    expected_verdict: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(
        tmp_path,
        provenance=provenance,
        verification_class=VerificationClass.ISOLATED_FIXTURE,
    )
    _stage(vault, candidate)

    def fixture_pass(*_arguments) -> verification_module.VerificationAttempt:
        return verification_module.VerificationAttempt(
            VerificationClass.ISOLATED_FIXTURE,
            VerificationClass.ISOLATED_FIXTURE,
            "pass",
            True,
            "A closed synthetic fixture passed without real-vault or network access.",
        )

    monkeypatch.setattr(
        verification_module,
        "_run_isolated_fixture",
        fixture_pass,
    )

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == expected_verdict
    assert report.reported_verifications[0].status == expected_status


def test_generated_disposition_without_behaviour_contract_is_blocked(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    _stage(vault, candidate)

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert (
        "Generated or native dispositions lack complete behavioural-contract "
        "coverage."
    ) in report.notes


def test_native_replacement_without_authenticated_user_confirmation_is_blocked(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_capsule(tmp_path)
    customization_id = candidate.files[0].customization_ids[0]
    candidate = replace(
        candidate,
        dispositions=tuple(
            replace(
                item,
                disposition=Disposition.NATIVE_REPLACEMENT,
                native_witness="skill:daily-plan",
                evidence_edge_ids=(),
                behaviour_contract_ids=(),
            )
            if item.customization_id == customization_id
            else item
            for item in candidate.dispositions
        ),
        files=(),
        dependency_remappings=(),
    )
    _stage(vault, candidate)

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert (
        "Native replacement lacks authenticated user-confirmation evidence."
        in report.notes
    )


def test_static_trust_permission_delta_blocks_declared_requirement(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    customization_id = candidate.files[0].customization_ids[0]
    candidate = replace(
        candidate,
        declared_requirements=(
            DeclaredRequirement(
                RequirementKind.PERMISSION,
                "Needs a new external permission.",
                (customization_id,),
            ),
        ),
    )
    _stage(vault, candidate)

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert any(
        check.name == "trust-permission-delta"
        and check.outcome == "fail"
        for check in report.static_results[0].checks
    )


def test_incomplete_staging_state_cannot_verify_ok(tmp_path: Path) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
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

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "UNKNOWN"


def test_live_target_hardlink_alias_blocks_private_staging(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    live = vault / candidate.files[0].target_path
    live.write_bytes(candidate.files[0].content)
    os.chmod(live, 0o600)
    staged = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "files"
        / candidate.files[0].sha256
    )
    staged.unlink()
    os.link(live, staged)

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert report.staged_paths_private is False


@pytest.mark.parametrize(
    "verification_class",
    (
        VerificationClass.ISOLATED_FIXTURE,
        VerificationClass.READ_ONLY_LIVE,
        VerificationClass.MANUAL,
        VerificationClass.UNSAFE_UNVERIFIED,
    ),
)
def test_unexercised_equivalence_is_unsafe_and_blocks(
    verification_class: VerificationClass,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(
        tmp_path,
        verification_class=verification_class,
    )
    _stage(vault, candidate)

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert report.reported_verifications[0].status == "unknown"
    assert "unsafe-unverified" in (
        report.reported_verifications[0].outcome.evidence_note
    )


def test_required_static_check_cannot_be_disabled_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    monkeypatch.delitem(
        verification_module._STATIC_CHECK_RUNNERS,
        "ownership-authorization",
    )

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert any(
        check.name == "ownership-authorization"
        and check.outcome == "fail"
        for check in report.static_results[0].checks
    )


def test_equal_byte_hardlink_at_another_live_path_blocks_private_staging(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    staged_blob = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "files"
        / candidate.files[0].sha256
    )
    live_alias = vault / "Notes" / "alias.md"
    live_alias.parent.mkdir()
    os.link(staged_blob, live_alias)

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert report.staged_paths_private is False


def test_staging_parent_symlink_swap_during_static_read_blocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    files = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "files"
    )
    moved_files = files.with_name("files-moved")
    original_content_check = verification_module._STATIC_CHECK_RUNNERS[
        "content-digest"
    ]
    swapped = False

    def swap_then_check(context):
        nonlocal swapped
        if not swapped:
            swapped = True
            files.rename(moved_files)
            files.symlink_to(moved_files, target_is_directory=True)
        return original_content_check(context)

    monkeypatch.setitem(
        verification_module._STATIC_CHECK_RUNNERS,
        "content-digest",
        swap_then_check,
    )

    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    assert report.verdict == "BLOCKED"
    assert report.static_results[0].status == "BLOCKED"
    assert report.staged_paths_private is False


def test_writing_report_is_capsule_confined_and_advances_staging_journal(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)
    outside_before = _non_lifecycle_bytes(vault)
    capsule_before = _capsule_bytes(vault, candidate.capsule_id)

    receipt = write_verification_report(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        report,
    )

    capsule_after = _capsule_bytes(vault, candidate.capsule_id)
    changed = {
        path
        for path in capsule_before.keys() | capsule_after.keys()
        if capsule_before.get(path) != capsule_after.get(path)
    }
    report_path = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "verification"
        / f"{candidate.proposal_id}.json"
    )
    assert report_path.read_bytes() == report.canonical_bytes()
    assert receipt.report_path.endswith(
        f"/verification/{candidate.proposal_id}.json"
    )
    assert changed == {
        f"verification/{candidate.proposal_id}.json",
        f"candidates/{candidate.proposal_id}/staging/journal.jsonl",
    }
    assert _non_lifecycle_bytes(vault) == outside_before
    assert read_staging_status(vault, candidate.capsule_id).proposals[0].state is (
        MigrationState.VERIFICATION_PASSED
    )
    assert not (vault / candidate.files[0].target_path).exists()


def test_stale_ok_report_cannot_commit_after_staged_bytes_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)
    staging = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
    )
    journal = staging / "journal.jsonl"
    journal_before = journal.read_bytes()
    blob = staging / "files" / candidate.files[0].sha256
    original_snapshot = Transaction._snapshot_phase

    def tamper_then_snapshot(transaction: Transaction) -> None:
        blob.write_bytes(b"changed after report refresh\n")
        original_snapshot(transaction)

    monkeypatch.setattr(Transaction, "_snapshot_phase", tamper_then_snapshot)

    with pytest.raises(VerificationError, match="drifted"):
        write_verification_report(
            vault,
            candidate.capsule_id,
            candidate.proposal_id,
            report,
        )

    assert journal.read_bytes() == journal_before
    assert not (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "verification"
        / f"{candidate.proposal_id}.json"
    ).exists()


def test_staged_drift_after_engine_verify_cannot_commit_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)
    staging = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
    )
    journal = staging / "journal.jsonl"
    journal_before = journal.read_bytes()
    blob = staging / "files" / candidate.files[0].sha256

    def tamper_after_layout(name: str) -> None:
        if name == "verification-after-layout":
            blob.write_bytes(b"changed after engine verify\n")

    monkeypatch.setattr(
        verification_module,
        "_verification_stop_seam",
        tamper_after_layout,
    )

    with pytest.raises(VerificationError, match="drifted"):
        write_verification_report(
            vault,
            candidate.capsule_id,
            candidate.proposal_id,
            report,
        )

    assert journal.read_bytes() == journal_before
    assert not (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "verification"
        / f"{candidate.proposal_id}.json"
    ).exists()


def test_tampered_persisted_report_projects_recovery_required(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)
    write_verification_report(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        report,
    )
    report_path = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "verification"
        / f"{candidate.proposal_id}.json"
    )
    report_path.write_bytes(b"{}\n")

    status = read_staging_status(vault, candidate.capsule_id)

    assert status.proposals[0].state is MigrationState.RECOVERY_REQUIRED


def test_rehashed_but_schema_invalid_report_is_recovery_required_and_broken(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)
    write_verification_report(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        report,
    )
    capsule = vault / CAPSULE_ROOT / candidate.capsule_id
    report_path = capsule / "verification" / f"{candidate.proposal_id}.json"
    report_path.write_bytes(b"{}\n")
    journal = (
        capsule
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "journal.jsonl"
    )
    records = [
        json.loads(line)
        for line in journal.read_text(encoding="utf-8").splitlines()
    ]
    records[-1]["report_sha256"] = hashlib.sha256(b"{}\n").hexdigest()
    journal.write_bytes(
        b"".join(
            (
                json.dumps(
                    record,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8")
            for record in records
        )
    )

    status = read_staging_status(vault, candidate.capsule_id)
    validation = validate_staging(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )

    assert status.proposals[0].state is MigrationState.RECOVERY_REQUIRED
    assert validation.status == "BROKEN"
    assert "verification/report-schema" in validation.mismatches


@pytest.mark.parametrize("mode_target", ("report", "directory"))
def test_verification_report_modes_are_sealed(
    mode_target: str,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)
    write_verification_report(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        report,
    )
    verification_dir = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "verification"
    )
    report_path = verification_dir / f"{candidate.proposal_id}.json"
    os.chmod(
        report_path if mode_target == "report" else verification_dir,
        0o644 if mode_target == "report" else 0o777,
    )

    status = read_staging_status(vault, candidate.capsule_id)
    validation = validate_staging(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )

    assert status.proposals[0].state is MigrationState.RECOVERY_REQUIRED
    assert validation.status == "BROKEN"
    assert "verification/report-mode" in validation.mismatches


def test_missing_bound_verification_report_is_unknown_not_ok(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)
    write_verification_report(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        report,
    )
    (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "verification"
        / f"{candidate.proposal_id}.json"
    ).unlink()

    status = read_staging_status(vault, candidate.capsule_id)
    validation = validate_staging(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )

    assert status.proposals[0].state is MigrationState.RECOVERY_REQUIRED
    assert validation.status == "UNKNOWN"
    assert "verification/report-missing" in validation.mismatches


def test_existing_verification_report_refuses_without_clobber(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)
    report_path = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "verification"
        / f"{candidate.proposal_id}.json"
    )
    journal = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "journal.jsonl"
    )
    journal_before = journal.read_bytes()
    report_path.parent.mkdir()
    report_path.write_bytes(b"competing verification report\n")

    with pytest.raises(VerificationError, match="already exists"):
        write_verification_report(
            vault,
            candidate.capsule_id,
            candidate.proposal_id,
            report,
        )

    assert report_path.read_bytes() == b"competing verification report\n"
    assert journal.read_bytes() == journal_before


@pytest.mark.parametrize(
    "seam",
    (
        "after-begin",
        "after-snapshot",
        "mid-apply:0",
        "mid-apply:1",
        "after-apply",
        "after-verify",
        "before-finalize",
        "verification-after-layout",
        "verification-mid-finalize",
    ),
)
def test_verification_report_crash_resumes_to_absent_and_staged(
    seam: str,
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)
    report_pickle = tmp_path / "report.pickle"
    report_pickle.write_bytes(pickle.dumps(report))
    staging = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
    )
    journal = staging / "journal.jsonl"
    journal_before = journal.read_bytes()
    script = (
        "from pathlib import Path\n"
        "import pickle,sys\n"
        "from core.customization_migration.verification import "
        "write_verification_report\n"
        "vault=Path(sys.argv[1])\n"
        "report=pickle.loads(Path(sys.argv[2]).read_bytes())\n"
        "write_verification_report("
        "vault,report.capsule_id,report.proposal_id,report)\n"
    )
    environment = dict(os.environ)
    environment["DEX_TX_TEST_STOP_AFTER"] = seam
    environment["PYTHONPATH"] = str(REPO_ROOT)

    child = subprocess.run(
        [sys.executable, "-c", script, str(vault), str(report_pickle)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert child.returncode == 137, (seam, child.stderr[-500:])
    Transaction.resume(vault)
    assert journal.read_bytes() == journal_before
    assert not (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "verification"
        / f"{candidate.proposal_id}.json"
    ).exists()
    assert read_staging_status(vault, candidate.capsule_id).proposals[0].state is (
        MigrationState.REGENERATION_STAGED
    )


def test_blocked_report_advances_journal_to_verification_blocked(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    _stage(vault, candidate)
    staged_blob = (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "candidates"
        / candidate.proposal_id
        / "staging"
        / "files"
        / candidate.files[0].sha256
    )
    staged_blob.write_bytes(b"tampered staged bytes\n")
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)

    write_verification_report(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        report,
    )

    assert report.verdict == "BLOCKED"
    assert read_staging_status(vault, candidate.capsule_id).proposals[0].state is (
        MigrationState.VERIFICATION_BLOCKED
    )
