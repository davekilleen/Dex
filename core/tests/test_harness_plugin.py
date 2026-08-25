"""Golden validation for the relocatable Agent Plugins v1 package."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-agent-plugin"
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate-portable-plugin.py"
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
    assert server["command"].startswith("./")
    assert "${PLUGIN_ROOT}" in server["cwd"]
    assert not str(PLUGIN_ROOT) in json.dumps(mcp)


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
        "codex",
        "copilot-cli",
        "cowork",
        "pi",
    }
    launcher = PLUGIN_ROOT / "bin" / "dex-mcp"
    assert launcher.stat().st_mode & 0o111
    text = launcher.read_text(encoding="utf-8")
    assert "PLUGIN_ROOT" in text
    assert "/srv/" not in text


def test_plugin_generator_check_is_clean() -> None:
    generator = _load_generator()
    assert generator.check_plugin(REPO_ROOT) == 0
