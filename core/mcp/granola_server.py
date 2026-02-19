#!/usr/bin/env python3
"""
Granola Meeting Notes MCP Server for Dex

Primary: Uses Granola's unofficial API for complete data
Fallback: Reads from local cache if API fails
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
import platform
import re
import requests
import time
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional, Dict, List, Any

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Analytics helper (optional - gracefully degrade if not available)
try:
    from analytics_helper import fire_event as _fire_analytics_event
    HAS_ANALYTICS = True
except ImportError:
    HAS_ANALYTICS = False
    def _fire_analytics_event(event_name, properties=None):
        return {'fired': False, 'reason': 'analytics_not_available'}

# Granola paths (cross-platform)
def get_granola_cache_path():
    """Get Granola cache path for current OS"""
    system = platform.system()
    home = Path.home()
    
    if system == "Darwin":  # macOS
        return home / "Library" / "Application Support" / "Granola" / "cache-v3.json"
    elif system == "Windows":
        # Try AppData\Roaming first, then Local
        roaming = Path(os.environ.get('APPDATA', home / 'AppData' / 'Roaming'))
        local = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
        
        for base_path in [roaming, local]:
            cache_path = base_path / "Granola" / "cache-v3.json"
            if cache_path.exists():
                return cache_path
        
        # Default to Roaming if neither exists
        return roaming / "Granola" / "cache-v3.json"
    else:  # Linux or other
        return home / ".config" / "Granola" / "cache-v3.json"

def get_granola_creds_path():
    """Get Granola credentials path for current OS"""
    system = platform.system()
    home = Path.home()
    
    if system == "Darwin":  # macOS
        return home / "Library" / "Application Support" / "Granola" / "supabase.json"
    elif system == "Windows":
        roaming = Path(os.environ.get('APPDATA', home / 'AppData' / 'Roaming'))
        local = Path(os.environ.get('LOCALAPPDATA', home / 'AppData' / 'Local'))
        
        for base_path in [roaming, local]:
            creds_path = base_path / "Granola" / "supabase.json"
            if creds_path.exists():
                return creds_path
        
        return roaming / "Granola" / "supabase.json"
    else:  # Linux or other
        return home / ".config" / "Granola" / "supabase.json"

GRANOLA_CACHE = get_granola_cache_path()
GRANOLA_CREDS = get_granola_creds_path()

# Vault paths
VAULT_PATH = Path(os.environ.get('VAULT_PATH', Path.cwd()))

# Health system — error queue and health reporting
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from core.utils.dex_logger import log_error as _log_health_error, mark_healthy as _mark_healthy
    _HAS_HEALTH = True
except ImportError:
    _HAS_HEALTH = False

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Response cache to avoid rate limits (5 min TTL)
_response_cache = {}
_cache_ttl = 300  # 5 minutes


# Custom JSON encoder for handling date/datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


# ============================================================================
# API CLIENT (Primary data source)
# ============================================================================

def get_api_access_token() -> Optional[str]:
    """Get Granola API access token from local credentials"""
    if not GRANOLA_CREDS.exists():
        logger.debug(f"Credentials file not found at: {GRANOLA_CREDS}")
        return None
    
    try:
        with open(GRANOLA_CREDS, 'r') as f:
            data = json.load(f)
        
        workos_tokens = json.loads(data.get('workos_tokens', '{}'))
        access_token = workos_tokens.get('access_token')
        
        if access_token:
            logger.debug("Successfully loaded API access token")
            return access_token
        else:
            logger.warning("No access token found in credentials")
            return None
    except Exception as e:
        logger.warning(f"Error reading credentials: {e}")
        return None


def fetch_from_api(endpoint: str, data: Dict[str, Any], retries: int = 2) -> Optional[Dict[str, Any]]:
    """
    Fetch data from Granola API with exponential backoff on failures
    
    Args:
        endpoint: API endpoint (e.g., '/v2/get-documents')
        data: Request payload
        retries: Number of retries on failure
    
    Returns:
        API response dict or None on failure
    """
    # Check response cache
    cache_key = f"{endpoint}:{json.dumps(data, sort_keys=True)}"
    if cache_key in _response_cache:
        cached_time, cached_response = _response_cache[cache_key]
        if time.time() - cached_time < _cache_ttl:
            logger.debug(f"Using cached response for {endpoint}")
            return cached_response
    
    token = get_api_access_token()
    if not token:
        logger.warning("No API token available, falling back to cache")
        return None
    
    url = f"https://api.granola.ai{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "User-Agent": "Granola/5.354.0",
        "X-Client-Version": "5.354.0"
    }
    
    for attempt in range(retries + 1):
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                # Cache successful response
                _response_cache[cache_key] = (time.time(), result)
                logger.debug(f"API request successful: {endpoint}")
                return result
            elif response.status_code == 429:
                # Rate limited - don't retry, fall back to cache
                logger.warning(f"API rate limited (429), falling back to cache")
                return None
            elif response.status_code == 401:
                # Auth failed - don't retry
                logger.warning(f"API auth failed (401), token may be expired")
                return None
            else:
                logger.warning(f"API returned {response.status_code}: {response.text[:200]}")
                
        except requests.exceptions.Timeout:
            logger.warning(f"API timeout on attempt {attempt + 1}/{retries + 1}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"API request failed: {e}")
        
        # Exponential backoff before retry
        if attempt < retries:
            wait_time = (2 ** attempt) * 0.5  # 0.5s, 1s, 2s...
            logger.debug(f"Retrying in {wait_time}s...")
            time.sleep(wait_time)
    
    logger.warning(f"API request failed after {retries + 1} attempts")
    return None


def convert_api_doc_to_meeting_info(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert API document format to standardized meeting info"""
    meeting_id = doc.get('id', '')
    title = doc.get('title', 'Untitled Meeting')
    created_at = doc.get('created_at', '')
    meeting_date = created_at.split('T')[0] if created_at else None
    
    # Extract notes from last_viewed_panel
    notes = ""
    has_content = False
    content_blocks = 0
    
    panel = doc.get('last_viewed_panel')
    if panel and isinstance(panel, dict):
        content = panel.get('content')
        if content and isinstance(content, dict):
            # Convert ProseMirror JSON to markdown
            notes = convert_prosemirror_to_markdown(content)
            if notes:
                has_content = True
                content_blocks = len(content.get('content', []))
        elif content and isinstance(content, str):
            # Convert HTML string to markdown (meetings recorded on other machines)
            notes = convert_html_to_markdown(content)
            if notes:
                has_content = True
    
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
    
    return {
        'id': meeting_id,
        'title': title,
        'date': meeting_date,
        'created_at': created_at,
        'notes': notes,
        'has_transcript': False,  # API doesn't include transcript in list view
        'transcript_length': 0,
        'participants': participants,
        'participant_count': len(participants),
        'source': 'api'
    }


