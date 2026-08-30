"""Golden validation for the relocatable Agent Plugins v1 package."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-agent-plugin"
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate-portable-plugin.py"
ARTIFACT_BUILDER = REPO_ROOT / "scripts" / "build-portable-harness-artifacts.py"
PLUGIN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "$schema": {"const": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"},
        "name": {"type": "string", "pattern": r"^(?!.*(?:--|\.\.))[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$"},
        "version": {"type": "string"},
        "description": {"type": "string"},
        "author": {"type": "object"},
        "homepage": {"type": "string"},
        "repository": {"type": "string"},
        "license": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "extensions": {"type": "object"},
    },
    "required": ["$schema", "name"],
    "additionalProperties": False,
}
MCP_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "$schema": {"const": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"},
        "mcpServers": {"type": "object"},
    },
    "required": ["$schema", "mcpServers"],
    "additionalProperties": False,
}


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_portable_plugin", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_manifest_and_mcp_config_match_agent_plugins_v1() -> None:
    manifest = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))
    jsonschema.validate(manifest, PLUGIN_SCHEMA)
    mcp = json.loads((PLUGIN_ROOT / "mcp.json").read_text(encoding="utf-8"))
    jsonschema.validate(mcp, MCP_SCHEMA)
    assert set(manifest) <= {
        "$schema",
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "extensions",
    }
    server = mcp["mcpServers"]["dex-core"]
    assert server["type"] == "stdio"
    assert server["command"] == "node"
    assert server["args"][:2] == ["${PLUGIN_ROOT}/bin/dex-python.mjs", "mcp"]
    assert "${PLUGIN_ROOT}" in server["cwd"]
    assert str(PLUGIN_ROOT) not in json.dumps(mcp)


def test_plugin_contains_skills_resources_registry_and_relocatable_launcher() -> None:
    assert (PLUGIN_ROOT / "skills").is_dir()
    assert any((path / "SKILL.md").is_file() for path in (PLUGIN_ROOT / "skills").iterdir())
    assert (PLUGIN_ROOT / "metadata" / "harnesses" / "registry.json").is_file()
    adapter_files = list((PLUGIN_ROOT / "ai.heydex.dex" / "adapters").glob("*.json"))
    assert {path.stem for path in adapter_files} == {
        "agent-plugin",
        "bb",
        "chatgpt-work",
        "claude-code",
        "claude-desktop",
        "codex",
        "copilot-cli",
        "cowork",
        "cursor",
        "gemini-cli",
        "pi",
    }
    launcher = PLUGIN_ROOT / "bin" / "dex-python.mjs"
    launcher_lib = PLUGIN_ROOT / "bin" / "dex-launcher-lib.mjs"
    assert launcher.is_file()
    assert launcher_lib.is_file()
    text = launcher.read_text(encoding="utf-8") + launcher_lib.read_text(encoding="utf-8")
    assert "DEX_PYTHON" in text
    assert "win32" in text
    assert "/srv/" not in text


def test_native_codex_and_claude_manifests_share_one_package() -> None:
    codex = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text())
    claude = json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text())
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())
    codex_mcp = json.loads((PLUGIN_ROOT / ".codex-mcp.json").read_text())
    claude_mcp = json.loads((PLUGIN_ROOT / ".mcp.json").read_text())

    assert codex["name"] == claude["name"] == "dex"
    assert codex["skills"] == "./skills/"
    assert codex["mcpServers"] == "./.codex-mcp.json"
    assert codex["hooks"] == "./hooks/codex.json"
    assert codex_mcp["dex-core"]["command"] == "node"
    assert codex_mcp["dex-core"]["args"][:2] == [
        "${PLUGIN_ROOT}/bin/dex-python.mjs",
        "mcp",
    ]
    assert claude_mcp["mcpServers"]["dex-core"]["command"] == "node"
    assert claude_mcp["mcpServers"]["dex-core"]["args"][:2] == [
        "${CLAUDE_PLUGIN_ROOT}/bin/dex-python.mjs",
        "mcp",
    ]
    assert set(codex_mcp) == {"dex-core"}
    assert set(claude_mcp) == {"mcpServers"}
    assert set(hooks["hooks"]) == {"SessionStart", "PreToolUse"}
    hook_text = json.dumps(hooks)
    assert "CLAUDE_PLUGIN_ROOT" in hook_text
    assert '"command": "node"' in hook_text

    codex_hooks = json.loads((PLUGIN_ROOT / "hooks" / "codex.json").read_text())
    codex_hook_text = json.dumps(codex_hooks)
    assert "PLUGIN_ROOT" in codex_hook_text
    assert "commandWindows" in codex_hook_text


def test_cursor_manifest_uses_native_hooks_and_the_shared_package() -> None:
    manifest = json.loads((PLUGIN_ROOT / ".cursor-plugin" / "plugin.json").read_text())
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "cursor.json").read_text())

    assert manifest["name"] == "dex"
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./mcp.json"
    assert manifest["hooks"] == "./hooks/cursor.json"
    assert hooks["version"] == 1
    assert set(hooks["hooks"]) == {"sessionStart", "preToolUse"}
    assert "--protocol cursor" in json.dumps(hooks)
    assert hooks["hooks"]["preToolUse"][0]["failClosed"] is True


def test_hook_bridge_translates_cursor_protocol(tmp_path: Path) -> None:
    vault = tmp_path / "cursor-vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "pillars.yaml").write_text(
        "pillars:\n  - id: portable\n    name: Cursor Portable\n    description: Verified\n",
        encoding="utf-8",
    )
    session = subprocess.run(
        ["node", str(PLUGIN_ROOT / "bin" / "dex-python.mjs"), "hook", "--protocol", "cursor"],
        input=json.dumps({"hook_event_name": "sessionStart", "workspace_roots": [str(vault)]}),
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Cursor Portable" in json.loads(session.stdout)["additional_context"]

    blocked = subprocess.run(
        ["node", str(PLUGIN_ROOT / "bin" / "dex-python.mjs"), "hook", "--protocol", "cursor"],
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
    denial = json.loads(blocked.stdout)
    assert denial["permission"] == "deny"
    assert denial["agent_message"]


def test_gemini_extension_source_and_hook_protocol(tmp_path: Path) -> None:
    source = REPO_ROOT / "packages" / "dex-gemini-extension"
    manifest = json.loads((source / "gemini-extension.json").read_text())
    hooks = json.loads((source / "hooks" / "hooks.json").read_text())
    assert manifest["name"] == "dex"
    assert manifest["mcpServers"]["dex-core"]["args"][-1] == "mcp"
    assert "${extensionPath}" in json.dumps(manifest)
    assert set(hooks["hooks"]) == {"SessionStart", "BeforeTool"}
    assert "--protocol gemini" in json.dumps(hooks)

    vault = tmp_path / "gemini-vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "pillars.yaml").write_text(
        "pillars:\n  - id: portable\n    name: Gemini Portable\n    description: Verified\n",
        encoding="utf-8",
    )
    session = subprocess.run(
        ["node", str(PLUGIN_ROOT / "bin" / "dex-python.mjs"), "hook", "--protocol", "gemini"],
        input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(vault), "source": "startup"}),
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Gemini Portable" in json.loads(session.stdout)["hookSpecificOutput"]["additionalContext"]

    blocked = subprocess.run(
        ["node", str(PLUGIN_ROOT / "bin" / "dex-python.mjs"), "hook", "--protocol", "gemini"],
        input=json.dumps(
            {
                "hook_event_name": "BeforeTool",
                "cwd": str(vault),
                "tool_name": "run_shell_command",
                "tool_input": {"command": "rm -rf /"},
            }
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    denial = json.loads(blocked.stdout)
    assert denial == {"decision": "deny", "reason": "Blocked: recursive delete targeting root, home, or /Users"}


def test_claude_desktop_manifest_uses_the_official_mcpb_contract() -> None:
    manifest = json.loads((REPO_ROOT / "packages" / "dex-claude-desktop" / "manifest.json").read_text())
    assert manifest["manifest_version"] == "0.4"
    assert manifest["name"] == "dex"
    assert manifest["server"]["type"] == "node"
    assert manifest["server"]["mcp_config"]["command"] == "node"
    assert manifest["server"]["mcp_config"]["args"][-1] == "mcp"
    assert "${__dirname}" in json.dumps(manifest)
    assert manifest["server"]["mcp_config"]["env"]["DEX_VAULT_PATH"] == ("${user_config.vault_path}")
    assert manifest["user_config"]["vault_path"]["type"] == "directory"
    assert manifest["user_config"]["vault_path"]["required"] is True
    assert set(manifest["compatibility"]["platforms"]) == {"darwin", "win32"}


def test_artifact_builder_produces_installable_gemini_and_mcpb_bundles(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [sys.executable, str(ARTIFACT_BUILDER), "--output-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "dex-gemini-extension" in completed.stdout
    assert "dex-claude-desktop.mcpb" in completed.stdout

    gemini = tmp_path / "dex-gemini-extension"
    assert (gemini / "gemini-extension.json").is_file()
    assert (gemini / "hooks" / "hooks.json").is_file()
    assert (gemini / "bin" / "dex-python.mjs").is_file()
    assert (gemini / "server.py").is_file()
    assert "gemini extensions install" in (gemini / "README.md").read_text()
    assert (gemini / "runtime" / "core" / "gates" / "safety.py").is_file()
    assert any((gemini / "skills").glob("*/SKILL.md"))

    with tarfile.open(tmp_path / "dex-gemini-extension.tar.gz", "r:gz") as archive:
        names = set(archive.getnames())
    assert "dex-gemini-extension/gemini-extension.json" in names
    assert "dex-gemini-extension/skills/getting-started/SKILL.md" in names

    mcpb = tmp_path / "dex-claude-desktop.mcpb"
    with zipfile.ZipFile(mcpb) as archive:
        names = set(archive.namelist())
        bundled_manifest = json.loads(archive.read("manifest.json"))
    assert bundled_manifest["manifest_version"] == "0.4"
    assert "bin/dex-python.mjs" in names
    assert "server.py" in names
    assert "runtime/core/context/session_boot.py" in names
    assert "Install Extension" in (
        tmp_path / "dex-claude-desktop" / "README.md"
    ).read_text()

    artifact_index = json.loads((tmp_path / "artifacts.json").read_text())
    assert artifact_index["release_status"] == "unreleased"
    assert {row["name"] for row in artifact_index["artifacts"]} == {
        "dex-claude-desktop.mcpb",
        "dex-gemini-extension.tar.gz",
    }
    assert all(len(row["sha256"]) == 64 for row in artifact_index["artifacts"])

    responses = _mcp_roundtrip(
        [{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}],
        cwd=gemini,
        plugin_root=gemini,
    )
    assert {tool["name"] for tool in responses[0]["result"]["tools"]} == {
        "dex_harness_profiles",
        "boot_today",
        "get_person_context",
        "ask_what_was_decided",
        "check_safety_gate",
    }
    desktop = tmp_path / "dex-claude-desktop"
    desktop_responses = _mcp_roundtrip(
        [{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}],
        cwd=desktop,
        plugin_root=desktop,
    )
    assert desktop_responses[0]["id"] == 2


def test_artifact_builder_marks_release_assets_with_the_declared_channel(
    tmp_path: Path,
) -> None:
    subprocess.run(
        [
            sys.executable,
            str(ARTIFACT_BUILDER),
            "--output-dir",
            str(tmp_path),
            "--release-status",
            "stable",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    artifact_index = json.loads((tmp_path / "artifacts.json").read_text())
    assert artifact_index["release_status"] == "stable"


def test_launcher_selects_platform_specific_python_candidates() -> None:
    script = """
      import { pythonCandidates } from './packages/dex-agent-plugin/bin/dex-launcher-lib.mjs';
      const result = {
        mac: pythonCandidates('darwin', {}),
        win: pythonCandidates('win32', {}),
        override: pythonCandidates('win32', {DEX_PYTHON: 'C:/Dex Python/python.exe'}),
      };
      process.stdout.write(JSON.stringify(result));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    candidates = json.loads(completed.stdout)
    assert candidates["mac"][0] == {"command": "python3", "args": []}
    assert candidates["win"][0] == {"command": "py", "args": ["-3"]}
    assert candidates["override"][0] == {
        "command": "C:/Dex Python/python.exe",
        "args": [],
    }


