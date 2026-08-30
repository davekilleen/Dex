"""Doctor names every written door on this machine, one sentence each."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.harnesses.chatgpt_work_personal_copy import STALE_WORK_COPY_SENTENCE
from core.harnesses.doors import (
    CONFIRMED_IS_NOT_WALKED,
    NOTES_PANEL_INSTALLED,
    NOTES_PANEL_MISSING,
    WALK_RULES,
    door_report,
)
from core.harnesses.registry import list_profiles
from core.onboarding.harness_receipt import (
    build_receipt_for_ids,
    canonical_receipt_bytes,
)
from core.utils import doctor

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_ROOT = REPO_ROOT / "core" / "harnesses" / "adapters"


@pytest.fixture
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> doctor.DoctorContext:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def _write_receipt(context: doctor.DoctorContext, profile_ids: list[str]) -> None:
    receipt = build_receipt_for_ids(
        profile_ids,
        detected_ids=tuple(profile_ids),
        source="user-confirmed",
        generated_at=NOW,
    )
    path = context.vault_root / "System/.dex/harness-profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_receipt_bytes(receipt))


def _assert_no_granted_true(payload: object) -> None:
    encoded = json.dumps(payload, default=str).lower()
    assert '"granted": true' not in encoded
    assert '"granted":true' not in encoded
    assert "granted=true" not in encoded


def test_every_written_adapter_has_a_walk_rule() -> None:
    adapter_ids = {path.stem for path in ADAPTER_ROOT.glob("*.json")}
    profile_ids = {profile.id for profile in list_profiles()}
    assert set(WALK_RULES) == adapter_ids == profile_ids


def test_doctor_names_every_written_door_before_setup(context: doctor.DoctorContext) -> None:
    result = doctor._probe_harness_capabilities(context)
    names = [profile.display_name for profile in list_profiles()]

    assert result.verdict == "OFF"
    assert "record your harnesses without restarting onboarding" in result.detail.lower()
    for name in names:
        assert f"{name} is a written door you have never opened." in result.detail
        assert f"You confirmed {name}." not in result.detail
    assert NOTES_PANEL_MISSING in result.detail
    assert CONFIRMED_IS_NOT_WALKED in result.detail
    assert result.detail.index(NOTES_PANEL_MISSING) < result.detail.index(
        CONFIRMED_IS_NOT_WALKED
    )
    assert [door["id"] for door in result.structured_detail["doors"]] == [
        profile.id for profile in list_profiles()
    ]
    assert result.structured_detail["notes_panel"]["installed"] is False
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(result.detail)


def test_doctor_names_confirmed_doors_without_calling_them_walked(
    context: doctor.DoctorContext,
) -> None:
    _write_receipt(context, ["codex"])
    result = doctor._probe_harness_capabilities(context)
    names = {profile.id: profile.display_name for profile in list_profiles()}

    assert result.verdict == "OK"
    assert "You confirmed Codex." in result.detail
    assert "You confirmed Codex, and it is walked on this machine." not in result.detail
    for profile_id, name in names.items():
        if profile_id == "codex":
            continue
        assert f"{name} is a written door you have never opened." in result.detail
        assert f"You confirmed {name}." not in result.detail
    assert NOTES_PANEL_MISSING in result.detail
    assert CONFIRMED_IS_NOT_WALKED in result.detail
    assert result.structured_detail["doors"][5]["id"] == "codex"
    assert result.structured_detail["doors"][5]["confirmed"] is True
    assert result.structured_detail["doors"][5]["walked"] is False
    _assert_no_granted_true(result.structured_detail)


def test_doctor_names_a_walked_work_copy_without_inventing_a_folder_grant(
    context: doctor.DoctorContext,
) -> None:
    _write_receipt(context, ["chatgpt-work"])
    manifest = (
        context.home
        / ".codex"
        / "plugins"
        / "dex"
        / ".codex-plugin"
        / "plugin.json"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "dex", "version": "1.0.1"}) + "\n")

    result = doctor._probe_harness_capabilities(context)

    assert "You confirmed ChatGPT Work companion, and it is walked on this machine." in (
        result.detail
    )
    assert "granted=true" not in result.detail.lower()
    work = next(door for door in result.structured_detail["doors"] if door["id"] == "chatgpt-work")
    assert work["confirmed"] is True
    assert work["walked"] is True
    _assert_no_granted_true(result.structured_detail)


def test_doctor_names_the_notes_panel_when_its_manifest_is_present(
    context: doctor.DoctorContext,
) -> None:
    _write_receipt(context, ["cursor"])
    manifest = context.vault_root / ".obsidian" / "plugins" / "dex-readonly" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}\n", encoding="utf-8")
    cursor_plugin = (
        context.home / ".cursor" / "plugins" / "local" / "dex" / ".cursor-plugin" / "plugin.json"
    )
    cursor_plugin.parent.mkdir(parents=True)
    cursor_plugin.write_text(json.dumps({"name": "dex"}) + "\n")

    result = doctor._probe_harness_capabilities(context)

    assert NOTES_PANEL_INSTALLED in result.detail
    assert NOTES_PANEL_MISSING not in result.detail
    assert "You confirmed Cursor, and it is walked on this machine." in result.detail
    assert result.structured_detail["notes_panel"]["installed"] is True
    assert result.detail.index(NOTES_PANEL_INSTALLED) < result.detail.index(
        CONFIRMED_IS_NOT_WALKED
    )


def test_stale_work_copy_sentence_stays_last_after_door_sentences(
    context: doctor.DoctorContext, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    packaged = repo / "packages" / "dex-agent-plugin" / ".codex-plugin" / "plugin.json"
    packaged.parent.mkdir(parents=True)
    packaged.write_text(json.dumps({"name": "dex", "version": "1.0.1"}) + "\n")
    personal = (
        context.home / ".codex" / "plugins" / "dex" / ".codex-plugin" / "plugin.json"
    )
    personal.parent.mkdir(parents=True)
    personal.write_text(json.dumps({"name": "dex", "version": "1.0.0"}) + "\n")
    stale_context = doctor.DoctorContext(
        vault_root=context.vault_root,
        repo_root=repo,
        home=context.home,
        now=NOW,
    )
    _write_receipt(stale_context, ["chatgpt-work"])

    result = doctor._probe_harness_capabilities(stale_context)
    rendered = doctor._result_json(
        next(check for check in doctor.QUICK_CHECKS if check.id == "harness.capabilities"),
        result,
    )

    assert result.detail.endswith(STALE_WORK_COPY_SENTENCE)
    assert rendered["detail"].endswith(STALE_WORK_COPY_SENTENCE)
    assert CONFIRMED_IS_NOT_WALKED in result.detail
    assert result.detail.index(CONFIRMED_IS_NOT_WALKED) < result.detail.index(
        STALE_WORK_COPY_SENTENCE
    )
    assert result.detail.count(STALE_WORK_COPY_SENTENCE) == 1
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(rendered)


def test_door_report_covers_the_adapter_registry_without_a_grant_flag(
    tmp_path: Path,
) -> None:
    report = door_report(home=tmp_path / "home", vault_root=tmp_path / "vault")
    encoded = json.dumps(report.as_structured())

    assert [door.id for door in report.doors] == [profile.id for profile in list_profiles()]
    assert all(not door.confirmed and not door.walked for door in report.doors)
    assert report.notes_panel_installed is False
    assert "granted" not in encoded
    assert encoded.count(CONFIRMED_IS_NOT_WALKED) == 1
