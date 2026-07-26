"""Dex Doctor integration for the deep-only customization assessment."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.customization_migration.service import assess
from core.tests.lifecycle_test_helpers import write_file, write_manifest
from core.tests.test_customization_assessment import (
    SHIPPED_SKILL,
    _install_verified_catalog,
)
from core.utils import doctor

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _context(tmp_path: Path) -> doctor.DoctorContext:
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir(parents=True)
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def _stub_probes(monkeypatch) -> None:
    for definition in (*doctor.QUICK_CHECKS, *doctor.DEEP_CHECKS):
        if definition.id in {"doctor.self", "customizations.assessment"}:
            continue
        monkeypatch.setattr(
            doctor,
            definition.probe,
            lambda _context: doctor.ProbeResult("OK", "Stub probe completed."),
        )
    monkeypatch.setattr(doctor, "_write_last_run", lambda _report, _context: None)


def test_deep_collect_includes_assessment_section_but_quick_does_not(
    monkeypatch,
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _install_verified_catalog(context.vault_root)
    _stub_probes(monkeypatch)

    quick = doctor.collect(context=context)
    deep = doctor.collect(deep=True, context=context)

    assert "customization_assessment" not in quick
    assert deep["customization_assessment"]["schema_version"] == 0
    assert deep["customization_assessment"]["verdict"] == "OK"
    assert any(
        check["id"] == "customizations.assessment"
        for check in deep["checks"]
    )


def test_probe_maps_verified_missing_and_ambiguous_catalog_states(
    tmp_path: Path,
) -> None:
    verified = _context(tmp_path / "verified")
    _install_verified_catalog(verified.vault_root)
    assert doctor._probe_customization_assessment(verified).verdict == "OK"

    older = _context(tmp_path / "older")
    older_assessment = assess(older.vault_root)
    assert older_assessment.verdict == "UNKNOWN"
    assert doctor._probe_customization_assessment(older).verdict == "UNKNOWN"

    ambiguous = _context(tmp_path / "ambiguous")
    _install_verified_catalog(ambiguous.vault_root)
    second_catalog = ambiguous.vault_root / "core/lifecycle/catalog/release.json"
    second_catalog.parent.mkdir(parents=True)
    second_catalog.write_bytes(
        (ambiguous.vault_root / "System/.release-catalog.json").read_bytes()
    )
    assert doctor._probe_customization_assessment(ambiguous).verdict == "UNKNOWN"


def test_probe_maps_invalid_catalog_to_broken(tmp_path: Path) -> None:
    context = _context(tmp_path)
    path = context.vault_root / "System/.release-catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    result = doctor._probe_customization_assessment(context)

    assert result.verdict == "BROKEN"
    assert result.structured_detail is not None


def test_manifest_only_probe_is_unknown_without_counts_or_records(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    write_file(
        context.vault_root,
        SHIPPED_SKILL,
        b"locally modified without hash authority\n",
    )
    write_manifest(context.vault_root, [SHIPPED_SKILL])

    result = doctor._probe_customization_assessment(context)
    encoded = json.dumps(result.structured_detail, sort_keys=True)

    assert result.verdict == "UNKNOWN"
    assert result.detail == (
        "I couldn't verify which Dex version is installed, so I can't tell you "
        "what you've changed."
    )
    assert result.structured_detail is not None
    assert result.structured_detail["incomplete_reasons"] == [
        "baseline-not-verified"
    ]
    assert "records" not in result.structured_detail
    assert "counts" not in result.structured_detail
    assert "customization_count" not in encoded
    assert result.structured_detail["records_truncated"] is False


def test_probe_persistence_detail_caps_record_listing_at_25(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    _install_verified_catalog(context.vault_root)
    for index in range(26):
        write_file(
            context.vault_root,
            f".scripts/custom-{index:02d}.py",
            f"VALUE = {index}\n".encode(),
        )

    result = doctor._probe_customization_assessment(context)

    assert result.verdict == "OK"
    assert result.structured_detail is not None
    assert result.structured_detail["counts"]["total"] == 26
    assert result.structured_detail["records_total"] == 26
    assert result.structured_detail["records_truncated"] is True
    assert len(result.structured_detail["records"]) == 25


def test_probe_summary_leads_with_blocked_customizations(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _install_verified_catalog(context.vault_root)
    write_file(
        context.vault_root,
        ".scripts/custom.py",
        b'TARGET = "missing/helper.py"\n',
    )

    result = doctor._probe_customization_assessment(context)

    assert result.verdict == "OK"
    assert result.detail == "Customization assessment completed: 1 customization, 1 blocked"
    assert result.structured_detail["blocked_count"] == 1
    assert result.structured_detail["needs_interpretation_count"] == 0


def test_probe_summary_without_blocked_customizations(tmp_path: Path) -> None:
    context = _context(tmp_path)
    _install_verified_catalog(context.vault_root)

    result = doctor._probe_customization_assessment(context)

    assert result.verdict == "OK"
    assert result.detail == "Customization assessment completed: 0 customizations"
    assert result.structured_detail["blocked_count"] == 0
    assert result.structured_detail["needs_interpretation_count"] == 0


def test_doctor_skill_requires_blocked_count_in_first_summary_sentence() -> None:
    skill = (
        Path(__file__).resolve().parents[2]
        / ".claude/skills/dex-doctor/SKILL.md"
    ).read_text(encoding="utf-8")
    section = skill.split("### Step 3b: Render the customization assessment", 1)[1].split(
        "### Step 3c:", 1
    )[0]

    assert (
        "When `blocked_count` is greater than zero, the first summary sentence must "
        "state that blocked count."
    ) in section
