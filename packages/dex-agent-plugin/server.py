#!/usr/bin/env python3
"""Small dependency-free stdio MCP bridge shipped in the Dex plugin.

The bridge keeps the package relocatable and exposes read-only capability
introspection. A host may layer the full Dex MCP servers beside this package;
the portable plugin never assumes a repository checkout or a host-specific
working directory.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "metadata" / "harnesses" / "registry.json"


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
        return _result(
            request_id,
            {
                "tools": [
                    {
                        "name": "dex_harness_profiles",
                        "description": "List the versioned, honest Dex harness descriptors.",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            },
        )
    if method == "tools/call":
        params = request.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        if name == "dex_harness_profiles":
            return _result(
                request_id,
                {"content": [{"type": "text", "text": json.dumps(_load_registry(), sort_keys=True)}]},
            )
        return _error(request_id, -32602, f"unknown tool: {name}")
    if method == "ping":
        return _result(request_id, {})
    if method in {"resources/list", "prompts/list"}:
        key = "resources" if method == "resources/list" else "prompts"
        return _result(request_id, {key: []})
    return _error(request_id, -32601, f"method not found: {method}")


def main() -> int:
    # PLUGIN_DATA is intentionally read only to prove the launcher receives
    # the Agent Plugins reserved variable; state is not written by this bridge.
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
