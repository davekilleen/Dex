"""Filing automations must use the real Archives and Resources folders."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.gates.safety import CODE_NEW_TOP_LEVEL_FOLDER, evaluate_safety_gate
from core.mcp import work_server
from core.vault_folders import (
    _curl_output_targets,
    locate_vault_folders,
    mkdir_targets,
    parse_shell_writes,
    planned_new_top_level,
    shell_write_targets,
)


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


def test_mkdir_of_new_top_level_inside_vault_keeps_dex_116_message(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    blocked = evaluate_safety_gate(command="mkdir NewTopLevel", vault=vault)
    allowed = evaluate_safety_gate(command="mkdir -p 00-Inbox/sub", vault=vault)
    assert blocked.refused is True
    assert blocked.code == CODE_NEW_TOP_LEVEL_FOLDER
    assert "new top-level folder named NewTopLevel" in blocked.reason
    assert allowed.refused is False


def test_mkdir_through_symlinked_parent_escaping_vault_is_blocked(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    inbox = vault / "00-Inbox"
    inbox.mkdir()
    (inbox / "escape").symlink_to("/etc")
    decision = evaluate_safety_gate(command="mkdir 00-Inbox/escape/foo", vault=vault)
    assert decision.refused is True
    assert decision.code in {"unsafe_path", "protected_location"}


def test_parsed_write_through_vault_symlink_to_protected_location_is_blocked(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path)
    inbox = vault / "00-Inbox"
    inbox.mkdir()
    (inbox / "escape").symlink_to("/etc")
    copy = evaluate_safety_gate(command="cp a.jpg 00-Inbox/escape/passwd", vault=vault)
    redirect = evaluate_safety_gate(command="echo x > 00-Inbox/escape/passwd", vault=vault)
    curl = evaluate_safety_gate(
        command="curl -o 00-Inbox/escape/passwd https://example.invalid/x",
        vault=vault,
    )
    assert copy.refused is True
    assert copy.code in {"unsafe_path", "protected_location"}
    assert redirect.refused is True
    assert redirect.code in {"unsafe_path", "protected_location"}
    assert curl.refused is True
    assert curl.code in {"unsafe_path", "protected_location"}


def test_shell_write_targets_reads_curl_cp_and_redirects() -> None:
    assert shell_write_targets("curl -o ~/CloudProj/x.jpg https://example.invalid/x.jpg") == [
        "~/CloudProj/x.jpg"
    ]
    assert shell_write_targets("curl --output=/tmp/out.bin https://example.invalid/x") == [
        "/tmp/out.bin"
    ]
    assert shell_write_targets("cp a.jpg ~/CloudProj/") == ["~/CloudProj/"]
    assert shell_write_targets("mv note.md 00-Inbox/note.md") == ["00-Inbox/note.md"]
    assert shell_write_targets("cat a.jpg > ~/CloudProj/x.jpg") == ["~/CloudProj/x.jpg"]
    assert shell_write_targets("echo mkdir Archives") == []


def test_curl_output_targets_reads_attached_and_combined_flags() -> None:
    assert _curl_output_targets("-oPATH https://example.invalid/x") == ["PATH"]
    assert _curl_output_targets("--output PATH https://example.invalid/x") == ["PATH"]
    assert _curl_output_targets("--output=PATH https://example.invalid/x") == ["PATH"]
    assert _curl_output_targets("-sSo PATH https://example.invalid/x") == ["PATH"]
    assert _curl_output_targets("-sSoPATH https://example.invalid/x") == ["PATH"]
    socks = parse_shell_writes("curl -socks5 127.0.0.1:1080 https://example.invalid/x")
    assert socks.unresolved is True
    socks_long = parse_shell_writes(
        "curl --socks5 127.0.0.1:1080 https://example.invalid/x"
    )
    assert socks_long.unresolved is True
    assert shell_write_targets("curl -oPATH https://example.invalid/x") == ["PATH"]
    assert shell_write_targets("curl --output PATH https://example.invalid/x") == ["PATH"]
    assert shell_write_targets("curl --output=PATH https://example.invalid/x") == ["PATH"]
    assert shell_write_targets("curl -sSo PATH https://example.invalid/x") == ["PATH"]
    assert shell_write_targets("curl -sSoPATH https://example.invalid/x") == ["PATH"]
    assert shell_write_targets("curl -o${HOME}/.ssh/x https://example.invalid/x") == [
        "${HOME}/.ssh/x"
    ]
    assert shell_write_targets("curl -sSo${HOME}/.ssh/x https://example.invalid/x") == [
        "${HOME}/.ssh/x"
    ]
    output_dir = parse_shell_writes(
        "curl --output-dir ~/.ssh -o authorized_keys https://example.invalid/x"
    )
    assert output_dir.unresolved is True
    output_dir_eq = parse_shell_writes(
        "curl --output-dir=/etc -O https://example.invalid/x"
    )
    assert output_dir_eq.unresolved is True
    output_dir_ok = parse_shell_writes(
        "curl --output-dir ~/CloudProj -o x.jpg https://example.invalid/x"
    )
    assert output_dir_ok.unresolved is True


def test_shell_write_targets_reads_noclobber_redirects() -> None:
    noclobber = parse_shell_writes("echo x >| ~/.ssh/authorized_keys")
    assert noclobber.unresolved is True
    etc = parse_shell_writes("echo x >| /etc/foo")
    assert etc.unresolved is True
    bang = parse_shell_writes("echo x >! /etc/foo")
    assert bang.unresolved is True
    amp = parse_shell_writes("echo x &>| ~/.ssh/x")
    assert amp.unresolved is True
    assert shell_write_targets("echo x > ~/.ssh/authorized_keys") == [
        "~/.ssh/authorized_keys"
    ]
    understood = parse_shell_writes("echo x > ~/.ssh/authorized_keys")
    assert understood.unresolved is False


def test_shell_write_targets_reads_attached_cp_target_directory() -> None:
    attached = parse_shell_writes("cp -t/etc/foo a.jpg")
    assert attached.unresolved is True
    moved = parse_shell_writes("mv -t/etc/foo a.jpg")
    assert moved.unresolved is True
    spaced = parse_shell_writes("cp -t /etc/foo a.jpg")
    assert spaced.unresolved is False
    assert spaced.targets == ("/etc/foo",)
    assert shell_write_targets("cp -t /etc/foo a.jpg") == ["/etc/foo"]
    attached_home = parse_shell_writes("cp -t~/CloudProj a.jpg")
    assert attached_home.unresolved is True
