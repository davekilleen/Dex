#!/usr/bin/env python3
"""
Granola Meeting Notes MCP Server for Dex

Reads meeting data directly from Granola's local cache.
Provides access to meeting notes, transcripts, and action items.

Tools:
- granola_check_available: Check if Granola is installed and cache exists
- granola_get_recent_meetings: Get recent meetings
- granola_get_meeting_details: Get full details for a specific meeting
- granola_search_meetings: Search meetings by title or attendee
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Any

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Granola cache location
GRANOLA_CACHE = Path.home() / "Library" / "Application Support" / "Granola" / "cache-v3.json"

# Vault paths
VAULT_PATH = Path(os.environ.get('VAULT_PATH', Path.cwd()))

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Custom JSON encoder for handling date/datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


def read_granola_cache() -> Dict[str, Any]:
    """Read and parse Granola's local cache file."""
    if not GRANOLA_CACHE.exists():
        return None
    
    try:
        raw_data = GRANOLA_CACHE.read_text()
        cache_wrapper = json.loads(raw_data)
        
        # The cache has a nested structure: { cache: JSON_STRING }
        cache_data = json.loads(cache_wrapper.get('cache', '{}'))
        
        return {
            'documents': cache_data.get('state', {}).get('documents', {}),
            'transcripts': cache_data.get('state', {}).get('transcripts', {}),
            'people': cache_data.get('state', {}).get('people', {})
        }
    except Exception as e:
        logger.error(f"Error reading Granola cache: {e}")
        return None


def extract_meeting_info(doc: Dict[str, Any], transcripts: Dict[str, Any], meeting_id: str) -> Dict[str, Any]:
    """Extract relevant meeting information from a Granola document."""
    
    # Get transcript if available
    transcript_entries = transcripts.get(meeting_id, [])
    if transcript_entries:
        transcript = ' '.join(
            t.get('text', '') 
            for t in sorted(transcript_entries, key=lambda x: x.get('start_timestamp', ''))
        ).strip()
    else:
        transcript = None
    
    # Extract participants
    participants = []
    if doc.get('people', {}).get('attendees'):
        for attendee in doc['people']['attendees']:
            name = (
                attendee.get('details', {}).get('person', {}).get('name', {}).get('fullName') or
                attendee.get('name') or
                attendee.get('email')
            )
            if name:
                participants.append({
                    'name': name,
                    'email': attendee.get('email')
                })
    
    # Parse created_at
    created_at = doc.get('created_at', '')
    meeting_date = created_at.split('T')[0] if created_at else None
    
    return {
        'id': meeting_id,
        'title': doc.get('title', 'Untitled Meeting'),
        'date': meeting_date,
        'created_at': created_at,
        'notes': doc.get('notes_markdown', ''),
        'has_transcript': bool(transcript),
        'transcript_length': len(transcript) if transcript else 0,
        'participants': participants,
        'participant_count': len(participants)
    }


