#!/usr/bin/env python3
"""
MCP Server for Dex Session Memory System
Exposes conversation intelligence from the dex-app SQLite DB to Cursor/CLI.

Read-only access to:
- Sessions (search, context, summaries)
- Entity timelines (cross-session awareness)
- Observations (tool-use history, decisions, insights)
- Progressive disclosure (3-layer token-efficient retrieval)

DB location: System/.dex-sessions.db (shared with dex-app via WAL mode)
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
BASE_DIR = Path(os.environ.get('VAULT_PATH', Path.cwd()))
DB_PATH = BASE_DIR / 'System' / '.dex-sessions.db'

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    """Open a read-only WAL-mode connection to the sessions DB."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Sessions DB not found at {DB_PATH}. Start the Dex app first to create it.")

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def rows_to_dicts(rows) -> List[Dict]:
    """Convert sqlite3.Row objects to plain dicts."""
    return [dict(row) for row in rows]


def safe_json_parse(val: Optional[str], default=None):
    """Parse a JSON string or return default."""
    if not val:
        return default
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def search_sessions_fts(query: str, limit: int = 10, include_messages: bool = True) -> Dict:
    """Search sessions and optionally messages via FTS5."""
    conn = get_db()
    results = {"sessions": [], "messages": []}
    fts_query = query.replace("'", "").replace('"', '').strip()
    if not fts_query:
        conn.close()
        return results

    # Search sessions (name, summary, entities)
    try:
        rows = conn.execute("""
            SELECT s.id, s.name, s.status, s.summary, s.entities,
                   s.message_count, s.created_at, s.updated_at,
                   snippet(sessions_fts, 0, '«', '»', '…', 32) as snippet
            FROM sessions_fts
            JOIN sessions s ON s.rowid = sessions_fts.rowid
            WHERE sessions_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (fts_query, limit)).fetchall()
        for row in rows:
            results["sessions"].append({
                "id": row["id"],
                "name": row["name"],
                "status": row["status"],
                "summary": row["summary"],
                "entity_count": len(safe_json_parse(row["entities"], {}).get("entities", [])) if row["entities"] else 0,
                "message_count": row["message_count"],
                "snippet": row["snippet"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
    except sqlite3.OperationalError:
        pass  # FTS5 syntax error — degrade gracefully

    # Search messages
    if include_messages:
        try:
            rows = conn.execute("""
                SELECT m.id, m.session_id, m.role, m.created_at,
                       s.name as session_name,
                       snippet(messages_fts, 0, '«', '»', '…', 48) as snippet
                FROM messages_fts
                JOIN messages m ON m.rowid = messages_fts.rowid
                JOIN sessions s ON s.id = m.session_id
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, limit)).fetchall()
            for row in rows:
                results["messages"].append({
                    "message_id": row["id"],
                    "session_id": row["session_id"],
                    "session_name": row["session_name"],
                    "role": row["role"],
                    "snippet": row["snippet"],
                    "created_at": row["created_at"],
                })
        except sqlite3.OperationalError:
            pass

    conn.close()
    return results


