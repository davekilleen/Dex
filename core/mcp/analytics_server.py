#!/usr/bin/env python3
"""
Dex Analytics MCP Server

Fires events to Pendo Track Events API for product analytics.
Privacy-first: Only fires when user has opted in via consent flow.

Usage:
    python analytics_server.py
"""

import json
import os
import sys
from importlib.util import find_spec

# Health system — error queue and health reporting
try:
    sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), '..', '..')))
    from core.utils.dex_logger import log_error as _log_health_error
    from core.utils.dex_logger import mark_healthy as _mark_healthy
    _HAS_HEALTH = True
except ImportError:
    _HAS_HEALTH = False
import logging
from pathlib import Path

# MCP SDK imports
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool
except ImportError:
    print("Error: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Import analytics helper (same directory)
sys.path.insert(0, str(Path(__file__).parent))
from analytics_helper import (
    check_consent,
    fire_event,
    get_analytics_transport,
    get_visitor_info,
    is_analytics_enabled,
    load_user_profile,
    mark_feature_used,
)

from core.utils.feature_status import feature_status

HAS_REQUESTS = find_spec("requests") is not None

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _meeting_processing_mode(value):
    """Return the configured mode from either supported profile shape."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("mode")
    return None


def _identify_delivery_response(delivery: dict) -> dict:
    """Map a failed or disabled identify attempt to its legacy-safe shape."""
    result = {
        "identified": delivery.get("fired", False),
        "reason": delivery.get("reason", "request_failed"),
        "receipt_written": delivery.get("receipt_written", False),
    }
    if "receipt_reason" in delivery:
        result["receipt_reason"] = delivery["receipt_reason"]
    return result


# Create MCP server
server = Server("dex-analytics")


@server.list_tools()
async def list_tools():
    """List available analytics tools."""
    return [
        Tool(
            name="track_event",
            description="Track a Dex usage event. Only fires if user has opted into analytics.",
            inputSchema={
                "type": "object",
                "properties": {
                    "event_name": {
                        "type": "string",
                        "description": "Event name (e.g., 'task_completed', 'daily_plan_completed')"
                    },
                    "properties": {
                        "type": "object",
                        "description": "Event properties (e.g., {skill_name: 'daily-plan'})",
                        "default": {}
                    }
                },
                "required": ["event_name"]
            }
        ),
        Tool(
            name="identify_user",
            description="Identify user in Pendo (called once during onboarding or session start).",
            inputSchema={
                "type": "object",
                "properties": {
                    "metadata": {
                        "type": "object",
                        "description": "User metadata (role, company_size, pillars_count, etc.)",
                        "default": {}
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="check_analytics_status",
            description="Check if analytics is enabled and configured correctly.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="mark_feature_used",
            description=(
                "Record that a Dex feature has been used, by ticking its box in "
                "System/usage_log.md. Local bookkeeping only: this writes to the vault and "
                "sends nothing, so it runs regardless of analytics consent. Call it when a "
                "skill completes, so /dex-level-up recommends features the user has not yet "
                "tried instead of ones they use daily."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "feature": {
                        "type": "string",
                        "description": (
                            "The feature to mark, identified by its slash command without the "
                            "leading slash (e.g. 'daily-plan'), or by its exact label in the log "
                            "(e.g. 'Person page created'). Ambiguous names are reported back "
                            "with the candidates rather than guessed at."
                        )
                    }
                },
                "required": ["feature"]
            }
        ),
        Tool(
            name="test_connection",
            description="Test Pendo connection with a test event.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    try:
        return await _call_tool_inner(name, arguments)
    except Exception as e:
        if _HAS_HEALTH:
            _log_health_error(
                source="dex-analytics",
                message=str(e),
                human_message=f"Analytics tool '{name}' failed",
                context={"tool": name}
            )
        raise

async def _call_tool_inner(name: str, arguments: dict) -> list[TextContent]:
    if name == "mark_feature_used":
        # Deliberately not consent-gated: nothing leaves the machine.
        result = mark_feature_used(arguments["feature"])
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "check_analytics_status":
        enabled = is_analytics_enabled()
        consent = check_consent()
        transport = get_analytics_transport()
        visitor_info = get_visitor_info()

        result = {
            "analytics_enabled": enabled,
            "consent_status": consent,
            "transport_mode": transport.get("mode"),
            "transport_endpoint": transport.get("endpoint"),
            "transport_configured": transport.get("configured", False),
            "transport_reason": transport.get("reason"),
            "requests_available": HAS_REQUESTS,
            "visitor_id": visitor_info['visitor_id'],
            "account_id": visitor_info['account_id'],
            "ready": enabled and transport.get("configured", False) and HAS_REQUESTS
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "track_event":
        event_name = arguments.get("event_name")
        properties = arguments.get("properties", {})

        if not event_name:
            delivery = fire_event(event_name)
            result = {
                "error": "event_name required",
                "receipt_written": delivery.get("receipt_written", False),
            }
            if "receipt_reason" in delivery:
                result["receipt_reason"] = delivery["receipt_reason"]
            return [TextContent(type="text", text=json.dumps(result))]

        # fire_event is the sole analytics-attempt route. It records one safe
        # local receipt whether delivery is disabled, unavailable, or successful.
        result = fire_event(event_name, properties)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "identify_user":
        metadata = arguments.get("metadata", {})

        try:
            analytics_enabled = is_analytics_enabled()
        except Exception:
            return [TextContent(
                type="text",
                text=json.dumps(_identify_delivery_response(fire_event("user_identified"))),
            )]

        if not analytics_enabled:
            # Keep the legacy identify_user response shape while still sending
            # every delivery outcome through fire_event's single receipt route.
            delivery = fire_event("user_identified")
            result = _identify_delivery_response(delivery)
            return [TextContent(type="text", text=json.dumps(result))]

        try:
            profile = load_user_profile()

            # Merge profile data with provided metadata.
            identify_props = {
                "role": profile.get("role", "unknown"),
                "role_group": profile.get("role_group", "unknown"),
                "company_size": profile.get("company_size", "unknown"),
                "pillars_count": len(profile.get("pillars", [])),
                "obsidian_enabled": profile.get("obsidian_mode", False),
                "granola_enabled": _meeting_processing_mode(profile.get("meeting_processing")) == "automatic",
                **metadata
            }
        except Exception:
            # The helper owns one normalized receipt even if the MCP's
            # optional profile enrichment cannot be prepared.
            return [TextContent(
                type="text",
                text=json.dumps(_identify_delivery_response(fire_event("user_identified"))),
            )]

        result = fire_event("user_identified", identify_props)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "test_connection":
        # The connection check is an ordinary analytics attempt: it must obey
        # consent and use the exact same receipt route as every other caller.
        result = fire_event("dex_analytics_test", _connection_test=True)
        reason = result.get("reason")
        if result.get("fired"):
            state = "ok"
            message = "Usage analytics connection check sent."
        elif reason == "requests_not_installed":
            state = "not_installed"
            message = "Usage analytics needs the request library installed."
        elif reason in {
            "analytics_disabled",
            "no_analytics_endpoint",
            "no_pendo_secret",
        }:
            state = "off"
            message = "Usage analytics is not ready to send a connection check."
        else:
            state = "broken"
            message = "Usage analytics could not send the connection check."
        payload = feature_status(
            "Usage analytics",
            state,
            message,
            reason=reason,
            receipt_written=result.get("receipt_written", False),
        )
        if "mode" in result:
            payload["transport_mode"] = result["mode"]
        if "receipt_reason" in result:
            payload["receipt_reason"] = result["receipt_reason"]
        return [TextContent(type="text", text=json.dumps(payload))]

    else:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


async def main():
    """Run the MCP server."""
    if _HAS_HEALTH:
        _mark_healthy("dex-analytics")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
