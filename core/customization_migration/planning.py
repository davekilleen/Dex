"""Pure exact-set validation for future disposition plans."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from core.customization_migration.model import Assessment

CUSTOMIZATION_ID = re.compile(r"^cust-[0-9a-f]{12}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class Disposition(str, Enum):
    CARRY_FORWARD = "carry-forward"
    REWRITE = "rewrite"
    COMPATIBILITY_SHIM = "compatibility-shim"
    NATIVE_REPLACEMENT = "native-replacement"
    KEEP_DISABLED = "keep-disabled"
    MANUAL_REVIEW = "manual-review"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class DispositionPlanItem:
    customization_id: str
    disposition: Disposition
    assessment_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.customization_id, str)
            or CUSTOMIZATION_ID.fullmatch(self.customization_id) is None
        ):
            raise ValueError("customization_id is not canonical")
        if not isinstance(self.disposition, Disposition):
            raise TypeError("disposition must be a closed Disposition value")
        if (
            not isinstance(self.assessment_digest, str)
            or SHA256.fullmatch(self.assessment_digest) is None
        ):
            raise ValueError("assessment_digest must be canonical SHA-256")


@dataclass(frozen=True)
class PlanValidation:
    accepted: bool
    verdict: str
    errors: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise TypeError("accepted must be a boolean")
        if self.verdict not in {"OK", "BROKEN"}:
            raise ValueError("plan validation verdict must be OK or BROKEN")
        if not isinstance(self.errors, tuple):
            raise TypeError("plan validation errors must be a tuple")
        if self.accepted != (self.verdict == "OK" and not self.errors):
            raise ValueError("plan validation fields are contradictory")


def validate_disposition_plan(
    assessment: Assessment,
    plan_items: Iterable[DispositionPlanItem],
) -> PlanValidation:
    """Refuse any plan whose ids are not an exact set or whose evidence drifted."""
    if not isinstance(assessment, Assessment):
        raise TypeError("assessment must be Assessment")
    items = tuple(plan_items)
    if any(type(item) is not DispositionPlanItem for item in items):
        raise TypeError("plan_items must contain DispositionPlanItem records")
    expected_ids = {record.customization_id for record in assessment.records}
    counts = Counter(item.customization_id for item in items)
    actual_digest = hashlib.sha256(assessment.canonical_assessment_bytes()).hexdigest()
    errors: list[str] = []
    for customization_id in sorted(expected_ids - counts.keys()):
        errors.append(f"missing customization id: {customization_id}")
    for customization_id in sorted(
        customization_id for customization_id, count in counts.items() if count > 1
    ):
        errors.append(f"duplicate customization id: {customization_id}")
    for customization_id in sorted(counts.keys() - expected_ids):
        errors.append(f"unknown customization id: {customization_id}")
    for item in items:
        if item.assessment_digest != actual_digest:
            errors.append(f"assessment digest mismatch for {item.customization_id}")
    ordered_errors = tuple(dict.fromkeys(errors))
    return PlanValidation(
        not ordered_errors,
        "OK" if not ordered_errors else "BROKEN",
        ordered_errors,
    )


__all__ = [
    "Disposition",
    "DispositionPlanItem",
    "PlanValidation",
    "validate_disposition_plan",
]
