"""Public-boundary checks for the session-memory MCP server."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import mcp

from core.utils.mcp_handshake import mcp_stdio_handshake


def _load_server(monkeypatch, vault: Path):
    monkeypatch.setenv("VAULT_PATH", str(vault))
    from core.mcp import session_memory_server

    return importlib.reload(session_memory_server)


async def _call_every_advertised_tool(server) -> list[dict]:
    payloads = []
    for tool in await server.handle_list_tools():
        arguments = {
            field: "probe"
            for field in tool.inputSchema.get("required", [])
        }
        response = await server.handle_call_tool(tool.name, arguments)
        payloads.append(json.loads(response[0].text))
    return payloads


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


def test_missing_database_is_created_with_the_schema_tools_query(
    tmp_path, monkeypatch
) -> None:
    server = _load_server(monkeypatch, tmp_path)
    database = tmp_path / "System" / ".dex-sessions.db"

    assert not database.exists()
    payloads = asyncio.run(_call_every_advertised_tool(server))

    assert len(payloads) == 8
    assert all("feature_status" not in payload for payload in payloads)
    assert all("no such table" not in json.dumps(payload) for payload in payloads)
    assert database.is_file()

    connection = sqlite3.connect(database)
    try:
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'trigger')"
            )
        }
    finally:
        connection.close()

    assert {
        "sessions",
        "messages",
        "observations",
        "sessions_fts",
        "messages_fts",
        "observations_fts",
    } <= names
    again = asyncio.run(_call_every_advertised_tool(server))
    assert len(again) == 8
    assert all("feature_status" not in payload for payload in again)


def test_created_database_answers_the_tool_queries(tmp_path, monkeypatch) -> None:
    server = _load_server(monkeypatch, tmp_path)
    database = tmp_path / "System" / ".dex-sessions.db"

    asyncio.run(server.handle_call_tool("get_recent_decisions", {}))
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            INSERT INTO sessions (
                id, name, status, pinned, pillar, summary, entities,
                message_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "session-1",
                "Acme pricing",
                "active",
                0,
                "sales",
                "Decided to move Acme to negotiation",
                '{"entities": ["Acme"], "decisions": ["move to negotiation"]}',
                1,
                "2026-09-20T10:00:00",
                "2026-09-20T10:00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO messages (id, session_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "message-1",
                "session-1",
                "user",
                "We talked about Acme Corp pricing",
                "2026-09-20T10:00:00",
            ),
        )
        connection.execute(
            """
            INSERT INTO observations (
                id, session_id, type, summary, entities, tool_name, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "observation-1",
                "session-1",
                "tool_call",
                "Wrote the Acme pricing note",
                '["Acme"]',
                "Write",
                "2026-09-20T10:01:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    summary = json.loads(
        asyncio.run(server.handle_call_tool("get_session_summary", {"session_id": "session-1"}))[0].text
    )
    search = json.loads(
        asyncio.run(server.handle_call_tool("search_sessions", {"query": "pricing"}))[0].text
    )
    timeline = json.loads(
        asyncio.run(server.handle_call_tool("get_entity_timeline", {"name": "Acme"}))[0].text
    )
    observations = json.loads(
        asyncio.run(server.handle_call_tool("search_observations", {"query": "pricing"}))[0].text
    )
    usage = json.loads(
        asyncio.run(server.handle_call_tool("get_recent_tool_usage", {"tool_name": "Write", "days": 3650}))[0].text
    )

    assert summary["id"] == "session-1"
    assert summary["decisions"] == ["move to negotiation"]
    assert search["sessions"][0]["id"] == "session-1"
    assert search["messages"][0]["message_id"] == "message-1"
    assert timeline[0]["session_id"] == "session-1"
    assert observations[0]["tool_name"] == "Write"
    assert usage[0]["id"] == "observation-1"


def test_existing_database_is_left_unchanged(tmp_path, monkeypatch) -> None:
    database = tmp_path / "System" / ".dex-sessions.db"
    database.parent.mkdir()
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            name TEXT,
            status TEXT,
            pinned INTEGER,
            pillar TEXT,
            summary TEXT,
            entities TEXT,
            message_count INTEGER,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    connection.execute("CREATE TABLE app_owned (note TEXT)")
    connection.execute("INSERT INTO app_owned (note) VALUES ('keep')")
    connection.execute(
        """
        INSERT INTO sessions (
            id, name, status, pinned, pillar, summary, entities,
            message_count, created_at, updated_at
        ) VALUES ('keep-me', 'Kept', 'active', 0, NULL, 'still here', '{}', 0, '2026-09-20', '2026-09-20')
        """
    )
    connection.commit()
    before = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master")
    }
    connection.close()

    server = _load_server(monkeypatch, tmp_path)
    summary = json.loads(
        asyncio.run(server.handle_call_tool("get_session_summary", {"session_id": "keep-me"}))[0].text
    )

    connection = sqlite3.connect(database)
    try:
        after = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master")
        }
        note = connection.execute("SELECT note FROM app_owned").fetchone()[0]
    finally:
        connection.close()

    assert summary["name"] == "Kept"
    assert summary["summary"] == "still here"
    assert after == before
    assert note == "keep"


def test_unwritable_vault_reports_not_installed_without_replacing_a_blocker(
    tmp_path, monkeypatch
) -> None:
    blocker = tmp_path / "System"
    blocker.write_text("not a directory", encoding="utf-8")
    server = _load_server(monkeypatch, tmp_path)

    payload = json.loads(
        asyncio.run(server.handle_call_tool("get_recent_decisions", {}))[0].text
    )

    assert payload["feature_status"] == "not_installed"
    assert "could not create the session memory database" in payload["user_message"]
    assert blocker.read_text(encoding="utf-8") == "not a directory"
    assert not (tmp_path / "System" / ".dex-sessions.db").exists()
