"""Shared safety gate parity for MCP and the Claude PreToolUse wrapper."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from core.gates.safety import (
    CODE_PROTECTED_LOCATION,
    REASON_PROTECTED_LOCATION,
    REASON_UNSAFE_PATH,
    evaluate_hook_payload,
    evaluate_safety_gate,
)
from core.mcp import work_server


@pytest.fixture(autouse=True)
def isolated_vault_binding(monkeypatch):
    # The suite bootstrap binds its own fixture; these tests select fresh vaults.
    for key in ("DEX_VAULT_PATH", "VAULT_PATH", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(key, raising=False)


REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / ".claude" / "hooks" / "dex-safety-guard.sh"
DESTRUCTIVE = "gh repo " + "delete example/repository"


def _vault(root: Path) -> Path:
    path = root / "vault"
    (path / "System" / ".dex").mkdir(parents=True)
    return path


def _hook(
    vault: Path,
    *,
    tool_name: str = "Bash",
    command: str | None = None,
    path: str | None = None,
    extra_env: dict[str, str] | None = None,
):
    tool_input: dict[str, str] = {}
    if command is not None:
        tool_input["command"] = command
    if path is not None:
        tool_input["path"] = path
    return subprocess.run(
        ["bash", str(GUARD)],
        input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input}),
        capture_output=True,
        text=True,
        cwd=vault,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(vault),
            "VAULT_PATH": str(vault),
            **(extra_env or {}),
        },
        timeout=20,
        check=False,
    )


def _mcp(monkeypatch, vault: Path, arguments) -> dict:
    monkeypatch.setattr(work_server, "BASE_DIR", vault)
    return json.loads(
        asyncio.run(work_server.handle_call_tool("check_safety_gate", arguments))[0].text
    )


def test_safety_hook_is_a_thin_wrapper() -> None:
    text = GUARD.read_text(encoding="utf-8")
    assert "core/gates/safety.py" in text
    assert "--hook" in text
    assert "diskutil" not in text
    assert "DROP" not in text
    assert "gh repo delete" not in text
    assert "mcp__firecrawl__" in text


def test_work_mcp_advertises_safety_tool() -> None:
    tools = {tool.name for tool in asyncio.run(work_server.handle_list_tools())}
    assert "check_safety_gate" in tools
    assert "locate_vault_folders" in tools


def test_destructive_command_has_identical_hook_and_mcp_decision(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    command = "git push --force origin main"
    shared = evaluate_safety_gate(command=command, vault=vault)
    hook = _hook(vault, command=command)
    mcp = _mcp(monkeypatch, vault, {"tool_name": "Bash", "command": command})
    assert shared.refused and shared.code == "force_push_main"
    assert hook.returncode == 2
    assert mcp["refused"] is True
    assert mcp["reason"] == shared.reason
    assert json.loads(hook.stdout)["reason"] == shared.reason


def test_unsafe_path_has_identical_hook_and_mcp_decision(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    shared = evaluate_safety_gate(path="../../../etc/passwd", vault=vault)
    hook = _hook(vault, tool_name="Write", path="../../../etc/passwd")
    mcp = _mcp(monkeypatch, vault, {"path": "../../../etc/passwd"})
    assert shared.refused and shared.code == "unsafe_path"
    assert hook.returncode == 2
    assert mcp["refused"] is True
    assert mcp["reason"] == shared.reason
    assert json.loads(hook.stdout)["reason"] == shared.reason


def test_migration_lock_only_blocks_mutating_git(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    (vault / "System" / ".dex" / "mutation.lock").write_text(
        json.dumps({"kind": "migration", "pid": os.getpid()}), encoding="utf-8"
    )
    blocked = evaluate_safety_gate(command="git reset --hard HEAD", vault=vault)
    allowed = evaluate_safety_gate(command="git status --short", vault=vault)
    assert blocked.refused and blocked.code == "migration_lock"
    assert allowed.refused is False


def test_malformed_safety_inputs_return_safe_payload(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    assert evaluate_safety_gate(command=object(), path=object(), vault=vault).refused is False
    assert evaluate_safety_gate(vault=object()).code == "vault_selection_conflict"
    result = _mcp(monkeypatch, vault, [])
    assert result["refused"] is False


def test_hook_refuses_when_the_shared_gate_cannot_decide(tmp_path: Path) -> None:
    """A gate that crashes must refuse, not fall through to allow."""
    repo = tmp_path / "repo"
    hooks = repo / ".claude" / "hooks"
    gates = repo / "core" / "gates"
    hooks.mkdir(parents=True)
    gates.mkdir(parents=True)
    (repo / "System" / ".dex").mkdir(parents=True)
    shutil.copy2(GUARD, hooks / GUARD.name)
    (gates / "safety.py").write_text("raise ImportError('broken core')\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(hooks / GUARD.name)],
        input=json.dumps(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": DESTRUCTIVE}}
        ),
        capture_output=True,
        text=True,
        cwd=repo,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo), "VAULT_PATH": str(repo)},
        timeout=20,
        check=False,
    )
    assert result.returncode == 2
    assert "could not reach a decision" in result.stdout


def test_scraper_preference_remains_claude_only(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    shared = evaluate_safety_gate(tool_name="mcp__firecrawl__scrape", vault=vault)
    hook = _hook(vault, tool_name="mcp__firecrawl__scrape")
    mcp = _mcp(monkeypatch, vault, {"tool_name": "mcp__firecrawl__scrape"})
    assert shared.refused is False
    assert hook.returncode == 2
    assert "WRONG SCRAPER" in hook.stdout
    assert mcp["refused"] is False


def _memory_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def _vault_memory_file(home: Path, vault: Path, name: str = "MEMORY.md") -> Path:
    import re

    slug = re.sub(r"[^A-Za-z0-9]", "-", str(vault.resolve()))
    folder = home / ".claude" / "projects" / slug / "memory"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def test_this_vault_claude_memory_folder_is_allowed(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    home = _memory_home(tmp_path, monkeypatch)
    memory = _vault_memory_file(home, vault)
    slug = memory.parent.parent.name
    tilde = f"~/.claude/projects/{slug}/memory/{memory.name}"
    home_var = f"$HOME/.claude/projects/{slug}/memory/{memory.name}"

    for candidate in (str(memory), tilde, home_var):
        shared = evaluate_safety_gate(path=candidate, vault=vault)
        assert shared.refused is False, candidate
        assert shared.code == "allow"

    hook = _hook(
        vault,
        tool_name="Write",
        path=str(memory),
        extra_env={"HOME": str(home)},
    )
    assert hook.returncode == 0, hook.stdout + hook.stderr


def test_claude_memory_allowance_stays_this_vault_memory_folder(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _vault(tmp_path)
    home = _memory_home(tmp_path, monkeypatch)
    slug = _vault_memory_file(home, vault).parent.parent.name
    blocked = [
        home / ".claude" / "projects" / slug / "session.jsonl",
        home / ".claude" / "projects" / "-other-project" / "memory" / "MEMORY.md",
        home / ".claude" / "settings.json",
        home / "secret.md",
        home / ".claude" / "projects" / slug / "memory" / ".." / "session.jsonl",
    ]
    for path in blocked:
        path.parent.mkdir(parents=True, exist_ok=True)
        shared = evaluate_safety_gate(path=str(path), vault=vault)
        assert shared.refused and shared.code == "unsafe_path", path


def _isolate_tempdir(monkeypatch, root: Path) -> Path:
    monkeypatch.setenv("TMPDIR", str(root))
    monkeypatch.setenv("TEMP", str(root))
    monkeypatch.setenv("TMP", str(root))
    monkeypatch.setattr("tempfile.tempdir", None)
    return root


def test_os_temp_scratch_is_allowed_for_custom_skills(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    scratch = _isolate_tempdir(monkeypatch, tmp_path / "scratch")
    scratch.mkdir()
    target = scratch / "skill-out.md"

    for candidate in (
        str(target),
        "$TMPDIR/skill-out.md",
        "/tmp/dex-custom-skill/out.md",
        "/private/tmp/dex-custom-skill/out.md",
        "/var/tmp/dex-custom-skill/out.md",
        "/var/folders/zz/abcdefgh/T/dex-custom-skill/out.md",
        "/private/var/folders/zz/abcdefgh/T/dex-custom-skill/out.md",
    ):
        shared = evaluate_safety_gate(path=candidate, vault=vault)
        assert shared.refused is False, candidate
        assert shared.code == "allow"

    mkdir = evaluate_safety_gate(command="mkdir -p /tmp/dex-custom-skill", vault=vault)
    assert mkdir.refused is False, mkdir.reason

    hook = _hook(
        vault,
        tool_name="Write",
        path=str(target),
        extra_env={"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)},
    )
    assert hook.returncode == 0, hook.stdout + hook.stderr


def test_os_temp_allowance_does_not_open_home_or_system_paths(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _vault(tmp_path)
    # Built at runtime so source never contains a literal /Users/ path.
    home = Path("/".join(("", "Users", "testuser")))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    _isolate_tempdir(monkeypatch, tmp_path / "scratch").mkdir()

    blocked = [
        "~/secret.md",
        "$HOME/.ssh/id_rsa",
        "/etc/passwd",
        "/private/etc/passwd",
        "/usr/bin/python",
        "/var/log/system.log",
        "/var/folders/zz/abcdefgh/Caches/secret",
        str(home / "Documents" / "note.md"),
        "$HOME/var/folders/zz/abcdefgh/T/out.md",
        "~/Documents/var/folders/zz/abcdefgh/T/note.md",
        "/usr/local/var/folders/zz/abcdefgh/T/out.md",
    ]
    for path in blocked:
        shared = evaluate_safety_gate(path=path, vault=vault)
        assert shared.refused and shared.code == "unsafe_path", path

    monkeypatch.setenv("TMPDIR", "/etc")
    monkeypatch.setattr("tempfile.tempdir", None)
    poisoned = evaluate_safety_gate(path="/etc/passwd", vault=vault)
    assert poisoned.refused and poisoned.code == "unsafe_path"
    poisoned_env = evaluate_safety_gate(path="$TMPDIR/passwd", vault=vault)
    assert poisoned_env.refused and poisoned_env.code == "unsafe_path"

    monkeypatch.setenv("TMPDIR", str(home))
    monkeypatch.setattr("tempfile.tempdir", None)
    home_as_temp = evaluate_safety_gate(path="$TMPDIR/secret.md", vault=vault)
    assert home_as_temp.refused and home_as_temp.code == "unsafe_path"


def test_temp_escape_via_parent_directory_stays_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _vault(tmp_path)
    _isolate_tempdir(monkeypatch, tmp_path / "scratch").mkdir()
    for candidate in ("/tmp/../etc/passwd", "$TMPDIR/../etc/passwd"):
        shared = evaluate_safety_gate(path=candidate, vault=vault)
        assert shared.refused and shared.code == "unsafe_path", candidate


def test_mkdir_outside_vault_in_ordinary_folder_is_allowed(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _vault(tmp_path)
    home = _memory_home(tmp_path, monkeypatch)
    for command in (
        "mkdir -p ~/CloudProj/new-sub",
        "mkdir -p ~/CloudProj/a/b/c",
        f"mkdir -p {home / 'CloudProj' / 'new-sub'}",
    ):
        decision = evaluate_safety_gate(command=command, vault=vault)
        assert decision.refused is False, (command, decision.reason)


def test_cp_and_curl_into_ordinary_outside_folder_match_mkdir(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _vault(tmp_path)
    _memory_home(tmp_path, monkeypatch)
    folder = "~/CloudProj/new-sub"
    mkdir = evaluate_safety_gate(command=f"mkdir -p {folder}", vault=vault)
    copy = evaluate_safety_gate(command=f"cp a.jpg {folder}/", vault=vault)
    curl = evaluate_safety_gate(
        command=f"curl -o {folder}/x.jpg https://example.invalid/x.jpg", vault=vault
    )
    redirect = evaluate_safety_gate(command=f"cat a.jpg > {folder}/x.jpg", vault=vault)
    assert mkdir.refused is False, mkdir.reason
    assert copy.refused is mkdir.refused
    assert curl.refused is mkdir.refused
    assert redirect.refused is mkdir.refused
    assert copy.code == mkdir.code
    assert curl.code == mkdir.code


@pytest.mark.parametrize(
    "command",
    (
        "mkdir /",
        "mkdir ~",
        "mkdir $HOME",
        "mkdir /Users/other",
        "mkdir -p /etc/foo",
        "mkdir -p /usr/local/x",
        "mkdir -p ~/Library/x",
        "mkdir -p ~/.ssh/x",
        "mkdir -p ~/.claude/other",
    ),
)
def test_mkdir_protected_locations_stay_blocked(
    tmp_path: Path, monkeypatch, command: str
) -> None:
    vault = _vault(tmp_path)
    _memory_home(tmp_path, monkeypatch)
    decision = evaluate_safety_gate(command=command, vault=vault)
    assert decision.refused is True, command
    assert decision.code == CODE_PROTECTED_LOCATION
    assert decision.reason == REASON_PROTECTED_LOCATION
    assert "outside the vault" not in decision.reason


def test_parsed_writes_to_protected_locations_match_mkdir(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _vault(tmp_path)
    _memory_home(tmp_path, monkeypatch)
    mkdir = evaluate_safety_gate(command="mkdir -p /etc/foo", vault=vault)
    copy = evaluate_safety_gate(command="cp a.jpg /etc/foo/x.jpg", vault=vault)
    curl = evaluate_safety_gate(
        command="curl -o /etc/foo/x.jpg https://example.invalid/x.jpg", vault=vault
    )
    assert mkdir.refused and copy.refused and curl.refused
    assert mkdir.reason == copy.reason == curl.reason == REASON_PROTECTED_LOCATION


def test_mkdir_os_temp_and_tmpdir_stay_allowed(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    scratch = _isolate_tempdir(monkeypatch, tmp_path / "scratch")
    scratch.mkdir()
    for command in (
        "mkdir -p /private/tmp/claude-501/proj/scratchpad/sub",
        "mkdir -p $TMPDIR/x",
        f"mkdir -p {scratch / 'x'}",
    ):
        decision = evaluate_safety_gate(command=command, vault=vault)
        assert decision.refused is False, (command, decision.reason)


def test_write_tool_path_outside_the_vault_stays_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    """File tools stay vault-confined. Documented for Dave as a follow-up."""
    vault = _vault(tmp_path)
    home = _memory_home(tmp_path, monkeypatch)
    outside = str(home / "CloudProj" / "x.jpg")
    decision = evaluate_safety_gate(path=outside, vault=vault)
    hook = evaluate_hook_payload(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": outside},
            "cwd": str(vault),
        },
        vault=vault,
    )
    tilde = evaluate_safety_gate(path="~/CloudProj/x.jpg", vault=vault)
    assert decision.refused and decision.code == "unsafe_path"
    assert REASON_UNSAFE_PATH == decision.reason
    assert "outside the vault" in decision.reason
    assert hook.refused and hook.reason == decision.reason
    assert tilde.refused and tilde.code == "unsafe_path"


def test_safety_hook_allows_ordinary_outside_mkdir_and_blocks_etc(
    tmp_path: Path, monkeypatch
) -> None:
    vault = _vault(tmp_path)
    home = _memory_home(tmp_path, monkeypatch)
    allowed = _hook(
        vault,
        command="mkdir -p ~/CloudProj/new-sub",
        extra_env={"HOME": str(home)},
    )
    blocked = _hook(vault, command="mkdir -p /etc/foo")
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert blocked.returncode == 2
    assert REASON_PROTECTED_LOCATION in blocked.stdout
    assert "outside the vault" not in blocked.stdout
