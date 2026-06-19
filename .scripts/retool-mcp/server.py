#!/usr/bin/env python3
"""Retool DB MCP server — email and calendar context for Dex."""

import json
import os
import sys
from datetime import datetime

import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("RETOOL_DB_URL")


def get_conn():
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


# ── MCP stdio protocol ────────────────────────────────────────────────────────

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def error_response(id_, code, message):
    send({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})


def ok(id_, result):
    send({"jsonrpc": "2.0", "id": id_, "result": result})


# ── Tool implementations ──────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_emails",
        "description": "Search important emails by keyword (subject or body), sender, or date range. Returns sender, subject, body preview, and received date.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword to search in subject or body preview"},
                "from_email": {"type": "string", "description": "Filter by sender email address (partial match)"},
                "days_back": {"type": "integer", "description": "Only return emails from the last N days (default: 30)"},
                "limit": {"type": "integer", "description": "Max results to return (default: 20)"},
            },
        },
    },
    {
        "name": "get_recent_emails",
        "description": "Get the most recent important emails, newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of emails to return (default: 10)"},
            },
        },
    },
    {
        "name": "get_emails_from_contact",
        "description": "Get all emails from a specific person or company domain.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "Email address, name, or domain (e.g. 'claire', 'prestige', 'prestigeequipment.com')"},
            },
            "required": ["contact"],
        },
    },
]


def search_emails(args):
    query = args.get("query", "")
    from_email = args.get("from_email", "")
    days_back = args.get("days_back", 30)
    limit = min(args.get("limit", 20), 50)

    conditions = [f"received_at > NOW() - INTERVAL '{days_back} days'", "from_email != ''"]
    params = []

    if query:
        conditions.append("(subject ILIKE %s OR body_preview ILIKE %s)")
        params += [f"%{query}%", f"%{query}%"]
    if from_email:
        conditions.append("from_email ILIKE %s")
        params.append(f"%{from_email}%")

    where = " AND ".join(conditions)
    sql = f"""
        SELECT from_email, from_name, subject, body_preview, received_at, priority, follow_up_note
        FROM important_emails
        WHERE {where}
        ORDER BY received_at DESC
        LIMIT %s
    """
    params.append(limit)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    return {"emails": [dict(r) for r in rows], "count": len(rows)}


def get_recent_emails(args):
    limit = min(args.get("limit", 10), 50)
    sql = """
        SELECT from_email, from_name, subject, body_preview, received_at, priority
        FROM important_emails
        WHERE from_email != ''
        ORDER BY received_at DESC
        LIMIT %s
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()

    return {"emails": [dict(r) for r in rows], "count": len(rows)}


def get_emails_from_contact(args):
    contact = args["contact"]
    sql = """
        SELECT from_email, from_name, subject, body_preview, received_at, priority, follow_up_note
        FROM important_emails
        WHERE from_email ILIKE %s OR from_name ILIKE %s
        ORDER BY received_at DESC
        LIMIT 50
    """
    pattern = f"%{contact}%"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (pattern, pattern))
            rows = cur.fetchall()

    return {"emails": [dict(r) for r in rows], "count": len(rows)}


TOOL_FNS = {
    "search_emails": search_emails,
    "get_recent_emails": get_recent_emails,
    "get_emails_from_contact": get_emails_from_contact,
}


# ── Main loop ─────────────────────────────────────────────────────────────────

def handle(msg):
    method = msg.get("method")
    id_ = msg.get("id")

    if method == "initialize":
        ok(id_, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "retool-email-mcp", "version": "1.0.0"},
        })

    elif method == "tools/list":
        ok(id_, {"tools": TOOLS})

    elif method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments", {})
        if name not in TOOL_FNS:
            error_response(id_, -32601, f"Unknown tool: {name}")
            return
        try:
            result = TOOL_FNS[name](args)
            # Serialize datetimes
            result_str = json.dumps(result, default=str)
            ok(id_, {"content": [{"type": "text", "text": result_str}]})
        except Exception as e:
            error_response(id_, -32603, str(e))

    elif method == "notifications/initialized":
        pass  # no response needed

    else:
        if id_ is not None:
            error_response(id_, -32601, f"Method not found: {method}")


def main():
    if not DB_URL:
        sys.stderr.write("RETOOL_DB_URL not set\n")
        sys.exit(1)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(msg)


if __name__ == "__main__":
    main()