def get_meetings_from_cache(
    cache: Dict[str, Any],
    days_back: int = 7,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get meetings from cache within the specified time range."""
    
    cutoff_date = datetime.now() - timedelta(days=days_back)
    meetings = []
    
    for meeting_id, doc in cache['documents'].items():
        # Skip non-meeting documents
        if doc.get('type') != 'meeting':
            continue
        
        # Skip deleted documents
        if doc.get('deleted_at'):
            continue
        
        # Check date cutoff
        created_at = doc.get('created_at', '')
        if created_at:
            try:
                meeting_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                if meeting_date.replace(tzinfo=None) < cutoff_date:
                    continue
            except:
                pass
        
        meeting_info = extract_meeting_info(doc, cache['transcripts'], meeting_id)
        meetings.append(meeting_info)
    
    # Sort by date descending
    meetings.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    return meetings[:limit]


def get_meeting_by_id(cache: Dict[str, Any], meeting_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed meeting information by ID."""
    
    doc = cache['documents'].get(meeting_id)
    if not doc:
        return None
    
    info = extract_meeting_info(doc, cache['transcripts'], meeting_id)
    
    # Add full transcript for detail view
    transcript_entries = cache['transcripts'].get(meeting_id, [])
    if transcript_entries:
        info['transcript'] = ' '.join(
            t.get('text', '') 
            for t in sorted(transcript_entries, key=lambda x: x.get('start_timestamp', ''))
        ).strip()
    
    # Add action items if present in notes
    notes = doc.get('notes_markdown', '')
    action_items = []
    for line in notes.split('\n'):
        line = line.strip()
        if line.startswith('- [ ]') or line.startswith('* [ ]'):
            action_items.append(line[5:].strip())
    
    info['action_items'] = action_items
    
    return info


def search_meetings(
    cache: Dict[str, Any],
    query: str,
    days_back: int = 30,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Search meetings by title, notes, or participant names."""
    
    query_lower = query.lower()
    cutoff_date = datetime.now() - timedelta(days=days_back)
    results = []
    
    for meeting_id, doc in cache['documents'].items():
        # Skip non-meeting documents
        if doc.get('type') != 'meeting':
            continue
        
        # Skip deleted documents
        if doc.get('deleted_at'):
            continue
        
        # Check date cutoff
        created_at = doc.get('created_at', '')
        if created_at:
            try:
                meeting_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                if meeting_date.replace(tzinfo=None) < cutoff_date:
                    continue
            except:
                pass
        
        # Search in title
        title = doc.get('title', '').lower()
        if query_lower in title:
            results.append(extract_meeting_info(doc, cache['transcripts'], meeting_id))
            continue
        
        # Search in notes
        notes = doc.get('notes_markdown', '').lower()
        if query_lower in notes:
            results.append(extract_meeting_info(doc, cache['transcripts'], meeting_id))
            continue
        
        # Search in participant names
        attendees = doc.get('people', {}).get('attendees', [])
        for attendee in attendees:
            name = (
                attendee.get('details', {}).get('person', {}).get('name', {}).get('fullName', '') or
                attendee.get('name', '') or
                attendee.get('email', '')
            ).lower()
            if query_lower in name:
                results.append(extract_meeting_info(doc, cache['transcripts'], meeting_id))
                break
    
    # Sort by date descending
    results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    return results[:limit]


# Initialize the MCP server
app = Server("dex-granola-mcp")


@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available Granola tools"""
    return [
        types.Tool(
            name="granola_check_available",
            description="Check if Granola is installed and cache exists",
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
        )
    ]


@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    
    arguments = arguments or {}
    
    if name == "granola_check_available":
        cache_exists = GRANOLA_CACHE.exists()
        
        result = {
            "available": cache_exists,
            "cache_path": str(GRANOLA_CACHE),
            "message": "Granola cache found" if cache_exists else "Granola cache not found. Is Granola installed?"
        }
        
        if cache_exists:
            cache = read_granola_cache()
            if cache:
                result["meetings_count"] = len(cache.get('documents', {}))
                result["last_modified"] = datetime.fromtimestamp(
                    GRANOLA_CACHE.stat().st_mtime
                ).isoformat()
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "granola_get_recent_meetings":
        cache = read_granola_cache()
        
        if not cache:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "Granola cache not found or could not be read"
            }, indent=2))]
        
        days_back = arguments.get("days_back", 7)
        limit = arguments.get("limit", 20)
        
        meetings = get_meetings_from_cache(cache, days_back, limit)
        
        result = {
            "success": True,
            "meetings": meetings,
            "count": len(meetings),
            "days_back": days_back
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "granola_get_meeting_details":
        meeting_id = arguments.get("meeting_id")
        
        if not meeting_id:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "meeting_id is required"
            }, indent=2))]
        
        cache = read_granola_cache()
        
        if not cache:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "Granola cache not found or could not be read"
            }, indent=2))]
        
        meeting = get_meeting_by_id(cache, meeting_id)
        
        if not meeting:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Meeting not found: {meeting_id}"
            }, indent=2))]
        
        result = {
            "success": True,
            "meeting": meeting
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "granola_search_meetings":
        query = arguments.get("query")
        
        if not query:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "query is required"
            }, indent=2))]
        
        cache = read_granola_cache()
        
        if not cache:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "Granola cache not found or could not be read"
            }, indent=2))]
        
        days_back = arguments.get("days_back", 30)
        limit = arguments.get("limit", 10)
        
        meetings = search_meetings(cache, query, days_back, limit)
        
        result = {
            "success": True,
            "query": query,
            "meetings": meetings,
            "count": len(meetings)
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "granola_get_today_meetings":
        cache = read_granola_cache()
        
        if not cache:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "Granola cache not found or could not be read"
            }, indent=2))]
        
        today = datetime.now().strftime("%Y-%m-%d")
        meetings = []
        
        for meeting_id, doc in cache['documents'].items():
            if doc.get('type') != 'meeting':
                continue
            if doc.get('deleted_at'):
                continue
            
            created_at = doc.get('created_at', '')
            meeting_date = created_at.split('T')[0] if created_at else None
            
            if meeting_date == today:
                meetings.append(extract_meeting_info(doc, cache['transcripts'], meeting_id))
        
        # Sort by time
        meetings.sort(key=lambda x: x.get('created_at', ''))
        
        result = {
            "success": True,
            "date": today,
            "meetings": meetings,
            "count": len(meetings)
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    else:
        return [types.TextContent(type="text", text=json.dumps({
            "error": f"Unknown tool: {name}"
        }, indent=2))]


async def _main():
    """Async main entry point for the MCP server"""
    logger.info("Starting Dex Granola MCP Server")
    logger.info(f"Granola cache path: {GRANOLA_CACHE}")
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-granola-mcp",
                server_version="1.0.0",
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
