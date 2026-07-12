"""Regression tests for the pre-flight MCP server path.

Bug (originally surfaced in #49): ``check_server()`` looked for MCP server
modules under ``<vault>/dex-core/core/mcp`` — a directory that does not exist —
so every session start falsely reported ``0/8 MCP servers ready`` and
``dex-core may need reinstalling`` even when the servers were fine. The servers
actually live at ``<vault>/core/mcp``. These tests pin the corrected path so the
``dex-core`` segment can never creep back in.
"""

import json
from pathlib import Path

from core.utils import preflight

REPO_ROOT = Path(__file__).resolve().parents[2]


def _known_server():
    """Return any registered core server name and its module filename."""
    return next(iter(preflight.SERVER_MODULES.items()))


def test_server_modules_match_registered_core_servers():
    """Every bundled core server in the install template is preflighted."""
    config = json.loads((REPO_ROOT / "System" / ".mcp.json.example").read_text())
    registered_core_modules = {}

    for server_name, server_config in config["mcpServers"].items():
        module_args = [
            Path(arg).name
            for arg in server_config.get("args", [])
            if isinstance(arg, str) and "/core/mcp/" in arg and arg.endswith(".py")
        ]
        if not module_args:
            continue
        assert len(module_args) == 1, f"{server_name} must register exactly one core server module"
        registered_core_modules[server_name] = module_args[0]

    assert preflight.SERVER_MODULES == registered_core_modules


def test_check_server_finds_module_under_core_mcp(tmp_path, monkeypatch):
    """A server file at ``<vault>/core/mcp`` passes the existence check."""
    server_name, module_file = _known_server()
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    mcp_dir = tmp_path / "core" / "mcp"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / module_file).write_text("# stub module\n")

    result = preflight.check_server(server_name)

    # Check 1 (file existence) must pass — the file is NOT reported missing.
    # (Later checks may still flag a missing 'mcp' package; that's unrelated.)
    assert result.get("error") != f"Server file not found: {module_file}"
    assert "may need reinstalling" not in result.get("humanError", "")


def test_check_server_ignores_stale_dexcore_path(tmp_path, monkeypatch):
    """A server file ONLY under the old ``dex-core/core/mcp`` path is NOT found.

    This is the actual regression guard: against the pre-fix code (which looked
    under ``dex-core/core/mcp``) this test would FAIL, because it would locate
    the stub there and not report it missing.
    """
    server_name, module_file = _known_server()
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    stale_dir = tmp_path / "dex-core" / "core" / "mcp"
    stale_dir.mkdir(parents=True)
    (stale_dir / module_file).write_text("# stub module\n")

    result = preflight.check_server(server_name)

    assert result["status"] == "error"
    assert result["error"] == f"Server file not found: {module_file}"


def test_mcp_config_path_prefers_root_when_both_configs_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    root = tmp_path / ".mcp.json"
    legacy = tmp_path / "System" / ".mcp.json"
    legacy.parent.mkdir()
    root.write_text(json.dumps({"mcpServers": {"root": {}}}))
    legacy.write_text(json.dumps({"mcpServers": {"legacy": {}}}))

    assert preflight.get_mcp_config_path() == root
    assert preflight.get_configured_servers() == ["root"]


def test_mcp_config_path_falls_back_to_legacy_when_root_is_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    legacy = tmp_path / "System" / ".mcp.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({"mcpServers": {"legacy": {}}}))

    assert preflight.get_mcp_config_path() == legacy
    assert preflight.get_configured_servers() == ["legacy"]
    assert not (tmp_path / ".mcp.json").exists()


def test_preflight_creates_runtime_health_cache_on_demand(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    health = preflight.run_preflight()

    health_path = tmp_path / ".logs" / "mcp-health.json"
    assert health_path.is_file()
    assert json.loads(health_path.read_text()) == health
