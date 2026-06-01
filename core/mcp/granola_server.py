#!/usr/bin/env python3
"""
Granola Meeting Notes MCP Server for Dex

Data source: Granola's official public REST API (https://public-api.granola.ai).

Authentication uses a Granola API key (format grn_...), created on a Granola
Business/Enterprise plan. The key is read from the GRANOLA_API_KEY environment
variable, or from a .env file at the vault root (VAULT_ROOT) if not set in the
environment. There is NO local-file fallback — the official API is the only
data source. If no key is configured, tools return a friendly "not connected"
message instead of erroring.

API shape:
- LIST:   GET /v1/notes (cursor pagination; list items have no summary/attendees/transcript)
- DETAIL: GET /v1/notes/{note_id}?include=transcript (full summary, attendees, transcript)

Tools (interface unchanged):
- granola_check_available: Check if the Granola API is connected and reachable
- granola_get_recent_meetings: Get recent meetings
- granola_get_meeting_details: Get full details for a specific meeting (incl. transcript)
- granola_search_meetings: Search meetings by title or attendee
- granola_get_today_meetings: Get today's meetings
- granola_get_extent: Get the date range and summary stats of available data
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# ============================================================================
# CONFIGURATION
# ============================================================================

API_BASE_URL = "https://public-api.granola.ai"

# Vault paths
VAULT_PATH = Path(os.environ.get("VAULT_PATH", Path.cwd()))

# Friendly message shown when no API key is configured (shared convention).
NOT_CONNECTED_MESSAGE = (
    "Granola not connected — run /granola-setup to add your Granola API key "
    "(requires a Granola Business plan)."
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Response cache to avoid hammering the API (5 min TTL)
_response_cache: Dict[str, Any] = {}
_cache_ttl = 300  # 5 minutes


# Custom JSON encoder for handling date/datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


# ============================================================================
# API KEY RESOLUTION
# ============================================================================


def _vault_root() -> Path:
    """Resolve the vault root for locating a .env file."""
    return Path(os.environ.get("VAULT_ROOT") or os.environ.get("VAULT_PATH") or Path.cwd())


def _read_key_from_env_file() -> Optional[str]:
    """Parse GRANOLA_API_KEY=... from a .env file at the vault root, if present."""
    env_path = _vault_root() / ".env"
    if not env_path.exists():
        return None

    try:
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() != "GRANOLA_API_KEY":
                continue
            value = value.strip()
            # Strip surrounding quotes if present.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            return value or None
    except Exception as e:
        logger.warning(f"Error reading .env file: {e}")

    return None


def get_api_key() -> Optional[str]:
    """Resolve the Granola API key from the environment, then a .env at VAULT_ROOT."""
    key = os.environ.get("GRANOLA_API_KEY")
    if key:
        return key.strip() or None
    return _read_key_from_env_file()


# ============================================================================
# OFFICIAL PUBLIC API CLIENT
# ============================================================================


def _api_get(path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    GET a JSON resource from the Granola public API.

    Returns the parsed JSON dict, or None on failure / missing key. Retries once
    on HTTP 429 with a short backoff (rate limits are undocumented; be gentle).
    """
    key = get_api_key()
    if not key:
        return None

    query = ""
    if params:
        # Drop None values, stringify the rest.
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            query = "?" + urllib.parse.urlencode(clean)

    url = f"{API_BASE_URL}{path}{query}"

    # Response cache check.
    cache_key = url
    if cache_key in _response_cache:
        cached_time, cached_response = _response_cache[cache_key]
        if time.time() - cached_time < _cache_ttl:
            logger.debug(f"Using cached response for {url}")
            return cached_response

    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    for attempt in range(2):  # initial try + one retry on 429
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = response.read().decode("utf-8")
                result = json.loads(payload) if payload else {}
                _response_cache[cache_key] = (time.time(), result)
                logger.debug(f"API request successful: {url}")
                return result
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                logger.warning("API rate limited (429), retrying after backoff")
                time.sleep(1.5)
                continue
            if e.code == 401:
                logger.warning("API auth failed (401) — Granola API key may be invalid")
            else:
                body = ""
                try:
                    body = e.read().decode("utf-8")[:200]
                except Exception:
                    pass
                logger.warning(f"API returned {e.code}: {body}")
            return None
        except urllib.error.URLError as e:
            logger.warning(f"API request failed: {e}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error calling API: {e}")
            return None

    return None


