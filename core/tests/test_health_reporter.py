"""Contract tests for proactive-health reporter normalization."""

from datetime import datetime, timezone

import pytest

from core.health import reporter
from core.health.doctor_reporter import (
    DOCTOR_REPORTER_IDENTITY,
    DOCTOR_REPORTER_SPEC,
    from_doctor_report,
)
from core.utils import doctor

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def _doctor_check(definition, *, verdict="OK"):
    return {
        "id": definition.id,
        "feature": definition.feature,
        "verdict": verdict,
        "detail": "Probe completed.",
        "heal": {"tier": 1, "action": "not copied"},
        "user_message": "not copied",
    }


def _complete_doctor_report():
    return {
        "generated_at": NOW.isoformat(),
        "checks": [
            _doctor_check(definition)
            for definition in (*doctor.QUICK_CHECKS, *doctor.DEEP_CHECKS)
        ],
    }


def test_doctor_report_is_normalized_across_the_complete_registry():
    normalized = from_doctor_report(_complete_doctor_report(), refresh_id="refresh-001")

    assert normalized.accepted is True
    assert normalized.errors == ()
    envelope = normalized.report
    assert envelope.contract == "dex.health.reporter/v1"
    assert envelope.reporter == DOCTOR_REPORTER_IDENTITY
    assert envelope.refresh_id == "refresh-001"
    # The role-transition snapshot probe joined the complete Doctor registry
    # after the harness-capability receipt, Apple Mail search, Pipedrive CRM,
    # and backup freshness. This literal is a deliberate tripwire: adding a
    # probe must update the complete reporter contract rather than silently
    # changing its result set.
    assert len(envelope.results) == 39
    assert [result.id for result in envelope.results] == [
        f"doctor.core/{definition.id}"
        for definition in (*doctor.QUICK_CHECKS, *doctor.DEEP_CHECKS)
    ]
    assert all(result.check_version == "1.0.0" for result in envelope.results)
    assert all(result.verdict == "OK" for result in envelope.results)
    assert all("heal" not in result.to_dict() for result in envelope.results)
    assert all("user_message" not in result.to_dict() for result in envelope.results)


def test_canonical_reporter_bytes_are_stable_and_only_contain_contract_fields():
    normalized = from_doctor_report(_complete_doctor_report(), refresh_id="refresh-001")
    raw = reporter.canonical_reporter_bytes(normalized.report)

    assert raw.endswith(b"\n")
    assert reporter.canonical_reporter_bytes(normalized.report) == raw
    assert b'"heal"' not in raw
    assert b'"user_message"' not in raw


def test_unsupported_report_is_explicit_unknown_and_bounded():
    oversized = "x" * 5000
    normalized = reporter.normalize_report(
        {
            "contract": "dex.health.reporter/v2",
            "reporter": DOCTOR_REPORTER_IDENTITY.to_dict(),
            "refresh_id": "refresh-001",
            "generated_at": NOW.isoformat(),
            "results": [{"detail": oversized}],
        },
        spec=DOCTOR_REPORTER_SPEC,
        now=NOW,
    )

    assert normalized.accepted is False
    assert any(error.startswith("unsupported-contract:") for error in normalized.errors)
    assert len(normalized.report.results) == 1
    result = normalized.report.results[0]
    assert result.verdict == "UNKNOWN"
    assert len(result.detail) <= reporter.MAX_DETAIL_LENGTH
    assert oversized not in result.detail


def test_unknown_and_missing_checks_are_surfaced_as_unknown():
    definition = doctor.QUICK_CHECKS[0]
    normalized = reporter.normalize_report(
        {
            "contract": reporter.CONTRACT,
            "reporter": DOCTOR_REPORTER_IDENTITY.to_dict(),
            "refresh_id": "refresh-001",
            "generated_at": NOW.isoformat(),
            "results": [
                {
                    "id": "doctor.core/not-a-registered-check",
                    "check_version": "1.0.0",
                    "verdict": "OK",
                    "detail": "This must not be accepted.",
                },
                {
                    "id": f"doctor.core/{definition.id}",
                    "check_version": "1.0.0",
                    "verdict": "OK",
                    "detail": "Valid one.",
                },
            ],
        },
        spec=DOCTOR_REPORTER_SPEC,
        now=NOW,
    )

    assert normalized.accepted is False
    assert any("unrecognized-check" in error for error in normalized.errors)
    unknown = next(
        result
        for result in normalized.report.results
        if result.id == "doctor.core/not-a-registered-check"
    )
    assert unknown.verdict == "UNKNOWN"
    missing = next(
        result
        for result in normalized.report.results
        if result.id == f"doctor.core/{doctor.QUICK_CHECKS[1].id}"
    )
    assert missing.verdict == "UNKNOWN"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda report: report["results"].append(report["results"][0].copy()),
        lambda report: report["results"][0].update({"verdict": "MAYBE"}),
        lambda report: report["results"][0].update({"check_version": "2.0.0"}),
        lambda report: report["results"][0].update({"unexpected": True}),
    ],
)
def test_malformed_results_never_disappear(mutator):
    report = {
        "contract": reporter.CONTRACT,
        "reporter": DOCTOR_REPORTER_IDENTITY.to_dict(),
        "refresh_id": "refresh-001",
        "generated_at": NOW.isoformat(),
        "results": [
            {
                "id": f"doctor.core/{doctor.QUICK_CHECKS[0].id}",
                "check_version": "1.0.0",
                "verdict": "OK",
                "detail": "Valid one.",
            }
        ],
    }
    mutator(report)

    normalized = reporter.normalize_report(report, spec=DOCTOR_REPORTER_SPEC, now=NOW)

    assert normalized.accepted is False
    assert normalized.errors
    assert any(result.verdict == "UNKNOWN" for result in normalized.report.results)
