"""Public-boundary checks for the session-memory MCP server."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

import mcp

from core.utils.mcp_handshake import mcp_stdio_handshake


def test_server_starts_from_outside_the_vault_working_directory(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dependency_root = Path(next(iter(mcp.__path__))).resolve().parent
    vault = tmp_path / "vault"
    vault.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(dependency_root)
    env["VAULT_PATH"] = str(vault)

    result = mcp_stdio_handshake(
        [sys.executable, str(repo_root / "core/mcp/session_memory_server.py")],
        cwd=tmp_path,
        env=env,
        timeout=10,
    )

    assert result.ok, f"{result.error}\nstderr:\n{result.stderr}"


def test_missing_database_reports_not_installed_without_creating_it(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    from core.mcp import session_memory_server

    server = importlib.reload(session_memory_server)
    database = tmp_path / "System" / ".dex-sessions.db"

    async def call_every_advertised_tool() -> list[dict]:
        payloads = []
        for tool in await server.handle_list_tools():
            arguments = {
                field: "probe"
                for field in tool.inputSchema.get("required", [])
            }
            response = await server.handle_call_tool(tool.name, arguments)
            payloads.append(json.loads(response[0].text))
        return payloads

    assert not database.exists()
    payloads = asyncio.run(call_every_advertised_tool())

    assert len(payloads) == 8
    assert {payload["feature_status"] for payload in payloads} == {"not_installed"}
    assert all("Sessions DB not found" in payload["error"] for payload in payloads)
    assert not database.exists()