def convert_prosemirror_to_markdown(content: Dict[str, Any]) -> str:
    """Convert ProseMirror JSON to Markdown"""
    if not content or not isinstance(content, dict) or 'content' not in content:
        return ""
    
    def process_node(node):
        if not isinstance(node, dict):
            return ""
        
        node_type = node.get('type', '')
        content = node.get('content', [])
        text = node.get('text', '')
        marks = node.get('marks', [])
        
        # Apply text marks
        if text and marks:
            for mark in marks:
                mark_type = mark.get('type', '')
                if mark_type == 'bold':
                    text = f"**{text}**"
                elif mark_type == 'italic':
                    text = f"*{text}*"
                elif mark_type == 'code':
                    text = f"`{text}`"
        
        if node_type == 'heading':
            level = node.get('attrs', {}).get('level', 1)
            heading_text = ''.join(process_node(child) for child in content)
            return f"{'#' * level} {heading_text}\n\n"
        elif node_type == 'paragraph':
            para_text = ''.join(process_node(child) for child in content)
            return f"{para_text}\n\n"
        elif node_type == 'bulletList':
            items = []
            for item in content:
                if item.get('type') == 'listItem':
                    item_content = ''.join(process_node(child) for child in item.get('content', []))
                    items.append(f"- {item_content.strip()}")
            return '\n'.join(items) + '\n\n'
        elif node_type == 'orderedList':
            items = []
            for idx, item in enumerate(content, 1):
                if item.get('type') == 'listItem':
                    item_content = ''.join(process_node(child) for child in item.get('content', []))
                    items.append(f"{idx}. {item_content.strip()}")
            return '\n'.join(items) + '\n\n'
        elif node_type == 'codeBlock':
            code_text = ''.join(process_node(child) for child in content)
            return f"```\n{code_text}```\n\n"
        elif node_type == 'blockquote':
            quote_text = ''.join(process_node(child) for child in content)
            return f"> {quote_text}\n\n"
        elif node_type == 'text':
            return text
        elif node_type == 'hardBreak':
            return '\n'
        
        # Recursively process children for unknown types
        return ''.join(process_node(child) for child in content)
    
    markdown = process_node(content)
    return markdown.strip()


