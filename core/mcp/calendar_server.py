#!/usr/bin/env python3
"""
Apple Calendar MCP Server for Dex

Provides read/write access to Apple Calendar via AppleScript.
Works with any calendar synced to Calendar.app, including Google accounts.

Tools:
- calendar_list_calendars: List all available calendars
- calendar_get_events: Get events for a date range
- calendar_get_today: Quick access to today's meetings
- calendar_create_event: Create a new event
- calendar_search_events: Search events by title
- calendar_delete_event: Delete an event
- calendar_get_next_event: Get the next upcoming event
- calendar_get_events_with_attendees: Get events with full attendee details
"""

import os
import subprocess
import json
import logging
import tempfile
import re
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Vault paths
VAULT_PATH = Path(os.environ.get('VAULT_PATH', Path.cwd()))
PEOPLE_DIR = VAULT_PATH / "People"

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Scripts directory
SCRIPTS_DIR = Path(__file__).parent / "scripts"


# Custom JSON encoder for handling date/datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)


def run_applescript(script: str) -> tuple[bool, str]:
    """Run an AppleScript and return (success, output).
    
    Uses os.system with temp file output to avoid subprocess.run timeout issues
    with Calendar.app AppleScript queries.
    """
    try:
        # Write script to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.scpt', delete=False) as script_file:
            script_file.write(script)
            script_path = script_file.name
        
        # Output file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as out_file:
            out_path = out_file.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as err_file:
            err_path = err_file.name
        
        try:
            # Run osascript via os.system (avoids subprocess pipe issues)
            exit_code = os.system(f'osascript "{script_path}" > "{out_path}" 2> "{err_path}"')
            
            with open(out_path, 'r') as f:
                stdout = f.read().strip()
            with open(err_path, 'r') as f:
                stderr = f.read().strip()
            
            if exit_code == 0:
                return True, stdout
            else:
                return False, stderr or f"Exit code: {exit_code}"
        finally:
            # Cleanup temp files
            for path in [script_path, out_path, err_path]:
                try:
                    os.unlink(path)
                except:
                    pass
                    
    except Exception as e:
        return False, str(e)


def run_shell_script(script_name: str, *args) -> tuple[bool, str]:
    """Run a shell script from the scripts directory."""
    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        return False, f"Script not found: {script_path}"
    
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as out_file:
            out_path = out_file.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as err_file:
            err_path = err_file.name
        
        try:
            # Build command with quoted args
            cmd_args = ' '.join(f'"{arg}"' for arg in args)
            cmd = f'"{script_path}" {cmd_args} > "{out_path}" 2> "{err_path}"'
            exit_code = os.system(cmd)
            
            with open(out_path, 'r') as f:
                stdout = f.read().strip()
            with open(err_path, 'r') as f:
                stderr = f.read().strip()
            
            if exit_code == 0:
                return True, stdout
            else:
                return False, stderr or f"Exit code: {exit_code}"
        finally:
            for path in [out_path, err_path]:
                try:
                    os.unlink(path)
                except:
                    pass
                    
    except Exception as e:
        return False, str(e)


def parse_applescript_list(output: str) -> list[str]:
    """Parse comma-separated AppleScript output into a list"""
    if not output:
        return []
    # AppleScript returns lists like: item1, item2, item3
    return [item.strip() for item in output.split(', ') if item.strip()]


def parse_attendee_string(attendee_str: str) -> dict:
    """Parse an attendee string like 'Name<email>[status]' into a dict."""
    match = re.match(r'^(.+?)<(.+?)>\[(.+?)\]$', attendee_str.strip())
    if match:
        name, email, status = match.groups()
        name = name.strip()
        email = email.strip().lower()
        
        # If name equals email, try to extract a proper name from email
        if name.lower() == email.lower() or '@' in name:
            # Extract from email: firstname.lastname@domain -> Firstname Lastname
            local_part = email.split('@')[0]
            name = local_part.replace('.', ' ').replace('_', ' ').replace('-', ' ').title()
        
        return {
            'name': name,
            'email': email,
            'status': status.strip()
        }
    return None


