"""Exact-set disposition validation contracts."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from core.customization_migration.model import AssessmentIdentity
from core.customization_migration.planning import (
    Disposition,
    DispositionPlanItem,
    validate_disposition_plan,
)
from core.customization_migration.service import assess
from core.tests.lifecycle_test_helpers import write_file, write_manifest
from core.tests.test_customization_assessment import _linked_customized_vault


def _plan_items(assessment):
    digest = hashlib.sha256(assessment.canonical_assessment_bytes()).hexdigest()
    return [
        DispositionPlanItem(record.customization_id, Disposition.MANUAL_REVIEW, digest)
        for record in assessment.records
    ]


def test_omitted_id_is_refused_red_when_exact_set_check_is_removed(tmp_path: Path) -> None:
    assessment = assess(_linked_customized_vault(tmp_path))
    items = _plan_items(assessment)

    validation = validate_disposition_plan(assessment, items[:-1])

    assert validation.accepted is False
    assert validation.verdict == "BROKEN"
    assert validation.errors == (
        f"missing customization id: {items[-1].customization_id}",
    )


def test_duplicate_id_is_refused(tmp_path: Path) -> None:
    assessment = assess(_linked_customized_vault(tmp_path))
    items = _plan_items(assessment)

    validation = validate_disposition_plan(assessment, [*items, items[0]])

    assert validation.accepted is False
    assert validation.verdict == "BROKEN"
    assert validation.errors == (
        f"duplicate customization id: {items[0].customization_id}",
    )


def test_unknown_id_is_refused(tmp_path: Path) -> None:
    assessment = assess(_linked_customized_vault(tmp_path))
    items = _plan_items(assessment)
    unknown = DispositionPlanItem(
        "cust-000000000000",
        Disposition.BLOCKED,
        items[0].assessment_digest,
    )

    validation = validate_disposition_plan(assessment, [*items, unknown])

    assert validation.accepted is False
    assert validation.verdict == "BROKEN"
    assert validation.errors == ("unknown customization id: cust-000000000000",)


def test_assessment_digest_drift_is_refused(tmp_path: Path) -> None:
    assessment = assess(_linked_customized_vault(tmp_path))
    items = _plan_items(assessment)
    items[0] = DispositionPlanItem(
        items[0].customization_id,
        items[0].disposition,
        "0" * 64,
    )

    validation = validate_disposition_plan(assessment, items)

    assert validation.accepted is False
    assert validation.verdict == "BROKEN"
    assert validation.errors == (
        f"assessment digest mismatch for {items[0].customization_id}",
    )


@pytest.mark.parametrize(
    "value",
    ["ignored", "probably-fine", "", None],
)
def test_disposition_is_closed(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        DispositionPlanItem("cust-000000000000", value, "0" * 64)  # type: ignore[arg-type]


def test_manifest_only_assessment_refuses_even_empty_plan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    write_file(vault, ".claude/skills/daily-plan/SKILL.md", b"modified\n")
    write_manifest(vault, [".claude/skills/daily-plan/SKILL.md"])

    validation = validate_disposition_plan(assess(vault), ())

    assert validation.accepted is False
    assert validation.verdict == "BROKEN"
    assert validation.errors == ("assessment is not a verified complete evidence set",)


def test_truncated_assessment_refuses_even_empty_plan(tmp_path: Path) -> None:
    complete = assess(_linked_customized_vault(tmp_path))
    truncated = replace(
        complete,
        identity=AssessmentIdentity(complete.identity.release_version, 0, 0, 0),
        incomplete_reasons=("walk-truncated",),
        records=(),
        edges=(),
        groups=(),
        completeness="UNKNOWN",
        verdict="UNKNOWN",
    )

    validation = validate_disposition_plan(truncated, ())

    assert validation.accepted is False
    assert validation.verdict == "BROKEN"
    assert validation.errors == ("assessment is not a verified complete evidence set",)


def test_verified_complete_empty_assessment_keeps_current_plan_behavior(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    from core.tests.test_customization_assessment import _install_verified_catalog

    _install_verified_catalog(vault)

    validation = validate_disposition_plan(assess(vault), ())

    assert validation.accepted is True
    assert validation.verdict == "OK"
    assert validation.errors == ()
