"""Public read-only customization assessment service."""

from __future__ import annotations

from pathlib import Path

from core.customization_migration.inventory import discover
from core.customization_migration.model import Assessment, AssessmentIdentity


def assess(vault_root: Path) -> Assessment:
    """Assess one vault entirely in memory; never cache or mutate it."""
    discovery = discover(Path(vault_root))
    completeness = "OK" if discovery.complete else "UNKNOWN"
    return Assessment(
        1,
        AssessmentIdentity(
            discovery.inventory.baseline.release_version,
            len(discovery.inventory.entries),
            len(discovery.records),
            len(discovery.edges),
        ),
        discovery.inventory.baseline.identity_state,
        discovery.inventory.baseline.errors,
        discovery.records,
        discovery.edges,
        discovery.groups,
        discovery.exclusions,
        completeness,
        "OK" if completeness == "OK" else "UNKNOWN",
    )


def assessment_to_dict(assessment: Assessment) -> dict[str, object]:
    if not isinstance(assessment, Assessment):
        raise TypeError("assessment must be Assessment")
    return assessment.to_dict()


__all__ = ["assess", "assessment_to_dict"]
