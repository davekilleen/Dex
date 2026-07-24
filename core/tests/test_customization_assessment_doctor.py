"""Dex Doctor integration for the deep-only customization assessment."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.customization_migration.service import assess
from core.tests.test_customization_assessment import _install_verified_catalog
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
    assert deep["customization_assessment"]["schema_version"] == 1
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
    assert doctor._probe_customization_assessment(older).verdict == "OFF"

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
