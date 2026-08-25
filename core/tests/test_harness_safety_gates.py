"""Shared safety gate parity for MCP and the Claude PreToolUse wrapper."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

from core.gates.safety import evaluate_safety_gate
from core.mcp import work_server


REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / ".claude" / "hooks" / "dex-safety-guard.sh"


def _vault(root: Path) -> Path:
    path = root / "vault"
    (path / "System" / ".dex").mkdir(parents=True)
    return path


def _hook(vault: Path, *, tool_name: str = "Bash", command: str | None = None, path: str | None = None):
    tool_input: dict[str, str] = {}
    if command is not None:
        tool_input["command"] = command
    if path is not None:
        tool_input["path"] = path
    return subprocess.run(
        ["bash", str(GUARD)],
        input=json.dumps({"tool_name": tool_name, "tool_input": tool_input}),
        capture_output=True,
        text=True,
        cwd=vault,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(vault), "VAULT_PATH": str(vault)},
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
    hook = _hook(vault, path="../../../etc/passwd")
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
    assert evaluate_safety_gate(vault=object()).refused is False
    result = _mcp(monkeypatch, vault, [])
    assert result["refused"] is False


def test_scraper_preference_remains_claude_only(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    shared = evaluate_safety_gate(tool_name="mcp__firecrawl__scrape", vault=vault)
    hook = _hook(vault, tool_name="mcp__firecrawl__scrape")
    mcp = _mcp(monkeypatch, vault, {"tool_name": "mcp__firecrawl__scrape"})
    assert shared.refused is False
    assert hook.returncode == 2
    assert "WRONG SCRAPER" in hook.stdout
    assert mcp["refused"] is False
