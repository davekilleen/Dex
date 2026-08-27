"""Lifecycle-owned persistence for confirmed onboarding context."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from core.lifecycle import service
from core.transaction.engine import PlanRejected


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    system = vault / "System"
    system.mkdir(parents=True)
    (system / "user-profile.yaml").write_text(
        yaml.safe_dump({"name": "Example User", "calendar": {"work_calendar": "Old"}}, sort_keys=False),
        encoding="utf-8",
    )
    return vault


def test_confirmed_onboarding_context_is_previewed_then_transactionally_applied(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    original = profile.read_text(encoding="utf-8")

    previewed = service.build_and_preview_onboarding_context(
        vault,
        working_context={"role_focus": "Lead product work", "key_people": []},
        calendar_source={"provider": "apple", "work_calendar": "Work"},
    )

    assert profile.read_text(encoding="utf-8") == original
    assert previewed["preview"]["working_context"] == {
        "role_focus": "Lead product work",
        "key_people": [],
    }
    assert previewed["preview"]["calendar_source"] == {
        "provider": "apple",
        "work_calendar": "Work",
    }

    executed = service.execute_approved_onboarding_context(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    saved = yaml.safe_load(profile.read_text(encoding="utf-8"))
    assert saved["working_context"] == previewed["preview"]["working_context"]
    assert saved["calendar"] == previewed["preview"]["calendar_source"]
    assert executed["receipt"]["purpose"] == "onboarding-context"


def test_confirmed_onboarding_context_accepts_google_calendar_account(tmp_path: Path) -> None:
    vault = _vault(tmp_path)

    previewed = service.build_and_preview_onboarding_context(
        vault,
        working_context={"role_focus": "Lead product work", "key_people": []},
        calendar_source={"provider": "google", "account": "doireann.marron@pendo.io"},
    )

    assert previewed["preview"]["calendar_source"] == {
        "provider": "google",
        "account": "doireann.marron@pendo.io",
    }

    service.execute_approved_onboarding_context(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )
    saved = yaml.safe_load((vault / "System" / "user-profile.yaml").read_text(encoding="utf-8"))
    assert saved["calendar"] == {"provider": "google", "account": "doireann.marron@pendo.io"}


def test_write_onboarding_lab_marker_creates_runtime_file(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    result = service.write_onboarding_lab_marker(vault)
    marker = vault / "System" / ".onboarding-lab"
    assert marker.is_file()
    saved = json.loads(marker.read_text(encoding="utf-8"))
    assert saved["lab"] is True
    assert result["receipt"]["purpose"] == "onboarding-lab"


def test_confirmed_onboarding_context_refuses_google_without_account(tmp_path: Path) -> None:
    vault = _vault(tmp_path)

    with pytest.raises(PlanRejected, match="account email"):
        service.build_and_preview_onboarding_context(
            vault,
            working_context={"role_focus": "Lead product work", "key_people": []},
            calendar_source={"provider": "google", "calendar_id": "primary"},
        )


def test_preview_reads_and_hashes_one_profile_buffer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    original_profile = profile.read_bytes()
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes
    profile_reads = 0
    captured_expected_sha = ""

    def forbid_split_profile_read(path: Path, *args, **kwargs) -> str:
        if path == profile:
            raise AssertionError("profile parsing must use the same bytes that are hashed")
        return original_read_text(path, *args, **kwargs)

    def count_profile_bytes(path: Path) -> bytes:
        nonlocal profile_reads
        if path == profile:
            profile_reads += 1
        return original_read_bytes(path)

    def capture_plan(_vault_root, plan, *, purpose, operation):
        nonlocal captured_expected_sha
        assert purpose == "onboarding-context"
        assert operation == "onboarding-context"
        captured_expected_sha = plan[0].expected_current_sha256
        return {"writes": [{"path": "System/user-profile.yaml"}]}

    monkeypatch.setattr(Path, "read_text", forbid_split_profile_read)
    monkeypatch.setattr(Path, "read_bytes", count_profile_bytes)
    monkeypatch.setattr(service, "_transaction_preview_document", capture_plan)

    service.build_and_preview_onboarding_context(
        vault,
        working_context={"role_focus": "Lead product work", "key_people": []},
        calendar_source={"provider": "none"},
    )

    assert profile_reads == 1
    assert captured_expected_sha == hashlib.sha256(original_profile).hexdigest()


@pytest.mark.parametrize("approved_token", ["", "0" * 64])
def test_execute_refuses_missing_or_wrong_approval_token(
    tmp_path: Path,
    approved_token: str,
) -> None:
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    original = profile.read_bytes()
    previewed = service.build_and_preview_onboarding_context(
        vault,
        working_context={"role_focus": "Lead product work", "key_people": []},
        calendar_source={"provider": "none"},
    )

    with pytest.raises(PlanRejected, match="approval does not match"):
        service.execute_approved_onboarding_context(
            vault,
            previewed["preview"],
            approved_token,
        )

    assert profile.read_bytes() == original


def test_execute_refuses_a_tampered_preview(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    original = profile.read_bytes()
    previewed = service.build_and_preview_onboarding_context(
        vault,
        working_context={"role_focus": "Lead product work", "key_people": []},
        calendar_source={"provider": "none"},
    )
    tampered = copy.deepcopy(previewed["preview"])
    tampered["working_context"]["role_focus"] = "Unapproved replacement"

    with pytest.raises(PlanRejected, match="approval does not match"):
        service.execute_approved_onboarding_context(
            vault,
            tampered,
            previewed["approval_token"],
        )

    assert profile.read_bytes() == original


def test_execute_refuses_a_profile_changed_after_preview(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    previewed = service.build_and_preview_onboarding_context(
        vault,
        working_context={"role_focus": "Lead product work", "key_people": []},
        calendar_source={"provider": "none"},
    )
    changed = yaml.safe_load(profile.read_text(encoding="utf-8"))
    changed["concurrent_edit"] = "keep me"
    profile.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")

    with pytest.raises(PlanRejected, match="approval does not match"):
        service.execute_approved_onboarding_context(
            vault,
            previewed["preview"],
            previewed["approval_token"],
        )

    saved = yaml.safe_load(profile.read_text(encoding="utf-8"))
    assert saved["concurrent_edit"] == "keep me"
    assert "working_context" not in saved


def test_onboarding_context_plans_only_the_live_profile(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    unrelated = vault / "System" / "unrelated.json"
    unrelated.write_text('{"keep": true}\n', encoding="utf-8")
    previewed = service.build_and_preview_onboarding_context(
        vault,
        working_context={"role_focus": "Lead product work", "key_people": []},
        calendar_source={"provider": "apple", "work_calendar": "Work"},
    )

    assert [write["path"] for write in previewed["preview"]["writes"]] == [
        "System/user-profile.yaml"
    ]

    executed = service.execute_approved_onboarding_context(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    assert [write["path"] for write in executed["receipt"]["files_written"]] == [
        "System/user-profile.yaml"
    ]
    assert unrelated.read_text(encoding="utf-8") == '{"keep": true}\n'
