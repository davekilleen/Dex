"""Write-free regeneration-candidate validation contracts."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from core.customization_migration.behaviour import (
    BehaviouralContract,
    ContractProvenance,
    VerificationClass,
)
from core.customization_migration.planning import (
    CandidateFile,
    DependencyRemapping,
    DependencyResolution,
    Disposition,
    DispositionPlanItem,
    RegenerationCandidate,
    ShimExpiry,
    validate_regeneration_candidate,
)
from core.customization_migration.service import assess
from core.tests.test_customization_assessment import _linked_customized_vault

CAPSULE_ID = "cap-0123456789abcdef"
PROPOSAL_ID = "prop-0123456789abcdef"


def _candidate_parts(tmp_path: Path):
    vault = _linked_customized_vault(tmp_path)
    assessment = assess(vault)
    digest = hashlib.sha256(assessment.canonical_assessment_bytes()).hexdigest()
    record = next(
        candidate
        for candidate in assessment.records
        if any(edge.source_path in candidate.source_paths for edge in assessment.edges)
    )
    owned_edges = tuple(
        edge
        for edge in assessment.edges
        if edge.source_path in record.source_paths
    )
    dispositions = tuple(
        sorted(
            (
                DispositionPlanItem(
                    candidate.customization_id,
                    Disposition.REWRITE
                    if candidate.customization_id == record.customization_id
                    else Disposition.MANUAL_REVIEW,
                    digest,
                    evidence_edge_ids=(owned_edges[0].edge_id,)
                    if candidate.customization_id == record.customization_id
                    else (),
                )
                for candidate in assessment.records
            ),
            key=lambda item: item.customization_id,
        )
    )
    candidate_file = CandidateFile.create(
        "CLAUDE-custom.md",
        b"# Migrated customization\n",
        (record.customization_id,),
    )
    remappings = tuple(
        DependencyRemapping(edge.edge_id, DependencyResolution.PRESERVE)
        for edge in owned_edges
    )
    return vault, assessment, record, dispositions, candidate_file, remappings


def _candidate(tmp_path: Path, **overrides: object):
    vault, assessment, record, dispositions, candidate_file, remappings = _candidate_parts(
        tmp_path
    )
    values: dict[str, object] = {
        "schema_version": 0,
        "proposal_id": PROPOSAL_ID,
        "capsule_id": CAPSULE_ID,
        "evidence_digest": hashlib.sha256(
            assessment.canonical_assessment_bytes()
        ).hexdigest(),
        "dispositions": dispositions,
        "files": (candidate_file,),
        "dependency_remappings": remappings,
        "behaviour_contracts": (),
        "declared_requirements": (),
        "confidence": 100,
        "unresolved_questions": (),
        "shim_expiries": (),
    }
    values.update(overrides)
    return vault, assessment, record, RegenerationCandidate(**values)


def test_complete_candidate_is_validated_without_writing_to_the_vault(
    tmp_path: Path,
) -> None:
    vault, assessment, _record, candidate = _candidate(tmp_path)

    validation = validate_regeneration_candidate(
        assessment,
        candidate,
        expected_capsule_id=CAPSULE_ID,
    )

    assert validation.accepted is True
    assert validation.verdict == "OK"
    assert validation.candidate_sha256 == candidate.candidate_sha256
    assert not (vault / "CLAUDE-custom.md").exists()
    assert not (vault / "System/.dex/customization-migrations").exists()


def test_rewrite_requires_captured_evidence_from_its_own_customization(
    tmp_path: Path,
) -> None:
    _vault, assessment, record, candidate = _candidate(tmp_path)
    without_evidence = tuple(
        replace(item, evidence_edge_ids=())
        if item.customization_id == record.customization_id
        else item
        for item in candidate.dispositions
    )
    candidate = replace(candidate, dispositions=without_evidence)

    validation = validate_regeneration_candidate(assessment, candidate)

    assert validation.accepted is False
    assert (
        f"rewrite requires captured dependency evidence: {record.customization_id}"
        in validation.errors
    )


def test_generated_content_requires_an_explicit_resolution_for_every_dependency(
    tmp_path: Path,
) -> None:
    _vault, assessment, record, candidate = _candidate(tmp_path)
    candidate = replace(
        candidate,
        dependency_remappings=candidate.dependency_remappings[:-1],
    )

    validation = validate_regeneration_candidate(assessment, candidate)

    assert validation.accepted is False
    assert any(
        error.startswith(
            f"generated customization has unresolved dependency: {record.customization_id}:"
        )
        for error in validation.errors
    )


def test_generated_content_cannot_be_attached_to_a_native_replacement(
    tmp_path: Path,
) -> None:
    _vault, assessment, record, candidate = _candidate(tmp_path)
    native_plan = tuple(
        replace(
            item,
            disposition=Disposition.NATIVE_REPLACEMENT,
            native_witness="skill:daily-plan",
            evidence_edge_ids=(),
        )
        if item.customization_id == record.customization_id
        else item
        for item in candidate.dispositions
    )
    candidate = replace(
        candidate,
        dispositions=native_plan,
        dependency_remappings=(),
    )

    validation = validate_regeneration_candidate(assessment, candidate)

    assert validation.accepted is False
    assert (
        f"disposition may not propose candidate content: {record.customization_id}"
        in validation.errors
    )


def test_generated_disposition_requires_complete_candidate_bytes(tmp_path: Path) -> None:
    _vault, assessment, record, candidate = _candidate(tmp_path)
    candidate = replace(candidate, files=())

    validation = validate_regeneration_candidate(assessment, candidate)

    assert validation.accepted is False
    assert (
        f"generated disposition has no candidate content: {record.customization_id}"
        in validation.errors
    )


def test_candidate_target_collision_is_rejected_before_any_staging(tmp_path: Path) -> None:
    _vault, _assessment, _record, candidate = _candidate(tmp_path)
    colliding_file = CandidateFile.create(
        "CLAUDE-custom.md",
        b"# Different proposed bytes\n",
        candidate.files[0].customization_ids,
    )

    with pytest.raises(ValueError, match="files must be sorted and unique"):
        replace(candidate, files=(candidate.files[0], colliding_file))


def test_compatibility_shim_requires_a_release_bound_removal_plan(
    tmp_path: Path,
) -> None:
    _vault, assessment, record, candidate = _candidate(tmp_path)
    shim_plan = tuple(
        replace(item, disposition=Disposition.COMPATIBILITY_SHIM)
        if item.customization_id == record.customization_id
        else item
        for item in candidate.dispositions
    )
    candidate = replace(candidate, dispositions=shim_plan)

    validation = validate_regeneration_candidate(assessment, candidate)

    assert validation.accepted is False
    assert f"compatibility-shim needs expiry: {record.customization_id}" in validation.errors

    candidate = replace(
        candidate,
        shim_expiries=(
            ShimExpiry(
                record.customization_id,
                "1.76.0",
                "Remove after the native replacement has an approved receipt.",
            ),
        ),
    )
    validation = validate_regeneration_candidate(assessment, candidate)

    assert validation.accepted is True


def test_candidate_binds_to_the_selected_capsule_and_its_candidate_bytes(tmp_path: Path) -> None:
    _vault, assessment, _record, candidate = _candidate(tmp_path)

    mismatched = validate_regeneration_candidate(
        assessment,
        candidate,
        expected_capsule_id="cap-fedcba9876543210",
    )
    changed_content = CandidateFile.create(
        "CLAUDE-custom.md",
        b"# Different regenerated content\n",
        candidate.files[0].customization_ids,
    )
    changed = replace(candidate, files=(changed_content,))

    assert mismatched.accepted is False
    assert "candidate capsule id does not match the selected capsule" in mismatched.errors
    assert changed.candidate_sha256 != candidate.candidate_sha256


def test_behaviour_contract_mapping_does_not_upgrade_model_proposal_to_verified(
    tmp_path: Path,
) -> None:
    _vault, assessment, record, candidate = _candidate(tmp_path)
    contract = BehaviouralContract.create(
        record.customization_id,
        "The new helper preserves the captured fixture output.",
        ContractProvenance.MODEL_PROPOSED,
        VerificationClass.ISOLATED_FIXTURE,
    )
    mapped_plans = tuple(
        replace(item, behaviour_contract_ids=(contract.contract_id,))
        if item.customization_id == record.customization_id
        else item
        for item in candidate.dispositions
    )
    candidate = replace(
        candidate,
        dispositions=mapped_plans,
        behaviour_contracts=(contract,),
    )

    validation = validate_regeneration_candidate(assessment, candidate)

    assert validation.accepted is True
    assert contract.provenance is ContractProvenance.MODEL_PROPOSED


def test_unsupported_and_protected_candidate_targets_are_refused() -> None:
    with pytest.raises(ValueError, match="supported customization seam"):
        CandidateFile.create(
            "core/customization_migration/unsafe.py",
            b"unsafe\n",
            ("cust-0123456789ab",),
        )
    with pytest.raises(ValueError, match="protected migration artifacts"):
        CandidateFile.create(
            "System/.dex/customization-migrations/cap-0123456789abcdef/staging/x.py",
            b"unsafe\n",
            ("cust-0123456789ab",),
        )
