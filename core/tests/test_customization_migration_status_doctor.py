"""Doctor and instruction contracts for the scoped customization journey."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from core.customization_migration import service as migration_service
from core.tests.test_customization_assessment import _linked_customized_vault
from core.utils import doctor

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def _context(vault: Path, tmp_path: Path) -> doctor.DoctorContext:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    return doctor.DoctorContext(
        vault_root=vault,
        repo_root=vault,
        home=home,
        now=NOW,
    )


def _stub_other_probes(monkeypatch) -> None:
    for definition in (*doctor.QUICK_CHECKS, *doctor.DEEP_CHECKS):
        if definition.id in {
            "doctor.self",
            "customizations.migration-status",
        }:
            continue
        structured_detail = None
        if definition.id == "customizations.assessment":
            structured_detail = {
                "schema_version": 0,
                "completeness": "OK",
                "verdict": "OK",
            }
        monkeypatch.setattr(
            doctor,
            definition.probe,
            lambda _context, detail=structured_detail: doctor.ProbeResult(
                "OK",
                "Stub probe completed.",
                structured_detail=detail,
            ),
        )
    monkeypatch.setattr(doctor, "_write_last_run", lambda _report, _context: None)


def _create_capsule(vault: Path):
    preview = migration_service.preview_to_dict(vault)
    token = preview["preview_sha256"]
    assert isinstance(token, str)
    return migration_service.create_confirmed_capsule(vault, token)


def _file_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        snapshot[path.relative_to(root).as_posix()] = (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return snapshot


def test_deep_collect_includes_migration_status_but_quick_does_not(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = _linked_customized_vault(tmp_path)
    context = _context(vault, tmp_path)
    _stub_other_probes(monkeypatch)

    quick = doctor.collect(context=context)
    deep = doctor.collect(deep=True, context=context)

    assert "customization_migration_status" not in quick
    assert not any(
        check["id"] == "customizations.migration-status"
        for check in quick["checks"]
    )
    assert deep["customization_migration_status"] == {
        "capsules": [],
        "truncated": False,
        "pending": False,
    }
    assert any(
        check["id"] == "customizations.migration-status"
        for check in deep["checks"]
    )


def test_no_capsules_is_ok_and_not_pending(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)

    result = doctor._probe_customization_migration_status(
        _context(vault, tmp_path)
    )

    assert result.verdict == "OK"
    assert result.structured_detail == {
        "capsules": [],
        "truncated": False,
        "pending": False,
    }


def test_created_capsule_is_ok_pending_and_lists_capsule_id(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    receipt = _create_capsule(vault)

    result = doctor._probe_customization_migration_status(
        _context(vault, tmp_path)
    )

    assert result.verdict == "OK"
    assert result.structured_detail is not None
    assert result.structured_detail["pending"] is True
    assert result.structured_detail["capsules"] == [
        {
            "capsule_id": receipt.capsule_id,
            "state": "capsule-created",
            "validation": {"status": "OK", "mismatches": []},
        }
    ]


def test_tampered_capsule_is_broken_and_surfaces_validation_mismatch(
    tmp_path: Path,
) -> None:
    vault = _linked_customized_vault(tmp_path)
    receipt = _create_capsule(vault)
    section = (
        vault
        / "System/.dex/customization-migrations"
        / receipt.capsule_id
        / "evidence/customizations.json"
    )
    raw = bytearray(section.read_bytes())
    raw[-1] = ord(" ")
    section.write_bytes(raw)

    result = doctor._probe_customization_migration_status(
        _context(vault, tmp_path)
    )

    assert result.verdict == "BROKEN"
    assert result.structured_detail is not None
    validation = result.structured_detail["capsules"][0]["validation"]
    assert validation["status"] == "BROKEN"
    assert "evidence/customizations.json" in validation["mismatches"]


def test_abandoned_capsule_is_not_pending(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    receipt = _create_capsule(vault)
    migration_service.abandon_existing_capsule(vault, receipt.capsule_id)

    result = doctor._probe_customization_migration_status(
        _context(vault, tmp_path)
    )

    assert result.verdict == "OK"
    assert result.structured_detail is not None
    assert result.structured_detail["pending"] is False
    assert result.structured_detail["capsules"][0]["state"] == "abandoned"


def test_probe_changes_no_vault_file_mtime_or_hash(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    _create_capsule(vault)
    before = _file_snapshot(vault)

    result = doctor._probe_customization_migration_status(
        _context(vault, tmp_path)
    )

    assert result.verdict == "OK"
    assert _file_snapshot(vault) == before


def test_missing_catalog_is_off(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    result = doctor._probe_customization_migration_status(
        _context(vault, tmp_path)
    )

    assert result.verdict == "OFF"
    assert result.structured_detail is None


def test_invalid_catalog_is_broken(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    (vault / "System/.release-catalog.json").write_text(
        "{not-json",
        encoding="utf-8",
    )

    result = doctor._probe_customization_migration_status(
        _context(vault, tmp_path)
    )

    assert result.verdict == "BROKEN"
    assert "release catalog is invalid" in result.detail


def test_unknown_capsule_validation_is_unknown(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    migration_root = vault / "System/.dex/customization-migrations"
    migration_root.parent.mkdir(parents=True)
    migration_root.write_text("not a directory", encoding="utf-8")

    result = doctor._probe_customization_migration_status(
        _context(vault, tmp_path)
    )

    assert result.verdict == "UNKNOWN"
    assert result.structured_detail is not None
    assert result.structured_detail["pending"] is False
    assert result.structured_detail["capsules"][0]["validation"] == {
        "status": "UNKNOWN",
        "mismatches": ["capsule-entry"],
    }


def test_structural_status_read_failure_is_unknown(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = _linked_customized_vault(tmp_path)

    def fail_read(_vault_root: Path) -> dict[str, object]:
        raise ValueError("malformed migration status")

    monkeypatch.setattr(migration_service, "migration_status_to_dict", fail_read)

    result = doctor._probe_customization_migration_status(
        _context(vault, tmp_path)
    )

    assert result.verdict == "UNKNOWN"
    assert "malformed migration status" in result.detail
    assert result.structured_detail is None
