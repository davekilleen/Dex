"""Dex release-catalog and lifecycle contracts.

B1 is deliberately read-only: it models release contents and declares handler
plans. Mutation remains owned by :mod:`core.transaction` in later chunks.
"""

from core.lifecycle.model import AdoptionState, CatalogItem, ReleaseCatalog
from core.lifecycle.plan import AdoptionPlan, AdoptionPlanItem, PlannedAction, build_adoption_plan

__all__ = [
    "AdoptionPlan",
    "AdoptionPlanItem",
    "AdoptionState",
    "CatalogItem",
    "PlannedAction",
    "ReleaseCatalog",
    "build_adoption_plan",
]