def _iter_note_pages(params: Dict[str, Any]):
    """
    Yield each page (list of note summaries) from GET /v1/notes, following the
    cursor until hasMore is false. `params` is the base query (created_after,
    page_size, etc.); the cursor is managed here.
    """
    cursor: Optional[str] = None
    while True:
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        response = _api_get("/v1/notes", page_params)
        if not response:
            return
        notes = response.get("notes", []) or []
        yield notes
        if not response.get("hasMore"):
            return
        cursor = response.get("cursor")
        if not cursor:
            return


def _list_notes(
    created_after: Optional[str] = None,
    max_notes: int = 1000,
    page_size: int = 30,
) -> List[Dict[str, Any]]:
    """
    List note summaries via cursor pagination, oldest filter applied server-side
    where possible. Stops once max_notes are collected.
    """
    params: Dict[str, Any] = {"page_size": max(1, min(page_size, 30))}
    if created_after:
        params["created_after"] = created_after

    collected: List[Dict[str, Any]] = []
    for page in _iter_note_pages(params):
        collected.extend(page)
        if len(collected) >= max_notes:
            return collected[:max_notes]
    return collected


def _get_note_detail(note_id: str, include_transcript: bool = True) -> Optional[Dict[str, Any]]:
    """Fetch a single note's full detail (and transcript) from the API."""
    params = {"include": "transcript"} if include_transcript else None
    return _api_get(f"/v1/notes/{note_id}", params)


# ============================================================================
# DATE HELPERS
# ============================================================================


