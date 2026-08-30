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
    cannot_see_opened_sentence,
    door_is_detectable,
    door_report,
    never_opened_sentence,
    notes_panel_sentence,
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


def _vault_folder_name(vault_root: Path) -> str:
    name = Path(vault_root).name
    assert name not in ("", ".")
    return name


def _installed_sentence(vault_root: Path) -> str:
    name = _vault_folder_name(vault_root)
    return f"The notes panel is installed in the {name} vault."


def _missing_sentence(vault_root: Path) -> str:
    name = _vault_folder_name(vault_root)
    return (
        f"The notes panel is not installed in the {name} vault. "
        f"This checkup looked only in the {name} vault, not across the machine."
    )


def _half_on_sentence(vault_root: Path) -> str:
    name = _vault_folder_name(vault_root)
    return (
        f"The notes panel files are there in the {name} vault, but the panel is not switched on. "
        f"The switch is {NOTES_PANEL_SWITCH}; this checkup will not flip it."
    )


def _assert_notes_panel_sentence_names_folder_only(
    sentence: str,
    vault_root: Path,
    *,
    allow_switch_slash: bool = False,
) -> None:
    name = _vault_folder_name(vault_root)
    assert name in sentence
    assert "this vault" not in sentence
    assert "on this machine" not in sentence
    assert "~" not in sentence
    assert "$HOME" not in sentence
    rooted = Path(vault_root)
    if rooted.parent.as_posix() not in (".", ""):
        assert str(rooted) not in sentence
        assert str(rooted.parent) not in sentence
        parent_name = rooted.parent.name
        if parent_name not in ("", ".", name):
            assert parent_name not in sentence
    checked = (
        sentence.replace("`.obsidian/community-plugins.json`", "")
        if allow_switch_slash
        else sentence
    )
    assert "/" not in checked


def test_every_written_adapter_has_a_walk_rule() -> None:
    adapter_ids = {path.stem for path in ADAPTER_ROOT.glob("*.json")}
    profile_ids = {profile.id for profile in list_profiles()}
    assert set(WALK_RULES) == adapter_ids == profile_ids
    assert set(LEFTOVER_COPY) == adapter_ids
    assert set(LEFTOVER_DETECTORS) == adapter_ids


def test_walk_rules_are_unchanged_and_name_unseen_doors() -> None:
    assert WALK_RULES == {
        "agent-plugin": None,
        "bb": None,
        "chatgpt-work": ("home-file", ".codex/plugins/dex/.codex-plugin/plugin.json"),
        "claude-code": None,
        "claude-desktop": None,
        "codex": None,
        "copilot-cli": ("home-dex-manifest", ".copilot/installed-plugins/_direct"),
        "cowork": None,
        "cursor": ("home-file", ".cursor/plugins/local/dex/.cursor-plugin/plugin.json"),
        "gemini-cli": ("home-dex-manifest", ".gemini/extensions"),
        "pi": None,
    }
    assert cannot_see_opened_sentence("Codex") == (
        "Codex is a written door and this checkup cannot see whether you have opened it."
    )
    assert never_opened_sentence("Cursor") == (
        "Cursor is a written door you have never opened."
    )


