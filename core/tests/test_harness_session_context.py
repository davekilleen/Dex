"""Shared session/person context contracts for every harness."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path

from core.context.person_context import (
    get_person_context,
    inject_person_context_for_file,
)
from core.context.session_boot import build_session_boot
from core.mcp import work_server

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_START = REPO_ROOT / ".claude" / "hooks" / "session-start.sh"
PERSON_HOOK = REPO_ROOT / ".claude" / "hooks" / "person-context-injector.cjs"

PILLAR_NAME = "Fixture Growth"
PILLAR_DESCRIPTION = "Grow the example product line"
GOAL_TITLE = "Ship the checkout rewrite"
PRIORITY_LINE = "1. Finish the checkout rewrite — **Fixture Growth**"
URGENT_TASK = "- [ ] P0 File the launch checklist today ^task-20260813-001"
PERSON_NAME = "Alice Smith"
PERSON_ROLE = "Product Manager"
PERSON_COMPANY = "Fixture Labs"
OPEN_ITEM = "Send the launch brief"


def _write_vault(root: Path) -> Path:
    vault = root / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "01-Quarter_Goals").mkdir()
    (vault / "02-Week_Priorities").mkdir()
    (vault / "03-Tasks").mkdir()
    (vault / "00-Inbox" / "Meetings").mkdir(parents=True)
    (vault / "05-Areas" / "People" / "Internal").mkdir(parents=True)
    (vault / "System" / ".onboarding-complete").write_text("{}\n", encoding="utf-8")
    (vault / "System" / "pillars.yaml").write_text(
        "pillars:\n"
        f"  - id: fixture_growth\n"
        f"    name: \"{PILLAR_NAME}\"\n"
        f"    description: \"{PILLAR_DESCRIPTION}\"\n",
        encoding="utf-8",
    )
    (vault / "01-Quarter_Goals" / "Quarter_Goals.md").write_text(
        "# Quarter Goals\n\n"
        f"### 1. {GOAL_TITLE} — **{PILLAR_NAME}** ^Q3-2026-goal-1\n\n"
        "**Progress:** 40%\n\n---\n",
        encoding="utf-8",
    )
    (vault / "02-Week_Priorities" / "Week_Priorities.md").write_text(
        "# Week Priorities\n\n"
        "## 🎯 This Week\n\n"
        f"{PRIORITY_LINE}\n\n---\n",
        encoding="utf-8",
    )
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n"
        f"{URGENT_TASK}\n"
        "- [ ] Later: write the recap ^task-20260813-002\n",
        encoding="utf-8",
    )
    (vault / "05-Areas" / "People" / "Internal" / "Alice_Smith.md").write_text(
        "---\n"
        f"name: {PERSON_NAME}\n"
        f"role: {PERSON_ROLE}\n"
        f"company: {PERSON_COMPANY}\n"
        "last_interaction: 2026-08-01\n"
        "---\n\n"
        f"# {PERSON_NAME}\n\n"
        f"- [ ] {OPEN_ITEM}\n"
        "- [ ] Book the follow-up\n",
        encoding="utf-8",
    )
    return vault


def _run_session_start(vault: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "CLAUDE_PROJECT_DIR": str(vault),
            "VAULT_PATH": str(vault),
            "HOME": str(tmp_path / "home"),
            "DEX_LAUNCH_AGENTS_DIR": str(tmp_path / "LaunchAgents"),
            "DEX_SESSION_CONTEXT_DEDUP_FILE": str(tmp_path / "dedup"),
        }
    )
    (tmp_path / "home").mkdir(exist_ok=True)
    (tmp_path / "LaunchAgents").mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", str(SESSION_START)],
        cwd=str(vault),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def _run_person_hook(vault: Path, note: Path) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_input": {"file_path": str(note)}})
    return subprocess.run(
        ["node", str(PERSON_HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=20,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(vault),
            "VAULT_PATH": str(vault),
            "DEX_HOOK_DEBUG": "1",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        check=False,
    )


def test_session_start_is_a_wrapper_and_preserves_offload_logic() -> None:
    text = SESSION_START.read_text(encoding="utf-8")
    assert "core/context/session_boot.py" in text
    assert "--format hook-text" in text
    assert "awk '/^  - id:'" not in text
    assert "--offloaded-check" in text
    assert "DEX_PYTHON_CMD" in text
    assert ".venv/Scripts/python.exe" in text
    assert "py -3" in text


def test_person_hook_is_a_wrapper() -> None:
    text = PERSON_HOOK.read_text(encoding="utf-8")
    assert "core/context/person_context.py" in text
    assert "--from-file" in text
    assert "parsePersonPage" not in text


def test_boot_today_matches_session_hook_and_mcp(tmp_path: Path, monkeypatch) -> None:
    vault = _write_vault(tmp_path)
    payload = build_session_boot(vault)
    assert payload["pillars"][0]["name"] == PILLAR_NAME
    assert payload["quarter_goals"][0]["title"].find(GOAL_TITLE) >= 0
    assert PRIORITY_LINE in payload["week_priorities"]
    assert URGENT_TASK in payload["urgent_tasks"]

    hook = _run_session_start(vault, tmp_path)
    assert hook.returncode == 0, hook.stderr
    for fact in (PILLAR_NAME, PILLAR_DESCRIPTION, GOAL_TITLE, PRIORITY_LINE, "launch checklist"):
        assert fact in payload["injected_text"]
        assert fact in hook.stdout

    monkeypatch.setattr(work_server, "BASE_DIR", vault)
    mcp = json.loads(asyncio.run(work_server.handle_call_tool("boot_today", {}))[0].text)
    assert mcp == payload


def test_person_context_matches_hook_and_mcp(tmp_path: Path, monkeypatch) -> None:
    vault = _write_vault(tmp_path)
    note = vault / "00-Inbox" / "Meetings" / "person-context.md"
    note.write_text("# Meeting\n\nMeeting with Alice Smith about the launch.\n", encoding="utf-8")

    shared = get_person_context(vault, PERSON_NAME)
    assert shared["found"] is True
    assert shared["matches"][0]["role"] == PERSON_ROLE
    assert OPEN_ITEM in shared["matches"][0]["open_items"]
    block = inject_person_context_for_file(vault, note)["additionalContext"]

    hook = _run_person_hook(vault, note)
    assert hook.returncode == 0, hook.stderr
    hook_text = json.loads(hook.stdout)["hookSpecificOutput"]["additionalContext"]
    assert hook_text.strip() == block.strip()

    monkeypatch.setattr(work_server, "BASE_DIR", vault)
    mcp = json.loads(
        asyncio.run(work_server.handle_call_tool("get_person_context", {"name": PERSON_NAME}))[0].text
    )
    assert mcp == shared


def test_context_malformed_inputs_fail_closed_to_empty_payload(tmp_path: Path) -> None:
    assert build_session_boot(None)["pillars"] == []
    assert build_session_boot(object())["injected_text"] == ""
    assert get_person_context(None, object())["found"] is False
    assert get_person_context(tmp_path, "")["matches"] == []


def test_person_context_rejects_file_outside_vault(tmp_path: Path) -> None:
    vault = _write_vault(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("Meeting with Alice Smith", encoding="utf-8")
    result = inject_person_context_for_file(vault, outside)
    assert result.get("skip", "").startswith("target-file-outside-vault")


def test_person_context_skips_relative_person_pages_to_prevent_recursion(
    tmp_path: Path,
) -> None:
    vault = _write_vault(tmp_path)
    relative = "People/Internal/Alice_Smith.md"

    shared = inject_person_context_for_file(vault, relative)
    hook = subprocess.run(
        ["node", str(PERSON_HOOK)],
        input=json.dumps({"tool_input": {"file_path": relative}}),
        capture_output=True,
        text=True,
        timeout=20,
        env={
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(vault),
            "VAULT_PATH": str(vault),
            "DEX_HOOK_DEBUG": "1",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        check=False,
    )

    assert shared == {"skip": "missing-file-path-or-recursive-person-file"}
    assert hook.returncode == 0
    assert "missing-file-path-or-recursive-person-file" in hook.stderr
    assert hook.stdout == ""


def test_work_mcp_advertises_context_tools() -> None:
    tools = {tool.name for tool in asyncio.run(work_server.handle_list_tools())}
    assert {"boot_today", "get_person_context"} <= tools
