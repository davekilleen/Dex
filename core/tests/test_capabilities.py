"""Behavioral coverage for onboarding-toggleable capability rooms."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core import capabilities, portable_contract
from core.mcp import career_server, resume_server, work_server

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "packages/dex-contracts/dist/portable-vault.contract.json"
ROOM_SKILLS = {
    "career": ("career-setup", "career-coach", "resume-builder"),
    "companies": (),
    "quarter_goals": ("quarter-plan", "quarter-review"),
}


def _profile(path: Path, **states: bool) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"capabilities": {room: {"enabled": enabled} for room, enabled in states.items()}},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _fake_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    for spine_path in (
        "00-Inbox/Meetings",
        "03-Tasks",
        "05-Areas/People/Internal",
        "05-Areas/People/External",
    ):
        (vault / spine_path).mkdir(parents=True, exist_ok=True)

    for room, skills in ROOM_SKILLS.items():
        for skill in skills:
            dormant = vault / ".claude/skills/_available/capabilities" / room / "skills" / skill / "SKILL.md"
            dormant.parent.mkdir(parents=True, exist_ok=True)
            dormant.write_text(
                f"---\nname: {skill}\ndescription: Test skill\n---\n",
                encoding="utf-8",
            )

    dormant_folders = vault / ".claude/skills/_available/capabilities"
    seed_files = {
        "career": "05-Areas/Career/Evidence/README.md",
        "companies": "05-Areas/Companies/README.md",
        "quarter_goals": "01-Quarter_Goals/Quarter_Goals.md",
    }
    for room, relative_path in seed_files.items():
        seed = dormant_folders / room / "folders" / relative_path
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text(f"# {room}\n", encoding="utf-8")
    return vault


def _fake_contract_with_skill_pins(
    tmp_path: Path,
    vault: Path,
    *,
    previous_payloads: dict[str, tuple[str, bytes]] | None = None,
) -> Path:
    """Clone the real room declaration and pin the synthetic release payloads."""
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    for room, skills in ROOM_SKILLS.items():
        pins = []
        for skill in skills:
            relative = Path(".claude/skills/_available/capabilities") / room / "skills" / skill / "SKILL.md"
            payload = (vault / relative).read_bytes()
            pins.append(
                {
                    "room": room,
                    "skill": skill,
                    "source_path": relative.as_posix(),
                    "target_path": f".claude/skills/{skill}/SKILL.md",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "byte_size": len(payload),
                    "previous_payloads": (
                        [
                            {
                                "release": previous_payloads[skill][0],
                                "sha256": hashlib.sha256(previous_payloads[skill][1]).hexdigest(),
                                "byte_size": len(previous_payloads[skill][1]),
                            }
                        ]
                        if previous_payloads and skill in previous_payloads
                        else []
                    ),
                }
            )
        contract["capabilities"][room]["skill_sources"] = pins
    path = tmp_path / "portable-vault.fixture.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return path


def _decode(result) -> dict:
    return json.loads(result[0].text)


def test_surfaces_are_read_from_the_portable_contract_registry() -> None:
    career = capabilities.surfaces_for("career", contract_path=CONTRACT_PATH)

    assert career["folders"] == ["05-Areas/Career"]
    assert career["skills"] == [
        "career-setup",
        "career-coach",
        "resume-builder",
    ]
    assert career["mcp"] == ["career_server", "resume_server"]


def test_capability_cli_starts_from_its_shipped_script_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "core/capabilities.py"), "--list"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "rooms": ["career", "companies", "quarter_goals"]
    }


def test_capability_cli_preflight_fails_closed_on_room_source_drift(
    tmp_path: Path,
) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["capabilities"]["career"]["skill_sources"][0]["sha256"] = "0" * 64
    drifted = tmp_path / "drifted-contract.json"
    drifted.write_text(json.dumps(contract), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "core/capabilities.py"),
            "--preflight",
            "--vault",
            str(tmp_path / "vault"),
            "--contract",
            str(drifted),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "identity" in result.stderr.lower() or "sha256" in result.stderr.lower()


def test_room_missing_from_contract_registry_is_unknown(tmp_path: Path) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["capabilities"].pop("career")
    reduced_contract = tmp_path / "contract.json"
    reduced_contract.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(capabilities.UnknownCapability, match="career"):
        capabilities.surfaces_for("career", contract_path=reduced_contract)


def test_no_opinion_rooms_default_on_and_legacy_quarterly_planning_is_a_fallback(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "System/user-profile.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("quarterly_planning:\n  enabled: true\n", encoding="utf-8")

    assert capabilities.enabled("career", profile_path=profile_path, contract_path=CONTRACT_PATH) is True
    assert capabilities.enabled("companies", profile_path=profile_path, contract_path=CONTRACT_PATH) is True
    assert capabilities.enabled("quarter_goals", profile_path=profile_path, contract_path=CONTRACT_PATH) is True

    profile_path.write_text(
        "capabilities:\n  quarter_goals:\n    enabled: false\nquarterly_planning:\n  enabled: true\n",
        encoding="utf-8",
    )
    assert capabilities.enabled("quarter_goals", profile_path=profile_path, contract_path=CONTRACT_PATH) is False

    profile_path.write_text("capabilities: malformed\n", encoding="utf-8")
    assert capabilities.enabled("career", profile_path=profile_path, contract_path=CONTRACT_PATH) is True


def test_profile_template_keeps_quarter_goal_defaults_aligned() -> None:
    profile = yaml.safe_load((REPO_ROOT / "System/user-profile-template.yaml").read_text(encoding="utf-8"))

    assert profile["capabilities"]["quarter_goals"]["enabled"] is True
    assert profile["quarterly_planning"]["enabled"] is True


def test_flipped_rooms_default_on_but_a_recorded_answer_always_wins(
    tmp_path: Path,
) -> None:
    """Career and Quarter Goals default on (Dave's 2026-07-28 rooms decision).

    The default is the *fallback*, never an override: a recorded answer outranks
    it in both directions, so flipping the default can never switch a room on for
    someone who said no, nor off for someone who said yes.
    """
    profile_path = tmp_path / "System/user-profile.yaml"

    for room in ("career", "quarter_goals"):
        _profile(profile_path, **{room: False})
        assert capabilities.enabled(room, profile_path=profile_path, contract_path=CONTRACT_PATH) is False

        _profile(profile_path, **{room: True})
        assert capabilities.enabled(room, profile_path=profile_path, contract_path=CONTRACT_PATH) is True

    # A map that names one room leaves the other on the contract default.
    _profile(profile_path, quarter_goals=False)
    assert capabilities.enabled("career", profile_path=profile_path, contract_path=CONTRACT_PATH) is True


def test_off_rooms_stay_dormant_and_leave_the_spine_intact(tmp_path: Path) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = _profile(
        vault / "System/user-profile.yaml",
        career=False,
        companies=False,
        quarter_goals=False,
    )

    capabilities.reconcile_all(
        vault,
        profile_path=profile_path,
        contract_path=CONTRACT_PATH,
    )

    for room in capabilities.room_ids(contract_path=CONTRACT_PATH):
        for folder in capabilities.surfaces_for(room, contract_path=CONTRACT_PATH).get("folders", []):
            assert not (vault / folder).exists()
        for skill in capabilities.surfaces_for(room, contract_path=CONTRACT_PATH).get("skills", []):
            assert not (vault / ".claude/skills" / skill).exists()

    assert (vault / "00-Inbox/Meetings").is_dir()
    assert (vault / "03-Tasks").is_dir()
    assert (vault / "05-Areas/People/Internal").is_dir()


def test_enabling_later_provisions_declared_folders_and_skills(tmp_path: Path) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = _profile(vault / "System/user-profile.yaml", career=False)

    result = capabilities.set_enabled(
        "career",
        True,
        vault_root=vault,
        profile_path=profile_path,
        contract_path=CONTRACT_PATH,
    )

    assert result["enabled"] is True
    assert (vault / "05-Areas/Career/Evidence/README.md").is_file()
    for skill in ROOM_SKILLS["career"]:
        assert (vault / ".claude/skills" / skill / "SKILL.md").is_file()
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert profile["capabilities"]["career"]["enabled"] is True
    assert "System/user-profile.yaml" in result["mutation_paths"]


def test_room_toggle_receipt_includes_new_profile_ancestors_and_file(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    result = capabilities.set_enabled(
        "career",
        True,
        vault_root=vault,
        contract_path=CONTRACT_PATH,
    )

    assert "System" in result["mutation_paths"]
    assert "System/user-profile.yaml" in result["mutation_paths"]
    assert (vault / "System/user-profile.yaml").is_file()


def test_room_reconcile_reports_every_persistent_mutation_and_then_reports_none(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    first = capabilities.reconcile_room(
        "career",
        True,
        vault_root=vault,
        contract_path=CONTRACT_PATH,
    )

    assert first["mutation_paths"] == [
        ".claude",
        ".claude/skills",
        ".claude/skills/career-coach",
        ".claude/skills/career-coach/SKILL.md",
        ".claude/skills/career-setup",
        ".claude/skills/career-setup/SKILL.md",
        ".claude/skills/resume-builder",
        ".claude/skills/resume-builder/SKILL.md",
        "05-Areas",
        "05-Areas/Career",
        "05-Areas/Career/Evidence",
        "05-Areas/Career/Evidence/README.md",
    ]

    second = capabilities.reconcile_room(
        "career",
        True,
        vault_root=vault,
        contract_path=CONTRACT_PATH,
    )

    assert second["mutation_paths"] == []


def test_disabling_stops_skill_surfacing_but_never_deletes_user_content(
    tmp_path: Path,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = _profile(vault / "System/user-profile.yaml", career=False)
    capabilities.set_enabled(
        "career",
        True,
        vault_root=vault,
        profile_path=profile_path,
        contract_path=CONTRACT_PATH,
    )
    user_note = vault / "05-Areas/Career/my-private-review.md"
    user_note.write_text("keep forever\n", encoding="utf-8")

    capabilities.set_enabled(
        "career",
        False,
        vault_root=vault,
        profile_path=profile_path,
        contract_path=CONTRACT_PATH,
    )

    assert user_note.read_text(encoding="utf-8") == "keep forever\n"
    for skill in ROOM_SKILLS["career"]:
        assert not (vault / ".claude/skills" / skill).exists()


def test_quarter_toggle_writes_new_state_and_keeps_legacy_config_in_sync(
    tmp_path: Path,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = vault / "System/user-profile.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        "quarterly_planning:\n  enabled: true\n  q1_start_month: 4\n",
        encoding="utf-8",
    )

    capabilities.set_enabled(
        "quarter_goals",
        False,
        vault_root=vault,
        profile_path=profile_path,
        contract_path=CONTRACT_PATH,
    )

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert profile["capabilities"]["quarter_goals"]["enabled"] is False
    assert profile["quarterly_planning"] == {
        "enabled": False,
        "q1_start_month": 4,
    }


def test_toggle_refuses_to_overwrite_a_malformed_existing_profile(
    tmp_path: Path,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = vault / "System/user-profile.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    original = "name: Keep Me\ncapabilities: [not, an, object\n"
    profile_path.write_text(original, encoding="utf-8")

    with pytest.raises(capabilities.CapabilityError, match="profile"):
        capabilities.set_enabled(
            "career",
            True,
            vault_root=vault,
            profile_path=profile_path,
            contract_path=CONTRACT_PATH,
        )

    assert profile_path.read_text(encoding="utf-8") == original
    assert not (vault / "05-Areas/Career").exists()


def test_reconcile_refuses_to_overwrite_unrecognized_active_skill_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _fake_vault(tmp_path)
    # The planted catalog plays the role of the brain (the real repo catalog
    # would otherwise shadow it — brain-first sourcing).
    monkeypatch.setattr(capabilities, "REPO_ROOT", vault)
    contract_path = _fake_contract_with_skill_pins(tmp_path, vault)
    profile_path = _profile(vault / "System/user-profile.yaml", career=True)
    custom = vault / ".claude/skills/career-setup/SKILL.md"
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text("user-owned custom skill\n", encoding="utf-8")
    original_profile = profile_path.read_bytes()

    with pytest.raises(capabilities.CapabilityError, match="identity|authoritative|target"):
        capabilities.reconcile_all(
            vault,
            profile_path=profile_path,
            contract_path=contract_path,
        )

    assert profile_path.read_bytes() == original_profile
    assert custom.read_text(encoding="utf-8") == "user-owned custom skill\n"
    assert not (vault / "05-Areas/Career").exists()
    assert not (vault / ".claude/skills/career-coach").exists()


def test_reconcile_upgrades_an_authoritative_previous_release_room_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _fake_vault(tmp_path)
    monkeypatch.setattr(capabilities, "REPO_ROOT", vault)
    previous = b"---\nname: career-setup\ndescription: Prior Dex release.\n---\n"
    contract_path = _fake_contract_with_skill_pins(
        tmp_path,
        vault,
        previous_payloads={"career-setup": ("v1.95.2", previous)},
    )
    profile_path = _profile(vault / "System/user-profile.yaml", career=True)
    target = vault / ".claude/skills/career-setup/SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(previous)
    current = (
        vault
        / ".claude/skills/_available/capabilities/career/skills/career-setup/SKILL.md"
    ).read_bytes()

    result = capabilities.reconcile_room(
        "career",
        True,
        vault_root=vault,
        contract_path=contract_path,
    )

    assert profile_path.is_file()
    assert target.read_bytes() == current
    assert ".claude/skills/career-setup/SKILL.md" in result["mutation_paths"]


def test_enable_rejects_a_non_directory_skill_ancestor_before_any_mutation(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    profile_path = _profile(vault / "System/user-profile.yaml", career=False)
    original_profile = profile_path.read_bytes()
    claude = vault / ".claude"
    claude.mkdir()
    (claude / "skills").write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(capabilities.CapabilityError, match="ancestor|directory|target"):
        capabilities.set_enabled(
            "career",
            True,
            vault_root=vault,
            profile_path=profile_path,
            contract_path=CONTRACT_PATH,
        )

    assert profile_path.read_bytes() == original_profile
    assert not (vault / "05-Areas/Career").exists()


def test_enable_rolls_back_profile_and_room_assets_when_reconciliation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    profile_path = _profile(vault / "System/user-profile.yaml", career=False)
    original_profile = profile_path.read_bytes()
    original_copy = capabilities._copy_verified_room_skill
    calls = 0

    def fail_during_second_skill(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected room reconciliation failure")
        return original_copy(*args, **kwargs)

    monkeypatch.setattr(
        capabilities,
        "_copy_verified_room_skill",
        fail_during_second_skill,
    )

    with pytest.raises(capabilities.CapabilityError, match="reconciliation|rollback|injected"):
        capabilities.set_enabled(
            "career",
            True,
            vault_root=vault,
            profile_path=profile_path,
            contract_path=CONTRACT_PATH,
        )

    assert profile_path.read_bytes() == original_profile
    assert not (vault / "05-Areas/Career").exists()
    assert not (vault / ".claude").exists()


def test_failed_room_upgrade_restores_the_exact_previous_release_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _fake_vault(tmp_path)
    monkeypatch.setattr(capabilities, "REPO_ROOT", vault)
    previous = b"---\nname: career-setup\ndescription: Previous release.\n---\n"
    contract_path = _fake_contract_with_skill_pins(
        tmp_path,
        vault,
        previous_payloads={"career-setup": ("v1.95.2", previous)},
    )
    profile_path = _profile(vault / "System/user-profile.yaml", career=False)
    original_profile = profile_path.read_bytes()
    target = vault / ".claude/skills/career-setup/SKILL.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(previous)
    original_copy = capabilities._copy_verified_room_skill
    calls = 0

    def fail_during_second_skill(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected failure after prior payload upgrade")
        return original_copy(*args, **kwargs)

    monkeypatch.setattr(capabilities, "_copy_verified_room_skill", fail_during_second_skill)

    with pytest.raises(capabilities.CapabilityError, match="rolled back|injected"):
        capabilities.set_enabled(
            "career",
            True,
            vault_root=vault,
            profile_path=profile_path,
            contract_path=contract_path,
        )

    assert profile_path.read_bytes() == original_profile
    assert target.read_bytes() == previous
    assert not (vault / "05-Areas/Career").exists()
    assert not (vault / ".claude/skills/career-coach").exists()


@pytest.mark.parametrize("unsafe_kind", ("symlink", "custom-bytes"))
def test_disable_preflights_active_skill_targets_before_profile_or_user_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    vault = _fake_vault(tmp_path)
    monkeypatch.setattr(capabilities, "REPO_ROOT", vault)
    contract_path = _fake_contract_with_skill_pins(tmp_path, vault)
    profile_path = _profile(vault / "System/user-profile.yaml", career=True)
    original_profile = profile_path.read_bytes()
    target = vault / ".claude/skills/resume-builder"

    if unsafe_kind == "symlink":
        protected = vault / "05-Areas/Do-Not-Touch"
        protected.mkdir(parents=True)
        (protected / "sentinel.md").write_text("preserve\n", encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(protected, target_is_directory=True)
    else:
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("user-owned custom skill\n", encoding="utf-8")

    with pytest.raises(capabilities.CapabilityError, match="target|symlink|identity|authoritative"):
        capabilities.set_enabled(
            "career",
            False,
            vault_root=vault,
            profile_path=profile_path,
            contract_path=contract_path,
        )

    assert profile_path.read_bytes() == original_profile
    if unsafe_kind == "symlink":
        assert target.is_symlink()
        assert (vault / "05-Areas/Do-Not-Touch/sentinel.md").read_text(encoding="utf-8") == "preserve\n"
    else:
        assert (target / "SKILL.md").read_text(encoding="utf-8") == "user-owned custom skill\n"


def test_reconcile_all_preflights_every_room_before_mutating_an_earlier_room(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _fake_vault(tmp_path)
    monkeypatch.setattr(capabilities, "REPO_ROOT", vault)
    contract_path = _fake_contract_with_skill_pins(tmp_path, vault)
    profile_path = _profile(
        vault / "System/user-profile.yaml",
        career=True,
        companies=True,
        quarter_goals=True,
    )
    protected = vault / "05-Areas/Do-Not-Touch"
    protected.mkdir(parents=True)
    (protected / "sentinel.md").write_text("preserve\n", encoding="utf-8")
    unsafe = vault / ".claude/skills/quarter-review"
    unsafe.parent.mkdir(parents=True, exist_ok=True)
    unsafe.symlink_to(protected, target_is_directory=True)

    with pytest.raises(capabilities.CapabilityError, match="target|symlink"):
        capabilities.reconcile_all(
            vault,
            profile_path=profile_path,
            contract_path=contract_path,
        )

    assert not (vault / "05-Areas/Career").exists()
    assert not (vault / "05-Areas/Companies").exists()
    assert not (vault / "01-Quarter_Goals").exists()
    assert not (vault / ".claude/skills/career-setup").exists()
    assert unsafe.is_symlink()
    assert (protected / "sentinel.md").read_text(encoding="utf-8") == "preserve\n"


def test_reconcile_all_rolls_back_every_earlier_room_when_the_final_room_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _fake_vault(tmp_path)
    monkeypatch.setattr(capabilities, "REPO_ROOT", vault)
    contract_path = _fake_contract_with_skill_pins(tmp_path, vault)
    profile_path = _profile(
        vault / "System/user-profile.yaml",
        career=True,
        companies=True,
        quarter_goals=True,
    )
    original_profile = profile_path.read_bytes()
    original_copy = capabilities._copy_verified_room_skill

    def fail_on_final_room(pin, *args, **kwargs):
        if pin.target_path.endswith("/quarter-review/SKILL.md"):
            raise OSError("injected final-room failure")
        return original_copy(pin, *args, **kwargs)

    monkeypatch.setattr(capabilities, "_copy_verified_room_skill", fail_on_final_room)

    with pytest.raises(capabilities.CapabilityError, match="all-room|rollback|final-room"):
        capabilities.reconcile_all(
            vault,
            profile_path=profile_path,
            contract_path=contract_path,
        )

    assert profile_path.read_bytes() == original_profile
    assert not (vault / "05-Areas/Career").exists()
    assert not (vault / "05-Areas/Companies").exists()
    assert not (vault / "01-Quarter_Goals").exists()
    for skills in ROOM_SKILLS.values():
        for skill in skills:
            assert not (vault / ".claude/skills" / skill).exists()


def test_current_runtime_accepts_a_schema_valid_portable_v1_room_contract(
    tmp_path: Path,
) -> None:
    contract_path = tmp_path / "portable-vault-v1.json"
    contract_path.write_text(
        json.dumps(portable_contract.build_contract_document(contract_version=1)),
        encoding="utf-8",
    )
    vault = tmp_path / "vault"
    vault.mkdir()

    rooms = capabilities.preflight_all(vault, contract_path=contract_path)

    assert rooms == ("career", "companies", "quarter_goals")


def test_portable_v1_room_contract_cannot_redirect_current_skill_authority(
    tmp_path: Path,
) -> None:
    document = portable_contract.build_contract_document(contract_version=1)
    document["capabilities"]["career"]["skills"] = ["career-setup"]
    contract_path = tmp_path / "portable-vault-v1-drifted.json"
    contract_path.write_text(json.dumps(document), encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(
        capabilities.CapabilityError,
        match="v1.*skills|current release authority|identity",
    ):
        capabilities.preflight_all(vault, contract_path=contract_path)


def test_enable_preflights_dormant_assets_before_changing_profile_or_folders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _fake_vault(tmp_path)
    monkeypatch.setattr(capabilities, "REPO_ROOT", vault)
    contract_path = _fake_contract_with_skill_pins(tmp_path, vault)
    profile_path = _profile(vault / "System/user-profile.yaml", career=False)
    missing = vault / ".claude/skills/_available/capabilities/career/skills/career-coach"
    shutil.rmtree(missing)

    with pytest.raises(capabilities.CapabilityError, match="Dormant skill"):
        capabilities.set_enabled(
            "career",
            True,
            vault_root=vault,
            profile_path=profile_path,
            contract_path=contract_path,
        )

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert profile["capabilities"]["career"]["enabled"] is False
    assert not (vault / "05-Areas/Career").exists()


def test_enable_rejects_pinned_room_drift_without_any_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _fake_vault(tmp_path)
    monkeypatch.setattr(capabilities, "REPO_ROOT", vault)
    contract_path = _fake_contract_with_skill_pins(tmp_path, vault)
    profile_path = _profile(vault / "System/user-profile.yaml", career=False)
    original_profile = profile_path.read_bytes()
    active = vault / ".claude/skills/career-setup/SKILL.md"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text("existing active payload\n", encoding="utf-8")
    original_active = active.read_bytes()
    dormant = vault / ".claude/skills/_available/capabilities/career/skills/career-coach/SKILL.md"
    dormant.write_text("changed after release pin\n", encoding="utf-8")

    with pytest.raises(capabilities.CapabilityError, match="identity|sha256|byte_size|bytes"):
        capabilities.set_enabled(
            "career",
            True,
            vault_root=vault,
            profile_path=profile_path,
            contract_path=contract_path,
        )

    assert profile_path.read_bytes() == original_profile
    assert active.read_bytes() == original_active
    assert not (vault / "05-Areas/Career").exists()
    assert not (vault / ".claude/skills/career-coach").exists()


@pytest.mark.parametrize("unsafe_kind", ("symlink", "unpinned-file"))
def test_enable_preflights_every_active_skill_target_before_any_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_kind: str,
) -> None:
    vault = _fake_vault(tmp_path)
    monkeypatch.setattr(capabilities, "REPO_ROOT", vault)
    contract_path = _fake_contract_with_skill_pins(tmp_path, vault)
    profile_path = _profile(vault / "System/user-profile.yaml", career=False)
    original_profile = profile_path.read_bytes()

    # Plant the unsafe state at the final skill so an implementation that only
    # validates while copying would already have surfaced the first two skills.
    target = vault / ".claude/skills/resume-builder"
    if unsafe_kind == "symlink":
        redirected = vault / "05-Areas/Do-Not-Touch"
        redirected.mkdir(parents=True)
        (redirected / "sentinel.md").write_text("preserve\n", encoding="utf-8")
        target.symlink_to(redirected, target_is_directory=True)
    else:
        target.mkdir(parents=True)
        (target / "UNPINNED.md").write_text("preserve\n", encoding="utf-8")

    with pytest.raises(capabilities.CapabilityError, match="target|symlink|unpinned|unsafe"):
        capabilities.set_enabled(
            "career",
            True,
            vault_root=vault,
            profile_path=profile_path,
            contract_path=contract_path,
        )

    assert profile_path.read_bytes() == original_profile
    assert not (vault / "05-Areas/Career").exists()
    assert not (vault / ".claude/skills/career-setup").exists()
    assert not (vault / ".claude/skills/career-coach").exists()
    if unsafe_kind == "symlink":
        assert target.is_symlink()
        assert (vault / "05-Areas/Do-Not-Touch/sentinel.md").read_text(encoding="utf-8") == "preserve\n"
    else:
        assert (target / "UNPINNED.md").read_text(encoding="utf-8") == "preserve\n"


def test_enabled_room_targets_read_back_to_the_authoritative_pins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _fake_vault(tmp_path)
    monkeypatch.setattr(capabilities, "REPO_ROOT", vault)
    contract_path = _fake_contract_with_skill_pins(tmp_path, vault)
    profile_path = _profile(vault / "System/user-profile.yaml", career=False)

    capabilities.set_enabled(
        "career",
        True,
        vault_root=vault,
        profile_path=profile_path,
        contract_path=contract_path,
    )

    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    for pin in contract["capabilities"]["career"]["skill_sources"]:
        surfaced = vault / pin["target_path"]
        payload = surfaced.read_bytes()
        assert hashlib.sha256(payload).hexdigest() == pin["sha256"]
        assert len(payload) == pin["byte_size"]


def test_career_and_resume_mcps_report_room_off_without_creating_folders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_path = _profile(tmp_path / "System/user-profile.yaml", career=False)
    career_dir = tmp_path / "05-Areas/Career"
    monkeypatch.setattr(career_server, "USER_PROFILE_FILE", profile_path)
    monkeypatch.setattr(career_server, "CAREER_DIR", career_dir)
    monkeypatch.setattr(resume_server, "USER_PROFILE_FILE", profile_path)
    monkeypatch.setattr(resume_server, "RESUME_DIR", career_dir / "Resume")
    monkeypatch.setattr(resume_server, "SESSIONS_DIR", career_dir / "Resume/Sessions")

    career = _decode(asyncio.run(career_server.handle_call_tool("scan_evidence", {})))
    resume = _decode(asyncio.run(resume_server.handle_call_tool("list_sessions", {})))

    assert career["feature_status"] == "off"
    assert resume["feature_status"] == "off"
    assert not career_dir.exists()


def test_company_and_quarter_write_tools_do_not_repair_off_rooms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_path = _profile(
        tmp_path / "System/user-profile.yaml",
        companies=False,
        quarter_goals=False,
    )
    companies_dir = tmp_path / "05-Areas/Companies"
    goals_file = tmp_path / "01-Quarter_Goals/Quarter_Goals.md"
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile_path)
    monkeypatch.setattr(work_server, "COMPANIES_DIR", companies_dir)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals_file)

    company = work_server.create_company_page("Uninvited Company")
    goal = work_server.create_quarterly_goal_in_file(
        {
            "title": "Uninvited goal",
            "pillar": "pillar_1",
            "success_criteria": "It exists",
            "quarter": "Q3 2026",
        }
    )

    assert company["feature_status"] == "off"
    assert goal["feature_status"] == "off"
    assert not companies_dir.exists()
    assert not goals_file.parent.exists()

    listed_companies = _decode(asyncio.run(work_server.handle_call_tool("list_companies", {})))
    listed_goals = _decode(asyncio.run(work_server.handle_call_tool("get_quarterly_goals", {})))
    summary = _decode(asyncio.run(work_server.handle_call_tool("get_work_summary", {})))
    assert listed_companies["feature_status"] == "off"
    assert listed_goals["feature_status"] == "off"
    assert summary["quarterly_summary"]["feature_status"] == "off"
    assert "daily_summary" in summary


def test_shipped_room_skills_live_only_in_the_dormant_catalog() -> None:
    for room, skills in ROOM_SKILLS.items():
        for skill in skills:
            assert not (REPO_ROOT / ".claude/skills" / skill / "SKILL.md").exists()
            assert (
                REPO_ROOT / ".claude/skills/_available/capabilities" / room / "skills" / skill / "SKILL.md"
            ).is_file()


def test_setup_defers_rooms_to_the_onboarding_flow_and_creates_nothing_itself() -> None:
    """Setup must route into the MCP-driven flow, never provision rooms itself.

    It used to instruct a manual `capabilities.py --reconcile` call. Room
    provisioning is now owned by finalize_onboarding and core/provision.cjs, so
    the skill carrying its own copy is how the two paths drifted apart.
    """
    setup = (REPO_ROOT / ".claude/skills/setup/SKILL.md").read_text(encoding="utf-8")

    # Routes into the one deterministic flow.
    assert "start_onboarding_session()" in setup
    assert "core/onboarding/FLOW.md" in setup

    # Hand-rolls nothing: no room reconciliation, no folder creation.
    assert "--reconcile" not in setup
    assert "- `05-Areas/Companies/`" not in setup


def test_legacy_onboarded_vault_restores_companies_and_honors_legacy_state(tmp_path):
    """An existing vault with no Companies opinion gets the current default,
    while its explicit legacy quarter choice remains authoritative."""
    from core import capabilities

    vault = _fake_vault(tmp_path)
    (vault / "System").mkdir(parents=True, exist_ok=True)
    (vault / "System" / ".onboarding-complete").write_text("{}\n", encoding="utf-8")
    (vault / "System" / "user-profile.yaml").write_text(
        "name: Legacy User\nquarterly_planning:\n  enabled: false\n",
        encoding="utf-8",
    )

    seeded = capabilities.migrate_legacy_room_state(vault)

    assert sorted(seeded) == ["career", "companies"]
    profile_path = vault / "System" / "user-profile.yaml"
    assert capabilities.enabled("career", profile_path=profile_path) is True
    assert capabilities.enabled("companies", profile_path=profile_path) is True
    assert capabilities.enabled("quarter_goals", profile_path=profile_path) is False
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert profile["capabilities"]["companies"]["enabled"] is True
    assert profile["quarterly_planning"]["enabled"] is False
    # Idempotent: a second run seeds nothing.
    assert capabilities.migrate_legacy_room_state(vault) == []


def test_pre_engine_identity_without_marker_gets_legacy_room_pins(
    tmp_path: Path,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = vault / "System/user-profile.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        "name: Legacy User\nrole: Founder\nemail_domain: example.com\n",
        encoding="utf-8",
    )

    seeded = capabilities.migrate_legacy_room_state(vault)

    assert sorted(seeded) == ["career", "companies", "quarter_goals"]
    assert capabilities.enabled("career", profile_path=profile_path) is True
    assert capabilities.enabled("companies", profile_path=profile_path) is True
    assert capabilities.enabled("quarter_goals", profile_path=profile_path) is True


def test_real_room_content_without_marker_counts_as_onboarding_evidence(
    tmp_path: Path,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = vault / "System/user-profile.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text('name: ""\n', encoding="utf-8")
    note = vault / "05-Areas/Companies/Acme.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# Acme\n\nUser-authored account notes.\n", encoding="utf-8")

    seeded = capabilities.migrate_legacy_room_state(vault)

    assert sorted(seeded) == ["career", "companies", "quarter_goals"]
    assert capabilities.enabled("companies", profile_path=profile_path) is True


def test_shipped_room_seed_without_identity_is_not_onboarding_evidence(
    tmp_path: Path,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = vault / "System/user-profile.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text('name: ""\n', encoding="utf-8")
    shipped_seed = capabilities._dormant_root("companies", vault) / "folders/05-Areas/Companies/README.md"
    active_seed = vault / "05-Areas/Companies/README.md"
    active_seed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(shipped_seed, active_seed)

    assert capabilities.migrate_legacy_room_state(vault) == []
    assert "capabilities:" not in profile_path.read_text(encoding="utf-8")


def test_user_edit_to_tracked_room_seed_is_onboarding_evidence(
    tmp_path: Path,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = vault / "System/user-profile.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text('name: ""\n', encoding="utf-8")
    shipped_seed = capabilities._dormant_root("quarter_goals", vault) / "folders/01-Quarter_Goals/Quarter_Goals.md"
    active_seed = vault / "01-Quarter_Goals/Quarter_Goals.md"
    active_seed.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(shipped_seed, active_seed)
    subprocess.run(["git", "init", "--quiet"], cwd=vault, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Capability Test"],
        cwd=vault,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "capability@example.com"],
        cwd=vault,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "add",
            "--",
            "System/user-profile.yaml",
            "01-Quarter_Goals/Quarter_Goals.md",
        ],
        cwd=vault,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "shipped vault"],
        cwd=vault,
        check=True,
    )
    assert capabilities.migrate_legacy_room_state(vault) == []

    active_seed.write_text(
        active_seed.read_text(encoding="utf-8") + "\nMy real quarterly goal.\n",
        encoding="utf-8",
    )

    assert sorted(capabilities.migrate_legacy_room_state(vault)) == [
        "career",
        "companies",
        "quarter_goals",
    ]


@pytest.mark.parametrize("company_enabled", [True, False])
def test_legacy_migration_preserves_explicit_company_state(
    tmp_path: Path,
    company_enabled: bool,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = vault / "System/user-profile.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    (vault / "System/.onboarding-complete").write_text("{}\n", encoding="utf-8")
    profile_path.write_text(
        yaml.safe_dump(
            {
                "capabilities": {
                    "companies": {
                        "enabled": company_enabled,
                        "custom": "keep",
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    capabilities.migrate_legacy_room_state(vault)

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert profile["capabilities"]["companies"] == {
        "enabled": company_enabled,
        "custom": "keep",
    }


def test_partial_capability_map_gains_the_enabled_companies_compatibility_pin(
    tmp_path: Path,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = vault / "System/user-profile.yaml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    (vault / "System/.onboarding-complete").write_text("{}\n", encoding="utf-8")
    profile_path.write_text(
        "capabilities:\n  career:\n    enabled: false\n",
        encoding="utf-8",
    )

    seeded = capabilities.migrate_legacy_room_state(vault)

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert seeded == ["companies"]
    assert profile["capabilities"] == {
        "career": {"enabled": False},
        "companies": {"enabled": True},
    }
    assert (
        capabilities.enabled(
            "quarter_goals",
            profile_path=profile_path,
            contract_path=CONTRACT_PATH,
        )
        is True
    )


def test_fresh_unonboarded_vault_is_never_migrated(tmp_path):
    from core import capabilities

    vault = _fake_vault(tmp_path)
    (vault / "System").mkdir(parents=True, exist_ok=True)
    assert capabilities.migrate_legacy_room_state(vault) == []


def test_toggle_preserves_profile_comments(tmp_path):
    """Review finding #2: enabling a room must not strip the user's profile
    comments — only the enabled lines may change."""
    from core import capabilities

    vault = _fake_vault(tmp_path)
    (vault / "System").mkdir(parents=True, exist_ok=True)
    profile = vault / "System" / "user-profile.yaml"
    profile.write_text(
        "# Your name (used to identify you in meetings)\n"
        'name: ""\n'
        "\n"
        "# Quarterly planning preferences\n"
        "quarterly_planning:\n"
        "  enabled: false  # switch on for OKR workflows\n",
        encoding="utf-8",
    )

    capabilities.set_enabled("quarter_goals", True, vault_root=vault, profile_path=profile)

    text = profile.read_text(encoding="utf-8")
    assert "# Your name (used to identify you in meetings)" in text
    assert "# Quarterly planning preferences" in text
    assert "# switch on for OKR workflows" in text
    assert capabilities.enabled("quarter_goals", profile_path=profile) is True
