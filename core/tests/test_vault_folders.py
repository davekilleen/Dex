"""Filing automations must use the real Archives and Resources folders."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.gates.safety import CODE_NEW_TOP_LEVEL_FOLDER, evaluate_safety_gate
from core.mcp import work_server
from core.vault_folders import locate_vault_folders, mkdir_targets, planned_new_top_level


@pytest.fixture(autouse=True)
def isolated_vault_binding(monkeypatch):
    for key in ("DEX_VAULT_PATH", "VAULT_PATH", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(key, raising=False)


def _vault(root: Path) -> Path:
    path = root / "vault"
    (path / "System" / ".dex").mkdir(parents=True)
    return path


def test_locate_vault_folders_returns_default_archives_and_resources(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    result = locate_vault_folders(vault)
    assert result["success"] is True
    assert result["archives"] == "07-Archives"
    assert result["resources"] == "06-Resources"
    assert "07-Archives" in result["message"]
    assert "06-Resources" in result["message"]


def test_locate_vault_folders_returns_moved_folders(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "System" / "folder-paths.yaml").write_text(
        "archives: Filing/Old\nresources: Library\n",
        encoding="utf-8",
    )
    result = locate_vault_folders(vault)
    assert result["archives"] == "Filing/Old"
    assert result["resources"] == "Library"
    assert "Filing/Old" in result["message"]
    assert "Library" in result["message"]


def test_work_mcp_locate_vault_folders_uses_the_selected_vault(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setattr(work_server, "BASE_DIR", vault)
    payload = json.loads(
        asyncio.run(work_server.handle_call_tool("locate_vault_folders", {}))[0].text
    )
    assert payload["archives"] == "07-Archives"
    assert payload["resources"] == "06-Resources"


@pytest.mark.parametrize(
    "path",
    (
        "Archives/note.md",
        "Archive/note.md",
        "Old_Notes/note.md",
    ),
)
def test_write_into_a_new_top_level_folder_is_blocked(tmp_path: Path, path: str) -> None:
    vault = _vault(tmp_path)
    decision = evaluate_safety_gate(path=path, vault=vault)
    assert decision.refused is True
    assert decision.code == CODE_NEW_TOP_LEVEL_FOLDER
    assert "07-Archives" in decision.reason
    assert "06-Resources" in decision.reason
    assert "locate_vault_folders" in decision.reason


@pytest.mark.parametrize(
    "command",
    (
        "mkdir Archives",
        "mkdir -p Archives",
        "mkdir -p Archives/2024",
        'mkdir "Old_Notes"',
        "mkdir -p -- Archives",
    ),
)
def test_mkdir_of_a_new_top_level_folder_is_blocked(tmp_path: Path, command: str) -> None:
    vault = _vault(tmp_path)
    decision = evaluate_safety_gate(command=command, vault=vault)
    assert decision.refused is True
    assert decision.code == CODE_NEW_TOP_LEVEL_FOLDER
    assert "locate_vault_folders" in decision.reason


@pytest.mark.parametrize(
    "path",
    (
        "note.md",
        "07-Archives/Plans/daily.md",
        "00-Inbox/Meetings/note.md",
        "06-Resources/guides/note.md",
        "System/pillars.yaml",
    ),
)
def test_known_dex_folders_and_root_files_are_allowed(tmp_path: Path, path: str) -> None:
    vault = _vault(tmp_path)
    decision = evaluate_safety_gate(path=path, vault=vault)
    assert decision.refused is False, decision.reason


@pytest.mark.parametrize(
    "command",
    (
        "mkdir -p 00-Inbox/Meetings",
        "mkdir -p 07-Archives/Plans",
        "mkdir 06-Resources",
        "echo mkdir Archives",
    ),
)
def test_legitimate_folder_creates_and_non_mkdir_text_are_allowed(
    tmp_path: Path, command: str
) -> None:
    vault = _vault(tmp_path)
    decision = evaluate_safety_gate(command=command, vault=vault)
    assert decision.refused is False, decision.reason


def test_existing_custom_top_level_folder_can_still_receive_files(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "Custom").mkdir()
    decision = evaluate_safety_gate(path="Custom/note.md", vault=vault)
    assert decision.refused is False


def test_moved_archives_folder_can_be_created(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "System" / "folder-paths.yaml").write_text(
        "archives: Filing/Old\n",
        encoding="utf-8",
    )
    allowed = evaluate_safety_gate(path="Filing/Old/note.md", vault=vault)
    blocked = evaluate_safety_gate(path="Archives/note.md", vault=vault)
    assert allowed.refused is False
    assert blocked.refused is True
    assert "Filing/Old" in blocked.reason


def test_mkdir_from_a_nested_folder_does_not_false_block(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    inbox = vault / "00-Inbox"
    inbox.mkdir()
    decision = evaluate_safety_gate(command="mkdir Meetings", vault=vault, cwd=inbox)
    assert decision.refused is False


def test_hook_and_mcp_agree_on_invented_archive_folder(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    shared = evaluate_safety_gate(path="Archives/note.md", vault=vault)
    monkeypatch.setattr(work_server, "BASE_DIR", vault)
    mcp = json.loads(
        asyncio.run(work_server.handle_call_tool("check_safety_gate", {"path": "Archives/note.md"}))[0].text
    )
    assert shared.refused and shared.code == CODE_NEW_TOP_LEVEL_FOLDER
    assert mcp["refused"] is True
    assert mcp["reason"] == shared.reason
    assert mcp["code"] == CODE_NEW_TOP_LEVEL_FOLDER


def test_mkdir_targets_skips_flags_and_reads_quoted_names() -> None:
    assert mkdir_targets('mkdir -p -- "Old Notes"') == ["Old Notes"]
    assert mkdir_targets("echo mkdir Archives") == []
    assert planned_new_top_level(Path("."), "note.md") is None
