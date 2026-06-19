#!/usr/bin/env python3
"""
ICS Calendar MCP Server for Dex

Reads calendar events directly from an Outlook ICS URL.
No OAuth, no Google Cloud — just a URL.

Tools:
- calendar_list_calendars: List configured calendars
- calendar_get_today: Get today's events
- calendar_get_events: Get events for a date range
- calendar_get_next_event: Get the next upcoming event
- calendar_get_events_with_attendees: Get events with attendee details
"""

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests
from icalendar import Calendar

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

CALENDAR_ICS_URL = os.environ.get("CALENDAR_ICS_URL", "")

server = Server("ics-calendar-mcp")


def fetch_calendar() -> Calendar:
    if not CALENDAR_ICS_URL:
        raise ValueError("CALENDAR_ICS_URL environment variable not set")
    resp = requests.get(CALENDAR_ICS_URL, timeout=30)
    resp.raise_for_status()
    return Calendar.from_ical(resp.content)


def to_aware(dt) -> datetime:
    """Normalize a date or datetime to an aware UTC datetime."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    # date-only → treat as start of day UTC
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def event_to_dict(component) -> dict:
    summary = str(component.get("SUMMARY", "No Title"))
    dtstart = component.get("DTSTART")
    dtend = component.get("DTEND")
    location = str(component.get("LOCATION", ""))
    description = str(component.get("DESCRIPTION", ""))
    organizer = str(component.get("ORGANIZER", "")).replace("mailto:", "")

    start_dt = to_aware(dtstart.dt) if dtstart else None
    end_dt = to_aware(dtend.dt) if dtend else None

    attendees = []
    raw_attendees = component.get("ATTENDEE")
    if raw_attendees:
        if not isinstance(raw_attendees, list):
            raw_attendees = [raw_attendees]
        for a in raw_attendees:
            email = str(a).replace("mailto:", "")
            cn = a.params.get("CN", email) if hasattr(a, "params") else email
            attendees.append({"name": cn, "email": email})

    return {
        "title": summary,
        "start": start_dt.isoformat() if start_dt else None,
        "end": end_dt.isoformat() if end_dt else None,
        "location": location,
        "description": description[:500] if description else "",
        "organizer": organizer,
        "attendees": attendees,
    }


def get_events_in_range(start: datetime, end: datetime) -> list[dict]:
    cal = fetch_calendar()
    results = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        dtstart = component.get("DTSTART")
        if not dtstart:
            continue
        event_start = to_aware(dtstart.dt)
        if start <= event_start < end:
            results.append(event_to_dict(component))
    results.sort(key=lambda e: e["start"] or "")
    return results


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="calendar_list_calendars",
            description="List configured ICS calendars",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="calendar_get_today",
            description="Get today's calendar events",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_name": {"type": "string", "description": "Ignored, for API compatibility"}
                },
            },
        ),
        types.Tool(
            name="calendar_get_events",
            description="Get calendar events for a date range",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
                    "calendar_name": {"type": "string", "description": "Ignored, for API compatibility"},
                    "limit": {"type": "integer", "description": "Max events to return", "default": 50},
                },
            },
        ),
        types.Tool(
            name="calendar_get_next_event",
            description="Get the next upcoming event",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_name": {"type": "string", "description": "Ignored, for API compatibility"}
                },
            },
        ),
        types.Tool(
            name="calendar_get_events_with_attendees",
            description="Get events with full attendee details for a date range",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "Start date YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "End date YYYY-MM-DD"},
                },
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "calendar_list_calendars":
            result = {
                "success": True,
                "calendars": ["Work Calendar (Outlook ICS)"],
                "source": "ICS URL",
            }

        elif name == "calendar_get_today":
            now = datetime.now(timezone.utc)
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            events = get_events_in_range(start, end)
            result = {
                "success": True,
                "date": now.date().isoformat(),
                "events": events,
                "count": len(events),
            }

        elif name == "calendar_get_events":
            start_str = arguments.get("start_date", date.today().isoformat())
            end_str = arguments.get("end_date", (date.today() + timedelta(days=1)).isoformat())
            limit = arguments.get("limit", 50)
            start = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(end_str).replace(tzinfo=timezone.utc)
            events = get_events_in_range(start, end)[:limit]
            result = {"success": True, "events": events, "count": len(events)}

        elif name == "calendar_get_next_event":
            now = datetime.now(timezone.utc)
            end = now + timedelta(days=7)
            events = get_events_in_range(now, end)
            next_event = events[0] if events else None
            result = {"success": True, "event": next_event}

        elif name == "calendar_get_events_with_attendees":
            start_str = arguments.get("start_date", date.today().isoformat())
            end_str = arguments.get("end_date", (date.today() + timedelta(days=7)).isoformat())
            start = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(end_str).replace(tzinfo=timezone.utc)
            events = get_events_in_range(start, end)
            result = {"success": True, "events": events, "count": len(events)}

        else:
            result = {"success": False, "error": f"Unknown tool: {name}"}

    except Exception as e:
        result = {"success": False, "error": str(e)}

    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="ics-calendar-mcp",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
