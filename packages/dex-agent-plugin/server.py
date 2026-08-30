#!/usr/bin/env python3
"""Dependency-free, read-only stdio MCP bridge shipped in the Dex plugin."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "metadata" / "harnesses" / "registry.json"
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from core.context.decision_record import ask_what_was_decided  # noqa: E402
from core.context.person_context import (  # noqa: E402
    ask_what_is_still_open_with_people,
    ask_who_is_in_todays_plan,
    ask_who_is_named_in_note,
    get_person_context,
)
from core.context.session_boot import build_session_boot  # noqa: E402
from core.gates.safety import evaluate_safety_gate  # noqa: E402


def _load_registry() -> dict[str, Any]:
    try:
        parsed = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "1.0.0", "profiles": []}
    return parsed if isinstance(parsed, dict) else {"schema_version": "1.0.0", "profiles": []}


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _vault(arguments: dict[str, Any]) -> Path:
    value = arguments.get("vault_path")
    if not isinstance(value, str) or not value.strip():
        value = os.environ.get("DEX_VAULT_PATH") or os.environ.get("VAULT_PATH")
    try:
        return Path(value).expanduser() if value else Path.cwd()
    except (OSError, TypeError, ValueError):
        return Path.cwd()


def _tool_result(request_id: Any, payload: Any) -> dict[str, Any]:
    return _result(
        request_id,
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, sort_keys=True, ensure_ascii=False),
                }
            ],
            "structuredContent": payload,
        },
    )


def _tools() -> list[dict[str, Any]]:
    vault = {
        "vault_path": {
            "type": "string",
            "description": "Dex vault root; defaults to DEX_VAULT_PATH, VAULT_PATH, or cwd.",
        }
    }
    return [
        {
            "name": "dex_harness_profiles",
            "description": "List the versioned, honest Dex harness descriptors.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "boot_today",
            "description": "Read today's pillars, goals, priorities, and urgent tasks.",
            "inputSchema": {"type": "object", "properties": vault},
        },
        {
            "name": "get_person_context",
            "description": "Read a person's role, company, last interaction, and open items.",
            "inputSchema": {
                "type": "object",
                "properties": {**vault, "name": {"type": "string"}},
                "required": ["name"],
            },
        },
        {
            "name": "ask_what_was_decided",
            "description": (
                "Answer what was decided about a topic, or what was decided "
                "lately with no topic, from this Dex folder's own decision "
                "record, including the file it came from."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {**vault, "topic": {"type": "string"}},
            },
        },
        {
            "name": "ask_what_is_still_open_with_people",
            "description": (
                "List every unchecked to-do from person pages, each naming "
                "the person and the page. Honest sentence if none."
            ),
            "inputSchema": {"type": "object", "properties": vault},
        },
        {
            "name": "ask_who_is_in_todays_plan",
            "description": (
                "Answer who is in today's plan: each named person's recorded "
                "role, company, last interaction, and every open item, each "
                "row naming the person page, in plan order. Missing field "
                "empty, never guessed."
            ),
            "inputSchema": {"type": "object", "properties": vault},
        },
        {
            "name": "ask_who_is_named_in_note",
            "description": (
                "Answer who is named in one note inside this Dex folder: "
                "each named person's recorded role, company, last "
                "interaction, and every open item, each row naming the "
                "person page, in the note's own order. Missing fields stay "
                "empty, never guessed. Refuses paths outside the folder."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    **vault,
                    "note_path": {
                        "type": "string",
                        "description": "A path inside the Dex folder",
                    },
                },
                "required": ["note_path"],
            },
        },
        {
            "name": "check_safety_gate",
            "description": "Check a proposed command or path before a harness executes it.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    **vault,
                    "tool_name": {"type": "string"},
                    "command": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
        },
    ]


def _handle(request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "dex-agent-plugin", "version": "1.0.0"},
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": _tools()})
    if method == "tools/call":
        params = request.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        raw_arguments = params.get("arguments") if isinstance(params, dict) else None
        arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
        if name == "dex_harness_profiles":
            return _tool_result(request_id, _load_registry())
        if name == "boot_today":
            return _tool_result(request_id, build_session_boot(_vault(arguments)))
        if name == "get_person_context":
            return _tool_result(
                request_id,
                get_person_context(_vault(arguments), arguments.get("name")),
            )
        if name == "ask_what_was_decided":
            return _tool_result(
                request_id,
                ask_what_was_decided(_vault(arguments), arguments.get("topic")),
            )
        if name == "ask_what_is_still_open_with_people":
            return _tool_result(
                request_id,
                ask_what_is_still_open_with_people(_vault(arguments)),
            )
        if name == "ask_who_is_in_todays_plan":
            return _tool_result(
                request_id,
                ask_who_is_in_todays_plan(_vault(arguments)),
            )
        if name == "ask_who_is_named_in_note":
            return _tool_result(
                request_id,
                ask_who_is_named_in_note(
                    _vault(arguments), arguments.get("note_path")
                ),
            )
        if name == "check_safety_gate":
            decision = evaluate_safety_gate(
                tool_name=arguments.get("tool_name"),
                command=arguments.get("command"),
                path=arguments.get("path"),
                vault=_vault(arguments),
            )
            return _tool_result(request_id, decision.as_payload())
        return _error(request_id, -32602, f"unknown tool: {name}")
    if method == "ping":
        return _result(request_id, {})
    if method in {"resources/list", "prompts/list"}:
        key = "resources" if method == "resources/list" else "prompts"
        return _result(request_id, {key: []})
    return _error(request_id, -32601, f"method not found: {method}")


def main() -> int:
    # Host data directories are intentionally read only; this bridge never
    # writes into plugin storage or a user's vault.
    os.environ.get("DEX_PLUGIN_DATA", "")
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(request, dict):
            continue
        response = _handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