def get_session_context_for_entity(entity_name: str, limit: int = 10) -> List[Dict]:
    """Find sessions mentioning an entity by name (in entities JSON, name, summary, or messages)."""
    conn = get_db()
    pattern = f"%{entity_name}%"

    rows = conn.execute("""
        SELECT DISTINCT s.id, s.name, s.status, s.summary, s.entities,
               s.message_count, s.created_at, s.updated_at
        FROM sessions s
        WHERE s.name LIKE ? OR s.summary LIKE ? OR s.entities LIKE ?
        ORDER BY s.updated_at DESC
        LIMIT ?
    """, (pattern, pattern, pattern, limit)).fetchall()

    results = []
    for row in rows:
        entities_data = safe_json_parse(row["entities"], {})
        results.append({
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "summary": row["summary"],
            "entities": entities_data.get("entities", []) if isinstance(entities_data, dict) else [],
            "decisions": entities_data.get("decisions", []) if isinstance(entities_data, dict) else [],
            "message_count": row["message_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })

    conn.close()
    return results


def get_recent_decisions(days: int = 7, limit: int = 20) -> List[Dict]:
    """Get decisions from recently archived/completed sessions."""
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    rows = conn.execute("""
        SELECT id, name, summary, entities, updated_at
        FROM sessions
        WHERE updated_at > ? AND summary IS NOT NULL
        ORDER BY updated_at DESC
        LIMIT ?
    """, (cutoff, limit)).fetchall()

    results = []
    for row in rows:
        entities_data = safe_json_parse(row["entities"], {})
        decisions = entities_data.get("decisions", []) if isinstance(entities_data, dict) else []
        if decisions or row["summary"]:
            results.append({
                "session_id": row["id"],
                "session_name": row["name"],
                "summary": row["summary"],
                "decisions": decisions,
                "topics": entities_data.get("topics", []) if isinstance(entities_data, dict) else [],
                "updated_at": row["updated_at"],
            })

    conn.close()
    return results


def get_entity_timeline(entity_name: str, limit: int = 20) -> List[Dict]:
    """Chronological entity mentions across sessions and messages."""
    conn = get_db()
    pattern = f"%{entity_name}%"

    # Get messages mentioning this entity
    rows = conn.execute("""
        SELECT m.id, m.session_id, m.role, m.content, m.created_at,
               s.name as session_name
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE m.content LIKE ?
        ORDER BY m.created_at DESC
        LIMIT ?
    """, (pattern, limit)).fetchall()

    timeline = []
    for row in rows:
        # Extract a snippet around the entity mention
        content = row["content"]
        lower_content = content.lower()
        idx = lower_content.find(entity_name.lower())
        if idx >= 0:
            start = max(0, idx - 80)
            end = min(len(content), idx + len(entity_name) + 80)
            snippet = ("…" if start > 0 else "") + content[start:end] + ("…" if end < len(content) else "")
        else:
            snippet = content[:160] + ("…" if len(content) > 160 else "")

        timeline.append({
            "message_id": row["id"],
            "session_id": row["session_id"],
            "session_name": row["session_name"],
            "role": row["role"],
            "snippet": snippet,
            "created_at": row["created_at"],
        })

    conn.close()
    return timeline


def get_session_detail(session_id: str, include_full: bool = False) -> Optional[Dict]:
    """Get full summary + entities for a session."""
    conn = get_db()

    row = conn.execute("""
        SELECT id, name, status, pinned, pillar, summary, entities,
               message_count, created_at, updated_at
        FROM sessions WHERE id = ?
    """, (session_id,)).fetchone()

    if not row:
        conn.close()
        return None

    entities_data = safe_json_parse(row["entities"], {})
    result = {
        "id": row["id"],
        "name": row["name"],
        "status": row["status"],
        "pinned": bool(row["pinned"]),
        "pillar": row["pillar"],
        "summary": row["summary"],
        "entities": entities_data.get("entities", []) if isinstance(entities_data, dict) else [],
        "decisions": entities_data.get("decisions", []) if isinstance(entities_data, dict) else [],
        "topics": entities_data.get("topics", []) if isinstance(entities_data, dict) else [],
        "message_count": row["message_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

    if include_full:
        # Include recent messages
        messages = conn.execute("""
            SELECT role, content, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT 20
        """, (session_id,)).fetchall()
        result["recent_messages"] = [
            {"role": m["role"], "content": m["content"][:500], "created_at": m["created_at"]}
            for m in reversed(messages)
        ]

    conn.close()
    return result


def search_observations_fts(query: str, obs_type: Optional[str] = None,
                            days: Optional[int] = None, limit: int = 20) -> List[Dict]:
    """Search observations via FTS5."""
    conn = get_db()
    results = []
    fts_query = query.replace("'", "").replace('"', '').strip()
    if not fts_query:
        conn.close()
        return results

    # Check if observations table exists
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='observations'"
    ).fetchone()
    if not tables:
        conn.close()
        return results

    conditions = ["observations_fts MATCH ?"]
    params: list = [fts_query]

    if obs_type:
        conditions.append("o.type = ?")
        params.append(obs_type)

    if days:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        conditions.append("o.timestamp > ?")
        params.append(cutoff)

    params.append(limit)
    where = " AND ".join(conditions)

    try:
        rows = conn.execute(f"""
            SELECT o.id, o.session_id, o.type, o.summary, o.entities,
                   o.tool_name, o.timestamp,
                   s.name as session_name,
                   snippet(observations_fts, 0, '«', '»', '…', 32) as snippet
            FROM observations_fts
            JOIN observations o ON o.rowid = observations_fts.rowid
            JOIN sessions s ON s.id = o.session_id
            WHERE {where}
            ORDER BY o.timestamp DESC
            LIMIT ?
        """, tuple(params)).fetchall()

        for row in rows:
            results.append({
                "id": row["id"],
                "session_id": row["session_id"],
                "session_name": row["session_name"],
                "type": row["type"],
                "summary": row["summary"],
                "entities": safe_json_parse(row["entities"], []),
                "tool_name": row["tool_name"],
                "snippet": row["snippet"],
                "timestamp": row["timestamp"],
            })
    except sqlite3.OperationalError:
        pass

    conn.close()
    return results


def get_observation_timeline_for_entity(entity_name: str, limit: int = 20) -> List[Dict]:
    """Get observations related to an entity, chronologically."""
    conn = get_db()
    results = []

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='observations'"
    ).fetchone()
    if not tables:
        conn.close()
        return results

    pattern = f"%{entity_name}%"
    rows = conn.execute("""
        SELECT o.id, o.session_id, o.type, o.summary, o.entities,
               o.tool_name, o.timestamp,
               s.name as session_name
        FROM observations o
        JOIN sessions s ON s.id = o.session_id
        WHERE o.summary LIKE ? OR o.entities LIKE ?
        ORDER BY o.timestamp DESC
        LIMIT ?
    """, (pattern, pattern, limit)).fetchall()

    for row in rows:
        results.append({
            "id": row["id"],
            "session_id": row["session_id"],
            "session_name": row["session_name"],
            "type": row["type"],
            "summary": row["summary"],
            "entities": safe_json_parse(row["entities"], []),
            "tool_name": row["tool_name"],
            "timestamp": row["timestamp"],
        })

    conn.close()
    return results


def get_recent_tool_usage(tool_name: Optional[str] = None,
                          days: int = 7, limit: int = 20) -> List[Dict]:
    """Get recent tool-use observations."""
    conn = get_db()
    results = []

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='observations'"
    ).fetchone()
    if not tables:
        conn.close()
        return results

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conditions = ["o.type = 'tool_call'", "o.timestamp > ?"]
    params: list = [cutoff]

    if tool_name:
        conditions.append("o.tool_name = ?")
        params.append(tool_name)

    params.append(limit)
    where = " AND ".join(conditions)

    rows = conn.execute(f"""
        SELECT o.id, o.session_id, o.type, o.summary, o.entities,
               o.tool_name, o.timestamp,
               s.name as session_name
        FROM observations o
        JOIN sessions s ON s.id = o.session_id
        WHERE {where}
        ORDER BY o.timestamp DESC
        LIMIT ?
    """, tuple(params)).fetchall()

    for row in rows:
        results.append({
            "id": row["id"],
            "session_id": row["session_id"],
            "session_name": row["session_name"],
            "summary": row["summary"],
            "entities": safe_json_parse(row["entities"], []),
            "tool_name": row["tool_name"],
            "timestamp": row["timestamp"],
        })

    conn.close()
    return results


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

app = Server("dex-session-memory")


@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_sessions",
            description=(
                "Search across Dex app conversation sessions and messages using full-text search. "
                "Progressive disclosure: default returns ~50 tokens/result (Layer 1: names + summaries). "
                "Add include_full=true for ~500 tokens/result (Layer 3: recent messages). "
                "Use include_messages=false for session-only search."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (keywords or phrases)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results per category (default 10)",
                        "default": 10
                    },
                    "include_messages": {
                        "type": "boolean",
                        "description": "Also search message content (default true)",
                        "default": True
                    },
                    "include_full": {
                        "type": "boolean",
                        "description": "Include recent messages for matched sessions (Layer 3, higher tokens)",
                        "default": False
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_session_context",
            description=(
                "Find all sessions that mention a specific entity (person, company, project). "
                "Returns session summaries, decisions, and entity lists. "
                "Use for cross-session awareness: 'What have I discussed about Acme Corp?'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "Name of the entity to search for (person, company, project)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max sessions to return (default 10)",
                        "default": 10
                    },
                },
                "required": ["entity_name"],
            },
        ),
        types.Tool(
            name="get_recent_decisions",
            description=(
                "Get decisions and summaries from recent conversation sessions. "
                "Useful for recalling what was decided recently without re-reading full conversations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Look back N days (default 7)",
                        "default": 7
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20
                    },
                },
            },
        ),
        types.Tool(
            name="get_entity_timeline",
            description=(
                "Get a chronological timeline of when an entity (person, company, project) was mentioned "
                "across conversation messages. Shows snippets with context around each mention."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Entity name to trace across conversations"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max timeline entries (default 20)",
                        "default": 20
                    },
                },
                "required": ["name"],
            },
        ),
        types.Tool(
            name="get_session_summary",
            description=(
                "Get full details for a specific session: summary, entities, decisions, topics. "
                "Layer 1 (default): ~100 tokens. Layer 3 (include_full=true): ~500 tokens with recent messages."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session UUID"
                    },
                    "include_full": {
                        "type": "boolean",
                        "description": "Include recent messages (Layer 3)",
                        "default": False
                    },
                },
                "required": ["session_id"],
            },
        ),
        types.Tool(
            name="search_observations",
            description=(
                "Search observations (tool calls, decisions, insights) logged during Dex app sessions. "
                "Observations capture what Dex actually did: files written, tasks created, decisions made."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for observation summaries"
                    },
                    "type": {
                        "type": "string",
                        "description": "Filter by type: tool_call, decision, artifact, insight",
                        "enum": ["tool_call", "decision", "artifact", "insight"]
                    },
                    "days": {
                        "type": "integer",
                        "description": "Look back N days (omit for all time)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_observation_timeline",
            description=(
                "Get a chronological timeline of observations related to an entity. "
                "Shows what Dex has done involving this person, company, or project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_name": {
                        "type": "string",
                        "description": "Entity name to trace"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entries (default 20)",
                        "default": 20
                    },
                },
                "required": ["entity_name"],
            },
        ),
        types.Tool(
            name="get_recent_tool_usage",
            description=(
                "See what tools Dex has used recently in the app. "
                "Useful for understanding what actions were taken and when."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Filter to a specific tool (e.g., 'Write', 'Edit'). Omit for all."
                    },
                    "days": {
                        "type": "integer",
                        "description": "Look back N days (default 7)",
                        "default": 7
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    args = arguments or {}

    try:
        if name == "search_sessions":
            query = args["query"]
            limit = args.get("limit", 10)
            include_messages = args.get("include_messages", True)
            include_full = args.get("include_full", False)
            results = search_sessions_fts(query, limit, include_messages)

            # Layer 3: enrich matched sessions with recent messages
            if include_full and results["sessions"]:
                for s in results["sessions"]:
                    detail = get_session_detail(s["id"], include_full=True)
                    if detail and "recent_messages" in detail:
                        s["recent_messages"] = detail["recent_messages"]

            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_session_context":
            entity_name = args["entity_name"]
            limit = args.get("limit", 10)
            results = get_session_context_for_entity(entity_name, limit)
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_recent_decisions":
            days = args.get("days", 7)
            limit = args.get("limit", 20)
            results = get_recent_decisions(days, limit)
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_entity_timeline":
            entity_name = args["name"]
            limit = args.get("limit", 20)
            results = get_entity_timeline(entity_name, limit)
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_session_summary":
            session_id = args["session_id"]
            include_full = args.get("include_full", False)
            result = get_session_detail(session_id, include_full)
            if not result:
                return [types.TextContent(type="text", text=json.dumps({"error": "Session not found"}))]
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "search_observations":
            query = args["query"]
            obs_type = args.get("type")
            days = args.get("days")
            limit = args.get("limit", 20)
            results = search_observations_fts(query, obs_type, days, limit)
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_observation_timeline":
            entity_name = args["entity_name"]
            limit = args.get("limit", 20)
            results = get_observation_timeline_for_entity(entity_name, limit)
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        elif name == "get_recent_tool_usage":
            tool_name = args.get("tool_name")
            days = args.get("days", 7)
            limit = args.get("limit", 20)
            results = get_recent_tool_usage(tool_name, days, limit)
            return [types.TextContent(type="text", text=json.dumps(results, indent=2))]

        else:
            return [types.TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except FileNotFoundError as e:
        return [types.TextContent(type="text", text=json.dumps({
            "error": str(e),
            "hint": "The Dex app creates this database. Start the app and have at least one conversation first."
        }))]
    except Exception as e:
        logger.error(f"Error in {name}: {e}")
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _main():
    logger.info("Starting Dex Session Memory MCP Server")
    logger.info(f"Vault path: {BASE_DIR}")
    logger.info(f"DB path: {DB_PATH}")
    logger.info(f"DB exists: {DB_PATH.exists()}")

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-session-memory",
                server_version="1.0.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main():
    import asyncio
    asyncio.run(_main())


if __name__ == "__main__":
    main()
