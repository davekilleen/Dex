"""MCP server smoke tests — verify each server imports and exposes a server object."""

import importlib
from pathlib import Path

import pytest


def _discover_server_modules() -> list[str]:
    mcp_dir = Path(__file__).resolve().parents[1] / "mcp"
    modules = [f"core.mcp.{path.stem}" for path in mcp_dir.glob("*_server.py")]
    modules.append("core.mcp.update_checker")
    return sorted(modules)


SERVERS = _discover_server_modules()


@pytest.mark.parametrize(
    "module_path",
    SERVERS,
    ids=[m.rsplit(".", 1)[-1] for m in SERVERS],
)
def test_server_imports_and_has_object(module_path: str):
    """Each MCP server module should import without error and expose its server object."""
    mod = importlib.import_module(module_path)
    assert any(hasattr(mod, attr) for attr in ("app", "server", "mcp")), (
        f"{module_path} imported OK but has no server object (expected one of app/server/mcp)"
    )
