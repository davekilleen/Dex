"""Adapter from the existing Doctor collector to the reporter contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from core.utils import doctor

from .reporter import (
    CONTRACT,
    DEFAULT_CHECK_VERSION,
    MAX_DETAIL_LENGTH,
    NormalizationResult,
    ReporterIdentity,
    ReporterSpec,
    _bounded_text,
    normalize_report,
)

if TYPE_CHECKING:
    from .snapshot import HealthSnapshot, HealthStore

DOCTOR_REPORTER_IDENTITY = ReporterIdentity(
    namespace="doctor.core",
    id="doctor",
    version="1.0.0",
)
DOCTOR_REPORTER_SPEC = ReporterSpec(
    identity=DOCTOR_REPORTER_IDENTITY,
    checks=tuple(
        (definition.id, DEFAULT_CHECK_VERSION)
        for definition in (*doctor.QUICK_CHECKS, *doctor.DEEP_CHECKS)
    ),
)


def from_doctor_report(
    report: Mapping[str, Any],
    *,
    refresh_id: str,
) -> NormalizationResult:
    """Normalize a complete existing Doctor report for proactive health.

    Doctor's legacy ``heal`` and ``user_message`` fields are intentionally not
    copied into this envelope.  They remain owned by Doctor and are reached via
    the later structured handoff contract.
    """

    checks = report.get("checks") if isinstance(report, Mapping) else None
    raw_results: list[object]
    if isinstance(checks, list):
        raw_results = []
        for check in checks:
            if not isinstance(check, Mapping):
                raw_results.append(check)
                continue
            detail = check.get("detail")
            if isinstance(detail, str):
                # Doctor's detail is long-form evidence for the person reading
                # the checkup; the snapshot carries a bounded summary. Without
                # this, one verbose but healthy check rejects the whole snapshot.
                detail = _bounded_text(detail, MAX_DETAIL_LENGTH)
            projected: dict[str, object] = {
                "id": f"{DOCTOR_REPORTER_IDENTITY.namespace}/{check.get('id', '')}",
                "check_version": DEFAULT_CHECK_VERSION,
                "verdict": check.get("verdict"),
                "detail": detail,
                "feature": check.get("feature"),
            }
            if "feature_status" in check:
                projected["feature_status"] = check["feature_status"]
            raw_results.append(projected)
    else:
        raw_results = checks if isinstance(checks, list) else []

    envelope = {
        "contract": CONTRACT,
        "reporter": DOCTOR_REPORTER_IDENTITY.to_dict(),
        "refresh_id": refresh_id,
        "generated_at": report.get("generated_at") if isinstance(report, Mapping) else None,
        "results": raw_results,
    }
    return normalize_report(envelope, spec=DOCTOR_REPORTER_SPEC)


def refresh_from_doctor(
    store: "HealthStore",
    *,
    refresh_id: str,
    heal: bool = False,
    context: doctor.DoctorContext | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> "HealthSnapshot":
    """Run the existing Doctor authority and publish one complete snapshot.

    The collector remains the sole source of factual checks and repair advice;
    this function only supplies the refresh lifecycle boundary around it.
    Exceptions leave the prior latest snapshot untouched and are recorded as a
    failed refresh by :class:`HealthStore`.
    """

    with store.refresh(refresh_id, started_at=started_at) as refresh:
        normalized = doctor.collect_reporter(
            refresh_id=refresh_id,
            heal=heal,
            context=context,
        )
        return refresh.publish(normalized, completed_at=completed_at)
