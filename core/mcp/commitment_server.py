"""
Commitment Detection MCP Server

Detects uncommitted asks and promises from ScreenPipe screen activity,
matches them to existing projects/people/goals, and surfaces them during reviews.

Tools:
- scan_for_commitments: Scan ScreenPipe data for potential commitments
- get_uncommitted_items: Get pending items from commitment queue
- process_commitment: Mark item as task-created, dismissed, or handled
- match_to_context: Match text to people, projects, goals
- get_commitment_stats: Get weekly commitment health stats
"""

import asyncio
import json
import re
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import logging

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.types import Resource, Tool, TextContent
import mcp.server.stdio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("commitment-detection")

# Server instance
server = Server("commitment-detection")

# Get vault path from environment
VAULT_PATH = os.environ.get("VAULT_PATH", os.path.expanduser("~/Claudesidian"))
QUEUE_FILE = Path(VAULT_PATH) / "System" / "commitment_queue.json"
USER_PROFILE = Path(VAULT_PATH) / "System" / "user-profile.yaml"

# ============================================================================
# CONFIGURATION HELPERS
# ============================================================================

def is_beta_activated() -> bool:
    """Check if the screenpipe beta feature is activated."""
    try:
        import yaml
        if USER_PROFILE.exists():
            with open(USER_PROFILE, 'r') as f:
                config = yaml.safe_load(f)
            beta = config.get('beta', {})
            activated = beta.get('activated', {})
            return 'screenpipe' in activated
    except Exception as e:
        logger.warning(f"Could not read user profile for beta check: {e}")
    return False

def is_screenpipe_enabled() -> bool:
    """Check if user has opted into ScreenPipe features. Requires beta activation first."""
    # Must have beta activated
    if not is_beta_activated():
        return False
    
    try:
        import yaml
        if USER_PROFILE.exists():
            with open(USER_PROFILE, 'r') as f:
                config = yaml.safe_load(f)
            screenpipe_config = config.get('screenpipe', {})
            return screenpipe_config.get('enabled', False)
    except Exception as e:
        logger.warning(f"Could not read user profile: {e}")
    return False

def is_commitment_detection_enabled() -> bool:
    """Check if commitment detection feature is enabled."""
    try:
        import yaml
        if USER_PROFILE.exists():
            with open(USER_PROFILE, 'r') as f:
                config = yaml.safe_load(f)
            screenpipe_config = config.get('screenpipe', {})
            if not screenpipe_config.get('enabled', False):
                return False
            features = screenpipe_config.get('features', {})
            return features.get('commitment_detection', True)
    except Exception as e:
        logger.warning(f"Could not read user profile: {e}")
    return False

# ============================================================================
# DETECTION PATTERNS
# ============================================================================

INBOUND_PATTERNS = [
    # Direct requests
    (r'(?:can|could|would) you (?:please )?(\w+)', 'direct_request'),
    (r'(?:need|needs?) your (input|review|feedback|help|approval|sign-off)', 'need_input'),
    (r'(?:could use|could really use) your (input|review|feedback|help)', 'need_input'),
    (r'(?:please|pls) (\w+) (?:this|the|my)', 'please_verb'),
    (r'(?:assigned|assigning) (?:to|this to) you', 'assignment'),
    (r'added you as (?:a )?reviewer', 'review_request'),
    (r'(?:waiting|need) (?:for )?(?:you|your)', 'waiting_on'),
    (r'@\w+ (?:can|could|would|please|need)', 'at_mention'),
    # Soft requests
    (r'when you get a chance', 'soft_request'),
    (r'if you have time', 'soft_request'),
    (r'would be great if you could', 'soft_request'),
]

OUTBOUND_PATTERNS = [
    # Direct promises
    (r"(?:i'll|i will|i'm going to) (\w+)", 'promise'),
    (r"(?:let me|lemme) (\w+)", 'offer'),
    (r"(?:i'll|i will) (?:get back|follow up|send|review|check)", 'followup_promise'),
    (r"(?:will|i'll) (?:do|handle|take care of)", 'handle_promise'),
    (r"(?:sure|yes),? (?:i'll|i can|i will)", 'agreement'),
    (r"(?:i can) (?:do|handle|send|review) (?:that|this|it)", 'can_do'),
]

