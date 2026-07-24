"""Deterministic Doctor authority for customization assessment."""

from __future__ import annotations

from collections import Counter

from core.customization_migration.model import (
    Assessment,
    AssessmentGroup,
    CustomizationKind,
    EdgeKind,
    ReferenceConfidence,
)

GROUP_SURFACES = {
    AssessmentGroup.ALREADY_PORTABLE: "These customizations already live in supported extension seams.",
    AssessmentGroup.CAN_BE_REGENERATED: "No regeneration claims are available in this read-only assessment.",
    AssessmentGroup.NEEDS_INTERPRETATION: "These customizations need their purpose or target mapping interpreted.",
    AssessmentGroup.BLOCKED: "These customizations have restricted, excluded, or missing dependency evidence.",
    AssessmentGroup.NO_LONGER_NEEDED: "No retirement claims are available in this read-only assessment.",
}


def assessment_report(assessment: Assessment) -> dict[str, object]:
    """Return strict authority plus the only lines a renderer may rephrase."""
    groups_by_id = {
        assignment.customization_id: assignment.group for assignment in assessment.groups
    }
    kind_counts = Counter(record.kind.value for record in assessment.records)
    group_counts = Counter(assignment.group.value for assignment in assessment.groups)
    edge_kind_counts = Counter(edge.edge_kind.value for edge in assessment.edges)
    confidence_counts = Counter(edge.confidence.value for edge in assessment.edges)
    return {
        "schema_version": assessment.schema_version,
        "identity": assessment.identity.to_dict(),
        "baseline_identity_state": assessment.baseline_identity_state,
        "baseline_errors": list(assessment.baseline_errors),
        "completeness": assessment.completeness,
        "verdict": assessment.verdict,
        "counts": {
            "total": len(assessment.records),
            "kinds": {
                kind.value: kind_counts[kind.value] for kind in CustomizationKind
            },
            "groups": {
                group.value: group_counts[group.value] for group in AssessmentGroup
            },
        },
        "records": [
            {
                "customization_id": record.customization_id,
                "kind": record.kind.value,
                "paths": list(record.source_paths),
                "group": groups_by_id[record.customization_id].value,
                "release_state": record.evidence.release_state,
            }
            for record in assessment.records
        ],
        "edges": {
            "count": len(assessment.edges),
            "by_kind": {
                kind.value: edge_kind_counts[kind.value] for kind in EdgeKind
            },
            "by_confidence": {
                confidence.value: confidence_counts[confidence.value]
                for confidence in ReferenceConfidence
            },
        },
        "exclusions": [item.to_dict() for item in assessment.exclusions],
        "groups": [
            {
                "id": group.value,
                "count": group_counts[group.value],
                "surface": GROUP_SURFACES[group],
            }
            for group in AssessmentGroup
        ],
    }


__all__ = ["assessment_report"]