def get_domain_from_email(email: str) -> str:
    """Extract domain from email address."""
    if '@' in email:
        return email.split('@')[1].lower()
    return None


def normalize_name_for_filename(name: str) -> str:
    """Convert a name to a filename-safe format."""
    # Replace spaces with underscores, remove special chars
    safe_name = re.sub(r'[^\w\s-]', '', name)
    safe_name = re.sub(r'\s+', '_', safe_name.strip())
    return safe_name


def find_person_page(name: str, email: str) -> Optional[Path]:
    """Find an existing person page by name or email."""
    # Try multiple name variations
    name_variations = [
        normalize_name_for_filename(name),
        # Also try extracting name from email (firstname.lastname@domain)
        normalize_name_for_filename(email.split('@')[0].replace('.', ' ').replace('_', ' ').title()) if '@' in email else None
    ]
    name_variations = [n for n in name_variations if n]
    
    # Check Internal and External folders
    for folder in ['Internal', 'External']:
        folder_path = PEOPLE_DIR / folder
        if folder_path.exists():
            for file in folder_path.glob('*.md'):
                file_stem_lower = file.stem.lower().replace('_', ' ').replace('-', ' ')
                
                # Check by filename variations
                for name_var in name_variations:
                    name_var_lower = name_var.lower().replace('_', ' ')
                    # Check if names match (allowing for partial matches)
                    if name_var_lower in file_stem_lower or file_stem_lower in name_var_lower:
                        return file
                    # Check individual name parts
                    name_parts = name_var_lower.split()
                    if len(name_parts) >= 2:
                        # Check if first and last name are in filename
                        if name_parts[0] in file_stem_lower and name_parts[-1] in file_stem_lower:
                            return file
                
                # Check by email in file content
                try:
                    content = file.read_text()
                    if email.lower() in content.lower():
                        return file
                except:
                    pass
    return None


# Initialize the MCP server
app = Server("dex-calendar-mcp")