def test_notes_panel_sentence_constants_pin_vault_scope() -> None:
    named = Path("alpha-notes")
    assert _installed_sentence(named) == "The notes panel is installed in the alpha-notes vault."
    assert _missing_sentence(named) == (
        "The notes panel is not installed in the alpha-notes vault. "
        "This checkup looked only in the alpha-notes vault, not across the machine."
    )
    assert _half_on_sentence(named) == (
        "The notes panel files are there in the alpha-notes vault, but the panel is not switched on. "
        "The switch is `.obsidian/community-plugins.json` listing `dex-readonly`; "
        "this checkup will not flip it."
    )
    assert notes_panel_sentence(
        installed=True, leftover=False, switched_on=True, vault_root=named
    ) == _installed_sentence(named)
    assert notes_panel_sentence(
        installed=False, leftover=False, switched_on=False, vault_root=named
    ) == _missing_sentence(named)
    assert notes_panel_sentence(
        installed=True, leftover=False, switched_on=False, vault_root=named
    ) == _half_on_sentence(named)
    assert notes_panel_sentence(
        installed=False, leftover=True, switched_on=True, vault_root=named
    ) == f"{_missing_sentence(named)} Leftover: {NOTES_PANEL_LEFTOVER}"
    assert NOTES_PANEL_INSTALLED == "The notes panel is installed in this vault."
    assert NOTES_PANEL_MISSING == (
        "The notes panel is not installed in this vault. "
        "This checkup looked only in this vault, not across the machine."
    )
    assert NOTES_PANEL_HALF_ON == (
        "The notes panel files are there, but the panel is not switched on. "
        "The switch is `.obsidian/community-plugins.json` listing `dex-readonly`; "
        "this checkup will not flip it."
    )
    assert notes_panel_sentence(
        installed=True, leftover=False, switched_on=True, vault_root=Path(".")
    ) == NOTES_PANEL_INSTALLED
    assert notes_panel_sentence(
        installed=False, leftover=False, switched_on=False, vault_root=""
    ) == NOTES_PANEL_MISSING
    assert notes_panel_sentence(
        installed=True, leftover=False, switched_on=False, vault_root=Path(".")
    ) == NOTES_PANEL_HALF_ON
    assert "on this machine" not in _installed_sentence(named)
    assert "on this machine" not in _missing_sentence(named)
    assert "on this machine" not in _half_on_sentence(named)
    assert "on this machine" not in NOTES_PANEL_INSTALLED
    assert "on this machine" not in NOTES_PANEL_MISSING
    assert "on this machine" not in NOTES_PANEL_HALF_ON
    _assert_notes_panel_sentence_names_folder_only(_installed_sentence(named), named)
    _assert_notes_panel_sentence_names_folder_only(_missing_sentence(named), named)
    _assert_notes_panel_sentence_names_folder_only(
        _half_on_sentence(named), named, allow_switch_slash=True
    )
    leftover = f"{_missing_sentence(named)} Leftover: {NOTES_PANEL_LEFTOVER}"
    assert leftover == (
        "The notes panel is not installed in the alpha-notes vault. "
        "This checkup looked only in the alpha-notes vault, not across the machine. "
        "Leftover: `.obsidian/community-plugins.json` may still list "
        "`dex-readonly` until you remove that name; the workspace layout "
        "may still show an empty Dex panel slot."
    )
    assert leftover.startswith(_missing_sentence(named) + " Leftover: ")
    assert leftover.endswith(NOTES_PANEL_LEFTOVER)


def test_notes_panel_absent_in_checked_vault_is_vault_scoped_not_machine(
    context: doctor.DoctorContext,
) -> None:
    result = doctor._probe_harness_capabilities(context)
    missing = _missing_sentence(context.vault_root)

    assert missing == (
        f"The notes panel is not installed in the {context.vault_root.name} vault. "
        f"This checkup looked only in the {context.vault_root.name} vault, not across the machine."
    )
    assert result.detail.count(missing) == 1
    assert result.structured_detail["notes_panel"]["sentence"] == missing
    _assert_notes_panel_sentence_names_folder_only(missing, context.vault_root)
    assert "on this machine" not in result.structured_detail["notes_panel"]["sentence"]
    assert "The notes panel is not installed on this machine." not in result.detail
    assert "this vault" not in result.structured_detail["notes_panel"]["sentence"]
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(result.detail)


