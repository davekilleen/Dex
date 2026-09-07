"""Run the real hook boundary with proposals; never execute those proposals."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "core/harnesses/templates/copilot"
MODES = [("copilot-cli", "preToolUse"), ("copilot-cli", "PreToolUse"), ("vscode", "PreToolUse")]


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    for key in ("DEX_VAULT_PATH", "VAULT_PATH", "CLAUDE_PROJECT_DIR", "PYTHONPATH"):
        monkeypatch.delenv(key, raising=False)
    package = tmp_path / "plugin with spaces"
    (package / "bin").mkdir(parents=True)
    shutil.copyfile(TEMPLATES / "dex-copilot-hook.mjs", package / "bin/dex-copilot-hook.mjs")
    shutil.copyfile(ROOT / "packages/dex-agent-plugin/bin/dex-launcher-lib.mjs", package / "bin/dex-launcher-lib.mjs")
    for relative in ("core/__init__.py", "core/path_safety.py", "core/vault_selection.py", "core/paths.py",
                     "core/harnesses/__init__.py", "core/harnesses/copilot_hooks.py",
                     "core/gates/__init__.py", "core/gates/safety.py",
                     "core/context/__init__.py", "core/context/person_context.py", "core/context/session_boot.py"):
        target = package / "runtime" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    vault = tmp_path / "selected"
    decoy = tmp_path / "decoy"
    for location in (vault, decoy):
        (location / "System").mkdir(parents=True)
        (location / "System/pillars.yaml").write_text(f"pillars:\n  - id: test\n    name: {location.name}\n")
    return package, vault, decoy


def payload(vault, surface, event, tool=None, arguments=None, **extra):
    native = surface == "copilot-cli" and event[0].islower()
    result = {"cwd": str(vault), "timestamp": 1 if native else "2026-09-07T12:00:00Z"}
    result["sessionId" if native else "session_id"] = "synthetic-session"
    if not native:
        result["hook_event_name"] = event
    if tool is not None:
        result["toolName" if native else "tool_name"] = tool
        result["toolArgs" if native else "tool_input"] = arguments
    return {**result, **extra}


def invoke(fixture, surface, event, request, *, env=None):
    package, vault, _ = fixture
    result = subprocess.run(
        ["node", str(package / "bin/dex-copilot-hook.mjs"), "--surface", surface, "--event", event],
        cwd=vault, input=request if isinstance(request, str) else json.dumps(request), text=True,
        capture_output=True, timeout=12, env={**os.environ, "DEX_PYTHON": sys.executable, **(env or {})},
    )
    output = json.loads(result.stdout)
    assert len(result.stdout.splitlines()) == 1
    return result, output


def assert_denied(result, output, surface):
    fields = output["hookSpecificOutput"] if surface == "vscode" else output
    assert fields["permissionDecision"] == "deny"
    assert fields["permissionDecisionReason"]
    if surface == "vscode":
        assert fields["hookEventName"] == "PreToolUse"
        assert "permissionDecision" not in output
    else:
        assert "hookSpecificOutput" not in output
    assert result.returncode in (0, 2)


@pytest.mark.parametrize("surface,event", MODES)
@pytest.mark.parametrize("command,blocked", [("rm -rf /", True), ("gh repo delete example/synthetic", True),
                                            ("git status", False), ("printf safe", False)])
def test_shell_proposals_use_canonical_policy(fixture, surface, event, command, blocked):
    _, vault, _ = fixture
    tool = "runTerminalCommand" if surface == "vscode" else "bash" if event == "preToolUse" else "Bash"
    result, output = invoke(fixture, surface, event, payload(vault, surface, event, tool, {"command": command}))
    if blocked:
        assert_denied(result, output, surface)
    else:
        assert result.returncode == 0
        assert output == {}  # No host auto-approval.


@pytest.mark.parametrize("surface,event,tool,key", [
    ("copilot-cli", "preToolUse", "create", "path"),
    ("copilot-cli", "PreToolUse", "Write", "file_path"),
    ("vscode", "PreToolUse", "create_file", "filePath"),
    ("vscode", "PreToolUse", "replace_string_in_file", "filePath"),
])
def test_file_targets_and_selected_vault(fixture, surface, event, tool, key):
    _, vault, decoy = fixture
    for target, blocked in [(str(decoy / "sentinel"), True), ("sentinel", False)]:
        result, output = invoke(fixture, surface, event, payload(vault, surface, event, tool, {key: target}))
        if blocked:
            assert_denied(result, output, surface)
        else:
            assert output == {}
        assert not (vault / "sentinel").exists()
        assert not (decoy / "sentinel").exists()
    result, output = invoke(fixture, surface, event, payload(decoy, surface, event, tool, {key: "sentinel"}),
                            env={"DEX_VAULT_PATH": str(vault)})
    assert_denied(result, output, surface)


@pytest.mark.parametrize("tool,args", [
    ("editFiles", {"files": ["safe", "../decoy/sentinel"]}),
    ("editFiles", {"path": "../decoy/sentinel", "files": ["safe"]}),
    ("create_file", {"filePath": "safe", "file_path": "../decoy/sentinel"}),
    ("multi_replace_string_in_file", {"replacements": [{"filePath": "safe"}, {"filePath": "../decoy/sentinel"}]}),
    ("multi_replace_string_in_file", {"destinationPath": "../decoy/sentinel", "replacements": [{"filePath": "safe"}]}),
    ("multi_replace_string_in_file", {"files": ["../decoy/sentinel"], "replacements": [{"filePath": "safe"}]}),
])
def test_every_batch_target_is_checked(fixture, tool, args):
    _, vault, decoy = fixture
    result, output = invoke(fixture, "vscode", "PreToolUse", payload(vault, "vscode", "PreToolUse", tool, args))
    assert_denied(result, output, "vscode")
    assert not (decoy / "sentinel").exists()


@pytest.mark.parametrize("tool,args", [("editFiles", {"files": ["one", "two"]}),
    ("multi_replace_string_in_file", {"replacements": [{"filePath": "one"}, {"filePath": "two"}]}),
    ("view", {"path": "one"})])
def test_allowed_batch_and_read_controls(fixture, tool, args):
    _, vault, _ = fixture
    result, output = invoke(fixture, "vscode", "PreToolUse", payload(vault, "vscode", "PreToolUse", tool, args))
    assert result.returncode == 0 and output == {}


@pytest.mark.parametrize("surface,event", MODES)
def test_live_migration_lock_is_shared(fixture, surface, event):
    _, vault, _ = fixture
    (vault / "System/.dex").mkdir()
    (vault / "System/.dex/mutation.lock").write_text(json.dumps({"kind": "migration", "pid": os.getpid()}))
    tool = "runTerminalCommand" if surface == "vscode" else "bash" if event == "preToolUse" else "Bash"
    result, output = invoke(fixture, surface, event, payload(vault, surface, event, tool, {"command": "git reset --hard"}))
    assert_denied(result, output, surface)
    assert "migration" in result.stdout


def test_relative_path_uses_host_cwd_and_allows_vault_descendant(fixture):
    _, vault, _ = fixture
    child = vault / "child"
    child.mkdir()
    for target, blocked in [("../safe", False), ("../../decoy/sentinel", True)]:
        result, output = invoke(fixture, "vscode", "PreToolUse", payload(child, "vscode", "PreToolUse", "create_file", {"filePath": target}),
                                env={"DEX_VAULT_PATH": str(vault)})
        if blocked:
            assert_denied(result, output, "vscode")
        else:
            assert result.returncode == 0 and output == {}


@pytest.mark.parametrize("surface,event", MODES)
def test_patch_targets_including_moves(fixture, surface, event):
    _, vault, _ = fixture
    tool = "Edit" if surface == "copilot-cli" and event == "PreToolUse" else "apply_patch"
    for destination, blocked in [("sentinel", False), ("../decoy/sentinel", True)]:
        patch = f"*** Begin Patch\n*** Update File: safe\n*** Move to: {destination}\n@@\n-a\n+b\n*** End Patch"
        result, output = invoke(fixture, surface, event, payload(vault, surface, event, tool, {"input": patch}))
        if blocked:
            assert_denied(result, output, surface)
        else:
            assert output == {}


@pytest.mark.parametrize("surface,event", MODES)
def test_literal_symlink_names_are_not_expanded_or_trimmed(fixture, surface, event):
    _, vault, decoy = fixture
    for name in ("$ALIAS", " strange ", "~literal"):
        (vault / name).symlink_to(decoy, target_is_directory=True)
        tool = "create_file" if surface == "vscode" else "create" if event == "preToolUse" else "Write"
        result, output = invoke(fixture, surface, event, payload(vault, surface, event, tool, {"path": f"{name}/sentinel"}))
        assert_denied(result, output, surface)


@pytest.mark.parametrize("tool,args", [("create_file", {}), ("editFiles", {"files": []}),
    ("editFiles", {"files": [None]}), ("runTerminalCommand", {"command": []}),
    ("apply_patch", {"input": "not a patch"}), ("new_tool", {}),
    ("mcp__unknown__write", {"opaque": "destination"}), ("create_file", {"filePath": None}),
    ("multi_replace_string_in_file", {"replacements": [{}]})])
def test_unknown_and_malformed_tool_schemas_refuse(fixture, tool, args):
    _, vault, _ = fixture
    result, output = invoke(fixture, "vscode", "PreToolUse", payload(vault, "vscode", "PreToolUse", tool, args))
    assert_denied(result, output, "vscode")


@pytest.mark.parametrize("raw", ["", "null", "[]", "{", '{"cwd":"a","cwd":"b"}', "NaN"])
@pytest.mark.parametrize("surface,event", MODES)
def test_invalid_json_is_single_denial(fixture, surface, event, raw):
    result, output = invoke(fixture, surface, event, raw)
    assert_denied(result, output, surface)
    assert result.returncode == 2


@pytest.mark.parametrize("change", [{"hook_event_name": "SessionStart"}, {"toolName": "create"},
    {"cwd": None}, {"tool_input": "{}"}, {"tool_name": ""}, {"timestamp": False}, {"unknown": 42}])
def test_conflicting_or_unknown_envelopes_refuse(fixture, change):
    _, vault, _ = fixture
    request = payload(vault, "vscode", "PreToolUse", "create_file", {"filePath": "safe"})
    result, output = invoke(fixture, "vscode", "PreToolUse", {**request, **change})
    assert_denied(result, output, "vscode")


def test_native_cli_string_arguments(fixture):
    _, vault, _ = fixture
    request = payload(vault, "copilot-cli", "preToolUse", "bash", '{"command":"rm -rf /"}')
    result, output = invoke(fixture, "copilot-cli", "preToolUse", request)
    assert_denied(result, output, "copilot-cli")


@pytest.mark.parametrize("surface,event,source", [("copilot-cli", "sessionStart", "resume"),
    ("copilot-cli", "SessionStart", "startup"), ("vscode", "SessionStart", "new")])
def test_session_context_comes_from_shared_selected_vault(fixture, surface, event, source):
    _, vault, decoy = fixture
    result, output = invoke(fixture, surface, event, payload(vault, surface, event, source=source))
    assert result.returncode == 0
    context = output["additionalContext"] if surface == "copilot-cli" else output["hookSpecificOutput"]["additionalContext"]
    assert "selected" in context and "decoy" not in context
    result, output = invoke(fixture, surface, event, payload(decoy, surface, event, source=source),
                            env={"DEX_VAULT_PATH": str(vault)})
    assert_denied(result, output, surface)
    assert str(vault) not in result.stdout and str(decoy) not in result.stdout
    assert context not in result.stdout


@pytest.mark.parametrize("surface,event,extra", [("copilot-cli", "sessionEnd", {"reason": "complete"}),
    ("copilot-cli", "SessionEnd", {"reason": "user_exit"}),
    ("copilot-cli", "agentStop", {"stopReason": "end_turn", "stop_hook_active": False}),
    ("vscode", "Stop", {"stop_hook_active": True})])
def test_finish_events_do_not_persist_or_restart(fixture, surface, event, extra):
    _, vault, _ = fixture
    before = sorted(p.relative_to(vault) for p in vault.rglob("*"))
    result, output = invoke(fixture, surface, event, payload(vault, surface, event, **extra))
    assert result.returncode == 0 and output == {}
    assert before == sorted(p.relative_to(vault) for p in vault.rglob("*"))


@pytest.mark.parametrize("event,extra", [("SessionStart", {"source": "resume"}),
    ("SessionEnd", {"reason": "complete"}), ("Stop", {"stop_hook_active": "false"})])
def test_vscode_unavailable_lifecycle_contracts_refuse(fixture, event, extra):
    _, vault, _ = fixture
    result, output = invoke(fixture, "vscode", event, payload(vault, "vscode", event, **extra))
    assert_denied(result, output, "vscode")


@pytest.mark.parametrize("broken", ["raise RuntimeError('private-payload')", "print('not json')", "print('{}{}')",
    "print('[]')", "print('{\"permissionDecision\":\"allow\"}')", "print('{\"invented\":true}')",
    "print('{\"systemMessage\":\"ok\",\"hookSpecificOutput\":{\"permissionDecision\":\"allow\"}}')"])
def test_checker_failures_and_unknown_outputs_are_converted(fixture, broken):
    package, vault, _ = fixture
    (package / "runtime/core/harnesses/copilot_hooks.py").write_text(broken)
    result, output = invoke(fixture, "vscode", "PreToolUse", payload(vault, "vscode", "PreToolUse", "create_file", {"path": "safe"}))
    assert_denied(result, output, "vscode")
    assert result.returncode == 2 and "private-payload" not in result.stderr


def test_child_timeout_becomes_denial_before_host_deadline(fixture):
    package, vault, _ = fixture
    (package / "runtime/core/harnesses/copilot_hooks.py").write_text("import time\ntime.sleep(30)\n")
    result, output = invoke(fixture, "copilot-cli", "preToolUse", payload(vault, "copilot-cli", "preToolUse", "create", {"path": "safe"}))
    assert_denied(result, output, "copilot-cli")
    assert result.returncode == 2
    assert not (vault / "safe").exists()


def test_context_import_failure_does_not_disable_pretool_safety(fixture):
    package, vault, _ = fixture
    (package / "runtime/core/context/session_boot.py").write_text("raise RuntimeError('broken context')")
    result, output = invoke(fixture, "copilot-cli", "preToolUse", payload(vault, "copilot-cli", "preToolUse", "bash", {"command": "rm -rf /"}))
    assert_denied(result, output, "copilot-cli")
    assert result.returncode == 0


def test_missing_launcher_dependency_is_blocking_in_vscode(fixture):
    package, vault, _ = fixture
    (package / "bin/dex-launcher-lib.mjs").unlink()
    result, output = invoke(fixture, "vscode", "PreToolUse", payload(vault, "vscode", "PreToolUse", "create_file", {"filePath": "safe"}))
    assert_denied(result, output, "vscode")
    assert result.returncode == 2


def test_templates_have_explicit_surface_event_and_no_matcher():
    for file, surface in [("cli-hooks.json", "copilot-cli"), ("vscode-hooks.json", "vscode")]:
        template = json.loads((TEMPLATES / file).read_text())
        for event, entries in template["hooks"].items():
            assert len(entries) == 1
            command = entries[0]["command"]
            assert f"--surface {surface} --event {event}" in command
            assert "matcher" not in entries[0]
        if surface == "vscode":
            assert "SessionEnd" not in template["hooks"]
