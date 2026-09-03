"""Transition capsules must snapshot, verify, and restore the reset-owned configs."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core import portable_contract
from core.customization_migration.capsule import read_capsule_status
from core.customization_migration.transition import (
    TRANSITION_CAPSULE_ROOT,
    TransitionCapsuleError,
    create_transition_capsule,
    effective_room_map,
    list_transition_capsule_ids,
    read_transition_capsule,
    restore_transition_capsule,
    verify_transition,
)

PROFILE = {
    "name": "Dana",
    "role": "Fractional CPO",
    "email_domain": "oldco.com",
    "work_email": "dana@oldco.com",
    "entity_creation": {"mode": "auto"},
    "journaling": {"morning": True, "evening": False},
    "capabilities": {
        "career": {"enabled": False},
        "companies": {"enabled": True},
        "quarter_goals": {"enabled": True},
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


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System/user-profile.yaml").write_text(
        yaml.safe_dump(PROFILE, sort_keys=False), encoding="utf-8"
    )
    (vault / "System/pillars.yaml").write_text(
        yaml.safe_dump(PILLARS, sort_keys=False), encoding="utf-8"
    )
    return vault


def _capture(vault: Path, allowed_prefixes: tuple[str, ...] = ()) -> str:
    receipt = create_transition_capsule(
        vault,
        allowed_prefixes=allowed_prefixes,
        rooms=effective_room_map(vault),
    )
    return receipt["capsule_id"]


def _write_profile(vault: Path, profile: dict) -> None:
    (vault / "System/user-profile.yaml").write_text(
        yaml.safe_dump(profile, sort_keys=False), encoding="utf-8"
    )


def test_capsule_round_trips_the_captured_bytes(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    profile_bytes = (vault / "System/user-profile.yaml").read_bytes()
    pillars_bytes = (vault / "System/pillars.yaml").read_bytes()

    capsule_id = _capture(vault, ("profile.role",))
    capsule = read_transition_capsule(vault, capsule_id)

    assert capsule.files["System/user-profile.yaml"] == profile_bytes
    assert capsule.files["System/pillars.yaml"] == pillars_bytes
    assert capsule.allowed_prefixes == ("profile.role",)
    assert capsule.rooms["career"] is False
    assert capsule.rooms["companies"] is True
    assert list_transition_capsule_ids(vault) == (capsule_id,)


def test_capsules_stay_out_of_the_update_migration_root(tmp_path: Path) -> None:
    """The update lane's status projection must never see a transition capsule."""
    vault = _vault(tmp_path)

    _capture(vault)

    assert not (vault / "System/.dex/customization-migrations").exists()
    assert read_capsule_status(vault).capsules == ()


