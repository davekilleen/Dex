"""Keep a user's Obsidian settings when Dex writes shipped defaults."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.obsidian import generate_obsidian_config
from core.obsidian.preserve_config import (
    OBSIDIAN_SETTING_FILES,
    backup_relative,
    merge_obsidian_json,
    write_obsidian_json,
)
from core.update import apply_update

WHEN = datetime(2026, 11, 16, 13, 0, 0, tzinfo=timezone.utc)


def test_setting_files_cover_app_appearance_hotkeys_and_workspace() -> None:
    assert OBSIDIAN_SETTING_FILES == (
        "app.json",
        "appearance.json",
        "hotkeys.json",
        "workspace.json",
    )


def test_merge_keeps_user_keys_and_lets_the_user_win() -> None:
    existing = json.dumps(
        {"theme": "moonstone-custom", "spellcheck": False, "nested": {"keep": 1}}
    ).encode("utf-8")
    shipped = json.dumps(
        {"spellcheck": True, "alwaysUpdateLinks": True, "nested": {"keep": 0, "add": 2}}
    ).encode("utf-8")

    merged = json.loads(
        merge_obsidian_json(existing, shipped, filename="app.json")
    )

    assert merged["theme"] == "moonstone-custom"
    assert merged["spellcheck"] is False
    assert merged["alwaysUpdateLinks"] is True
    assert merged["nested"] == {"keep": 1, "add": 2}


def test_workspace_layout_is_kept_whole_when_valid() -> None:
    existing = json.dumps({"main": {"id": "user-layout"}}).encode("utf-8")
    shipped = json.dumps({"main": {"id": "dex-main"}}).encode("utf-8")

    merged = json.loads(
        merge_obsidian_json(existing, shipped, filename="workspace.json")
    )

    assert merged == {"main": {"id": "user-layout"}}


def test_write_saves_a_timestamped_backup_before_changing(tmp_path: Path) -> None:
    path = tmp_path / "app.json"
    original = b'{"spellcheck": false}\n'
    path.write_bytes(original)

    backup = write_obsidian_json(
        path,
        {"spellcheck": True, "alwaysUpdateLinks": True},
        now=WHEN,
    )

    assert backup is not None
    assert backup.name == "app.json.bak-20261116-130000"
    assert backup.read_bytes() == original
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["spellcheck"] is False
    assert saved["alwaysUpdateLinks"] is True


def test_generate_config_merges_and_backs_up_existing_files(tmp_path: Path) -> None:
    obsidian = tmp_path / ".obsidian"
    obsidian.mkdir()
    (obsidian / "app.json").write_text(
        json.dumps({"readableLineLength": False, "customFlag": True}) + "\n",
        encoding="utf-8",
    )
    (obsidian / "workspace.json").write_text(
        json.dumps({"main": {"id": "user-layout"}}) + "\n",
        encoding="utf-8",
    )

    generate_obsidian_config.generate_config(tmp_path)

    app = json.loads((obsidian / "app.json").read_text(encoding="utf-8"))
    workspace = json.loads((obsidian / "workspace.json").read_text(encoding="utf-8"))
    backups = list(obsidian.glob("app.json.bak-*")) + list(
        obsidian.glob("workspace.json.bak-*")
    )

    assert app["customFlag"] is True
    assert app["readableLineLength"] is False
    assert app["alwaysUpdateLinks"] is True
    assert workspace == {"main": {"id": "user-layout"}}
    assert backups


def test_compose_obsidian_app_json_merges_the_live_file(tmp_path: Path) -> None:
    live = tmp_path / ".obsidian" / "app.json"
    live.parent.mkdir()
    live.write_text(
        json.dumps({"spellcheck": False, "userTheme": "custom"}) + "\n",
        encoding="utf-8",
    )
    shipped = json.dumps({"spellcheck": True, "alwaysUpdateLinks": True}).encode(
        "utf-8"
    )

    merged = json.loads(apply_update._compose_obsidian_app_json(shipped, tmp_path))

    assert merged["spellcheck"] is False
    assert merged["userTheme"] == "custom"
    assert merged["alwaysUpdateLinks"] is True


def test_backup_relative_uses_the_utc_timestamp() -> None:
    assert backup_relative("app.json", WHEN) == (
        ".obsidian/app.json.bak-20261116-130000"
    )
