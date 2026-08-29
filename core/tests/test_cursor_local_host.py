"""Cursor local-plugin copy is a written path, not a live Cursor session."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from core.harnesses.registry import get_profile

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-agent-plugin"
ADAPTER_PATH = REPO_ROOT / "core" / "harnesses" / "adapters" / "cursor.json"
LOCAL_COPY = Path(".cursor") / "plugins" / "local" / "dex"


def _expand_plugin_vars(value: str, plugin_root: Path, plugin_data: Path) -> str:
    return value.replace("${PLUGIN_ROOT}", str(plugin_root)).replace(
        "${PLUGIN_DATA}", str(plugin_data)
    )


def test_written_cursor_path_is_the_reviewed_local_plugin_copy() -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    guide = (REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md").read_text(encoding="utf-8")
    limitations = " ".join(get_profile("cursor").limitations).lower()

    assert adapter["example"]["local_package"] == "./packages/dex-agent-plugin"
    assert adapter["example"]["local_copy"] == "~/.cursor/plugins/local/dex"
    assert "~/.cursor/plugins/local/dex" in adapter["example"]["install_guide"]
    assert "~/.cursor/plugins/local/dex" in guide
    assert "fixture is not a live cursor session" in guide.lower()
    assert "sessionstart" in limitations
    assert "cloud" in limitations
    assert not (PLUGIN_ROOT / "AGENTS.md").exists()


def test_local_copy_fixture_reads_a_vault_without_claiming_a_live_session(
    tmp_path: Path,
) -> None:
    adapter = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    home = tmp_path / "home"
    installed = home.joinpath(*LOCAL_COPY.parts)
    plugin_data = tmp_path / "plugin-data"
    plugin_data.mkdir()
    vault = tmp_path / "Dex"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "pillars.yaml").write_text(
        'pillars:\n  - id: focus\n    name: "Focus"\n    description: "Do the important work"\n',
        encoding="utf-8",
    )
    shutil.copytree(
        PLUGIN_ROOT,
        installed,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    manifest = json.loads((installed / ".cursor-plugin" / "plugin.json").read_text())
    hooks = json.loads((installed / "hooks" / "cursor.json").read_text())
    mcp = json.loads((installed / "mcp.json").read_text())
    server = mcp["mcpServers"]["dex-core"]
    args = [
        _expand_plugin_vars(argument, installed, plugin_data)
        for argument in server["args"]
    ]
    env = {**os.environ, "PYTHONNOUSERSITE": "1"}
    for key, value in server.get("env", {}).items():
        env[key] = _expand_plugin_vars(value, installed, plugin_data)
    payload = "".join(
        json.dumps(message) + "\n"
        for message in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "boot_today", "arguments": {"vault_path": str(vault)}},
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "check_safety_gate",
                    "arguments": {"vault_path": str(vault), "command": "rm -rf /"},
                },
            },
        )
    )
    completed = subprocess.run(
        [server["command"], *args],
        input=payload,
        text=True,
        capture_output=True,
        cwd=vault,
        env=env,
        check=True,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    session = subprocess.run(
        ["node", str(installed / "bin" / "dex-python.mjs"), "hook", "--protocol", "cursor"],
        input=json.dumps(
            {"hook_event_name": "sessionStart", "workspace_roots": [str(vault)]}
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    blocked = subprocess.run(
        ["node", str(installed / "bin" / "dex-python.mjs"), "hook", "--protocol", "cursor"],
        input=json.dumps(
            {
                "hook_event_name": "preToolUse",
                "cwd": str(vault),
                "tool_name": "Shell",
                "tool_input": {"command": "rm -rf /"},
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    skills = list((installed / "skills").glob("*/SKILL.md"))
    limitations = " ".join(get_profile("cursor").limitations).lower()

    assert installed == home / ".cursor" / "plugins" / "local" / "dex"
    assert installed != PLUGIN_ROOT
    for relative in adapter["native_paths"]:
        assert (installed / relative).exists()
    assert skills
    assert manifest["hooks"] == "./hooks/cursor.json"
    assert hooks["hooks"]["preToolUse"][0]["failClosed"] is True
    assert responses[1]["result"]["structuredContent"]["pillars"][0]["name"] == "Focus"
    assert responses[2]["result"]["structuredContent"]["refused"] is True
    assert "Focus" in json.loads(session.stdout)["additional_context"]
    assert json.loads(blocked.stdout)["permission"] == "deny"
    assert "cloud" in limitations
    assert "sessionstart" in limitations
    assert "vscode" not in adapter["example"]["install_guide"].lower()
    assert "kiro" not in adapter["example"]["install_guide"].lower()
    assert "obsidian" not in adapter["example"]["install_guide"].lower()