@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available calendar tools"""
    return [
        types.Tool(
            name="calendar_list_calendars",
            description="List all calendars available in Apple Calendar",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="calendar_get_events",
            description="Get events from a specific calendar for a date range",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar (e.g., 'Work' or 'user@example.com')"
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format (defaults to today)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format (defaults to start_date + 1 day)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of events to return (default: 50)",
                        "default": 50
                    }
                },
                "required": ["calendar_name"]
            }
        ),
        types.Tool(
            name="calendar_get_today",
            description="Quick access to today's events from a calendar",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Calendar name"
                    }
                },
                "required": ["calendar_name"]
            }
        ),
        types.Tool(
            name="calendar_create_event",
            description="Create a new calendar event",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar to add the event to"
                    },
                    "title": {
                        "type": "string",
                        "description": "Event title/summary"
                    },
                    "start_datetime": {
                        "type": "string",
                        "description": "Start datetime in 'YYYY-MM-DD HH:MM' format"
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duration in minutes (default: 30)",
                        "default": 30
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional event description/notes"
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional event location"
                    }
                },
                "required": ["calendar_name", "title", "start_datetime"]
            }
        ),
        types.Tool(
            name="calendar_search_events",
            description="Search for events by title across a calendar",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar to search"
                    },
                    "query": {
                        "type": "string",
                        "description": "Search term to match against event titles"
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "How many days back to search (default: 30)",
                        "default": 30
                    },
                    "days_forward": {
                        "type": "integer",
                        "description": "How many days forward to search (default: 30)",
                        "default": 30
                    }
                },
                "required": ["calendar_name", "query"]
            }
        ),
        types.Tool(
            name="calendar_delete_event",
            description="Delete a calendar event by its title and date",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar containing the event"
                    },
                    "title": {
                        "type": "string",
                        "description": "Exact title of the event to delete"
                    },
                    "event_date": {
                        "type": "string",
                        "description": "Date of the event in YYYY-MM-DD format"
                    }
                },
                "required": ["calendar_name", "title", "event_date"]
            }
        ),
        types.Tool(
            name="calendar_get_next_event",
            description="Get the next upcoming event from a calendar",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Calendar name"
                    }
                },
                "required": ["calendar_name"]
            }
        ),
        types.Tool(
            name="calendar_get_events_with_attendees",
            description="Get events with full attendee details (name, email, status)",
            inputSchema={
                "type": "object",
                "properties": {
                    "calendar_name": {
                        "type": "string",
                        "description": "Name of the calendar"
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format (defaults to today)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format (defaults to start_date + 1 day)"
                    }
                },
                "required": ["calendar_name"]
            }
        )
    ]


@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    
    arguments = arguments or {}
    
    if name == "calendar_list_calendars":
        success, output = run_shell_script("calendar_list.sh")
        
        if success:
            calendars = parse_applescript_list(output)
            result = {
                "success": True,
                "calendars": calendars,
                "count": len(calendars)
            }
        else:
            result = {"success": False, "error": output}
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "calendar_get_events":
        calendar_name = arguments["calendar_name"]
        start_date = arguments.get("start_date", datetime.now().strftime("%Y-%m-%d"))
        
        # Parse start date
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        
        # End date defaults to start + 1 day
        if "end_date" in arguments:
            end_dt = datetime.strptime(arguments["end_date"], "%Y-%m-%d")
        else:
            end_dt = start_dt + timedelta(days=1)
        
        # Calculate days offset from today for AppleScript
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_offset = (start_dt - today).days
        end_offset = (end_dt - today).days
        
        # Use shell script for reliable execution
        success, output = run_shell_script(
            "calendar_get_events.sh",
            calendar_name,
            str(start_offset),
            str(end_offset)
        )
        
        if success:
            # Parse the output into structured events
            events = []
            for line in output.split('\n'):
                if line.strip():
                    event = {}
                    for part in line.split('|'):
                        if ':' in part:
                            key, value = part.split(':', 1)
                            event[key.lower()] = value.strip()
                    if event:
                        events.append(event)
            
            # Sort by start time
            events.sort(key=lambda x: x.get('start', ''))
            
            result = {
                "success": True,
                "calendar": calendar_name,
                "date_range": f"{start_date} to {end_dt.strftime('%Y-%m-%d')}",
                "events": events,
                "count": len(events)
            }
        else:
            result = {"success": False, "error": output}
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "calendar_get_today":
        calendar_name = arguments["calendar_name"]
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Reuse get_events logic
        arguments = {"calendar_name": calendar_name, "start_date": today}
        return await handle_call_tool("calendar_get_events", arguments)
    
    elif name == "calendar_create_event":
        calendar_name = arguments["calendar_name"]
        title = arguments["title"]
        start_str = arguments["start_datetime"]
        duration = arguments.get("duration_minutes", 30)
        description = arguments.get("description", "")
        location = arguments.get("location", "")
        
        # Validate datetime format
        try:
            datetime.strptime(start_str, "%Y-%m-%d %H:%M")
        except ValueError:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Invalid datetime format. Use 'YYYY-MM-DD HH:MM', got: {start_str}"
            }, indent=2))]
        
        # Use shell script
        success, output = run_shell_script(
            "calendar_create_event.sh",
            calendar_name,
            title,
            start_str,
            str(duration),
            description,
            location
        )
        
        if success:
            result = {
                "success": True,
                "message": output,
                "event": {
                    "title": title,
                    "calendar": calendar_name,
                    "start": start_str,
                    "duration_minutes": duration
                }
            }
        else:
            result = {"success": False, "error": output}
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "calendar_search_events":
        calendar_name = arguments["calendar_name"]
        query = arguments["query"]
        days_back = arguments.get("days_back", 30)
        days_forward = arguments.get("days_forward", 30)
        
        success, output = run_shell_script(
            "calendar_search.sh",
            calendar_name,
            query,
            str(days_back),
            str(days_forward)
        )
        
        if success:
            events = []
            for line in output.split('\n'):
                if line.strip():
                    event = {}
                    for part in line.split('|'):
                        if ':' in part:
                            key, value = part.split(':', 1)
                            event[key.lower()] = value.strip()
                    if event:
                        events.append(event)
            
            result = {
                "success": True,
                "query": query,
                "calendar": calendar_name,
                "events": events,
                "count": len(events)
            }
        else:
            result = {"success": False, "error": output}
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "calendar_delete_event":
        calendar_name = arguments["calendar_name"]
        title = arguments["title"]
        event_date = arguments["event_date"]
        
        # Parse the date and calculate offset from today
        try:
            target_dt = datetime.strptime(event_date, "%Y-%m-%d")
        except ValueError:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Invalid date format. Use 'YYYY-MM-DD', got: {event_date}"
            }, indent=2))]
        
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        day_offset = (target_dt - today).days
        
        success, output = run_shell_script(
            "calendar_delete_event.sh",
            calendar_name,
            title,
            str(day_offset)
        )
        
        if success:
            result = {
                "success": True,
                "message": output
            }
        else:
            result = {"success": False, "error": output}
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "calendar_get_next_event":
        calendar_name = arguments["calendar_name"]
        
        success, output = run_shell_script("calendar_next_event.sh", calendar_name)
        
        if success:
            if output.startswith("TITLE:"):
                event = {}
                for part in output.split('|'):
                    if ':' in part:
                        key, value = part.split(':', 1)
                        event[key.lower()] = value.strip()
                result = {
                    "success": True,
                    "next_event": event
                }
            else:
                result = {
                    "success": True,
                    "message": output,
                    "next_event": None
                }
        else:
            result = {"success": False, "error": output}
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    
    elif name == "calendar_get_events_with_attendees":
        calendar_name = arguments["calendar_name"]
        start_date = arguments.get("start_date", datetime.now().strftime("%Y-%m-%d"))
        
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        if "end_date" in arguments:
            end_dt = datetime.strptime(arguments["end_date"], "%Y-%m-%d")
        else:
            end_dt = start_dt + timedelta(days=1)
        
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_offset = (start_dt - today).days
        end_offset = (end_dt - today).days
        
        success, output = run_shell_script(
            "calendar_get_events_with_attendees.sh",
            calendar_name,
            str(start_offset),
            str(end_offset)
        )
        
        if success:
            events = []
            for line in output.split('\n'):
                if line.strip():
                    event = {}
                    for part in line.split('|'):
                        if ':' in part:
                            key, value = part.split(':', 1)
                            key = key.lower()
                            if key == 'attendees' and value:
                                # Parse attendees into structured data
                                attendees = []
                                for att_str in value.split(';'):
                                    att = parse_attendee_string(att_str)
                                    if att:
                                        # Check if person page exists
                                        person_page = find_person_page(att['name'], att['email'])
                                        att['has_person_page'] = person_page is not None
                                        if person_page:
                                            att['person_page'] = str(person_page.relative_to(VAULT_PATH))
                                        attendees.append(att)
                                event[key] = attendees
                            else:
                                event[key] = value.strip()
                    if event:
                        events.append(event)
            
            # Sort by start time
            events.sort(key=lambda x: x.get('start', ''))
            
            result = {
                "success": True,
                "calendar": calendar_name,
                "date_range": f"{start_date} to {end_dt.strftime('%Y-%m-%d')}",
                "events": events,
                "count": len(events)
            }
        else:
            result = {"success": False, "error": output}
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    else:
        return [types.TextContent(type="text", text=json.dumps({
            "error": f"Unknown tool: {name}"
        }, indent=2))]


async def _main():
    """Async main entry point for the MCP server"""
    logger.info("Starting Dex Calendar MCP Server")
    logger.info("Using Apple Calendar via AppleScript")
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-calendar-mcp",
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
