"""Reach Wispr Flow's remote MCP server from Dex, with or without a host.

This is the half that makes the credential worth holding. Wispr exposes its
meetings over MCP rather than REST, so Dex has to be an MCP *client* to read
them. Granola's adapter wraps an HTTP API; this one bridges one MCP endpoint to
callers that are not MCP clients themselves.

The public functions here are ordinary synchronous calls. That is deliberate:
a scheduled job, a test, or a skill must be able to fetch captures without an
MCP host in the loop, which is the entire difference between a source that
works unattended and one that only works while someone is signed in.

Batch through ``session()`` when making several calls. Each one-shot helper
opens and closes its own connection, which is fine for a single lookup and
wasteful for a sweep.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from core.meeting_sources.wispr_auth import RESOURCE, access_token

MCP_ENDPOINT = RESOURCE
REQUEST_TIMEOUT_SECONDS = 30


class WisprUnavailable(RuntimeError):
    """Wispr could not be reached or answered unusably.

    Deliberately distinct from "no meetings". A sweep that cannot reach the
    recorder must never be reported as a quiet week.
    """


@asynccontextmanager
async def session(vault_root: Path):
    """An initialised MCP session against Wispr. Refreshes the token first."""
    from mcp import ClientSession
    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

    token = access_token(vault_root)
    http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    try:
        async with streamable_http_client(MCP_ENDPOINT, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as client:
                await client.initialize()
                yield client
    except Exception as error:  # noqa: BLE001 - surfaced as one honest failure
        raise WisprUnavailable(f"Wispr could not be reached: {error}") from error


def _payload(result: Any) -> Any:
    """Unwrap an MCP tool result into plain data."""
    import json

    if not getattr(result, "content", None):
        return None
    text = getattr(result.content[0], "text", None)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def call_async(client: Any, tool: str, arguments: dict[str, Any] | None = None) -> Any:
    return _payload(await client.call_tool(tool, arguments or {}))


def call(vault_root: Path, tool: str, arguments: dict[str, Any] | None = None) -> Any:
    """One-shot synchronous tool call. Opens and closes its own connection."""

    async def run() -> Any:
        async with session(vault_root) as client:
            return await call_async(client, tool, arguments)

    return asyncio.run(run())


def batch(vault_root: Path, work) -> Any:
    """Run several calls over one connection.

    ``work`` is an async callable taking the session. Use this for sweeps: a
    per-call connection multiplies both latency and token refreshes.
    """

    async def run() -> Any:
        async with session(vault_root) as client:
            return await work(client)

    return asyncio.run(run())


def search_meetings(vault_root: Path, *, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
    """Newest first, paged.

    Note for callers: Wispr's ``since``/``until`` filters select on when a
    capture was last modified, not when the meeting happened. They answer "what
    changed", so they cannot build a catch-up window. Page and compare ``start``.
    """
    arguments: dict[str, Any] = {"limit": limit}
    if cursor:
        arguments["cursor"] = cursor
    result = call(vault_root, "search_meetings", arguments)
    if not isinstance(result, dict):
        raise WisprUnavailable("search_meetings returned an unexpected shape")
    return result


def get_meeting(vault_root: Path, meeting_id: str, *, with_transcript: bool = False) -> Any:
    arguments: dict[str, Any] = {"meeting_id": meeting_id}
    if with_transcript:
        arguments["view_transcript"] = {}
    return call(vault_root, "get_meeting", arguments)


def list_tools(vault_root: Path) -> list[str]:
    """Names of the tools Wispr currently exposes. Useful for setup checks."""

    async def run() -> list[str]:
        async with session(vault_root) as client:
            listed = await client.list_tools()
            return [tool.name for tool in listed.tools]

    return asyncio.run(run())