def test_repo_marketplace_exposes_the_unreleased_local_openai_plugin() -> None:
    marketplace = json.loads((REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    assert marketplace["interface"]["displayName"] == "Dex (unreleased local build)"
    assert marketplace["plugins"] == [
        {
            "name": "dex",
            "source": {
                "source": "local",
                "path": "./packages/dex-agent-plugin",
            },
            "policy": {
                "installation": "AVAILABLE",
                "authentication": "ON_INSTALL",
            },
            "category": "Productivity",
        }
    ]


def test_vendored_runtime_is_byte_identical_to_shared_core() -> None:
    for relative in (
        "core/__init__.py",
        "core/paths.py",
        "core/path_safety.py",
        "core/context/__init__.py",
        "core/context/person_context.py",
        "core/context/decision_record.py",
        "core/context/session_boot.py",
        "core/gates/__init__.py",
        "core/gates/safety.py",
    ):
        assert (PLUGIN_ROOT / "runtime" / relative).read_bytes() == (REPO_ROOT / relative).read_bytes()


def _mcp_roundtrip(
    messages: list[dict],
    *,
    cwd: Path | None = None,
    plugin_root: Path = PLUGIN_ROOT,
) -> list[dict]:
    payload = "".join(json.dumps(message) + "\n" for message in messages)
    completed = subprocess.run(
        ["node", str(plugin_root / "bin" / "dex-python.mjs"), "mcp"],
        input=payload,
        text=True,
        capture_output=True,
        cwd=cwd,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        check=True,
    )
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def test_plugin_mcp_lists_and_calls_shared_read_only_tools(tmp_path: Path) -> None:
    vault = tmp_path / "Dex Vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "pillars.yaml").write_text(
        'pillars:\n  - id: focus\n    name: "Focus"\n    description: "Do the important work"\n',
        encoding="utf-8",
    )
    person_dir = vault / "05-Areas" / "People" / "Internal"
    person_dir.mkdir(parents=True)
    (person_dir / "Ada_Lovelace.md").write_text(
        "---\nname: Ada Lovelace\nrole: Founder\ncompany: Analytical Engines\n---\n- [ ] Send the operating memo\n",
        encoding="utf-8",
    )
    decisions = vault / "06-Resources" / "Decisions"
    decisions.mkdir(parents=True)
    (decisions / "Decision_Log.md").write_text(
        "## 2026-04-12 — Keep pricing annual-only\n\n"
        "**Decision:** Sell only annual plans.\n",
        encoding="utf-8",
    )
    responses = _mcp_roundtrip(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "boot_today", "arguments": {"vault_path": str(vault)}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "get_person_context",
                    "arguments": {"vault_path": str(vault), "name": "Ada Lovelace"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "check_safety_gate",
                    "arguments": {"vault_path": str(vault), "command": "rm -rf /"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "ask_what_was_decided",
                    "arguments": {"vault_path": str(vault), "topic": "pricing"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "ask_what_was_decided",
                    "arguments": {"vault_path": str(vault)},
                },
            },
        ],
        cwd=vault,
    )
    assert len(responses) == 7
    names = {tool["name"] for tool in responses[1]["result"]["tools"]}
    assert names == {
        "dex_harness_profiles",
        "boot_today",
        "get_person_context",
        "ask_what_was_decided",
        "check_safety_gate",
    }
    ask_tool = next(
        tool
        for tool in responses[1]["result"]["tools"]
        if tool["name"] == "ask_what_was_decided"
    )
    required = (ask_tool.get("inputSchema") or {}).get("required") or []
    assert "topic" not in required
    assert responses[2]["result"]["structuredContent"]["pillars"][0]["name"] == "Focus"
    person = responses[3]["result"]["structuredContent"]
    assert person["found"] is True
    assert person["matches"][0]["company"] == "Analytical Engines"
    safety = responses[4]["result"]["structuredContent"]
    assert safety["refused"] is True
    ask = responses[5]["result"]["structuredContent"]
    assert ask["found"] is True
    assert ask["matches"][0]["decision"] == "Sell only annual plans."
    assert ask["matches"][0]["file"] == "06-Resources/Decisions/Decision_Log.md"
    lately = responses[6]["result"]["structuredContent"]
    assert lately["found"] is True
    assert lately["topic"] == ""
    assert lately["matches"][0]["decision"] == "Sell only annual plans."


def test_plugin_hooks_inject_session_context_and_block_destructive_work(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "pillars.yaml").write_text(
        "pillars:\n  - id: customer\n    name: Customer\n    description: Listen\n",
        encoding="utf-8",
    )
    session = subprocess.run(
        ["node", str(PLUGIN_ROOT / "bin" / "dex-python.mjs"), "hook"],
        input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(vault)}),
        text=True,
        capture_output=True,
        check=True,
    )
    injected = json.loads(session.stdout)
    assert injected["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Customer" in injected["hookSpecificOutput"]["additionalContext"]

    blocked = subprocess.run(
        ["node", str(PLUGIN_ROOT / "bin" / "dex-python.mjs"), "hook"],
        input=json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(vault),
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /"},
            }
        ),
        text=True,
        capture_output=True,
    )
    assert blocked.returncode == 2
    assert json.loads(blocked.stdout)["decision"] == "block"


def test_plugin_generator_check_is_clean() -> None:
    generator = _load_generator()
    assert generator.check_plugin(REPO_ROOT) == 0


def test_ci_runs_the_runtime_verifier_on_macos_and_windows() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "portable-plugin-platforms:" in workflow
    job = workflow.split("portable-plugin-platforms:", 1)[1]
    assert "macos-latest" in job
    assert "windows-latest" in job
    assert "build-portable-harness-artifacts.py" in job
    assert "build-mcp-registry-artifact.py" in job
    assert "--plugin-root build/mcp-registry-artifact/dex-mcp --skip-hooks" in job
    assert "verify-portable-plugin-runtime.py --require-release-ready" in job
    assert "--plugin-root build/portable-artifacts/dex-gemini-extension" in job
    assert "--plugin-root build/portable-artifacts/dex-claude-desktop --skip-hooks" in job
