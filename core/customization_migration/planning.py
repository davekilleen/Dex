"""Pure exact-set validation for future disposition plans."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from core.customization_migration.model import (
    Assessment,
    validate_native_witness_target,
)

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
    native_witness: str | None = None

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
        if self.native_witness is not None:
            validate_native_witness_target(self.native_witness)

    def to_dict(self) -> dict[str, object]:
        return {
            "customization_id": self.customization_id,
            "disposition": self.disposition.value,
            "assessment_digest": self.assessment_digest,
            "native_witness": self.native_witness,
        }


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
    if (
        assessment.baseline_identity_state != "VERIFIED"
        or assessment.completeness != "OK"
        or assessment.verdict != "OK"
    ):
        return PlanValidation(
            False,
            "BROKEN",
            ("assessment is not a verified complete evidence set",),
        )
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
        # A deterministic witness makes the plan validatable, never user-approved.
        # User confirmation belongs to the Lane G consent layer, not model input.
        if (
            item.disposition is Disposition.NATIVE_REPLACEMENT
            and item.native_witness is None
        ):
            errors.append(
                "native-replacement requires a deterministic witness: "
                f"{item.customization_id}"
            )
        elif (
            item.disposition is not Disposition.NATIVE_REPLACEMENT
            and item.native_witness is not None
        ):
            errors.append(
                "only native-replacement accepts a deterministic witness: "
                f"{item.customization_id}"
            )
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