DEADLINE_PATTERNS = [
    (r'by (?:end of )?(?:day|eod)', 'today'),
    (r'by (?:end of )?(?:week|eow)', 'this_week'),
    (r'by (?:end of )?(?:month|eom)', 'this_month'),
    (r'by (monday|tuesday|wednesday|thursday|friday|saturday|sunday)', 'day_of_week'),
    (r'by (\d{1,2}[\/\-]\d{1,2})', 'specific_date'),
    (r'before (?:the )?(\w+)', 'before_event'),
    (r'(?:asap|urgent|urgently)', 'urgent'),
    (r'this (?:week|afternoon|morning)', 'this_period'),
    (r'tomorrow', 'tomorrow'),
    (r'(?:in|within) (\d+) (?:days?|hours?|weeks?)', 'relative'),
]

# Apps to monitor (default)
DEFAULT_SCAN_APPS = ["Slack", "Gmail", "Mail", "Microsoft Teams", "Notion", "Linear"]

# Apps to always exclude
EXCLUDED_APPS = ["1Password", "Bitwarden", "LastPass", "Keychain Access", "System Preferences"]

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def load_queue() -> dict:
    """Load commitment queue from file."""
    if QUEUE_FILE.exists():
        try:
            with open(QUEUE_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logger.warning("Corrupted queue file, starting fresh")
    
    return {
        "version": 1,
        "last_scan": None,
        "commitments": [],
        "stats": {
            "total_detected": 0,
            "created_tasks": 0,
            "dismissed": 0,
            "already_handled": 0
        }
    }

def save_queue(queue: dict):
    """Save commitment queue to file."""
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_FILE, 'w') as f:
        json.dump(queue, f, indent=2)

def generate_commitment_id() -> str:
    """Generate unique commitment ID."""
    now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    
    # Load queue to get next sequence number
    queue = load_queue()
    today_items = [c for c in queue["commitments"] 
                   if c["id"].startswith(f"comm-{date_str}")]
    seq = len(today_items) + 1
    
    return f"comm-{date_str}-{seq:03d}"