def _parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO timestamp into a timezone-aware datetime (UTC if naive)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _cutoff_iso(days_back: int) -> str:
    """Return an ISO datetime `days_back` days ago (UTC), for created_after."""
    return (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()


def _date_only(value: str) -> Optional[str]:
    """Extract the YYYY-MM-DD date portion from an ISO timestamp."""
    if not value:
        return None
    return value.split("T")[0]


# ============================================================================
# NORMALIZATION
# ============================================================================


def _attendees_from_detail(detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build a participant list from a note detail's attendees array."""
    participants = []
    for attendee in detail.get("attendees", []) or []:
        name = attendee.get("name") or attendee.get("email")
        if name:
            participants.append(
                {"name": name, "email": attendee.get("email")}
            )
    return participants


def _summary_from_list_item(note: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a list-view note summary into the standardized meeting info shape.

    List items contain no summary/attendees/transcript, so those fields are empty
    here. Use _meeting_info_from_detail for the full record.
    """
    created_at = note.get("created_at", "") or ""
    return {
        "id": note.get("id", ""),
        "title": note.get("title") or "Untitled Meeting",
        "date": _date_only(created_at),
        "created_at": created_at,
        "updated_at": note.get("updated_at", ""),
        "notes": "",
        "has_transcript": False,
        "transcript_length": 0,
        "participants": [],
        "participant_count": 0,
        "source": "api",
    }


def _meeting_info_from_detail(detail: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a full note detail into the standardized meeting info shape."""
    created_at = detail.get("created_at", "") or ""
    participants = _attendees_from_detail(detail)

    # Prefer markdown summary, fall back to plain text summary.
    notes = detail.get("summary_markdown") or detail.get("summary_text") or ""

    # Flatten the transcript (list of speaker turns) into a single string.
    transcript_text = ""
    transcript = detail.get("transcript")
    if isinstance(transcript, list) and transcript:
        transcript_text = " ".join(
            (turn.get("text") or "").strip()
            for turn in transcript
            if isinstance(turn, dict) and turn.get("text")
        ).strip()

    # Action items: checkbox lines in the markdown summary.
    action_items = []
    for line in notes.split("\n"):
        line = line.strip()
        if line.startswith("- [ ]") or line.startswith("* [ ]"):
            action_items.append(line[5:].strip())

    return {
        "id": detail.get("id", ""),
        "title": detail.get("title") or "Untitled Meeting",
        "date": _date_only(created_at),
        "created_at": created_at,
        "updated_at": detail.get("updated_at", ""),
        "web_url": detail.get("web_url"),
        "notes": notes,
        "has_transcript": bool(transcript_text),
        "transcript_length": len(transcript_text),
        "transcript": transcript_text,
        "participants": participants,
        "participant_count": len(participants),
        "action_items": action_items,
        "source": "api",
    }


# ============================================================================
# HIGH-LEVEL DATA FUNCTIONS
# ============================================================================


def get_recent_meetings(days_back: int = 7, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Get recent meetings via the public API.

    Lists note summaries within the date window. NOTE: list items contain no
    attendees, so participant data is only populated by detail fetches (used by
    get_meeting_details and get_extent, which enrich per note).
    """
    logger.info(f"Fetching recent meetings (days_back={days_back}, limit={limit})")
    notes = _list_notes(created_after=_cutoff_iso(days_back), max_notes=max(limit, 1))
    meetings = [_summary_from_list_item(n) for n in notes]
    meetings.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return meetings[:limit]


def get_meeting_details(meeting_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed meeting information (incl. transcript) by ID via the API."""
    logger.info(f"Fetching details for meeting {meeting_id}")
    detail = _get_note_detail(meeting_id, include_transcript=True)
    if not detail:
        logger.warning(f"Meeting {meeting_id} not found via API")
        return None
    return _meeting_info_from_detail(detail)


def search_meetings(query: str, days_back: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Search meetings by title or participant name via the API.

    The public API has no full-text search endpoint, so this lists notes in the
    window, matches titles directly, then fetches detail for unmatched notes to
    match on attendees and summary. Detail fetches are sequential and bounded.
    """
    logger.info(f"Searching meetings for '{query}' (days_back={days_back}, limit={limit})")
    query_lower = query.lower()
    notes = _list_notes(created_after=_cutoff_iso(days_back), max_notes=1000)

    results: List[Dict[str, Any]] = []

    # First pass: cheap title matches from the list view.
    title_matched_ids = set()
    unmatched: List[Dict[str, Any]] = []
    for note in notes:
        title = (note.get("title") or "").lower()
        if query_lower in title:
            results.append(_summary_from_list_item(note))
            title_matched_ids.add(note.get("id"))
        else:
            unmatched.append(note)

    # Second pass: enrich unmatched notes with detail to match attendees/summary.
    # Bounded so we don't fetch the whole history for a broad query.
    detail_budget = max(limit * 5, 25)
    for note in unmatched:
        if len(results) >= limit or detail_budget <= 0:
            break
        note_id = note.get("id")
        if not note_id:
            continue
        detail_budget -= 1
        detail = _get_note_detail(note_id, include_transcript=False)
        if not detail:
            continue

        matched = False
        for attendee in detail.get("attendees", []) or []:
            name = (attendee.get("name") or attendee.get("email") or "").lower()
            if name and query_lower in name:
                matched = True
                break
        if not matched:
            summary = (detail.get("summary_markdown") or detail.get("summary_text") or "").lower()
            if summary and query_lower in summary:
                matched = True

        if matched:
            results.append(_meeting_info_from_detail(detail))

    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results[:limit]


# Initialize the MCP server
app = Server("dex-granola-mcp")


@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available Granola tools"""
    return [
        types.Tool(
            name="granola_check_available",
            description="Check if the Granola API is connected and reachable",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="granola_get_recent_meetings",
            description="Get recent meetings from Granola",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": "How many days back to look (default: 7)",
                        "default": 7
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum meetings to return (default: 20)",
                        "default": 20
                    }
                }
            }
        ),
        types.Tool(
            name="granola_get_meeting_details",
            description="Get full details for a specific meeting including transcript",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_id": {
                        "type": "string",
                        "description": "The meeting ID from Granola"
                    }
                },
                "required": ["meeting_id"]
            }
        ),
        types.Tool(
            name="granola_search_meetings",
            description="Search meetings by title, notes, or participant name",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term"
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "How many days back to search (default: 30)",
                        "default": 30
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return (default: 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="granola_get_today_meetings",
            description="Get today's meetings from Granola",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="granola_get_extent",
            description="Get the date range and summary stats of available Granola data (optimized for quick discovery). Defaults to 6 months for speed, set extended=true for up to 2 years.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_email_domain": {
                        "type": "string",
                        "description": "User's company email domain(s) for internal/external classification (comma-separated if multiple)",
                        "default": ""
                    },
                    "extended": {
                        "type": "boolean",
                        "description": "If true, fetch up to 2 years of data. If false (default), fetch 6 months for faster results.",
                        "default": False
                    }
                }
            }
        )
    ]


