"""Behavioral coverage for onboarding-toggleable capability rooms."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
import yaml

from core import capabilities
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
            {
                "capabilities": {
                    room: {"enabled": enabled} for room, enabled in states.items()
                }
            },
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
            dormant = (
                vault
                / ".claude/skills/_available/capabilities"
                / room
                / "skills"
                / skill
                / "SKILL.md"
            )
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


def test_room_missing_from_contract_registry_is_unknown(tmp_path: Path) -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    contract["capabilities"].pop("career")
    reduced_contract = tmp_path / "contract.json"
    reduced_contract.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(capabilities.UnknownCapability, match="career"):
        capabilities.surfaces_for("career", contract_path=reduced_contract)


def test_all_rooms_default_off_and_legacy_quarterly_planning_is_a_fallback(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "System/user-profile.yaml"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text("quarterly_planning:\n  enabled: true\n", encoding="utf-8")

    assert capabilities.enabled(
        "career", profile_path=profile_path, contract_path=CONTRACT_PATH
    ) is False
    assert capabilities.enabled(
        "companies", profile_path=profile_path, contract_path=CONTRACT_PATH
    ) is False
    assert capabilities.enabled(
        "quarter_goals", profile_path=profile_path, contract_path=CONTRACT_PATH
    ) is True

    profile_path.write_text(
        "capabilities:\n  quarter_goals:\n    enabled: false\n"
        "quarterly_planning:\n  enabled: true\n",
        encoding="utf-8",
    )
    assert capabilities.enabled(
        "quarter_goals", profile_path=profile_path, contract_path=CONTRACT_PATH
    ) is False

    profile_path.write_text("capabilities: malformed\n", encoding="utf-8")
    assert capabilities.enabled(
        "career", profile_path=profile_path, contract_path=CONTRACT_PATH
    ) is False


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
        for folder in capabilities.surfaces_for(
            room, contract_path=CONTRACT_PATH
        ).get("folders", []):
            assert not (vault / folder).exists()
        for skill in capabilities.surfaces_for(
            room, contract_path=CONTRACT_PATH
        ).get("skills", []):
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


def test_reconcile_refreshes_enabled_skills_after_a_brain_update(
    tmp_path: Path,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = _profile(vault / "System/user-profile.yaml", career=True)
    stale = vault / ".claude/skills/career-setup/SKILL.md"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale release copy\n", encoding="utf-8")

    capabilities.reconcile_all(
        vault,
        profile_path=profile_path,
        contract_path=CONTRACT_PATH,
    )

    assert "description: Test skill" in stale.read_text(encoding="utf-8")


def test_enable_preflights_dormant_assets_before_changing_profile_or_folders(
    tmp_path: Path,
) -> None:
    vault = _fake_vault(tmp_path)
    profile_path = _profile(vault / "System/user-profile.yaml", career=False)
    missing = vault / ".claude/skills/_available/capabilities/career/skills/career-coach"
    shutil.rmtree(missing)

    with pytest.raises(capabilities.CapabilityError, match="Dormant skill"):
        capabilities.set_enabled(
            "career",
            True,
            vault_root=vault,
            profile_path=profile_path,
            contract_path=CONTRACT_PATH,
        )

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert profile["capabilities"]["career"]["enabled"] is False
    assert not (vault / "05-Areas/Career").exists()


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

    listed_companies = _decode(
        asyncio.run(work_server.handle_call_tool("list_companies", {}))
    )
    listed_goals = _decode(
        asyncio.run(work_server.handle_call_tool("get_quarterly_goals", {}))
    )
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
                REPO_ROOT
                / ".claude/skills/_available/capabilities"
                / room
                / "skills"
                / skill
                / "SKILL.md"
            ).is_file()


def test_setup_reconciles_rooms_without_creating_companies_directly() -> None:
    setup = (REPO_ROOT / ".claude/skills/setup/SKILL.md").read_text(encoding="utf-8")

    assert "core/capabilities.py\" --reconcile" in setup
    assert "- `05-Areas/Companies/`" not in setup