def convert_html_to_markdown(html: str) -> str:
    """Convert HTML string content to basic Markdown.

    Granola stores notes as HTML strings for meetings recorded on other machines,
    rather than ProseMirror JSON. This handles that case.
    """
    if not html or not isinstance(html, str):
        return ""

    text = html
    # Headings
    text = re.sub(r'<h([1-6])[^>]*>(.*?)</h\1>', lambda m: '#' * int(m.group(1)) + ' ' + m.group(2) + '\n\n', text)
    # Paragraphs
    text = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', text, flags=re.DOTALL)
    # Line breaks
    text = re.sub(r'<br\s*/?>', '\n', text)
    # List items
    text = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', text, flags=re.DOTALL)
    # Bold
    text = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', text)
    text = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', text)
    # Italic
    text = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', text)
    text = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', text)
    # Code
    text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text)
    # Strip remaining tags
    text = re.sub(r'<[^>]+>', '', text)
    # Clean up whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


# ============================================================================
# CACHE CLIENT (Fallback data source)
# ============================================================================


def read_granola_cache() -> Optional[Dict[str, Any]]:
    """Read and parse Granola's local cache file (fallback data source)"""
    if not GRANOLA_CACHE.exists():
        logger.debug("Cache file not found")
        return None
    
    try:
        raw_data = GRANOLA_CACHE.read_text()
        cache_wrapper = json.loads(raw_data)
        
        # The cache has a nested structure: { cache: JSON_STRING }
        cache_data = json.loads(cache_wrapper.get('cache', '{}'))
        
        logger.debug("Successfully read cache file")
        return {
            'documents': cache_data.get('state', {}).get('documents', {}),
            'transcripts': cache_data.get('state', {}).get('transcripts', {}),
            'people': cache_data.get('state', {}).get('people', {})
        }
    except Exception as e:
        logger.error(f"Error reading Granola cache: {e}")
        return None


def extract_meeting_info_from_cache(doc: Dict[str, Any], transcripts: Dict[str, Any], meeting_id: str) -> Dict[str, Any]:
    """Extract relevant meeting information from a Granola cache document (fallback)"""
    
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
    
    # Extract notes: try notes_markdown first, fall back to last_viewed_panel
    notes = doc.get('notes_markdown', '')
    if not notes:
        panel = doc.get('last_viewed_panel')
        if panel and isinstance(panel, dict):
            panel_content = panel.get('content')
            if panel_content and isinstance(panel_content, dict):
                notes = convert_prosemirror_to_markdown(panel_content)
        elif panel and isinstance(panel, str):
            try:
                parsed_panel = json.loads(panel)
                if isinstance(parsed_panel, dict):
                    panel_content = parsed_panel.get('content')
                    if panel_content and isinstance(panel_content, dict):
                        notes = convert_prosemirror_to_markdown(panel_content)
            except (json.JSONDecodeError, TypeError):
                pass
    
    return {
        'id': meeting_id,
        'title': doc.get('title', 'Untitled Meeting'),
        'date': meeting_date,
        'created_at': created_at,
        'notes': notes,
        'has_transcript': bool(transcript),
        'transcript_length': len(transcript) if transcript else 0,
        'participants': participants,
        'participant_count': len(participants),
        'source': 'cache'
    }