def _not_connected_response() -> list[types.TextContent]:
    """Standard payload returned by every tool when no API key is configured."""
    return [types.TextContent(type="text", text=json.dumps({
        "success": False,
        "connected": False,
        "message": NOT_CONNECTED_MESSAGE
    }, indent=2))]


@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""

    arguments = arguments or {}

    # Validate the tool name first, so an unknown tool always returns an explicit
    # error, even when no API key is configured.
    valid_tools = {
        "granola_check_available",
        "granola_get_recent_meetings",
        "granola_get_meeting_details",
        "granola_search_meetings",
        "granola_get_today_meetings",
        "granola_get_extent",
    }
    if name not in valid_tools:
        return [types.TextContent(type="text", text=json.dumps({
            "error": f"Unknown tool: {name}"
        }, indent=2))]

    # Every tool requires a configured API key. If absent, return the friendly
    # not-connected message rather than erroring.
    if not get_api_key():
        return _not_connected_response()

    if name == "granola_check_available":
        # Quick reachability test — fetch a single note page.
        test_response = _api_get("/v1/notes", {"page_size": 1})
        api_available = test_response is not None

        result = {
            "available": api_available,
            "connected": True,
            "api": {
                "base_url": API_BASE_URL,
                "status": "ready" if api_available else "unavailable"
            },
            "data_source": "official_api",
            "message": (
                "Granola API connected and reachable" if api_available else
                "Granola API key configured but the API is not reachable "
                "(check the key is valid and you have a Granola Business plan)."
            )
        }

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "granola_get_recent_meetings":
        days_back = arguments.get("days_back", 7)
        limit = arguments.get("limit", 20)

        meetings = get_recent_meetings(days_back, limit)

        if not meetings:
            return [types.TextContent(type="text", text=json.dumps({
                "success": True,
                "meetings": [],
                "count": 0,
                "days_back": days_back,
                "data_source": "official_api"
            }, indent=2))]

        result = {
            "success": True,
            "meetings": meetings,
            "count": len(meetings),
            "days_back": days_back,
            "data_source": "official_api"
        }

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    elif name == "granola_get_meeting_details":
        meeting_id = arguments.get("meeting_id")

        if not meeting_id:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "meeting_id is required"
            }, indent=2))]

        meeting = get_meeting_details(meeting_id)

        if not meeting:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Meeting not found: {meeting_id}"
            }, indent=2))]

        result = {
            "success": True,
            "meeting": meeting,
            "data_source": "official_api"
        }

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    elif name == "granola_search_meetings":
        query = arguments.get("query")

        if not query:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "query is required"
            }, indent=2))]

        days_back = arguments.get("days_back", 30)
        limit = arguments.get("limit", 10)

        meetings = search_meetings(query, days_back, limit)

        result = {
            "success": True,
            "query": query,
            "meetings": meetings,
            "count": len(meetings),
            "data_source": "official_api"
        }

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    elif name == "granola_get_today_meetings":
        # Get meetings from the last 1 day, then filter to today.
        meetings = get_recent_meetings(days_back=1, limit=50)

        today = datetime.now().strftime("%Y-%m-%d")
        today_meetings = [
            m for m in meetings
            if m.get("date") == today
        ]

        today_meetings.sort(key=lambda x: x.get("created_at", ""))

        result = {
            "success": True,
            "date": today,
            "meetings": today_meetings,
            "count": len(today_meetings),
            "data_source": "official_api"
        }

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    elif name == "granola_get_extent":
        user_email_domain = arguments.get("user_email_domain", "")
        extended = arguments.get("extended", False)

        # Default to 6 months for speed, optionally extend to 2 years.
        days_to_fetch = 365 * 2 if extended else 180
        notes = _list_notes(created_after=_cutoff_iso(days_to_fetch), max_notes=1000)

        if not notes:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "No meetings found",
                "has_data": False
            }, indent=2))]

        meetings = [_summary_from_list_item(n) for n in notes]

        # People/company stats require attendees, which only appear in detail.
        # Enrich a bounded number of notes so discovery stays fast.
        enrich_budget = min(len(notes), 150)
        for note in notes[:enrich_budget]:
            note_id = note.get("id")
            if not note_id:
                continue
            detail = _get_note_detail(note_id, include_transcript=False)
            if not detail:
                continue
            participants = _attendees_from_detail(detail)
            for meeting in meetings:
                if meeting["id"] == note_id:
                    meeting["participants"] = participants
                    meeting["participant_count"] = len(participants)
                    break

        # Find oldest and newest dates.
        dates = [m["date"] for m in meetings if m.get("date")]
        if not dates:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "has_data": False,
                "meetings_count": 0
            }, indent=2))]

        oldest = min(dates)
        newest = max(dates)

        # Calculate days back.
        oldest_dt = datetime.fromisoformat(oldest)
        newest_dt = datetime.fromisoformat(newest)
        days_back = (newest_dt - oldest_dt).days + 1

        # Extract unique people and companies.
        people = set()
        internal_people = set()
        external_people = set()
        companies = set()

        # Normalize user domain for comparison.
        user_domains = [d.strip().lower() for d in user_email_domain.split(",")] if user_email_domain else []

        for meeting in meetings:
            for participant in meeting.get("participants", []):
                name = participant.get("name")
                email = participant.get("email")

                if name:
                    people.add(name)

                    if email and "@" in email:
                        domain = email.split("@")[1].lower()

                        # Classify as internal or external.
                        if user_domains and any(d in domain or domain in d for d in user_domains):
                            internal_people.add(name)
                        else:
                            external_people.add(name)
                            companies.add(domain)
                    else:
                        # No email provided - default to external.
                        external_people.add(name)

        # Calculate meetings in different time ranges.
        now = datetime.now()
        meetings_7d = sum(1 for m in meetings if m.get("date") and
                          (now - datetime.fromisoformat(m["date"])).days <= 7)
        meetings_30d = sum(1 for m in meetings if m.get("date") and
                           (now - datetime.fromisoformat(m["date"])).days <= 30)
        meetings_90d = sum(1 for m in meetings if m.get("date") and
                           (now - datetime.fromisoformat(m["date"])).days <= 90)

        # Check if there might be more data beyond what we fetched.
        has_more = False
        if not extended:
            if len(meetings) >= 900 or days_back >= 175:
                has_more = True

        result = {
            "success": True,
            "has_data": True,
            "meetings_count": len(meetings),
            "days_back": days_back,
            "oldest_date": oldest,
            "newest_date": newest,
            "unique_people": len(people),
            "internal_people": len(internal_people),
            "external_people": len(external_people),
            "unique_companies": len(companies),
            "people_sample": list(people)[:10],
            "companies_list": sorted(list(companies)),
            "meetings_7d": meetings_7d,
            "meetings_30d": meetings_30d,
            "meetings_90d": meetings_90d,
            "has_more_data": has_more,
            "fetched_range_days": days_to_fetch,
            "people_enriched": enrich_budget,
            "data_source": "official_api"
        }

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    else:
        return [types.TextContent(type="text", text=json.dumps({
            "error": f"Unknown tool: {name}"
        }, indent=2))]


async def _main():
    """Async main entry point for the MCP server"""
    logger.info("Starting Dex Granola MCP Server (official public API)")
    logger.info(f"API base URL: {API_BASE_URL}")
    if not get_api_key():
        logger.info(NOT_CONNECTED_MESSAGE)

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-granola-mcp",
                server_version="3.0.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main():
    """Sync entry point for console script"""
    import asyncio
    asyncio.run(_main())


if __name__ == "__main__":
    main()