def test_doctor_names_every_written_door_before_setup(context: doctor.DoctorContext) -> None:
    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "OFF"
    assert "record your harnesses without restarting onboarding" in result.detail.lower()
    for profile in list_profiles():
        assert f"You confirmed {profile.display_name}." not in result.detail
        if door_is_detectable(profile.id):
            assert never_opened_sentence(profile.display_name) in result.detail
            assert cannot_see_opened_sentence(profile.display_name) not in result.detail
        else:
            assert cannot_see_opened_sentence(profile.display_name) in result.detail
            assert never_opened_sentence(profile.display_name) not in result.detail
    missing = _missing_sentence(context.vault_root)
    assert missing == (
        f"The notes panel is not installed in the {context.vault_root.name} vault. "
        f"This checkup looked only in the {context.vault_root.name} vault, not across the machine."
    )
    assert missing in result.detail
    assert result.detail.count(missing) == 1
    assert CONFIRMED_IS_NOT_WALKED in result.detail
    assert result.detail.index(missing) < result.detail.index(
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
    assert cannot_see_opened_sentence("Codex") not in result.detail
    for profile_id, name in names.items():
        if profile_id == "codex":
            continue
        assert f"You confirmed {name}." not in result.detail
        if door_is_detectable(profile_id):
            assert never_opened_sentence(name) in result.detail
            assert cannot_see_opened_sentence(name) not in result.detail
        else:
            assert cannot_see_opened_sentence(name) in result.detail
            assert never_opened_sentence(name) not in result.detail
    missing = _missing_sentence(context.vault_root)
    assert missing == (
        f"The notes panel is not installed in the {context.vault_root.name} vault. "
        f"This checkup looked only in the {context.vault_root.name} vault, not across the machine."
    )
    assert missing in result.detail
    assert result.detail.count(missing) == 1
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
    half_on = _half_on_sentence(context.vault_root)
    assert half_on == (
        f"The notes panel files are there in the {context.vault_root.name} vault, but the panel is not switched on. "
        "The switch is `.obsidian/community-plugins.json` listing `dex-readonly`; "
        "this checkup will not flip it."
    )
    assert half_on in result.detail
    assert result.detail.count(half_on) == 1
    assert _installed_sentence(context.vault_root) not in result.detail
    assert _missing_sentence(context.vault_root) not in result.detail
    assert NOTES_PANEL_SWITCH in result.detail
    assert "this checkup will not flip it." in result.detail
    _assert_notes_panel_sentence_names_folder_only(
        half_on, context.vault_root, allow_switch_slash=True
    )
    assert result.structured_detail["notes_panel"]["installed"] is True
    assert result.structured_detail["notes_panel"]["switched_on"] is False
    assert result.structured_detail["notes_panel"]["left"] is False
    assert result.structured_detail["notes_panel"]["switch"] == NOTES_PANEL_SWITCH
    assert result.detail.index(half_on) < result.detail.index(
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
    for door in report.doors:
        if door_is_detectable(door.id):
            assert door.sentence == never_opened_sentence(door.name)
        else:
            assert door.sentence == cannot_see_opened_sentence(door.name)
    assert report.notes_panel_installed is False
    assert report.notes_panel_switched_on is False
    assert report.notes_panel_left is False
    assert report.notes_panel_switch is None
    assert report.notes_panel_sentence == _missing_sentence(tmp_path / "vault")
    _assert_notes_panel_sentence_names_folder_only(
        report.notes_panel_sentence, tmp_path / "vault"
    )
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
    assert cannot_see_opened_sentence("ChatGPT Work companion") not in result.detail
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
    missing = _missing_sentence(context.vault_root)
    expected = f"{missing} Leftover: {NOTES_PANEL_LEFTOVER}"

    assert missing == (
        f"The notes panel is not installed in the {context.vault_root.name} vault. "
        f"This checkup looked only in the {context.vault_root.name} vault, not across the machine."
    )
    assert NOTES_PANEL_LEFTOVER == (
        "`.obsidian/community-plugins.json` may still list `dex-readonly` until you "
        "remove that name; the workspace layout may still show an empty Dex panel slot."
    )
    assert expected == f"{missing} Leftover: {NOTES_PANEL_LEFTOVER}"
    assert expected in result.detail
    assert result.detail.count(expected) == 1
    assert result.detail.index(expected) < result.detail.index(CONFIRMED_IS_NOT_WALKED)
    assert expected.startswith(missing + " Leftover: ")
    assert expected.endswith(NOTES_PANEL_LEFTOVER)
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

    installed = _installed_sentence(context.vault_root)
    assert installed == f"The notes panel is installed in the {context.vault_root.name} vault."
    assert installed in result.detail
    assert result.detail.count(installed) == 1
    assert _half_on_sentence(context.vault_root) not in result.detail
    assert _missing_sentence(context.vault_root) not in result.detail
    _assert_notes_panel_sentence_names_folder_only(installed, context.vault_root)
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

    half_on = _half_on_sentence(context.vault_root)
    assert half_on == (
        f"The notes panel files are there in the {context.vault_root.name} vault, but the panel is not switched on. "
        "The switch is `.obsidian/community-plugins.json` listing `dex-readonly`; "
        "this checkup will not flip it."
    )
    assert half_on in result.detail
    assert result.detail.count(half_on) == 1
    assert _installed_sentence(context.vault_root) not in result.detail
    assert _missing_sentence(context.vault_root) not in result.detail
    assert NOTES_PANEL_SWITCH in result.detail
    assert "this checkup will not flip it." in result.detail
    _assert_notes_panel_sentence_names_folder_only(
        half_on, context.vault_root, allow_switch_slash=True
    )
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
    half_on = _half_on_sentence(context.vault_root)
    assert half_on in result.detail
    assert NOTES_PANEL_SWITCH in result.detail
    assert "this checkup will not flip it." in result.detail
    _assert_notes_panel_sentence_names_folder_only(
        half_on, context.vault_root, allow_switch_slash=True
    )
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

    half_on = _half_on_sentence(context.vault_root)
    assert half_on in result.detail
    assert result.detail.endswith(STALE_WORK_COPY_SENTENCE)
    assert rendered["detail"].endswith(STALE_WORK_COPY_SENTENCE)
    assert result.detail.index(half_on) < result.detail.index(
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
    _assert_no_granted_true(cannot_see_opened_sentence("Codex"))
    _assert_no_granted_true(never_opened_sentence("Cursor"))


def test_doctor_names_undetectable_doors_as_unseen_not_never_opened(
    context: doctor.DoctorContext,
) -> None:
    result = doctor._probe_harness_capabilities(context)

    for profile in list_profiles():
        if door_is_detectable(profile.id):
            continue
        assert cannot_see_opened_sentence(profile.display_name) in result.detail
        assert never_opened_sentence(profile.display_name) not in result.detail
        assert f"You left {profile.display_name}." not in result.detail
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(result.detail)


def test_detectable_unopened_doors_keep_never_opened_sentence(
    context: doctor.DoctorContext,
) -> None:
    result = doctor._probe_harness_capabilities(context)

    for profile in list_profiles():
        if not door_is_detectable(profile.id):
            continue
        assert never_opened_sentence(profile.display_name) in result.detail
        assert cannot_see_opened_sentence(profile.display_name) not in result.detail
        assert f"You confirmed {profile.display_name}." not in result.detail
    _assert_no_granted_true(result.structured_detail)


def test_detectable_walked_leave_and_confirmed_sentences_stay_byte_identical(
    context: doctor.DoctorContext,
) -> None:
    _write_receipt(context, ["cursor", "chatgpt-work"])
    cursor_plugin = (
        context.home / ".cursor" / "plugins" / "local" / "dex" / ".cursor-plugin" / "plugin.json"
    )
    cursor_plugin.parent.mkdir(parents=True)
    cursor_plugin.write_text(json.dumps({"name": "dex"}) + "\n")
    work_cache = (
        context.home
        / ".codex"
        / "plugins"
        / "cache"
        / "dex-unreleased"
        / "dex"
        / "local"
    )
    work_cache.mkdir(parents=True)

    result = doctor._probe_harness_capabilities(context)

    assert "You confirmed Cursor, and it is walked on this machine." in result.detail
    leftover = LEFTOVER_COPY["chatgpt-work"]
    assert f"You left ChatGPT Work companion. Leftover: {leftover}" in result.detail
    assert cannot_see_opened_sentence("Cursor") not in result.detail
    assert cannot_see_opened_sentence("ChatGPT Work companion") not in result.detail
    assert never_opened_sentence("GitHub Copilot CLI") in result.detail
    assert cannot_see_opened_sentence("Codex") in result.detail
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(result.detail)


def test_doctor_does_not_write_or_invent_a_walk_for_undetectable_doors(
    context: doctor.DoctorContext,
) -> None:
    before_home = {
        path: path.read_bytes()
        for path in context.home.rglob("*")
        if path.is_file()
    }
    before_vault = {
        path: path.read_bytes()
        for path in context.vault_root.rglob("*")
        if path.is_file()
    }

    result = doctor._probe_harness_capabilities(context)

    after_home = {
        path: path.read_bytes()
        for path in context.home.rglob("*")
        if path.is_file()
    }
    after_vault = {
        path: path.read_bytes()
        for path in context.vault_root.rglob("*")
        if path.is_file()
    }
    assert after_home == before_home
    assert after_vault == before_vault
    assert cannot_see_opened_sentence("Codex") in result.detail
    assert "granted=true" not in result.detail.lower()
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(result.detail)


def test_stale_work_copy_sentence_stays_last_after_cannot_see_doors(
    context: doctor.DoctorContext, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    packaged = repo / "packages" / "dex-agent-plugin" / ".codex-plugin" / "plugin.json"
    packaged.parent.mkdir(parents=True)
    packaged.write_text(json.dumps({"name": "dex", "version": "1.0.1"}) + "\n")
    personal = context.home / ".codex" / "plugins" / "dex" / ".codex-plugin" / "plugin.json"
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

    assert cannot_see_opened_sentence("Codex") in result.detail
    assert result.detail.endswith(STALE_WORK_COPY_SENTENCE)
    assert rendered["detail"].endswith(STALE_WORK_COPY_SENTENCE)
    assert result.detail.index(cannot_see_opened_sentence("Codex")) < result.detail.index(
        STALE_WORK_COPY_SENTENCE
    )
    assert result.detail.count(STALE_WORK_COPY_SENTENCE) == 1
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(rendered)


def test_eleven_door_sentences_and_payload_keys_stay_byte_identical(
    context: doctor.DoctorContext,
) -> None:
    result = doctor._probe_harness_capabilities(context)
    names = {profile.id: profile.display_name for profile in list_profiles()}
    evidence_backed = [
        names[profile_id]
        for profile_id, rule in WALK_RULES.items()
        if rule is not None
    ]
    cannot_see = [
        names[profile_id]
        for profile_id, rule in WALK_RULES.items()
        if rule is None
    ]

    assert len(evidence_backed) == 4
    assert len(cannot_see) == 7
    for name in evidence_backed:
        assert never_opened_sentence(name) in result.detail
        assert cannot_see_opened_sentence(name) not in result.detail
    for name in cannot_see:
        assert cannot_see_opened_sentence(name) in result.detail
        assert never_opened_sentence(name) not in result.detail
    assert CONFIRMED_IS_NOT_WALKED == "A confirmed door is not the same as a walked one."
    assert CONFIRMED_IS_NOT_WALKED in result.detail
    assert result.detail.count(CONFIRMED_IS_NOT_WALKED) == 1
    assert set(result.structured_detail) == {
        "doors",
        "notes_panel",
        "confirmed_is_not_walked",
    }
    assert set(result.structured_detail["notes_panel"]) == {
        "installed",
        "switched_on",
        "left",
        "sentence",
    }
    assert result.structured_detail["confirmed_is_not_walked"] == CONFIRMED_IS_NOT_WALKED
    notes_sentence = result.structured_detail["notes_panel"]["sentence"]
    assert notes_sentence == _missing_sentence(context.vault_root)
    _assert_notes_panel_sentence_names_folder_only(notes_sentence, context.vault_root)
    assert "on this machine" not in notes_sentence
    _assert_no_granted_true(result.structured_detail)
    _assert_no_granted_true(result.detail)


def test_two_vault_folders_name_themselves_in_the_missing_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    first = tmp_path / "maya-first"
    second = tmp_path / "maya-second"
    shared_home = tmp_path / "shared-home"
    shared_home.mkdir()
    for vault in (first, second):
        (vault / "System").mkdir(parents=True)
    first_result = doctor._probe_harness_capabilities(
        doctor.DoctorContext(vault_root=first, repo_root=first, home=shared_home, now=NOW)
    )
    second_result = doctor._probe_harness_capabilities(
        doctor.DoctorContext(vault_root=second, repo_root=second, home=shared_home, now=NOW)
    )
    first_missing = _missing_sentence(first)
    second_missing = _missing_sentence(second)

    assert first_missing == (
        "The notes panel is not installed in the maya-first vault. "
        "This checkup looked only in the maya-first vault, not across the machine."
    )
    assert second_missing == (
        "The notes panel is not installed in the maya-second vault. "
        "This checkup looked only in the maya-second vault, not across the machine."
    )
    assert first_result.detail.count(first_missing) == 1
    assert second_result.detail.count(second_missing) == 1
    assert first_result.structured_detail["notes_panel"]["sentence"] == first_missing
    assert second_result.structured_detail["notes_panel"]["sentence"] == second_missing
    assert first_missing != second_missing
    assert "this vault" not in first_missing
    assert "this vault" not in second_missing
    _assert_notes_panel_sentence_names_folder_only(first_missing, first)
    _assert_notes_panel_sentence_names_folder_only(second_missing, second)
    assert first_missing.count("maya-first") == 2
    assert second_missing.count("maya-second") == 2
    _assert_no_granted_true(first_result.structured_detail)
    _assert_no_granted_true(second_result.structured_detail)
    _assert_no_granted_true(first_result.detail)
    _assert_no_granted_true(second_result.detail)
