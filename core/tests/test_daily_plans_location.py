"""Existing daily-plan folders stay put; new vaults still use the inbox default."""

from __future__ import annotations

from pathlib import Path

from core.daily_plans_location import (
    DEFAULT_DAILY_PLANS_RELATIVE,
    detect_existing_daily_plans_relative,
    resolve_daily_plans_relative,
    skip_default_daily_plans_seed,
)
from core.lifecycle.inventory import DEFAULT_FOLDER_PATHS
from core.update.apply_update import skip_default_daily_plans_seed as apply_skip


def _write_plan(directory: Path, day: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{day}.md").write_text(
        f"---\ndate: {day}\ntype: daily-plan\n---\n# Daily Plan — {day}\n",
        encoding="utf-8",
    )


def test_folder_map_names_daily_plans() -> None:
    assert DEFAULT_FOLDER_PATHS["daily_plans"] == DEFAULT_DAILY_PLANS_RELATIVE


def test_new_vault_uses_the_inbox_default(tmp_path: Path) -> None:
    assert resolve_daily_plans_relative(tmp_path) == DEFAULT_DAILY_PLANS_RELATIVE
    assert detect_existing_daily_plans_relative(tmp_path) is None
    assert skip_default_daily_plans_seed(
        f"{DEFAULT_DAILY_PLANS_RELATIVE}/README.md", tmp_path
    ) is False


def test_folder_paths_yaml_wins(tmp_path: Path) -> None:
    (tmp_path / "System").mkdir()
    (tmp_path / "System" / "folder-paths.yaml").write_text(
        "daily_plans: Planning/My_Days\n",
        encoding="utf-8",
    )
    _write_plan(tmp_path / "00-Inbox" / "Daily_Plans", "2026-09-29")
    assert resolve_daily_plans_relative(tmp_path) == "Planning/My_Days"
    assert skip_default_daily_plans_seed(
        f"{DEFAULT_DAILY_PLANS_RELATIVE}/README.md", tmp_path
    ) is True


def test_legacy_archive_plans_are_kept(tmp_path: Path) -> None:
    _write_plan(tmp_path / "07-Archives" / "Plans", "2026-09-28")
    assert resolve_daily_plans_relative(tmp_path) == "07-Archives/Plans"
    assert skip_default_daily_plans_seed(
        f"{DEFAULT_DAILY_PLANS_RELATIVE}/README.md", tmp_path
    ) is True
    assert (tmp_path / "07-Archives" / "Plans" / "2026-09-28.md").exists()
    assert not (tmp_path / "00-Inbox" / "Daily_Plans").exists()


def test_custom_folder_is_kept_and_not_moved(tmp_path: Path) -> None:
    custom = tmp_path / "05-Areas" / "Planning" / "Days"
    _write_plan(custom, "2026-09-20")
    _write_plan(custom, "2026-09-21")
    assert resolve_daily_plans_relative(tmp_path) == "05-Areas/Planning/Days"
    assert skip_default_daily_plans_seed(
        f"{DEFAULT_DAILY_PLANS_RELATIVE}/README.md", tmp_path
    ) is True
    assert list(custom.glob("*.md"))
    assert not (tmp_path / "00-Inbox" / "Daily_Plans").exists()


def test_inbox_default_wins_when_it_already_has_plans(tmp_path: Path) -> None:
    _write_plan(tmp_path / "00-Inbox" / "Daily_Plans", "2026-09-30")
    _write_plan(tmp_path / "07-Archives" / "Plans", "2026-01-01")
    assert resolve_daily_plans_relative(tmp_path) == DEFAULT_DAILY_PLANS_RELATIVE
    assert skip_default_daily_plans_seed(
        f"{DEFAULT_DAILY_PLANS_RELATIVE}/README.md", tmp_path
    ) is False


def test_meetings_are_not_treated_as_daily_plans(tmp_path: Path) -> None:
    meetings = tmp_path / "00-Inbox" / "Meetings"
    meetings.mkdir(parents=True)
    (meetings / "2026-09-30.md").write_text("# Standup\n", encoding="utf-8")
    assert resolve_daily_plans_relative(tmp_path) == DEFAULT_DAILY_PLANS_RELATIVE


def test_apply_update_uses_the_same_skip_helper() -> None:
    assert apply_skip is skip_default_daily_plans_seed
