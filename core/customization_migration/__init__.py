"""Read-only customization assessment public interface."""

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
    Disposition,
    DispositionPlanItem,
    PlanValidation,
    validate_disposition_plan,
)
from core.customization_migration.report import assessment_report
from core.customization_migration.service import assess, assessment_to_dict

__all__ = [
    "Assessment",
    "AssessmentAssignment",
    "AssessmentExclusion",
    "AssessmentGroup",
    "AssessmentIdentity",
    "BaselineInfo",
    "CustomizationEvidence",
    "CustomizationKind",
    "CustomizationRecord",
    "Disposition",
    "DispositionPlanItem",
    "EdgeKind",
    "LiveInfo",
    "PlanValidation",
    "ReferenceConfidence",
    "ReferenceEdge",
    "assess",
    "assessment_report",
    "assessment_to_dict",
    "validate_disposition_plan",
]
