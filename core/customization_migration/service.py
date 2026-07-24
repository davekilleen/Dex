"""Public read-only customization assessment service."""

from __future__ import annotations

from pathlib import Path

from core.customization_migration.inventory import discover
from core.customization_migration.model import Assessment, AssessmentIdentity


def assess(vault_root: Path) -> Assessment:
    """Assess one vault entirely in memory; never cache or mutate it."""
    discovery = discover(Path(vault_root))
    inventory = discovery.inventory
    folder_map_state = getattr(
        getattr(inventory, "folder_map", None),
        "state",
        "DEFAULT",
    )
    walk_truncated = (
        "filesystem inventory reached its configured entry bound"
        in inventory.errors
    )
    reasons: set[str] = set()
    if inventory.baseline.identity_state != "VERIFIED":
        reasons.add("baseline-not-verified")
    if not inventory.complete:
        reasons.add("inventory-incomplete")
    if folder_map_state == "UNKNOWN":
        reasons.add("folder-map-unknown")
    if walk_truncated:
        reasons.add("walk-truncated")
    if any(
        exclusion.reason != "embedded-secret"
        for exclusion in discovery.exclusions
    ):
        reasons.add("assessment-exclusions")
    if inventory.errors and inventory.baseline.identity_state == "VERIFIED":
        reasons.add("inventory-errors")
    proved_complete = (
        inventory.baseline.identity_state == "VERIFIED"
        and inventory.complete
        and folder_map_state != "UNKNOWN"
        and not walk_truncated
        and discovery.complete
    )
    if not proved_complete and not reasons:
        reasons.add("inventory-incomplete")
    completeness = "OK" if proved_complete else "UNKNOWN"
    public_records = discovery.records if completeness == "OK" else ()
    public_edges = discovery.edges if completeness == "OK" else ()
    public_groups = discovery.groups if completeness == "OK" else ()
    return Assessment(
        0,
        AssessmentIdentity(
            inventory.baseline.release_version,
            len(inventory.entries) if completeness == "OK" else 0,
            len(public_records),
            len(public_edges),
        ),
        inventory.baseline.identity_state,
        inventory.baseline.errors,
        tuple(sorted(reasons)),
        public_records,
        public_edges,
        public_groups,
        discovery.exclusions,
        completeness,
        "OK" if completeness == "OK" else "UNKNOWN",
    )


def assessment_to_dict(assessment: Assessment) -> dict[str, object]:
    if not isinstance(assessment, Assessment):
        raise TypeError("assessment must be Assessment")
    return assessment.to_dict()


__all__ = ["assess", "assessment_to_dict"]
