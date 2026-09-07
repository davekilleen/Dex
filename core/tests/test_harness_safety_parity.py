"""Execute native/package boundaries with proposals only; never execute their actions."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "packages/dex-agent-plugin"


@pytest.fixture
def vaults(tmp_path, monkeypatch):
    for key in ("DEX_VAULT_PATH", "VAULT_PATH", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(key, raising=False)
    roots = [tmp_path / "one", tmp_path / "two"]
    for root in roots:
        (root / "System").mkdir(parents=True)
        (root / "System/pillars.yaml").write_text(f"pillars:\n  - id: test\n    name: {root.name}\n")
    return roots


def hook(vault, payload, *, native=False, protocol="claude", env=None, plugin=PLUGIN):
    cmd = (["bash", str(ROOT / ".claude/hooks/dex-safety-guard.sh")] if native else
           ["node", str(plugin / "bin/dex-python.mjs"), "hook", "--protocol", protocol])
    return subprocess.run(cmd, input=payload if isinstance(payload, str) else json.dumps(payload),
                          cwd=vault, env={**os.environ, **(env or {})}, text=True,
                          capture_output=True, timeout=15)


def proposal(vault, tool="Write", **tool_input):
    return {"hook_event_name": "PreToolUse", "cwd": str(vault), "tool_name": tool,
            "tool_input": tool_input}


def mcp(vault, name, arguments, env=None):
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": name, "arguments": arguments}}
    result = subprocess.run([sys.executable, str(PLUGIN / "server.py")], cwd=vault,
                            env={**os.environ, **(env or {})}, input=json.dumps(request)+"\n",
                            text=True, capture_output=True, timeout=15, check=True)
    return json.loads(result.stdout)["result"]["structuredContent"]


@pytest.mark.parametrize("native", [False, True])
def test_selected_vault_conflict_is_refused(vaults, native):
    one, two = vaults
    result = hook(two, proposal(two, file_path="note.md"), native=native,
                  env={"DEX_VAULT_PATH": str(one)})
    assert result.returncode == 2, result.stdout + result.stderr


@pytest.mark.parametrize("tool", ["boot_today", "get_person_context", "check_safety_gate"])
def test_mcp_request_cannot_override_configured_vault(vaults, tool):
    one, two = vaults
    result = mcp(two, tool, {"vault_path": str(two), "name": "Ada", "path": "note.md"},
                 {"DEX_VAULT_PATH": str(one)})
    assert result["refused"] is True
    assert result["code"] == "vault_selection_conflict"
    assert "pillars" not in result


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("payload", ["not json", "[]", "{}", '{"tool_name":"Bash","tool_input":[]}'])
def test_malformed_hook_refuses(vaults, native, payload):
    assert hook(vaults[0], payload, native=native).returncode == 2


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("tool,arguments", [
    ("apply_patch", {"command": "*** Begin Patch\n*** Add File: ../escaped.md\n+x\n*** End Patch"}),
    ("apply_patch", {"command": "*** Begin Patch\n*** Update File: note.md\n*** Move to: ../escaped.md\n@@\n-x\n+y\n*** End Patch"}),
    ("Write", {"file_path": "note.md", "path": "../escaped.md"}),
    ("NotebookEdit", {"notebook_path": "../escaped.ipynb"}),
    ("mcp__files__move", {"source": "note.md", "destination": "../escaped.md"}),
])
def test_every_proposed_target_is_checked(vaults, native, tool, arguments):
    root = vaults[0]
    assert hook(root, proposal(root, tool, **arguments), native=native).returncode == 2
    assert not (root.parent / "escaped.md").exists()


@pytest.mark.parametrize("manifest", ["hooks/hooks.json", "hooks/codex.json"])
def test_portable_matcher_includes_mcp(manifest):
    entries = json.loads((PLUGIN / manifest).read_text())["hooks"]["PreToolUse"]
    assert any(re.search(entry["matcher"], "mcp__files__write") for entry in entries)


def test_native_matcher_includes_file_edits():
    entries = json.loads((ROOT / ".claude/settings.json").read_text())["hooks"]["PreToolUse"]
    for name in ("Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch"):
        assert any(re.search(entry["matcher"], name) and
                   any("dex-safety-guard.sh" in hook["command"] for hook in entry["hooks"])
                   for entry in entries)


@pytest.mark.parametrize("protocol", ["claude", "codex", "cursor", "gemini"])
def test_unknown_event_and_dangerous_proposal_refuse_in_host_protocol(vaults, protocol):
    root = vaults[0]
    for payload in ({"hook_event_name": "future-event"}, proposal(root, "Bash", command="gh repo delete fixture/example")):
        result = hook(root, payload, protocol=protocol)
        output = json.loads(result.stdout)
        if protocol == "cursor":
            assert result.returncode == 0 and output["permission"] == "deny"
        elif protocol == "gemini":
            assert result.returncode == 0 and output["decision"] == "deny"
        else:
            assert result.returncode == 2 and output["decision"] == "block"


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("tool,arguments", [
    ("Bash", {"command": "git status --short"}),
    ("Write", {"file_path": "note.md"}),
    ("Edit", {"file_path": "note.md", "old_string": "a", "new_string": "b"}),
    ("MultiEdit", {"file_path": "note.md", "edits": []}),
    ("apply_patch", {"command": "*** Begin Patch\n*** Add File: note.md\n+rm -rf /\n*** End Patch"}),
    ("mcp__opaque__lookup", {"query": "a harmless query"}),
])
def test_allowed_action_and_unknown_tool_are_not_blanket_blocked(vaults, native, tool, arguments):
    one, two = vaults
    nested = one / "nested"
    nested.mkdir()
    payload = proposal(nested, tool, **arguments)
    payload["workspace_roots"] = [str(one), str(two)]
    result = hook(nested, payload, native=native, env={"DEX_VAULT_PATH": str(one)})
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (nested / "note.md").exists()


def test_multivault_requires_selection_and_can_select_either(vaults):
    one, two = vaults
    payload = proposal(one, file_path="note.md")
    payload["workspace_roots"] = [str(one), str(two)]
    assert hook(one, payload).returncode == 2
    for selected in vaults:
        payload["cwd"] = str(selected)
        payload["vault_path"] = str(selected)
        assert hook(selected, payload).returncode == 0
        result = mcp(selected, "boot_today", {"vault_path": str(selected)})
        assert result["pillars"][0]["name"] == selected.name


def test_binding_alias_conflict_and_symlink_identity(vaults):
    one, two = vaults
    assert hook(one, proposal(one, file_path="note.md"), env={
        "DEX_VAULT_PATH": str(one), "VAULT_PATH": str(two)}).returncode == 2
    alias = one.parent / "alias"
    alias.symlink_to(one, target_is_directory=True)
    result = hook(one, proposal(one, file_path="note.md"), env={
        "DEX_VAULT_PATH": str(one), "VAULT_PATH": str(alias), "CLAUDE_PROJECT_DIR": str(one)})
    assert result.returncode == 0


def test_configuration_wins_over_process_launch_directory(vaults):
    one, two = vaults
    for root in vaults:
        result = mcp(two, "boot_today", {}, {"DEX_VAULT_PATH": str(root)})
        assert result["pillars"][0]["name"] == root.name


@pytest.mark.parametrize("fault", ["crash", "missing-runtime", "missing-python", "missing-launcher-helper"])
def test_portable_launcher_refuses_when_checker_cannot_start(vaults, tmp_path, fault):
    import shutil
    one = vaults[0]
    copied = tmp_path / "plugin"
    shutil.copytree(PLUGIN, copied)
    env = {}
    if fault == "crash":
        (copied / "hook.py").write_text("raise RuntimeError('deliberate checker break')\n")
    elif fault == "missing-runtime":
        shutil.rmtree(copied / "runtime/core/gates")
    elif fault == "missing-launcher-helper":
        (copied / "bin/dex-launcher-lib.mjs").unlink()
    else:
        empty = tmp_path / "empty-path"
        empty.mkdir()
        env = {"PATH": str(empty), "DEX_PYTHON": ""}
    node = shutil.which("node")
    result = subprocess.run([node, str(copied / "bin/dex-python.mjs"), "hook"],
                            input=json.dumps(proposal(one, "Bash", command="git status")),
                            cwd=one, env={**os.environ, **env}, text=True, capture_output=True, timeout=15)
    assert result.returncode == 2, result.stdout + result.stderr


def test_file_target_resolves_from_subdirectory_and_blocks_symlink_escape(vaults):
    one, two = vaults
    nested = one / "nested"
    nested.mkdir()
    (nested / "outside").symlink_to(two, target_is_directory=True)
    env = {"DEX_VAULT_PATH": str(one)}
    assert hook(nested, proposal(nested, file_path="../note.md"), env=env).returncode == 0
    assert hook(nested, proposal(nested, file_path="outside/note.md"), env=env).returncode == 2


@pytest.mark.parametrize("value", [None, "", "relative-root", 42, [], "/missing-selected-vault-for-test"])
def test_invalid_explicit_vault_never_falls_back(vaults, value):
    result = mcp(vaults[0], "boot_today", {"vault_path": value})
    assert result["refused"] is True
    assert result["code"] == "vault_selection_conflict"


@pytest.mark.parametrize("native", [False, True])
def test_missing_cwd_does_not_hide_actual_working_directory_conflict(vaults, native):
    one, two = vaults
    payload = proposal(two, file_path="note.md")
    del payload["cwd"]
    assert hook(two, payload, native=native, env={"DEX_VAULT_PATH": str(one)}).returncode == 2


def test_native_unknown_event_refuses(vaults):
    root = vaults[0]
    payload = proposal(root, "Bash", command="git status")
    payload["hook_event_name"] = "unknown-event"
    assert hook(root, payload, native=True).returncode == 2
