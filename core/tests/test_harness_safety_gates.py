"""Safety gates: MCP tools return the same refusal as the Claude hook.

Fixture vault only (Alice Smith / Fixture Labs). No personal data.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from core.gates.safety import (
    CODE_DESTRUCTIVE_RM_ROOT,
    CODE_FORCE_PUSH_MAIN,
    CODE_MIGRATION_LOCK,
    CODE_UNSAFE_PATH,
    evaluate_safety_gate,
)
from core.mcp import work_server

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / ".claude" / "hooks" / "dex-safety-guard.sh"

PERSON_NAME = "Alice Smith"
PERSON_COMPANY = "Fixture Labs"


def _write_fixture_vault(root: Path) -> Path:
    vault = root / "vault"
    (vault / "System" / ".dex").mkdir(parents=True)
    (vault / "03-Tasks").mkdir()
    (vault / "05-Areas" / "People" / "Internal").mkdir(parents=True)
    (vault / "System" / ".onboarding-complete").write_text("{}\n", encoding="utf-8")
    (vault / "03-Tasks" / "Tasks.md").write_text("# Tasks\n", encoding="utf-8")
    (vault / "05-Areas" / "People" / "Internal" / "Alice_Smith.md").write_text(
        "---\n"
        f"name: {PERSON_NAME}\n"
        f"company: {PERSON_COMPANY}\n"
        "role: Product Manager\n"
        "---\n\n"
        f"# {PERSON_NAME}\n",
        encoding="utf-8",
    )
    return vault


def _run_hook(
    vault: Path,
    *,
    tool_name: str = "Bash",
    command: str | None = None,
    path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    tool_input: dict[str, str] = {}
    if command is not None:
        tool_input["command"] = command
    if path is not None:
        tool_input["path"] = path
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    return subprocess.run(
        ["bash", str(GUARD)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=20,
        cwd=str(vault),
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(vault),
            "VAULT_PATH": str(vault),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        check=False,
    )


def _call_mcp(monkeypatch: pytest.MonkeyPatch, vault: Path, arguments: dict) -> dict:
    monkeypatch.setattr(work_server, "BASE_DIR", vault)
    return json.loads(
        asyncio.run(work_server.handle_call_tool("check_safety_gate", arguments))[0].text
    )


def test_safety_hook_is_a_thin_wrapper_of_shared_gate() -> None:
    text = GUARD.read_text(encoding="utf-8")
    assert "core/gates/safety.py" in text
    assert "check_safety_gate" in text
    assert "diskutil" not in text
    assert "DROP" not in text
    assert "gh repo delete" not in text
    assert "mcp__firecrawl__" in text


def test_work_mcp_advertises_check_safety_gate() -> None:
    tools = {tool.name for tool in asyncio.run(work_server.handle_list_tools())}
    assert "check_safety_gate" in tools


@pytest.mark.parametrize(
    ("command", "code", "reason_snippet"),
    (
        ("rm -rf /", CODE_DESTRUCTIVE_RM_ROOT, "root, home, or /Users"),
        ("git push --force origin main", CODE_FORCE_PUSH_MAIN, "force push"),
        ("gh repo delete fixture-labs/demo", "github_repo_delete", "GitHub repo deletion"),
        ("DROP TABLE users", "sql_drop", "SQL DROP"),
        ("diskutil eraseDisk JHFS+ Untitled disk0", "disk_wipe", "disk wipe"),
    ),
)
def test_destructive_command_refused_by_hook_and_mcp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    code: str,
    reason_snippet: str,
) -> None:
    vault = _write_fixture_vault(tmp_path)
    shared = evaluate_safety_gate(tool_name="Bash", command=command, vault=vault)
    assert shared.refused is True
    assert shared.code == code
    assert reason_snippet in shared.reason

    hook = _run_hook(vault, command=command)
    assert hook.returncode == 2, hook.stdout + hook.stderr
    hook_payload = json.loads(hook.stdout)
    assert hook_payload["decision"] == "block"
    assert reason_snippet in hook_payload["reason"]

    mcp = _call_mcp(
        monkeypatch,
        vault,
        {"tool_name": "Bash", "command": command},
    )
    assert mcp["refused"] is True
    assert mcp["decision"] == "block"
    assert mcp["code"] == code
    assert mcp["reason"] == shared.reason
    assert mcp["reason"] == hook_payload["reason"]


def test_unsafe_path_refused_by_hook_and_mcp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _write_fixture_vault(tmp_path)
    outside = "/Users/Shared/fixture-wipe"
    shared = evaluate_safety_gate(path=outside, vault=vault)
    assert shared.refused is True
    assert shared.code == CODE_UNSAFE_PATH
    assert evaluate_safety_gate(path="/", vault=vault).refused is True
    assert evaluate_safety_gate(path="~", vault=vault).refused is True

    hook = _run_hook(vault, path=outside)
    assert hook.returncode == 2, hook.stdout + hook.stderr
    hook_payload = json.loads(hook.stdout)
    assert hook_payload["decision"] == "block"

    mcp = _call_mcp(monkeypatch, vault, {"path": outside})
    assert mcp["refused"] is True
    assert mcp["code"] == CODE_UNSAFE_PATH
    assert mcp["reason"] == shared.reason
    assert mcp["reason"] == hook_payload["reason"]


def test_vault_relative_escape_is_refused(tmp_path: Path) -> None:
    vault = _write_fixture_vault(tmp_path)
    shared = evaluate_safety_gate(path="../../../etc/passwd", vault=vault)
    assert shared.refused is True
    assert shared.code == CODE_UNSAFE_PATH


def test_safe_fixture_path_is_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _write_fixture_vault(tmp_path)
    relative = "05-Areas/People/Internal/Alice_Smith.md"
    inside = vault / relative
    shared = evaluate_safety_gate(path=relative, vault=vault)
    assert shared.refused is False
    assert evaluate_safety_gate(path=str(inside), vault=vault).refused is False
    hook = _run_hook(vault, path=relative)
    assert hook.returncode == 0, hook.stdout + hook.stderr
    mcp = _call_mcp(monkeypatch, vault, {"path": relative})
    assert mcp["refused"] is False
    assert mcp["decision"] == "allow"


def test_migration_lock_blocks_git_on_fixture_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _write_fixture_vault(tmp_path)
    lock = vault / "System" / ".dex" / "mutation.lock"
    lock.write_text(
        json.dumps({"pid": os.getpid(), "kind": "migration"}) + "\n",
        encoding="utf-8",
    )
    command = "git reset --hard HEAD"
    shared = evaluate_safety_gate(tool_name="Bash", command=command, vault=vault)
    assert shared.refused is True
    assert shared.code == CODE_MIGRATION_LOCK
    assert "--resume" in shared.reason
    assert "--restore" in shared.reason

    hook = _run_hook(vault, command=command)
    assert hook.returncode == 2, hook.stdout + hook.stderr
    assert "--resume" in hook.stdout

    mcp = _call_mcp(monkeypatch, vault, {"tool_name": "Bash", "command": command})
    assert mcp["refused"] is True
    assert mcp["code"] == CODE_MIGRATION_LOCK
    assert mcp["reason"] == shared.reason

    allowed = evaluate_safety_gate(
        tool_name="Bash", command="git status --short", vault=vault
    )
    assert allowed.refused is False
    status_hook = _run_hook(vault, command="git status --short")
    assert status_hook.returncode == 0, status_hook.stdout + status_hook.stderr


def test_stale_migration_lock_does_not_block(tmp_path: Path) -> None:
    vault = _write_fixture_vault(tmp_path)
    lock = vault / "System" / ".dex" / "mutation.lock"
    lock.write_text(
        json.dumps({"pid": 2147483647, "kind": "migration"}) + "\n",
        encoding="utf-8",
    )
    shared = evaluate_safety_gate(
        tool_name="Bash", command="git reset --hard HEAD", vault=vault
    )
    assert shared.refused is False


def test_scraper_matcher_stays_in_the_hook_not_the_shared_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _write_fixture_vault(tmp_path)
    shared = evaluate_safety_gate(
        tool_name="mcp__firecrawl__firecrawl_scrape", vault=vault
    )
    assert shared.refused is False
    mcp = _call_mcp(
        monkeypatch,
        vault,
        {"tool_name": "mcp__firecrawl__firecrawl_scrape"},
    )
    assert mcp["refused"] is False
    hook = _run_hook(vault, tool_name="mcp__firecrawl__firecrawl_scrape")
    assert hook.returncode == 2, hook.stdout + hook.stderr
    assert "WRONG SCRAPER" in hook.stdout