def test_verify_passes_when_only_allowed_keys_change(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    capsule_id = _capture(
        vault,
        (
            "profile.role",
            "profile.email_domain",
            "profile.capabilities.career",
            "rooms.career",
            "pillars.pillars",
        ),
    )

    profile = dict(PROFILE)
    profile["role"] = "Chief Product Officer"
    profile["email_domain"] = "newco.com"
    profile["capabilities"] = {
        **PROFILE["capabilities"],
        "career": {"enabled": True},
    }
    _write_profile(vault, profile)
    (vault / "System/pillars.yaml").write_text(
        yaml.safe_dump(
            {**PILLARS, "pillars": [{"id": "team", "name": "Team"}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = verify_transition(vault, capsule_id)

    assert report["verified"] is True
    assert report["lost"] == []
    assert report["unexpected"] == []
    assert "profile.role" in report["changed_allowed"]
    assert "pillars.pillars" in report["changed_allowed"]
    assert report["carried_forward_count"] > 0
    assert report["summary"].startswith("Changed (you chose): role, email_domain")
    assert "Lost: none." in report["summary"]


def test_verify_defaults_to_the_most_recent_capsule(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _capture(vault, ("profile.role",))

    report = verify_transition(vault)

    assert report["verified"] is True
    assert report["capsule_id"] == list_transition_capsule_ids(vault)[-1]


def test_verify_fails_on_a_mutation_outside_the_manifest(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    capsule_id = _capture(vault, ("profile.role",))

    profile = dict(PROFILE)
    profile["work_email"] = "someone@else.com"
    profile["entity_creation"] = {"mode": "suggest"}
    _write_profile(vault, profile)

    report = verify_transition(vault, capsule_id)

    assert report["verified"] is False
    mutated = {item["key"]: item for item in report["unexpected"]}
    assert mutated["profile.work_email"]["old"] == "dana@oldco.com"
    assert mutated["profile.work_email"]["new"] == "someone@else.com"
    assert mutated["profile.entity_creation.mode"]["old"] == "auto"
    assert "Changed outside your answers: entity_creation.mode, work_email." in (
        report["summary"]
    )


def test_verify_fails_on_a_lost_setting(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    capsule_id = _capture(vault, ("pillars.pillars",))

    (vault / "System/pillars.yaml").write_text(
        yaml.safe_dump({"pillars": PILLARS["pillars"]}, sort_keys=False),
        encoding="utf-8",
    )

    report = verify_transition(vault, capsule_id)

    assert report["verified"] is False
    lost_keys = {item["key"] for item in report["lost"]}
    assert lost_keys == {
        "pillars.priority_limits.P0",
        "pillars.priority_limits.P1",
    }
    assert "Lost: pillars.priority_limits.P0, pillars.priority_limits.P1." in (
        report["summary"]
    )


def test_template_gap_fills_do_not_fail_verification(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    capsule_id = _capture(vault, ("profile.role",))

    profile = dict(PROFILE)
    profile["obsidian_mode"] = False
    _write_profile(vault, profile)

    report = verify_transition(vault, capsule_id)

    assert report["verified"] is True
    assert report["filled_defaults"] == ["profile.obsidian_mode"]


def test_restore_previews_then_round_trips_exactly(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    profile_bytes = (vault / "System/user-profile.yaml").read_bytes()
    pillars_bytes = (vault / "System/pillars.yaml").read_bytes()
    capsule_id = _capture(vault)

    _write_profile(vault, {**PROFILE, "role": "Chief Product Officer"})
    (vault / "System/pillars.yaml").write_text(
        yaml.safe_dump({"pillars": []}, sort_keys=False), encoding="utf-8"
    )
    mutated_profile = (vault / "System/user-profile.yaml").read_bytes()

    preview = restore_transition_capsule(vault, capsule_id)

    assert preview["dry_run"] is True
    assert preview["restored"] is False
    actions = {item["path"]: item for item in preview["files"]}
    assert actions["System/user-profile.yaml"]["action"] == "restore"
    changes = {
        change["key"]: change
        for change in actions["System/user-profile.yaml"]["changes"]
    }
    assert changes["role"]["old"] == "Chief Product Officer"
    assert changes["role"]["new"] == "Fractional CPO"
    assert (vault / "System/user-profile.yaml").read_bytes() == mutated_profile

    applied = restore_transition_capsule(vault, capsule_id, dry_run=False)

    assert applied["restored"] is True
    assert (vault / "System/user-profile.yaml").read_bytes() == profile_bytes
    assert (vault / "System/pillars.yaml").read_bytes() == pillars_bytes


def test_restore_refuses_a_tampered_capsule(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    capsule_id = _capture(vault)
    capsule_dir = vault / TRANSITION_CAPSULE_ROOT / capsule_id
    blob = next((capsule_dir / "blobs").iterdir())
    blob.chmod(0o600)
    blob.write_bytes(b"role: attacker\n")
    mutated = {**PROFILE, "role": "Changed"}
    _write_profile(vault, mutated)
    profile_bytes = (vault / "System/user-profile.yaml").read_bytes()

    with pytest.raises(TransitionCapsuleError, match="does not match its manifest"):
        restore_transition_capsule(vault, capsule_id, dry_run=False)

    assert (vault / "System/user-profile.yaml").read_bytes() == profile_bytes


def test_restore_never_deletes_a_file_the_capture_did_not_see(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "System/pillars.yaml").unlink()
    capsule_id = _capture(vault)

    (vault / "System/pillars.yaml").write_text(
        yaml.safe_dump(PILLARS, sort_keys=False), encoding="utf-8"
    )
    report = restore_transition_capsule(vault, capsule_id, dry_run=False)

    actions = {item["path"]: item for item in report["files"]}
    assert actions["System/pillars.yaml"]["action"] == "left-in-place"
    assert (vault / "System/pillars.yaml").exists()


def test_contract_scopes_each_transition_lane_to_its_own_paths() -> None:
    capsule_write = portable_contract.update_write_verdict(
        "System/.dex/transition-capsules/tcap-x/manifest.json",
        exists=False,
        operation="transition-capsule",
    )
    capsule_cannot_touch_profile = portable_contract.update_write_verdict(
        "System/user-profile.yaml",
        exists=True,
        operation="transition-capsule",
    )
    restore_write = portable_contract.update_write_verdict(
        "System/pillars.yaml",
        exists=True,
        operation="transition-restore",
    )
    restore_cannot_reach_elsewhere = portable_contract.update_write_verdict(
        "System/.onboarding-complete",
        exists=True,
        operation="transition-restore",
    )
    denied_inside_capsule = portable_contract.update_write_verdict(
        "System/.dex/transition-capsules/tcap-x/.env",
        exists=False,
        operation="transition-capsule",
    )

    assert capsule_write.allowed is True
    assert capsule_write.action == "write-transition-capsule"
    assert capsule_cannot_touch_profile.allowed is False
    assert restore_write.allowed is True
    assert restore_write.action == "write-transition-restore"
    assert restore_cannot_reach_elsewhere.allowed is False
    assert denied_inside_capsule.allowed is False
    assert denied_inside_capsule.action == "deny"
