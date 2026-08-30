"""Doctor names every written door on this machine, one sentence each."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.harnesses.chatgpt_work_personal_copy import STALE_WORK_COPY_SENTENCE
from core.harnesses.doors import (
    CONFIRMED_IS_NOT_WALKED,
    LEFTOVER_COPY,
    LEFTOVER_DETECTORS,
    NOTES_PANEL_HALF_ON,
    NOTES_PANEL_INSTALLED,
    NOTES_PANEL_LEFTOVER,
    NOTES_PANEL_MISSING,
    NOTES_PANEL_SWITCH,
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
    assert set(LEFTOVER_COPY) == adapter_ids
    assert set(LEFTOVER_DETECTORS) == adapter_ids


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
    assert result.structured_detail["notes_panel"]["switched_on"] is False
    assert result.structured_detail["notes_panel"]["left"] is False
    assert "switch" not in result.structured_detail["notes_panel"]
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
    assert result.structured_detail["doors"][5]["left"] is False
    assert "You left Codex." not in result.detail
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
    assert work["left"] is False
    assert "You left ChatGPT Work companion." not in result.detail
    _assert_no_granted_true(result.structured_detail)


def test_doctor_names_half_on_notes_panel_files_and_the_switch(
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

    assert "You confirmed Cursor, and it is walked on this machine." in result.detail
    assert NOTES_PANEL_HALF_ON in result.detail
    assert NOTES_PANEL_INSTALLED not in result.detail
    assert NOTES_PANEL_SWITCH in result.detail
    assert "this checkup will not flip it." in result.detail
    assert result.structured_detail["notes_panel"]["installed"] is True
    assert result.structured_detail["notes_panel"]["switched_on"] is False
    assert result.structured_detail["notes_panel"]["left"] is False
    assert result.structured_detail["notes_panel"]["switch"] == NOTES_PANEL_SWITCH
    assert result.detail.index(NOTES_PANEL_HALF_ON) < result.detail.index(
        CONFIRMED_IS_NOT_WALKED
    )
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(result.detail)


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
    assert all(not door.confirmed and not door.walked and not door.left for door in report.doors)
    assert report.notes_panel_installed is False
    assert report.notes_panel_switched_on is False
    assert report.notes_panel_left is False
    assert report.notes_panel_switch is None
    assert "granted" not in encoded
    assert encoded.count(CONFIRMED_IS_NOT_WALKED) == 1
    assert "You left " not in encoded
    assert "Leftover:" not in encoded


def test_doctor_proves_a_work_leave_and_names_the_grant_leftover(
    context: doctor.DoctorContext,
) -> None:
    _write_receipt(context, ["chatgpt-work"])
    cache = (
        context.home
        / ".codex"
        / "plugins"
        / "cache"
        / "dex-unreleased"
        / "dex"
        / "local"
    )
    cache.mkdir(parents=True)

    result = doctor._probe_harness_capabilities(context)
    leftover = LEFTOVER_COPY["chatgpt-work"]
    work = next(door for door in result.structured_detail["doors"] if door["id"] == "chatgpt-work")

    assert f"You left ChatGPT Work companion. Leftover: {leftover}" in result.detail
    assert "You confirmed ChatGPT Work companion." not in result.detail
    assert "You confirmed ChatGPT Work companion, and it is walked on this machine." not in (
        result.detail
    )
    assert "ChatGPT Work companion is a written door you have never opened." not in result.detail
    assert work["confirmed"] is True
    assert work["walked"] is False
    assert work["left"] is True
    assert work["leftover"] == leftover
    assert "granted" not in json.dumps(work)
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(result.detail)


def test_doctor_proves_a_work_leave_from_a_marketplace_listing_without_inventing_a_grant(
    context: doctor.DoctorContext,
) -> None:
    marketplace = context.home / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(
        json.dumps(
            {
                "name": "dex-unreleased",
                "plugins": [{"name": "dex", "source": {"source": "local", "path": "./.codex/plugins/dex"}}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = doctor._probe_harness_capabilities(context)
    leftover = LEFTOVER_COPY["chatgpt-work"]
    work = next(door for door in result.structured_detail["doors"] if door["id"] == "chatgpt-work")

    assert f"You left ChatGPT Work companion. Leftover: {leftover}" in result.detail
    assert work["confirmed"] is False
    assert work["walked"] is False
    assert work["left"] is True
    assert work["leftover"] == leftover
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(result.detail)


def test_confirmed_work_without_residue_is_not_a_leave(
    context: doctor.DoctorContext,
) -> None:
    _write_receipt(context, ["chatgpt-work"])

    result = doctor._probe_harness_capabilities(context)
    work = next(door for door in result.structured_detail["doors"] if door["id"] == "chatgpt-work")

    assert "You confirmed ChatGPT Work companion." in result.detail
    assert "You left ChatGPT Work companion." not in result.detail
    assert "Leftover:" not in result.detail
    assert work["left"] is False
    assert "leftover" not in work
    _assert_no_granted_true(result.structured_detail)


def test_walked_work_copy_with_cache_is_not_a_leave(
    context: doctor.DoctorContext,
) -> None:
    _write_receipt(context, ["chatgpt-work"])
    manifest = (
        context.home / ".codex" / "plugins" / "dex" / ".codex-plugin" / "plugin.json"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "dex", "version": "1.0.1"}) + "\n")
    cache = (
        context.home
        / ".codex"
        / "plugins"
        / "cache"
        / "dex-unreleased"
        / "dex"
        / "local"
    )
    cache.mkdir(parents=True)

    result = doctor._probe_harness_capabilities(context)
    work = next(door for door in result.structured_detail["doors"] if door["id"] == "chatgpt-work")

    assert "You confirmed ChatGPT Work companion, and it is walked on this machine." in (
        result.detail
    )
    assert "You left ChatGPT Work companion." not in result.detail
    assert work["walked"] is True
    assert work["left"] is False
    _assert_no_granted_true(result.structured_detail)


def test_doctor_proves_a_notes_panel_leave_and_names_the_listing_leftover(
    context: doctor.DoctorContext,
) -> None:
    listing = context.vault_root / ".obsidian" / "community-plugins.json"
    listing.parent.mkdir(parents=True)
    listing.write_text('["dex-readonly"]\n', encoding="utf-8")

    result = doctor._probe_harness_capabilities(context)
    expected = f"{NOTES_PANEL_MISSING} Leftover: {NOTES_PANEL_LEFTOVER}"

    assert expected in result.detail
    assert result.detail.index(expected) < result.detail.index(CONFIRMED_IS_NOT_WALKED)
    assert result.structured_detail["notes_panel"]["installed"] is False
    assert result.structured_detail["notes_panel"]["switched_on"] is True
    assert result.structured_detail["notes_panel"]["left"] is True
    assert result.structured_detail["notes_panel"]["leftover"] == NOTES_PANEL_LEFTOVER
    assert "switch" not in result.structured_detail["notes_panel"]
    _assert_no_granted_true(result.structured_detail)


def test_notes_panel_listing_is_not_a_leave_while_the_plugin_is_installed(
    context: doctor.DoctorContext,
) -> None:
    manifest = context.vault_root / ".obsidian" / "plugins" / "dex-readonly" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}\n", encoding="utf-8")
    listing = context.vault_root / ".obsidian" / "community-plugins.json"
    listing.write_text('["dex-readonly"]\n', encoding="utf-8")

    result = doctor._probe_harness_capabilities(context)

    assert NOTES_PANEL_INSTALLED in result.detail
    assert NOTES_PANEL_HALF_ON not in result.detail
    assert "Leftover:" not in result.detail
    assert result.structured_detail["notes_panel"]["installed"] is True
    assert result.structured_detail["notes_panel"]["switched_on"] is True
    assert result.structured_detail["notes_panel"]["left"] is False
    assert "switch" not in result.structured_detail["notes_panel"]
    _assert_no_granted_true(result.structured_detail)


def test_doctor_names_cursor_and_copilot_leftovers_after_a_leave(
    context: doctor.DoctorContext,
) -> None:
    cursor_dir = context.home / ".cursor" / "plugins" / "local" / "dex"
    cursor_dir.mkdir(parents=True)
    copilot_dir = (
        context.home / ".copilot" / "installed-plugins" / "_direct" / "dex-agent-plugin"
    )
    copilot_dir.mkdir(parents=True)

    result = doctor._probe_harness_capabilities(context)
    by_id = {door["id"]: door for door in result.structured_detail["doors"]}

    assert f"You left Cursor. Leftover: {LEFTOVER_COPY['cursor']}" in result.detail
    assert (
        f"You left GitHub Copilot CLI. Leftover: {LEFTOVER_COPY['copilot-cli']}"
        in result.detail
    )
    assert by_id["cursor"]["left"] is True
    assert by_id["copilot-cli"]["left"] is True
    assert by_id["cursor"]["walked"] is False
    assert by_id["copilot-cli"]["walked"] is False
    _assert_no_granted_true(result.structured_detail)


def test_half_on_notes_panel_is_not_a_leave(context: doctor.DoctorContext) -> None:
    manifest = context.vault_root / ".obsidian" / "plugins" / "dex-readonly" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}\n", encoding="utf-8")

    result = doctor._probe_harness_capabilities(context)

    assert NOTES_PANEL_HALF_ON in result.detail
    assert "Leftover:" not in result.detail
    assert result.structured_detail["notes_panel"]["left"] is False
    assert "leftover" not in result.structured_detail["notes_panel"]
    _assert_no_granted_true(result.structured_detail)


def test_doctor_does_not_flip_the_notes_panel_switch(context: doctor.DoctorContext) -> None:
    plugin_dir = context.vault_root / ".obsidian" / "plugins" / "dex-readonly"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
    listing = context.vault_root / ".obsidian" / "community-plugins.json"
    listing.write_text('["unrelated-plugin"]\n', encoding="utf-8")
    before = {
        path: path.read_bytes()
        for path in (context.vault_root / ".obsidian").rglob("*")
        if path.is_file()
    }

    result = doctor._probe_harness_capabilities(context)

    after = {
        path: path.read_bytes()
        for path in (context.vault_root / ".obsidian").rglob("*")
        if path.is_file()
    }
    assert NOTES_PANEL_HALF_ON in result.detail
    assert listing.read_text(encoding="utf-8") == '["unrelated-plugin"]\n'
    assert "dex-readonly" not in listing.read_text(encoding="utf-8")
    assert after == before
    assert result.structured_detail["notes_panel"]["switched_on"] is False
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(result.detail)


def test_stale_work_copy_sentence_stays_last_after_half_on_notes_panel(
    context: doctor.DoctorContext, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    packaged = repo / "packages" / "dex-agent-plugin" / ".codex-plugin" / "plugin.json"
    packaged.parent.mkdir(parents=True)
    packaged.write_text(json.dumps({"name": "dex", "version": "1.0.1"}) + "\n")
    personal = context.home / ".codex" / "plugins" / "dex" / ".codex-plugin" / "plugin.json"
    personal.parent.mkdir(parents=True)
    personal.write_text(json.dumps({"name": "dex", "version": "1.0.0"}) + "\n")
    manifest = context.vault_root / ".obsidian" / "plugins" / "dex-readonly" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}\n", encoding="utf-8")
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

    assert NOTES_PANEL_HALF_ON in result.detail
    assert result.detail.endswith(STALE_WORK_COPY_SENTENCE)
    assert rendered["detail"].endswith(STALE_WORK_COPY_SENTENCE)
    assert result.detail.index(NOTES_PANEL_HALF_ON) < result.detail.index(
        STALE_WORK_COPY_SENTENCE
    )
    assert result.detail.count(STALE_WORK_COPY_SENTENCE) == 1
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(rendered)


def test_leftover_copy_is_final_and_never_sets_granted() -> None:
    assert LEFTOVER_COPY["chatgpt-work"] == (
        "the vault-folder grant — a person must revoke it; this runner will not "
        "invent that grant. The cache at `~/.codex/plugins/cache/dex-unreleased/dex/local/` "
        "is not Work proof."
    )
    assert LEFTOVER_COPY["cursor"] == "hook approval."
    assert (
        LEFTOVER_COPY["copilot-cli"]
        == "a direct-install copy under `~/.copilot/installed-plugins/_direct/`."
    )
    _assert_no_granted_true(LEFTOVER_COPY)
    _assert_no_granted_true(NOTES_PANEL_LEFTOVER)
    _assert_no_granted_true(NOTES_PANEL_HALF_ON)
    _assert_no_granted_true(NOTES_PANEL_SWITCH)
