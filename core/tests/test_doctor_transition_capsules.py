"""Doctor's role-transition snapshot probe must report honestly, never restore."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from core.customization_migration.transition import (
    TRANSITION_CAPSULE_ROOT,
    create_transition_capsule,
    effective_room_map,
)
from core.utils import doctor

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

PROFILE = {
    "name": "Dana",
    "role": "Fractional CPO",
    "email_domain": "oldco.com",
    "work_email": "dana@oldco.com",
    "entity_creation": {"mode": "auto"},
    "capabilities": {
        "career": {"enabled": False},
        "companies": {"enabled": True},
    },
}

PILLARS = {
    "pillars": [
        {
            "id": "product-strategy",
            "name": "Product Strategy",
            "keywords": ["roadmap", "strategy"],
        }
    ],
    "priority_limits": {"P0": 2, "P1": 4},
}


@pytest.fixture
def context(tmp_path):
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def _write_configs(vault: Path) -> None:
    (vault / "System/user-profile.yaml").write_text(
        yaml.safe_dump(PROFILE, sort_keys=False), encoding="utf-8"
    )
    (vault / "System/pillars.yaml").write_text(
        yaml.safe_dump(PILLARS, sort_keys=False), encoding="utf-8"
    )


def _capture(
    vault: Path,
    allowed_prefixes: tuple[str, ...] = ("profile.role", "profile.email_domain"),
    *,
    created: float = 1_756_900_000.0,
) -> str:
    receipt = create_transition_capsule(
        vault,
        allowed_prefixes=allowed_prefixes,
        rooms=effective_room_map(vault),
        clock=lambda: created,
    )
    return receipt["capsule_id"]


def _write_profile(vault: Path, profile: dict) -> None:
    (vault / "System/user-profile.yaml").write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )


def test_probe_is_calmly_off_when_no_transition_was_recorded(context):
    _write_configs(context.vault_root)

    result = doctor._probe_transition_capsules(context)

    assert result.verdict == "OFF"
    assert "No role transition has been recorded" in result.detail
    assert result.heal is None


def test_probe_is_off_when_the_capsule_root_is_absent_entirely(context):
    # Not even System/ content: absence is normal, never a finding.
    result = doctor._probe_transition_capsules(context)

    assert result.verdict == "OFF"
    assert "No role transition has been recorded" in result.detail


def test_probe_reports_ok_with_capsule_id_and_summary_on_a_clean_capsule(context):
    _write_configs(context.vault_root)
    capsule_id = _capture(context.vault_root)

    result = doctor._probe_transition_capsules(context)

    assert result.verdict == "OK"
    assert capsule_id in result.detail
    assert "Carried forward" in result.detail
    assert "Lost: none" in result.detail
    assert result.heal is None


def test_probe_flags_a_mutation_outside_the_manifest_without_restoring(context):
    _write_configs(context.vault_root)
    _capture(context.vault_root)
    drifted = dict(PROFILE)
    drifted["entity_creation"] = {"mode": "off"}
    _write_profile(context.vault_root, drifted)
    drifted_bytes = (context.vault_root / "System/user-profile.yaml").read_bytes()

    result = doctor._probe_transition_capsules(context)

    assert result.verdict == "BROKEN"
    assert "drifted" in result.detail
    assert "entity_creation.mode" in result.detail
    assert result.heal is not None
    assert result.heal.tier == 3
    assert result.heal.applied is False
    assert "restore_transition_capsule" in result.heal.action
    assert "verify_transition" in result.heal.action
    # The probe reported; it must not have restored the live config.
    assert (
        context.vault_root / "System/user-profile.yaml"
    ).read_bytes() == drifted_bytes


def test_probe_names_a_lost_setting_as_lost(context):
    _write_configs(context.vault_root)
    _capture(context.vault_root)
    drifted = {key: value for key, value in PROFILE.items() if key != "work_email"}
    _write_profile(context.vault_root, drifted)

    result = doctor._probe_transition_capsules(context)

    assert result.verdict == "BROKEN"
    assert "Lost: work_email" in result.detail


def test_probe_verifies_only_the_latest_and_lists_older_ids(context):
    _write_configs(context.vault_root)
    older_id = _capture(context.vault_root, created=1_756_900_000.0)
    latest_id = _capture(context.vault_root, created=1_756_900_100.0)

    result = doctor._probe_transition_capsules(context)

    assert result.verdict == "OK"
    assert latest_id in result.detail
    assert f"1 earlier snapshot kept ({older_id})" in result.detail


def test_probe_reports_a_corrupted_manifest_as_could_not_check(context):
    _write_configs(context.vault_root)
    capsule_id = _capture(context.vault_root)
    manifest = (
        context.vault_root / TRANSITION_CAPSULE_ROOT / capsule_id / "manifest.json"
    )
    manifest.write_bytes(b"{not json")

    result = doctor._probe_transition_capsules(context)

    assert result.verdict == "UNKNOWN"
    assert capsule_id in result.detail
    assert "could not be verified" in result.detail
    assert result.heal is None


def test_probe_reports_a_tampered_blob_as_could_not_check(context):
    _write_configs(context.vault_root)
    capsule_id = _capture(context.vault_root)
    blobs = context.vault_root / TRANSITION_CAPSULE_ROOT / capsule_id / "blobs"
    for blob in blobs.iterdir():
        blob.write_bytes(blob.read_bytes() + b"\ntampered: true\n")

    result = doctor._probe_transition_capsules(context)

    assert result.verdict == "UNKNOWN"
    assert "tampered" in result.detail


def test_probe_registry_entry_matches_the_probe(context):
    definition = next(
        check
        for check in doctor.QUICK_CHECKS
        if check.id == "customizations.transition"
    )

    assert definition.feature == "Role-transition snapshots"
    assert definition.probe == "_probe_transition_capsules"
    result = getattr(doctor, definition.probe)(context)
    assert result.verdict == "OFF"
