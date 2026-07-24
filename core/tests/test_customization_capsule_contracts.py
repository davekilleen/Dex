"""Closed contracts for customization capsules and migration state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from core.customization_migration.behaviour import (
    BehaviouralContract,
    ContractProvenance,
    ReportedVerification,
    VerificationClass,
    VerificationOutcome,
    derive_reported_status,
)
from core.customization_migration.capsule_model import (
    CAPSULE_LAYOUT_V0,
    CapsuleManifest,
)
from core.customization_migration.model import (
    Assessment,
    AssessmentAssignment,
    AssessmentGroup,
    AssessmentIdentity,
    BaselineInfo,
    CustomizationEvidence,
    CustomizationKind,
    CustomizationRecord,
    LiveInfo,
)
from core.customization_migration.planning import (
    Disposition,
    DispositionPlanItem,
    validate_disposition_plan,
)
from core.customization_migration.sensitivity import capsule_readability
from core.customization_migration.state import (
    ALLOWED_TRANSITIONS,
    MigrationEvent,
    MigrationState,
    is_allowed_transition,
    project_state,
    validate_transition,
)

CUSTOMIZATION_ID = "cust-0123456789ab"
ASSESSMENT_DIGEST = "a" * 64


def _contract(
    provenance: ContractProvenance = ContractProvenance.DETERMINISTIC,
) -> BehaviouralContract:
    return BehaviouralContract.create(
        CUSTOMIZATION_ID,
        "The customization preserves its deterministic fixture output.",
        provenance,
        VerificationClass.ISOLATED_FIXTURE,
    )


def _manifest(**overrides: object) -> CapsuleManifest:
    values: dict[str, object] = {
        "schema_version": 0,
        "capsule_id": "cap-0123456789abcdef",
        "source_release_version": "1.75.1",
        "target_release_version": None,
        "created_epoch_seconds": 1,
        "inventory_digest": "1" * 64,
        "assessment_digest": "2" * 64,
        "customization_count": 1,
        "dependency_count": 2,
        "behaviour_contract_count": 3,
        "restricted_item_count": 1,
        "excluded_reasons": ("restricted",),
        "completeness": "OK",
        "section_digests": (
            ("behaviours", "3" * 64, 30),
            ("customizations", "4" * 64, 40),
        ),
    }
    values.update(overrides)
    return CapsuleManifest(**values)  # type: ignore[arg-type]


def _assessment() -> Assessment:
    record = CustomizationRecord.create(
        CustomizationKind.MODIFIED_SHIPPED_FILE,
        (".claude/example.md",),
        BaselineInfo("1.75.1", "b" * 64),
        LiveInfo("c" * 64, 1, "readable"),
        CustomizationEvidence("stock-modified", ()),
    )
    return Assessment(
        schema_version=0,
        identity=AssessmentIdentity("1.75.1", 1, 1, 0),
        baseline_identity_state="VERIFIED",
        baseline_errors=(),
        incomplete_reasons=(),
        records=(record,),
        edges=(),
        groups=(
            AssessmentAssignment(
                record.customization_id,
                AssessmentGroup.UPDATE_REPLACEABLE_LOCATION,
            ),
        ),
        exclusions=(),
        completeness="OK",
        verdict="OK",
    )


def _plan_items(assessment) -> list[DispositionPlanItem]:
    digest = hashlib.sha256(assessment.canonical_assessment_bytes()).hexdigest()
    return [
        DispositionPlanItem(
            record.customization_id,
            Disposition.MANUAL_REVIEW,
            digest,
        )
        for record in assessment.records
    ]


def test_model_proposed_contract_cannot_be_reported_verified() -> None:
    contract = _contract(ContractProvenance.MODEL_PROPOSED)
    outcome = VerificationOutcome(contract.contract_id, "pass", "")

    with pytest.raises(ValueError, match="only legal reported status"):
        ReportedVerification(contract, outcome, "verified")

    assert (
        ReportedVerification(contract, outcome, "model-claimed-pass").status
        == "model-claimed-pass"
    )


@pytest.mark.parametrize(
    ("provenance", "outcome", "expected"),
    [
        (ContractProvenance.DETERMINISTIC, "pass", "verified"),
        (ContractProvenance.DETERMINISTIC, "fail", "failed"),
        (ContractProvenance.DETERMINISTIC, "unknown", "unknown"),
        (ContractProvenance.USER_CONFIRMED, "pass", "verified"),
        (ContractProvenance.USER_CONFIRMED, "fail", "failed"),
        (ContractProvenance.USER_CONFIRMED, "unknown", "unknown"),
        (ContractProvenance.MODEL_PROPOSED, "pass", "model-claimed-pass"),
        (ContractProvenance.MODEL_PROPOSED, "fail", "failed"),
        (ContractProvenance.MODEL_PROPOSED, "unknown", "unknown"),
    ],
)
def test_derive_reported_status_truth_table(
    provenance: ContractProvenance,
    outcome: str,
    expected: str,
) -> None:
    contract = _contract(provenance)
    result = VerificationOutcome(contract.contract_id, outcome, "fixture")

    assert derive_reported_status(contract, result) == expected


def test_behaviour_contract_id_is_stable_and_statement_bound() -> None:
    first = _contract()
    second = _contract()
    changed = BehaviouralContract.create(
        CUSTOMIZATION_ID,
        first.statement + " Changed.",
        first.provenance,
        first.verification_class,
    )

    assert first.contract_id == second.contract_id
    assert first.contract_id.startswith("beh-")
    assert changed.contract_id != first.contract_id


def test_behaviour_contract_id_binds_provenance_and_verification_class() -> None:
    statement = "The customization preserves its deterministic fixture output."
    deterministic = BehaviouralContract.create(
        CUSTOMIZATION_ID,
        statement,
        ContractProvenance.DETERMINISTIC,
        VerificationClass.ISOLATED_FIXTURE,
    )
    model_proposed = BehaviouralContract.create(
        CUSTOMIZATION_ID,
        statement,
        ContractProvenance.MODEL_PROPOSED,
        VerificationClass.MANUAL,
    )

    assert deterministic.contract_id != model_proposed.contract_id


def test_migration_state_vocabulary_and_transition_matrix_are_exact() -> None:
    assert {state.value for state in MigrationState} == {
        "not-assessed",
        "assessment-ready",
        "capsule-previewed",
        "capsule-created",
        "target-ready",
        "regeneration-proposed",
        "regeneration-staged",
        "verification-passed",
        "verification-blocked",
        "activation-previewed",
        "activated",
        "rewound",
        "abandoned",
        "recovery-required",
        "unknown",
    }
    expected = frozenset(
        {
            (MigrationState.NOT_ASSESSED, MigrationState.ASSESSMENT_READY),
            (MigrationState.ASSESSMENT_READY, MigrationState.CAPSULE_PREVIEWED),
            (MigrationState.CAPSULE_PREVIEWED, MigrationState.CAPSULE_CREATED),
            (MigrationState.CAPSULE_CREATED, MigrationState.TARGET_READY),
            (MigrationState.TARGET_READY, MigrationState.REGENERATION_PROPOSED),
            (
                MigrationState.REGENERATION_PROPOSED,
                MigrationState.REGENERATION_STAGED,
            ),
            (
                MigrationState.REGENERATION_STAGED,
                MigrationState.VERIFICATION_PASSED,
            ),
            (
                MigrationState.REGENERATION_STAGED,
                MigrationState.VERIFICATION_BLOCKED,
            ),
            (
                MigrationState.VERIFICATION_BLOCKED,
                MigrationState.REGENERATION_PROPOSED,
            ),
            (
                MigrationState.VERIFICATION_PASSED,
                MigrationState.ACTIVATION_PREVIEWED,
            ),
            (MigrationState.ACTIVATION_PREVIEWED, MigrationState.ACTIVATED),
            (MigrationState.ACTIVATED, MigrationState.REWOUND),
            (MigrationState.ASSESSMENT_READY, MigrationState.ABANDONED),
            (MigrationState.CAPSULE_CREATED, MigrationState.ABANDONED),
        }
    )

    assert ALLOWED_TRANSITIONS == expected
    for current in MigrationState:
        for target in MigrationState:
            assert is_allowed_transition(current, target) == (
                (current, target) in expected
            )
            if (current, target) in expected:
                assert validate_transition(current, target) is None
            else:
                with pytest.raises(ValueError):
                    validate_transition(current, target)


def test_state_projection_happy_path_to_activated_and_rewound() -> None:
    activated = (
        MigrationEvent.ASSESSED,
        MigrationEvent.CAPSULE_PREVIEWED,
        MigrationEvent.CAPSULE_CREATED,
        MigrationEvent.TARGET_VERIFIED,
        MigrationEvent.REGENERATION_PROPOSED,
        MigrationEvent.REGENERATION_STAGED,
        MigrationEvent.VERIFICATION_PASSED,
        MigrationEvent.ACTIVATION_PREVIEWED,
        MigrationEvent.ACTIVATED,
    )

    assert project_state(event.value for event in activated) is MigrationState.ACTIVATED
    assert (
        project_state([*(event.value for event in activated), "rewound"])
        is MigrationState.REWOUND
    )


@pytest.mark.parametrize(
    "events",
    [
        ["not-a-v0-event"],
        ["capsule-created"],
        ["assessed", "abandoned", "capsule-previewed"],
    ],
)
def test_bad_journal_evidence_projects_to_recovery_required(
    events: list[str],
) -> None:
    assert project_state(events) is MigrationState.RECOVERY_REQUIRED


def test_empty_journal_projects_to_not_assessed() -> None:
    assert project_state(()) is MigrationState.NOT_ASSESSED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 1),
        ("inventory_digest", "not-a-digest"),
        ("customization_count", -1),
        ("section_digests", (("not-a-section", "3" * 64, 30),)),
        ("section_digests", (("behaviours", "3" * 64, -1),)),
    ],
)
def test_capsule_manifest_refuses_open_or_invalid_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        _manifest(**{field: value})


def test_capsule_manifest_canonical_bytes_round_trip_stably() -> None:
    manifest = _manifest()
    emitted = manifest.to_dict()
    rebuilt = CapsuleManifest(
        schema_version=emitted["schema_version"],
        capsule_id=emitted["capsule_id"],
        source_release_version=emitted["source_release_version"],
        target_release_version=emitted["target_release_version"],
        created_epoch_seconds=emitted["created_epoch_seconds"],
        inventory_digest=emitted["inventory_digest"],
        assessment_digest=emitted["assessment_digest"],
        customization_count=emitted["customization_count"],
        dependency_count=emitted["dependency_count"],
        behaviour_contract_count=emitted["behaviour_contract_count"],
        restricted_item_count=emitted["restricted_item_count"],
        excluded_reasons=tuple(emitted["excluded_reasons"]),
        completeness=emitted["completeness"],
        section_digests=tuple(
            (entry["section_name"], entry["sha256"], entry["byte_size"])
            for entry in emitted["section_digests"]
        ),
    )

    assert rebuilt.canonical_manifest_bytes() == manifest.canonical_manifest_bytes()
    assert json.loads(manifest.canonical_manifest_bytes()) == emitted
    assert {"digest", "manifest_digest", "capsule_digest"}.isdisjoint(emitted)


def test_capsule_layout_v0_is_frozen_and_exact() -> None:
    assert CAPSULE_LAYOUT_V0 == (
        "manifest.json",
        "journal.jsonl",
        "evidence/",
        "blobs/",
        "restricted/",
        "interpretations/",
        "candidates/",
        "verification/",
        "receipts/",
        "report.md",
    )
    with pytest.raises(TypeError):
        CAPSULE_LAYOUT_V0[0] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    "path",
    [
        ".mcp.json",
        "System/integrations/config.yaml",
        ".claude/settings.json",
        "MyKey.PEM",
    ],
)
def test_credential_bearing_or_denied_paths_are_restricted(path: str) -> None:
    assert capsule_readability(path) == "restricted"


@pytest.mark.parametrize(
    "path",
    [
        "./.mcp.json",
        ".claude/./settings.json",
        "dir/../System/integrations/c.yaml",
        "sub/../.mcp.json",
        "..",
        "../x",
    ],
)
def test_traversal_or_dot_paths_are_restricted(path: str) -> None:
    assert capsule_readability(path) == "restricted"


def test_normal_content_is_capsule_readable() -> None:
    assert capsule_readability("04-Projects/x.md") == "readable"


def test_restricted_fixture_content_never_enters_contract_output() -> None:
    canary = "sk-FAKE123LEAKCANARY"
    restricted_fixture = {".mcp.json": canary}
    assert capsule_readability(next(iter(restricted_fixture))) == "restricted"
    contract = _contract()
    manifest = _manifest()
    item = DispositionPlanItem(
        CUSTOMIZATION_ID,
        Disposition.NATIVE_REPLACEMENT,
        ASSESSMENT_DIGEST,
        ".mcp.json",
    )
    outputs = (
        json.dumps(contract.to_dict(), sort_keys=True),
        manifest.canonical_manifest_bytes().decode("utf-8"),
        json.dumps(item.to_dict(), sort_keys=True),
    )

    assert all(canary not in output for output in outputs)


def test_native_replacement_without_witness_is_refused() -> None:
    assessment = _assessment()
    items = _plan_items(assessment)
    items[0] = DispositionPlanItem(
        items[0].customization_id,
        Disposition.NATIVE_REPLACEMENT,
        items[0].assessment_digest,
    )

    validation = validate_disposition_plan(assessment, items)

    assert validation.errors == (
        f"native-replacement requires a deterministic witness: {items[0].customization_id}",
    )


def test_witness_on_other_disposition_is_refused() -> None:
    assessment = _assessment()
    items = _plan_items(assessment)
    items[0] = DispositionPlanItem(
        items[0].customization_id,
        Disposition.MANUAL_REVIEW,
        items[0].assessment_digest,
        "skill:daily-plan",
    )

    validation = validate_disposition_plan(assessment, items)

    assert validation.errors == (
        f"only native-replacement accepts a deterministic witness: {items[0].customization_id}",
    )


@pytest.mark.parametrize(
    "witness",
    [
        "",
        "../escape",
        "/absolute",
        "skill:Uppercase",
        "env:API_KEY",
        "outside-vault:absolute",
    ],
)
def test_native_witness_grammar_is_closed(witness: str) -> None:
    with pytest.raises(ValueError):
        DispositionPlanItem(
            CUSTOMIZATION_ID,
            Disposition.NATIVE_REPLACEMENT,
            ASSESSMENT_DIGEST,
            witness,
        )


def test_contract_records_are_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        _contract().statement = "changed"  # type: ignore[misc]