def get_meetings_from_cache(
    cache: Dict[str, Any],
    days_back: int = 7,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get meetings from cache within the specified time range (fallback)"""
    
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
        
        meeting_info = extract_meeting_info_from_cache(doc, cache['transcripts'], meeting_id)
        meetings.append(meeting_info)
    
    # Sort by date descending
    meetings.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    return meetings[:limit]


# ============================================================================
# HYBRID FUNCTIONS (API-first with cache fallback)
# ============================================================================

def get_recent_meetings(days_back: int = 7, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Get recent meetings (API-first with cache fallback)
    
    Tries API first for better data, falls back to cache if API fails
    """
    # Try API first
    logger.info(f"Fetching recent meetings (days_back={days_back}, limit={limit})")
    api_response = fetch_from_api('/v2/get-documents', {
        'limit': 100,  # Get more to filter by date
        'offset': 0,
        'include_last_viewed_panel': True
    })
    
    if api_response and 'docs' in api_response:
        logger.info(f"Using API data ({len(api_response['docs'])} documents)")
        
        # Filter and convert API documents
        cutoff_date = datetime.now() - timedelta(days=days_back)
        meetings = []
        
        for doc in api_response['docs']:
            created_at = doc.get('created_at', '')
            if created_at:
                try:
                    meeting_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    if meeting_date.replace(tzinfo=None) < cutoff_date:
                        continue
                except:
                    # If date parsing fails, include it anyway
                    pass
            
            meetings.append(convert_api_doc_to_meeting_info(doc))
        
        # Sort by date descending and limit
        meetings.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return meetings[:limit]
    
    # Fallback to cache
    logger.info("API failed, falling back to cache")
    cache = read_granola_cache()
    if cache:
        return get_meetings_from_cache(cache, days_back, limit)
    
    logger.error("Both API and cache failed")
    return []


def get_meeting_by_id_from_cache(cache: Dict[str, Any], meeting_id: str) -> Optional[Dict[str, Any]]:
    """Get detailed meeting information by ID from cache (fallback)"""
    
    doc = cache['documents'].get(meeting_id)
    if not doc:
        return None
    
    info = extract_meeting_info_from_cache(doc, cache['transcripts'], meeting_id)
    
    # Add full transcript for detail view
    transcript_entries = cache['transcripts'].get(meeting_id, [])
    if transcript_entries:
        info['transcript'] = ' '.join(
            t.get('text', '') 
            for t in sorted(transcript_entries, key=lambda x: x.get('start_timestamp', ''))
        ).strip()
    
    # Add action items if present in notes (uses notes from extract_meeting_info_from_cache which checks last_viewed_panel)
    notes = info.get('notes', '')
    action_items = []
    for line in notes.split('\n'):
        line = line.strip()
        if line.startswith('- [ ]') or line.startswith('* [ ]'):
            action_items.append(line[5:].strip())
    
    info['action_items'] = action_items
    
    return info


def get_meeting_details(meeting_id: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed meeting information by ID (API-first with cache fallback)
    """
    logger.info(f"Fetching details for meeting {meeting_id}")
    
    # Try API first - get all meetings and find the one we need
    api_response = fetch_from_api('/v2/get-documents', {
        'limit': 100,
        'offset': 0,
        'include_last_viewed_panel': True
    })
    
    if api_response and 'docs' in api_response:
        for doc in api_response['docs']:
            if doc.get('id') == meeting_id:
                logger.info(f"Found meeting in API data")
                info = convert_api_doc_to_meeting_info(doc)
                
                # Extract action items from notes
                action_items = []
                notes = info.get('notes', '')
                for line in notes.split('\n'):
                    line = line.strip()
                    if line.startswith('- [ ]') or line.startswith('* [ ]'):
                        action_items.append(line[5:].strip())
                
                info['action_items'] = action_items
                return info
    
    # Fallback to cache
    logger.info("Meeting not in API data or API failed, trying cache")
    cache = read_granola_cache()
    if cache:
        result = get_meeting_by_id_from_cache(cache, meeting_id)
        if result:
            return result
    
    logger.warning(f"Meeting {meeting_id} not found in API or cache")
    return None


def search_meetings_in_cache(
    cache: Dict[str, Any],
    query: str,
    days_back: int = 30,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Search meetings by title, notes, or participant names in cache (fallback)"""
    
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
            results.append(extract_meeting_info_from_cache(doc, cache['transcripts'], meeting_id))
            continue
        
        # Search in notes (check notes_markdown and last_viewed_panel)
        notes = doc.get('notes_markdown', '')
        if not notes:
            panel = doc.get('last_viewed_panel')
            if panel and isinstance(panel, dict):
                panel_content = panel.get('content')
                if panel_content and isinstance(panel_content, dict):
                    notes = convert_prosemirror_to_markdown(panel_content)
        if query_lower in notes.lower():
            results.append(extract_meeting_info_from_cache(doc, cache['transcripts'], meeting_id))
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
                results.append(extract_meeting_info_from_cache(doc, cache['transcripts'], meeting_id))
                break
    
    # Sort by date descending
    results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    return results[:limit]


def search_meetings(query: str, days_back: int = 30, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Search meetings by title, notes, or participant names (API-first with cache fallback)
    """
    logger.info(f"Searching meetings for '{query}' (days_back={days_back}, limit={limit})")
    
    # Try API first - get broader set and filter
    api_response = fetch_from_api('/v2/get-documents', {
        'limit': 100,
        'offset': 0,
        'include_last_viewed_panel': True
    })
    
    if api_response and 'docs' in api_response:
        logger.info(f"Searching in API data ({len(api_response['docs'])} documents)")
        
        query_lower = query.lower()
        cutoff_date = datetime.now() - timedelta(days=days_back)
        results = []
        
        for doc in api_response['docs']:
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
            title = doc.get('title') or ''
            if query_lower in title.lower():
                results.append(convert_api_doc_to_meeting_info(doc))
                continue
            
            # Search in notes content (ProseMirror JSON or HTML string)
            panel = doc.get('last_viewed_panel', {})
            if isinstance(panel, dict):
                content = panel.get('content')
                notes_text = ""
                if content and isinstance(content, dict):
                    notes_text = convert_prosemirror_to_markdown(content)
                elif content and isinstance(content, str):
                    notes_text = convert_html_to_markdown(content)
                if notes_text and query_lower in notes_text.lower():
                    results.append(convert_api_doc_to_meeting_info(doc))
                    continue
            
            # Search in participant names
            attendees = doc.get('people', {}).get('attendees', [])
            for attendee in attendees:
                name = (
                    attendee.get('details', {}).get('person', {}).get('name', {}).get('fullName') or
                    attendee.get('name') or
                    attendee.get('email') or
                    ''
                )
                if name and query_lower in name.lower():
                    results.append(convert_api_doc_to_meeting_info(doc))
                    break
        
        # Sort by date descending and limit
        results.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return results[:limit]
    
    # Fallback to cache
    logger.info("API failed, falling back to cache for search")
    cache = read_granola_cache()
    if cache:
        return search_meetings_in_cache(cache, query, days_back, limit)
    
    logger.error("Both API and cache failed for search")
    return []


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


@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    try:
        return await _handle_call_tool_inner(name, arguments)
    except Exception as e:
        if _HAS_HEALTH:
            _tool_human_messages = {
                "granola_check_available": "Granola availability check failed",
                "granola_get_recent_meetings": "Recent meetings lookup failed",
                "granola_get_meeting_details": "Meeting details lookup failed",
                "granola_search_meetings": "Meeting search failed",
                "granola_get_today_meetings": "Today's meetings lookup failed",
                "granola_get_extent": "Granola data extent lookup failed",
            }
            _log_health_error(
                source="granola-mcp",
                message=str(e),
                human_message=_tool_human_messages.get(name, f"Granola tool '{name}' failed"),
                context={"tool": name},
            )
        raise


async def _handle_call_tool_inner(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Inner tool handler — wrapped by handle_call_tool for health reporting."""

    arguments = arguments or {}

    if name == "granola_check_available":
        # Check API availability
        api_available = False
        api_token = get_api_access_token()
        if api_token:
            # Quick test - try to fetch 1 document
            test_response = fetch_from_api('/v2/get-documents', {'limit': 1, 'offset': 0})
            api_available = test_response is not None
        
        # Check cache availability
        cache_exists = GRANOLA_CACHE.exists()
        cache_available = False
        meetings_count = 0
        
        if cache_exists:
            cache = read_granola_cache()
            if cache:
                cache_available = True
                meetings_count = len([
                    doc for doc in cache.get('documents', {}).values()
                    if doc.get('type') == 'meeting' and not doc.get('deleted_at')
                ])
        
        result = {
            "available": api_available or cache_available,
            "api": {
                "available": api_available,
                "creds_path": str(GRANOLA_CREDS),
                "status": "ready" if api_available else "unavailable"
            },
            "cache": {
                "available": cache_available,
                "path": str(GRANOLA_CACHE),
                "status": "ready" if cache_available else "unavailable"
            },
            "meetings_count": meetings_count,
            "data_source": "api (primary)" if api_available else "cache (fallback)" if cache_available else "none",
            "message": (
                "Granola API and cache available" if (api_available and cache_available) else
                "Granola API available (cache unavailable)" if api_available else
                "Granola cache available (API unavailable)" if cache_available else
                "Granola not available. Is Granola installed?"
            )
        }
        
        if cache_exists:
            result["cache"]["last_modified"] = datetime.fromtimestamp(
                GRANOLA_CACHE.stat().st_mtime
            ).isoformat()
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "granola_get_recent_meetings":
        days_back = arguments.get("days_back", 7)
        limit = arguments.get("limit", 20)
        
        meetings = get_recent_meetings(days_back, limit)
        
        if not meetings:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "No meetings found. Both API and cache unavailable."
            }, indent=2))]
        
        result = {
            "success": True,
            "meetings": meetings,
            "count": len(meetings),
            "days_back": days_back,
            "data_source": meetings[0].get('source', 'unknown') if meetings else 'none'
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
            "data_source": meeting.get('source', 'unknown')
        }
        
        try:
            _fire_analytics_event('granola_meeting_viewed')
        except Exception:
            pass
        
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
            "data_source": meetings[0].get('source', 'unknown') if meetings else 'none'
        }
        
        try:
            _fire_analytics_event('granola_meetings_searched')
        except Exception:
            pass
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "granola_get_today_meetings":
        # Get meetings from last 1 day using hybrid function
        meetings = get_recent_meetings(days_back=1, limit=50)
        
        # Filter to only today
        today = datetime.now().strftime("%Y-%m-%d")
        today_meetings = [
            m for m in meetings 
            if m.get('date') == today
        ]
        
        # Sort by time
        today_meetings.sort(key=lambda x: x.get('created_at', ''))
        
        result = {
            "success": True,
            "date": today,
            "meetings": today_meetings,
            "count": len(today_meetings),
            "data_source": today_meetings[0].get('source', 'unknown') if today_meetings else 'none'
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "granola_get_extent":
        user_email_domain = arguments.get("user_email_domain", "")
        extended = arguments.get("extended", False)
        
        # Default to 6 months for speed, optionally extend to 2 years
        days_to_fetch = 365 * 2 if extended else 180
        meetings = get_recent_meetings(days_back=days_to_fetch, limit=1000)
        
        if not meetings:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "No meetings found",
                "has_data": False
            }, indent=2))]
        
        # Find oldest and newest dates
        dates = [m['date'] for m in meetings if m.get('date')]
        if not dates:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "has_data": False,
                "meetings_count": 0
            }, indent=2))]
        
        oldest = min(dates)
        newest = max(dates)
        
        # Calculate days back
        oldest_dt = datetime.fromisoformat(oldest)
        newest_dt = datetime.fromisoformat(newest)
        days_back = (newest_dt - oldest_dt).days + 1
        
        # Extract unique people and companies
        people = set()
        internal_people = set()
        external_people = set()
        companies = set()
        
        # Normalize user domain for comparison
        user_domains = [d.strip().lower() for d in user_email_domain.split(',')] if user_email_domain else []
        
        for meeting in meetings:
            for participant in meeting.get('participants', []):
                name = participant.get('name')
                email = participant.get('email')
                
                if name:
                    people.add(name)
                    
                    if email and '@' in email:
                        domain = email.split('@')[1].lower()
                        
                        # Classify as internal or external
                        if user_domains and any(d in domain or domain in d for d in user_domains):
                            internal_people.add(name)
                        else:
                            external_people.add(name)
                            companies.add(domain)
                    else:
                        # No email provided - default to external
                        external_people.add(name)
        
        # Calculate meetings in different time ranges
        now = datetime.now()
        meetings_7d = sum(1 for m in meetings if m.get('date') and 
                          (now - datetime.fromisoformat(m['date'])).days <= 7)
        meetings_30d = sum(1 for m in meetings if m.get('date') and 
                           (now - datetime.fromisoformat(m['date'])).days <= 30)
        meetings_90d = sum(1 for m in meetings if m.get('date') and 
                           (now - datetime.fromisoformat(m['date'])).days <= 90)
        
        # Check if there might be more data beyond what we fetched
        has_more = False
        if not extended:
            # If we got close to 1000 meetings or date range is close to 180 days, likely more data exists
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
            "data_source": meetings[0].get('source', 'unknown') if meetings else 'none'
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    else:
        return [types.TextContent(type="text", text=json.dumps({
            "error": f"Unknown tool: {name}"
        }, indent=2))]


async def _main():
    """Async main entry point for the MCP server"""
    if _HAS_HEALTH:
        _mark_healthy("granola-mcp")
    logger.info("Starting Dex Granola MCP Server (API-first with cache fallback)")
    logger.info(f"API credentials: {GRANOLA_CREDS}")
    logger.info(f"Cache fallback: {GRANOLA_CACHE}")
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-granola-mcp",
                server_version="2.0.0",
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
