"""Behavior tests for MCP tool handlers."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
from pathlib import Path

import pytest


def _discover_server_modules() -> list[str]:
    mcp_dir = Path(__file__).resolve().parents[1] / "mcp"
    modules = [f"core.mcp.{path.stem}" for path in mcp_dir.glob("*_server.py")]
    modules.append("core.mcp.update_checker")
    return sorted(modules)


def _get_handler(module):
    for name in ("handle_call_tool", "call_tool", "_call_tool_inner"):
        fn = getattr(module, name, None)
        if callable(fn):
            return fn, name
    return None, None


def _render_payload(payload) -> str:
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        return " ".join(getattr(item, "text", str(item)) for item in payload)
    return json.dumps(payload, default=str)


@pytest.mark.parametrize("module_path", _discover_server_modules(), ids=lambda m: m.rsplit(".", 1)[-1])
def test_invalid_tool_call_returns_explicit_error(module_path: str):
    module = importlib.import_module(module_path)
    handler, handler_name = _get_handler(module)
    if handler is None:
        pytest.skip(f"{module_path} has no callable tool handler")

    signature = inspect.signature(handler)
    kwargs = {}
    if "name" in signature.parameters:
        kwargs["name"] = "__invalid_tool_name__"
    if "arguments" in signature.parameters:
        kwargs["arguments"] = {}
    if not kwargs:
        pytest.skip(f"{module_path}.{handler_name} has unsupported signature: {signature}")

    async def invoke():
        return await asyncio.wait_for(handler(**kwargs), timeout=5)

    keywords = ("invalid", "unknown", "not found", "unsupported", "error")

    try:
        result = asyncio.run(invoke())
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        assert message, f"{module_path}.{handler_name} raised without message"
        assert any(word in message for word in keywords), (
            f"{module_path}.{handler_name} raised non-explicit error: {exc}"
        )
        return

    rendered = _render_payload(result).lower()
    assert any(word in rendered for word in keywords), (
        f"{module_path}.{handler_name} returned non-explicit response for invalid tool call: {result!r}"
    )
