"""Read-only customization assessment public interface."""

from core.customization_migration.behaviour import (
    BehaviouralContract,
    ContractProvenance,
    ReportedVerification,
    VerificationClass,
    VerificationOutcome,
    derive_reported_status,
)
from core.customization_migration.capsule import (
    CAPSULE_ROOT,
    CapsuleError,
    CapsulePreview,
    CapsuleReceipt,
    CapsuleStatus,
    CapsuleValidation,
    MigrationStatus,
    PlannedCapsuleFile,
    abandon_capsule,
    create_capsule,
    preview_capsule,
    read_capsule_status,
    validate_capsule,
)
from core.customization_migration.capsule_model import (
    CAPSULE_ID,
    CAPSULE_LAYOUT_V0,
    EVIDENCE_SECTIONS_V0,
    CapsuleManifest,
)
from core.customization_migration.model import (
    Assessment,
    AssessmentAssignment,
    AssessmentExclusion,
    AssessmentGroup,
    AssessmentIdentity,
    BaselineInfo,
    CustomizationEvidence,
    CustomizationKind,
    CustomizationRecord,
    EdgeKind,
    LiveInfo,
    ReferenceConfidence,
    ReferenceEdge,
)
from core.customization_migration.planning import (
    CandidateFile,
    CandidateValidation,
    DeclaredRequirement,
    DependencyRemapping,
    DependencyResolution,
    Disposition,
    DispositionPlanItem,
    PlanValidation,
    RegenerationCandidate,
    RequirementKind,
    ShimExpiry,
    validate_disposition_plan,
    validate_regeneration_candidate,
)
from core.customization_migration.report import assessment_report
from core.customization_migration.sensitivity import (
    CREDENTIAL_BEARING_CONFIGS,
    SECRET_ARCHIVAL_POLICY,
    capsule_readability,
)
from core.customization_migration.service import assess, assessment_to_dict
from core.customization_migration.staging import (
    STAGING_SUBDIR,
    PlannedStagedFile,
    ProposalStagingStatus,
    StagingError,
    StagingPreview,
    StagingReceipt,
    StagingStatus,
    StagingValidation,
    load_staged_candidate,
    preview_staging,
    read_staging_status,
    stage_candidate,
    validate_staging,
)
from core.customization_migration.state import (
    ALLOWED_TRANSITIONS,
    MigrationEvent,
    MigrationState,
    is_allowed_transition,
    project_state,
    validate_transition,
)

_LAZY_VERIFICATION_EXPORTS = frozenset(
    {
        "StaticFileResult",
        "VerificationAttempt",
        "VerificationCheckOutcome",
        "VerificationError",
        "VerificationReport",
        "VerificationWriteReceipt",
        "verify_staging",
        "write_verification_report",
    }
)


def __getattr__(name: str) -> object:
    if name not in _LAZY_VERIFICATION_EXPORTS:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )
    from core.customization_migration import verification

    value = getattr(verification, name)
    globals()[name] = value
    return value

__all__ = [
    "Assessment",
    "AssessmentAssignment",
    "AssessmentExclusion",
    "AssessmentGroup",
    "AssessmentIdentity",
    "ALLOWED_TRANSITIONS",
    "BaselineInfo",
    "BehaviouralContract",
    "CandidateFile",
    "CandidateValidation",
    "CAPSULE_ID",
    "CAPSULE_LAYOUT_V0",
    "CREDENTIAL_BEARING_CONFIGS",
    "CapsuleManifest",
    "CapsuleError",
    "CapsulePreview",
    "CapsuleReceipt",
    "CapsuleStatus",
    "CapsuleValidation",
    "ContractProvenance",
    "CustomizationEvidence",
    "CustomizationKind",
    "CustomizationRecord",
    "DeclaredRequirement",
    "DependencyRemapping",
    "DependencyResolution",
    "Disposition",
    "DispositionPlanItem",
    "EVIDENCE_SECTIONS_V0",
    "EdgeKind",
    "LiveInfo",
    "MigrationEvent",
    "MigrationState",
    "MigrationStatus",
    "PlanValidation",
    "PlannedCapsuleFile",
    "PlannedStagedFile",
    "ProposalStagingStatus",
    "RegenerationCandidate",
    "ReferenceConfidence",
    "ReferenceEdge",
    "ReportedVerification",
    "RequirementKind",
    "SECRET_ARCHIVAL_POLICY",
    "STAGING_SUBDIR",
    "ShimExpiry",
    "StagingError",
    "StagingPreview",
    "StagingReceipt",
    "StagingStatus",
    "StagingValidation",
    "StaticFileResult",
    "VerificationAttempt",
    "VerificationCheckOutcome",
    "VerificationClass",
    "VerificationError",
    "VerificationOutcome",
    "VerificationReport",
    "VerificationWriteReceipt",
    "assess",
    "abandon_capsule",
    "assessment_report",
    "assessment_to_dict",
    "capsule_readability",
    "create_capsule",
    "derive_reported_status",
    "is_allowed_transition",
    "load_staged_candidate",
    "project_state",
    "preview_capsule",
    "preview_staging",
    "read_capsule_status",
    "read_staging_status",
    "stage_candidate",
    "validate_transition",
    "validate_disposition_plan",
    "validate_regeneration_candidate",
    "validate_capsule",
    "validate_staging",
    "verify_staging",
    "write_verification_report",
    "CAPSULE_ROOT",
]
