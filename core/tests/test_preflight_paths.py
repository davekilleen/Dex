"""Regression tests for the pre-flight MCP server path.

Bug (originally surfaced in #49): ``check_server()`` looked for MCP server
modules under ``<vault>/dex-core/core/mcp`` — a directory that does not exist —
so every session start falsely reported ``0/8 MCP servers ready`` and
``dex-core may need reinstalling`` even when the servers were fine. The servers
actually live at ``<vault>/core/mcp``. These tests pin the corrected path so the
``dex-core`` segment can never creep back in.
"""

from core.utils import preflight


def _known_server():
    """Return any registered core server name and its module filename."""
    return next(iter(preflight.SERVER_MODULES.items()))


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