def detect_commitment_type(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Detect if text contains a commitment pattern.
    Returns (type, pattern_name) or (None, None).
    """
    text_lower = text.lower()
    
    # Check inbound patterns
    for pattern, name in INBOUND_PATTERNS:
        if re.search(pattern, text_lower):
            return ("inbound", name)
    
    # Check outbound patterns
    for pattern, name in OUTBOUND_PATTERNS:
        if re.search(pattern, text_lower):
            return ("outbound", name)
    
    return (None, None)

def extract_deadline(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract deadline from text.
    Returns (deadline_date, deadline_type) or (None, None).
    """
    text_lower = text.lower()
    today = datetime.now()
    
    for pattern, dtype in DEADLINE_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            if dtype == "today":
                return (today.strftime("%Y-%m-%d"), dtype)
            elif dtype == "tomorrow":
                return ((today + timedelta(days=1)).strftime("%Y-%m-%d"), dtype)
            elif dtype == "this_week":
                # Friday of this week
                days_until_friday = (4 - today.weekday()) % 7
                friday = today + timedelta(days=days_until_friday)
                return (friday.strftime("%Y-%m-%d"), dtype)
            elif dtype == "day_of_week":
                day_name = match.group(1).lower()
                days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                target_day = days.index(day_name)
                days_ahead = (target_day - today.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7  # Next week if same day
                target_date = today + timedelta(days=days_ahead)
                return (target_date.strftime("%Y-%m-%d"), dtype)
            elif dtype == "urgent":
                return (today.strftime("%Y-%m-%d"), dtype)
            else:
                return (None, dtype)
    
    return (None, None)

def extract_person_name(text: str, app: str) -> Optional[str]:
    """Extract person name from text based on app context."""
    # Common patterns
    patterns = [
        r"@(\w+)",  # Slack/Teams mention
        r"^(\w+ \w+):",  # "John Smith: message"
        r"From: (\w+ \w+)",  # Email
        r"(\w+ \w+) said",  # Quote attribution
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    
    return None

def list_people_pages() -> list[dict]:
    """List all person pages in the vault."""
    people = []
    people_dir = Path(VAULT_PATH) / "05-Areas" / "People"
    
    if people_dir.exists():
        for subdir in ["Internal", "External"]:
            subpath = people_dir / subdir
            if subpath.exists():
                for f in subpath.glob("*.md"):
                    name = f.stem.replace("_", " ")
                    people.append({
                        "name": name,
                        "path": str(f.relative_to(VAULT_PATH)),
                        "type": subdir.lower()
                    })
    
    return people

def list_projects() -> list[dict]:
    """List all projects in the vault."""
    projects = []
    projects_dir = Path(VAULT_PATH) / "04-Projects"
    
    if projects_dir.exists():
        for f in projects_dir.glob("**/*.md"):
            # Extract keywords from filename
            name = f.stem.replace("_", " ").replace("-", " ")
            keywords = name.lower().split()
            projects.append({
                "name": name,
                "path": str(f.relative_to(VAULT_PATH)),
                "keywords": keywords
            })
    
    return projects

def match_to_vault_context(text: str, detected_person: Optional[str] = None) -> dict:
    """Match commitment text to people, projects, and goals."""
    matches = {
        "person_page": None,
        "project": None,
        "goal": None,
        "company": None
    }
    
    text_lower = text.lower()
    
    # Match person
    people = list_people_pages()
    for person in people:
        name_parts = person["name"].lower().split()
        # Match if any name part appears in text or detected_person
        if any(part in text_lower for part in name_parts):
            matches["person_page"] = person["path"]
            break
        if detected_person:
            if any(part in detected_person.lower() for part in name_parts):
                matches["person_page"] = person["path"]
                break
    
    # Match project (keyword matching)
    projects = list_projects()
    for project in projects:
        if any(kw in text_lower for kw in project["keywords"] if len(kw) > 3):
            matches["project"] = project["path"]
            break
    
    # TODO: Match goals and companies
    
    return matches

# ============================================================================
# SCREENPIPE INTEGRATION
# ============================================================================

async def query_screenpipe(start_time: str, end_time: str, apps: list[str] = None) -> list[dict]:
    """
    Query ScreenPipe for screen content in time range.
    Returns list of content items with app, timestamp, and text.
    """
    import aiohttp
    
    SCREENPIPE_URL = "http://localhost:3030"
    
    try:
        # ScreenPipe uses different param names
        params = {
            "content_type": "ocr",
            "limit": 500
        }
        
        # Add time filters if provided (ScreenPipe expects specific format)
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{SCREENPIPE_URL}/search", params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", [])
                    
                    # Filter by apps if specified
                    if apps:
                        apps_lower = [a.lower() for a in apps]
                        items = [
                            item for item in items
                            if item.get("content", {}).get("app_name", "").lower() in apps_lower
                        ]
                    
                    return items
                else:
                    logger.error(f"ScreenPipe query failed: {resp.status}")
                    return []
    except Exception as e:
        logger.error(f"ScreenPipe connection error: {e}")
        return []

async def scan_screenpipe_for_commitments(start_time: str, end_time: str, apps: list[str] = None) -> list[dict]:
    """
    Scan ScreenPipe data for commitment patterns.
    Returns list of detected commitments.
    """
    apps = apps or DEFAULT_SCAN_APPS
    
    # Filter out excluded apps
    apps = [a for a in apps if a not in EXCLUDED_APPS]
    
    # Query ScreenPipe
    content_items = await query_screenpipe(start_time, end_time, apps)
    
    commitments = []
    seen_texts = set()  # Dedupe
    
    for item in content_items:
        # Extract text content
        text = item.get("content", {}).get("text", "") or ""
        app = item.get("content", {}).get("app_name", "") or "Unknown"
        timestamp = item.get("timestamp", "")
        
        # Skip empty or very short text
        if len(text) < 20:
            continue
        
        # Skip if we've seen similar text (fuzzy dedupe)
        text_key = text[:100].lower()
        if text_key in seen_texts:
            continue
        seen_texts.add(text_key)
        
        # Detect commitment pattern
        comm_type, pattern_name = detect_commitment_type(text)
        
        if comm_type:
            # Extract additional context
            deadline, deadline_type = extract_deadline(text)
            person = extract_person_name(text, app)
            matches = match_to_vault_context(text, person)
            
            commitment = {
                "id": generate_commitment_id(),
                "type": comm_type,
                "pattern": pattern_name,
                "detected_at": timestamp or datetime.now().isoformat(),
                "app": app,
                "raw_text": text[:500],  # Truncate for storage
                "person": person,
                "deadline_detected": deadline,
                "deadline_type": deadline_type,
                "matches": matches,
                "status": "pending",
                "processed_at": None,
                "action_taken": None
            }
            
            commitments.append(commitment)
    
    return commitments

# ============================================================================
# MCP TOOL HANDLERS
# ============================================================================

@server.list_tools()
async def handle_list_tools():
    """Return available tools."""
    return [
        Tool(
            name="scan_for_commitments",
            description="Scan ScreenPipe data for uncommitted asks and promises. Call during daily/weekly review.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_time": {
                        "type": "string",
                        "description": "Start time in ISO format (e.g., 2026-02-04T09:00:00)"
                    },
                    "end_time": {
                        "type": "string", 
                        "description": "End time in ISO format"
                    },
                    "apps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Apps to scan (default: Slack, Gmail, Teams, Notion)"
                    }
                },
                "required": ["start_time", "end_time"]
            }
        ),
        Tool(
            name="get_uncommitted_items",
            description="Get pending items from commitment queue that haven't been converted to tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_dismissed": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include previously dismissed items"
                    },
                    "since": {
                        "type": "string",
                        "description": "Only items detected since this datetime"
                    }
                }
            }
        ),
        Tool(
            name="process_commitment",
            description="Mark a commitment as handled. Actions: create_task, dismiss, already_handled",
            inputSchema={
                "type": "object",
                "properties": {
                    "commitment_id": {
                        "type": "string",
                        "description": "The commitment ID (e.g., comm-20260204-001)"
                    },
                    "action": {
                        "type": "string",
                        "enum": ["create_task", "dismiss", "already_handled"],
                        "description": "Action to take"
                    },
                    "task_title": {
                        "type": "string",
                        "description": "Task title if creating task"
                    }
                },
                "required": ["commitment_id", "action"]
            }
        ),
        Tool(
            name="match_to_context",
            description="Match commitment text to people, projects, and goals in the vault.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The commitment text to match"
                    },
                    "detected_person": {
                        "type": "string",
                        "description": "Person name if already detected"
                    }
                },
                "required": ["text"]
            }
        ),
        Tool(
            name="get_commitment_stats",
            description="Get commitment detection stats for reporting in weekly review.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date (YYYY-MM-DD)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (YYYY-MM-DD)"
                    }
                }
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict):
    """Handle tool calls."""
    
    if name == "scan_for_commitments":
        # Check if beta is activated first
        if not is_beta_activated():
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": "beta_not_activated",
                    "message": "ScreenPipe is a beta feature. Run /beta-activate DEXSCREENPIPE2026 to enable.",
                    "hint": "Beta activation required before ScreenPipe features are available"
                })
            )]
        
        # Check if user has opted into ScreenPipe
        if not is_commitment_detection_enabled():
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": "not_enabled",
                    "message": "ScreenPipe commitment detection is not enabled. Run /screenpipe-setup to opt in.",
                    "hint": "User must enable ScreenPipe in System/user-profile.yaml → screenpipe.enabled: true"
                })
            )]
        
        start_time = arguments.get("start_time")
        end_time = arguments.get("end_time")
        apps = arguments.get("apps")
        
        # Scan ScreenPipe
        new_commitments = await scan_screenpipe_for_commitments(start_time, end_time, apps)
        
        # Add to queue
        queue = load_queue()
        
        # Dedupe against existing
        existing_ids = {c["id"] for c in queue["commitments"]}
        
        added = 0
        for comm in new_commitments:
            # Check if similar commitment already exists (by text similarity)
            is_dupe = any(
                c["raw_text"][:100] == comm["raw_text"][:100] 
                for c in queue["commitments"]
            )
            
            if not is_dupe:
                queue["commitments"].append(comm)
                queue["stats"]["total_detected"] += 1
                added += 1
        
        queue["last_scan"] = datetime.now().isoformat()
        save_queue(queue)
        
        # Return summary
        pending = [c for c in queue["commitments"] if c["status"] == "pending"]
        
        return [TextContent(
            type="text",
            text=json.dumps({
                "scanned_range": f"{start_time} to {end_time}",
                "new_commitments_found": added,
                "total_pending": len(pending),
                "commitments": new_commitments[:10]  # Return first 10
            }, indent=2)
        )]
    
    elif name == "get_uncommitted_items":
        include_dismissed = arguments.get("include_dismissed", False)
        since = arguments.get("since")
        
        queue = load_queue()
        
        items = queue["commitments"]
        
        # Filter by status
        if not include_dismissed:
            items = [c for c in items if c["status"] == "pending"]
        
        # Filter by date
        if since:
            items = [c for c in items if c["detected_at"] >= since]
        
        # Group by type
        inbound = [c for c in items if c["type"] == "inbound"]
        outbound = [c for c in items if c["type"] == "outbound"]
        
        return [TextContent(
            type="text",
            text=json.dumps({
                "total_pending": len(items),
                "inbound_asks": inbound,
                "outbound_promises": outbound,
                "last_scan": queue.get("last_scan")
            }, indent=2)
        )]
    
    elif name == "process_commitment":
        commitment_id = arguments.get("commitment_id")
        action = arguments.get("action")
        task_title = arguments.get("task_title")
        
        queue = load_queue()
        
        # Find commitment
        commitment = None
        for c in queue["commitments"]:
            if c["id"] == commitment_id:
                commitment = c
                break
        
        if not commitment:
            return [TextContent(
                type="text",
                text=json.dumps({"error": f"Commitment {commitment_id} not found"})
            )]
        
        # Update status
        commitment["status"] = "processed"
        commitment["processed_at"] = datetime.now().isoformat()
        commitment["action_taken"] = action
        
        # Update stats
        if action == "create_task":
            queue["stats"]["created_tasks"] += 1
        elif action == "dismiss":
            queue["stats"]["dismissed"] += 1
        elif action == "already_handled":
            queue["stats"]["already_handled"] += 1
        
        save_queue(queue)
        
        return [TextContent(
            type="text",
            text=json.dumps({
                "commitment_id": commitment_id,
                "action": action,
                "success": True,
                "message": f"Commitment marked as {action}"
            })
        )]
    
    elif name == "match_to_context":
        text = arguments.get("text", "")
        detected_person = arguments.get("detected_person")
        
        matches = match_to_vault_context(text, detected_person)
        
        return [TextContent(
            type="text",
            text=json.dumps({
                "text": text[:100] + "..." if len(text) > 100 else text,
                "matches": matches
            }, indent=2)
        )]
    
    elif name == "get_commitment_stats":
        start_date = arguments.get("start_date")
        end_date = arguments.get("end_date")
        
        queue = load_queue()
        
        # Filter by date range
        commitments = queue["commitments"]
        if start_date:
            commitments = [c for c in commitments if c["detected_at"][:10] >= start_date]
        if end_date:
            commitments = [c for c in commitments if c["detected_at"][:10] <= end_date]
        
        # Calculate stats
        total = len(commitments)
        by_status = {}
        by_app = {}
        by_person = {}
        
        for c in commitments:
            # By status
            status = c.get("action_taken") or "pending"
            by_status[status] = by_status.get(status, 0) + 1
            
            # By app
            app = c.get("app", "Unknown")
            by_app[app] = by_app.get(app, 0) + 1
            
            # By person
            person = c.get("person")
            if person:
                by_person[person] = by_person.get(person, 0) + 1
        
        # Sort by count
        top_apps = sorted(by_app.items(), key=lambda x: x[1], reverse=True)[:5]
        top_people = sorted(by_person.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return [TextContent(
            type="text",
            text=json.dumps({
                "date_range": f"{start_date or 'all'} to {end_date or 'now'}",
                "total_detected": total,
                "by_status": by_status,
                "top_apps": top_apps,
                "top_people_asking": top_people,
                "lifetime_stats": queue.get("stats", {})
            }, indent=2)
        )]
    
    return [TextContent(type="text", text=f"Unknown tool: {name}")]

# ============================================================================
# MAIN
# ============================================================================

async def main():
    """Run the MCP server."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="commitment-detection",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={}
                )
            )
        )

if __name__ == "__main__":
    asyncio.run(main())
