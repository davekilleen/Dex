#!/usr/bin/env python3
"""
MCP Server for Dex Onboarding System

Provides stateful onboarding with validation, dependency checking, and vault creation.
Ensures all required fields (especially email_domain) are collected before completion.

Features:
- Session state management with resume capability
- Step-by-step validation enforcement
- Dependency verification (Python packages, Calendar.app)
- Automatic MCP configuration
- PARA folder structure creation
"""

import os
import sys
import json
import logging
import re
import platform
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, date

try:
    import yaml
except ImportError:
    yaml = None

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Custom JSON encoder for handling date/datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

# Configuration - Vault paths
BASE_DIR = Path(os.environ.get('VAULT_PATH', Path.cwd()))
SESSION_FILE = BASE_DIR / 'System' / '.onboarding-session.json'
MARKER_FILE = BASE_DIR / 'System' / '.onboarding-complete'
USER_PROFILE_FILE = BASE_DIR / 'System' / 'user-profile.yaml'
USER_PROFILE_TEMPLATE = BASE_DIR / 'System' / 'user-profile-template.yaml'
PILLARS_FILE = BASE_DIR / 'System' / 'pillars.yaml'
CLAUDE_MD = BASE_DIR / 'CLAUDE.md'
MCP_CONFIG_EXAMPLE = BASE_DIR / 'System' / '.mcp.json.example'
MCP_CONFIG_TARGET = BASE_DIR / 'System' / '.mcp.json'

# Role definitions for validation
ROLES = {
    1: ("Product Manager", "product"),
    2: ("Sales / Account Executive", "sales"),
    3: ("Marketing", "marketing"),
    4: ("Engineering", "engineering"),
    5: ("Design", "design"),
    6: ("Customer Success", "customer_success"),
    7: ("Solutions Engineering", "engineering"),
    8: ("Product Operations", "operations"),
    9: ("RevOps / BizOps", "operations"),
    10: ("Data / Analytics", "operations"),
    11: ("Finance", "finance"),
    12: ("People (HR)", "support"),
    13: ("Legal", "support"),
    14: ("IT Support", "support"),
    15: ("Founder", "leadership"),
    16: ("CEO", "leadership"),
    17: ("CFO", "leadership"),
    18: ("COO", "leadership"),
    19: ("CMO", "leadership"),
    20: ("CRO", "leadership"),
    21: ("CTO", "leadership"),
    22: ("CPO", "leadership"),
    23: ("CIO", "leadership"),
    24: ("CISO", "leadership"),
    25: ("CHRO / Chief People Officer", "leadership"),
    26: ("CLO / General Counsel", "leadership"),
    27: ("CCO (Chief Customer Officer)", "leadership"),
    28: ("Fractional CPO", "advisory"),
    29: ("Consultant", "advisory"),
    30: ("Coach", "advisory"),
    31: ("Venture Capital / Private Equity", "advisory"),
}

COMPANY_SIZES = ["startup", "scaling", "enterprise", "large_enterprise"]
FORMALITY_LEVELS = ["formal", "professional_casual", "casual"]
DIRECTNESS_LEVELS = ["very_direct", "balanced", "supportive"]
CAREER_LEVELS = ["junior", "mid", "senior", "leadership", "c_suite"]

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def create_success_response(data: Any, message: str = None) -> Dict:
    """Create a standardized success response"""
    response = {"success": True, "data": data}
    if message:
        response["message"] = message
    return response

def create_error_response(error: str, step: int = None, field: str = None, suggestion: str = None) -> Dict:
    """Create a standardized error response"""
    response = {"success": False, "error": error}
    if step is not None:
        response["step"] = step
    if field:
        response["field"] = field
    if suggestion:
        response["suggestion"] = suggestion
    return response

def load_session() -> Optional[Dict]:
    """Load existing onboarding session"""
    if not SESSION_FILE.exists():
        return None
    
    try:
        with open(SESSION_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading session: {e}")
        return None

def save_session(session_data: Dict) -> bool:
    """Save onboarding session"""
    try:
        # Ensure System directory exists
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        session_data['last_updated'] = datetime.now().isoformat()
        
        with open(SESSION_FILE, 'w') as f:
            json.dump(session_data, f, indent=2, cls=DateTimeEncoder)
        return True
    except Exception as e:
        logger.error(f"Error saving session: {e}")
        return False

def create_new_session() -> Dict:
    """Create a new onboarding session"""
    return {
        "version": "1.0",
        "started_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat(),
        "completed_steps": [],
        "current_step": 1,
        "data": {}
    }

def validate_email_domain(domain: str) -> tuple[bool, Optional[str]]:
    """Validate email domain format (supports multiple domains separated by commas)"""
    if not domain or not domain.strip():
        return False, "Email domain cannot be empty"
    
    domain = domain.strip()
    
    # Check for @ symbol
    if '@' in domain:
        return False, "Domain should not include @ symbol (e.g., 'pendo.io' not '@pendo.io')"
    
    # Split by comma if multiple domains
    domains = [d.strip() for d in domain.split(',')]
    
    for d in domains:
        if not d:
            continue
        
        # Check for at least one dot (basic domain validation)
        if '.' not in d:
            return False, f"Domain '{d}' should include at least one dot (e.g., 'acme.com')"
        
        # Check for valid characters (alphanumeric, dots, hyphens)
        if not re.match(r'^[a-zA-Z0-9\-\.]+$', d):
            return False, f"Domain '{d}' contains invalid characters"
    
    return True, None

def validate_pillars(pillars: List[str]) -> tuple[bool, Optional[str]]:
    """Validate strategic pillars"""
    if not pillars or not isinstance(pillars, list):
        return False, "Pillars must be a non-empty list"
    
    # Filter out empty strings
    pillars = [p.strip() for p in pillars if p and p.strip()]
    
    if len(pillars) < 2:
        return False, "Need at least 2 pillars"
    
    if len(pillars) > 3:
        return True, f"Warning: {len(pillars)} pillars provided. 2-3 is recommended for focus."
    
    return True, None

def check_python_packages() -> Dict[str, Any]:
    """Check if required Python packages are installed"""
    packages = {'mcp': '>=1.0.0', 'yaml': '>=6.0', 'aiohttp': '>=3.9.0'}
    results = {}
    
    for package, version in packages.items():
        try:
            if package == 'yaml':
                import yaml as _yaml
                results['yaml'] = {"installed": True, "version": "available"}
            elif package == 'mcp':
                import mcp
                results['mcp'] = {"installed": True, "version": "available"}
            elif package == 'aiohttp':
                import aiohttp
                results['aiohttp'] = {"installed": True, "version": aiohttp.__version__}
        except ImportError:
            results[package] = {"installed": False, "required": version}
    
    return results

def check_calendar_app() -> Dict[str, Any]:
    """Check if Calendar.app is accessible (macOS only)"""
    if platform.system() != 'Darwin':
        return {
            "available": False,
            "reason": "Not macOS",
            "required": False
        }
    
    try:
        # Try to run a simple AppleScript to check Calendar access
        result = subprocess.run(
            ['osascript', '-e', 'tell application "Calendar" to get name of calendars'],
            capture_output=True,
            timeout=5,
            text=True
        )
        
        if result.returncode == 0:
            return {"available": True, "calendars_found": True}
        else:
            return {
                "available": False,
                "reason": "Calendar.app not accessible or permission denied",
                "required": False
            }
    except Exception as e:
        return {
            "available": False,
            "reason": str(e),
            "required": False
        }

def check_granola() -> Dict[str, Any]:
    """Check if Granola is installed"""
    # Check common Granola cache locations
    if platform.system() == 'Darwin':
        cache_path = Path.home() / 'Library' / 'Application Support' / 'Granola' / 'cache-v3.json'
    elif platform.system() == 'Windows':
        appdata = os.getenv('APPDATA') or os.getenv('LOCALAPPDATA')
        if appdata:
            cache_path = Path(appdata) / 'Granola' / 'cache-v3.json'
        else:
            cache_path = None
    else:  # Linux
        cache_path = Path.home() / '.config' / 'Granola' / 'cache-v3.json'
    
    if cache_path and cache_path.exists():
        return {"installed": True, "cache_found": True, "path": str(cache_path)}
    else:
        return {"installed": False, "optional": True}

def create_para_structure(base_path: Path) -> List[str]:
    """Create PARA folder structure"""
    folders = [
        "04-Projects",
        "05-Areas/People/Internal",
        "05-Areas/People/External",
        "05-Areas/Companies",
        "00-Inbox/Meetings",
        "00-Inbox/Ideas",
        "06-Resources/Learnings",
        "06-Resources/Quarterly_Reviews",
        "07-Archives/04-Projects",
        "07-Archives/Plans",
        "07-Archives/Reviews",
        "System/Templates",
        "01-Quarter_Goals",
        "03-Tasks",
        "02-Week_Priorities"
    ]
    
    created = []
    for folder in folders:
        folder_path = base_path / folder
        if not folder_path.exists():
            folder_path.mkdir(parents=True, exist_ok=True)
            created.append(folder)
    
    return created

def create_initial_files(base_path: Path, session_data: Dict) -> List[str]:
    """Create initial state files"""
    created = []
    
    # Create Tasks.md
    tasks_file = base_path / '03-Tasks' / 'Tasks.md'
    if not tasks_file.exists():
        tasks_content = """# Tasks

## Instructions
- Tasks are organized by pillar and priority
- Use task IDs (^task-YYYYMMDD-XXX) for cross-file sync
- Priorities: P0 (urgent), P1 (important), P2 (normal), P3 (low)

---

"""
        # Add pillar sections
        for pillar in session_data['data'].get('pillars', []):
            pillar_id = pillar.lower().replace(' ', '-')
            tasks_content += f"## {pillar} #{pillar_id}\n\n"
        
        tasks_file.write_text(tasks_content)
        created.append('03-Tasks/Tasks.md')
    
    # Create Week_Priorities.md
    priorities_file = base_path / '02-Week_Priorities' / 'Week_Priorities.md'
    if not priorities_file.exists():
        priorities_content = """# Week Priorities

*Updated: Week of [date]*

## This Week's Focus

### Top 3 Priorities

1. 
2. 
3. 

---

"""
        priorities_file.write_text(priorities_content)
        created.append('02-Week_Priorities/Week_Priorities.md')
    
    return created

def create_user_profile(session_data: Dict) -> bool:
    """Create user-profile.yaml from session data"""
    try:
        # Load template
        if not USER_PROFILE_TEMPLATE.exists():
            logger.error("user-profile-template.yaml not found")
            return False
        
        with open(USER_PROFILE_TEMPLATE, 'r') as f:
            profile = yaml.safe_load(f) if yaml else {}
        
        # Update with session data
        data = session_data['data']
        profile['name'] = data.get('name', '')
        profile['role'] = data.get('role', '')
        profile['role_group'] = data.get('role_group', '')
        profile['company'] = data.get('company', '')
        profile['company_size'] = data.get('company_size', '')
        profile['email_domain'] = data.get('email_domain', '')
        
        # Update Obsidian mode (defaults to false)
        profile['obsidian_mode'] = data.get('obsidian_mode', False)
        
        # Update communication preferences
        comm = data.get('communication', {})
        if 'communication' not in profile:
            profile['communication'] = {}
        profile['communication']['formality'] = comm.get('formality', 'professional_casual')
        profile['communication']['directness'] = comm.get('directness', 'balanced')
        profile['communication']['career_level'] = comm.get('career_level', 'mid')
        profile['communication']['coaching_style'] = comm.get('coaching_style', 'collaborative')
        
        # Save
        with open(USER_PROFILE_FILE, 'w') as f:
            yaml.dump(profile, f, default_flow_style=False, sort_keys=False)
        
        return True
    except Exception as e:
        logger.error(f"Error creating user profile: {e}")
        return False

def create_pillars_file(pillars: List[str]) -> bool:
    """Create pillars.yaml from pillar list"""
    try:
        pillars_data = {"pillars": []}
        
        for pillar in pillars:
            pillar_id = pillar.lower().replace(' ', '-').replace('_', '-')
            pillars_data["pillars"].append({
                "id": pillar_id,
                "name": pillar,
                "description": ""
            })
        
        with open(PILLARS_FILE, 'w') as f:
            yaml.dump(pillars_data, f, default_flow_style=False, sort_keys=False)
        
        return True
    except Exception as e:
        logger.error(f"Error creating pillars file: {e}")
        return False

def update_claude_md(session_data: Dict) -> bool:
    """Update CLAUDE.md User Profile section"""
    try:
        if not CLAUDE_MD.exists():
            logger.error("CLAUDE.md not found")
            return False
        
        content = CLAUDE_MD.read_text()
        data = session_data['data']
        
        # Find and replace User Profile section
        profile_section = f"""## User Profile

<!-- Updated during onboarding -->
**Name:** {data.get('name', 'Not configured')}
**Role:** {data.get('role', 'Not configured')}
**Company Size:** {data.get('company_size', 'Not configured')}
**Working Style:** {data.get('communication', {}).get('formality', 'Not configured')}
**Pillars:**
"""
        for pillar in data.get('pillars', []):
            profile_section += f"- {pillar}\n"
        
        # Replace between "## User Profile" and next "---"
        pattern = r'## User Profile.*?---'
        replacement = profile_section + "\n---"
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
        
        CLAUDE_MD.write_text(content)
        return True
    except Exception as e:
        logger.error(f"Error updating CLAUDE.md: {e}")
        return False

def setup_mcp_config(vault_path: Path) -> tuple[bool, Optional[str]]:
    """Setup .mcp.json by replacing {{VAULT_PATH}} in example"""
    try:
        if not MCP_CONFIG_EXAMPLE.exists():
            return False, ".mcp.json.example not found"
        
        # Read example
        with open(MCP_CONFIG_EXAMPLE, 'r') as f:
            config_content = f.read()
        
        # Replace {{VAULT_PATH}} with actual path
        config_content = config_content.replace('{{VAULT_PATH}}', str(vault_path))
        
        # Validate JSON
        try:
            json.loads(config_content)
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON after substitution: {e}"
        
        # Write to target
        with open(MCP_CONFIG_TARGET, 'w') as f:
            f.write(config_content)
        
        return True, None
    except Exception as e:
        return False, str(e)

# ============================================================================
# PRE-ANALYSIS HELPER FUNCTIONS
# ============================================================================

def get_calendar_events_for_week() -> List[Dict]:
    """
    Get calendar events for the current week by importing and calling calendar MCP.
    Returns empty list if calendar not available.
    """
    try:
        # Import calendar server functions
        calendar_server_path = BASE_DIR / 'core' / 'mcp' / 'calendar_server.py'
        if not calendar_server_path.exists():
            logger.warning("calendar_server.py not found")
            return []
        
        # Dynamic import to avoid circular dependencies
        import importlib.util
        spec = importlib.util.spec_from_file_location("calendar_server", calendar_server_path)
        calendar_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(calendar_module)
        
        # Get this week's events
        from datetime import timedelta
        today = datetime.now()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)
        
        events = calendar_module.get_events_for_range(start, end)
        return events if events else []
    except Exception as e:
        logger.warning(f"Failed to get calendar events: {e}")
        return []

def analyze_calendar_events(events: List[Dict]) -> Dict:
    """Analyze calendar events to extract insights"""
    if not events:
        return {}
    
    # Count meetings
    total = len(events)
    
    # Count 1:1s (events with 2 attendees)
    one_on_ones = sum(1 for e in events if len(e.get('attendees', [])) == 2)
    
    # Find busiest day
    day_counts = {}
    for event in events:
        day = event['start'].strftime('%A')
        day_counts[day] = day_counts.get(day, 0) + 1
    busiest_day = max(day_counts.items(), key=lambda x: x[1]) if day_counts else ('Unknown', 0)
    
    # Get frequent attendees (excluding self)
    attendee_counts = {}
    for event in events:
        for attendee in event.get('attendees', []):
            email = attendee.get('email', '')
            name = attendee.get('name', email)
            if email and name:
                attendee_counts[email] = attendee_counts.get(email, 0) + 1
    
    # Top 3 people
    top_people = sorted(attendee_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    
    return {
        'total_meetings': total,
        'one_on_ones': one_on_ones,
        'busiest_day': busiest_day[0],
        'busiest_day_count': busiest_day[1],
        'top_people': [{'email': email, 'count': count} for email, count in top_people]
    }

def generate_weekly_plan(events: List[Dict], pillars: List[str], role: str) -> str:
    """Generate weekly plan markdown content from calendar events"""
    from datetime import timedelta
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    
    content = f"""# Week Priorities - {week_start.strftime('%b %d')} to {week_end.strftime('%b %d, %Y')}

## This Week's Focus

Based on your calendar and pillars, here are suggested priorities:

"""
    
    # Add pillar-based priorities
    for i, pillar in enumerate(pillars[:3], 1):
        content += f"{i}. **{pillar}**: [Define specific outcome for this week]\n"
    
    content += f"\n## Meeting Overview\n\n"
    content += f"You have **{len(events)} meetings** scheduled this week.\n\n"
    
    # Group by day
    days = {}
    for event in events:
        day = event['start'].strftime('%A')
        if day not in days:
            days[day] = []
        days[day].append(event)
    
    content += "### Key Meetings\n\n"
    for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
        if day in days:
            content += f"**{day}** ({len(days[day])} meetings)\n"
            for event in days[day][:3]:  # Show first 3
                time = event['start'].strftime('%I:%M %p')
                content += f"- {time}: {event['title']}\n"
            if len(days[day]) > 3:
                content += f"- ... and {len(days[day]) - 3} more\n"
            content += "\n"
    
    content += """## Action Items

- [ ] Review and prep for key meetings
- [ ] Block focus time for deep work
- [ ] Check in on project progress

## Notes

*This plan was automatically generated during onboarding based on your calendar.*
"""
    
    return content

def write_weekly_plan(content: str) -> bool:
    """Write weekly plan to file"""
    try:
        week_priorities_dir = BASE_DIR / '02-Week_Priorities'
        week_priorities_dir.mkdir(parents=True, exist_ok=True)
        
        week_file = week_priorities_dir / 'Week_Priorities.md'
        week_file.write_text(content)
        return True
    except Exception as e:
        logger.error(f"Failed to write weekly plan: {e}")
        return False

def get_frequent_attendees(events: List[Dict], limit: int = 3) -> List[Dict]:
    """Get most frequent meeting attendees"""
    attendee_data = {}
    
    for event in events:
        for attendee in event.get('attendees', []):
            email = attendee.get('email', '')
            name = attendee.get('name', email)
            if email and name:
                if email not in attendee_data:
                    attendee_data[email] = {
                        'email': email,
                        'name': name,
                        'count': 0
                    }
                attendee_data[email]['count'] += 1
    
    # Sort by count and return top N
    sorted_attendees = sorted(attendee_data.values(), key=lambda x: x['count'], reverse=True)
    return sorted_attendees[:limit]

def create_person_page(contact: Dict, email_domain: str) -> bool:
    """Create a person page, routing to Internal or External based on email domain"""
    try:
        email = contact['email']
        name = contact['name']
        
        # Determine if internal or external
        contact_domain = email.split('@')[1] if '@' in email else ''
        is_internal = contact_domain in email_domain.split(',')
        
        # Create appropriate folder
        folder = 'Internal' if is_internal else 'External'
        people_dir = BASE_DIR / '05-Areas' / 'People' / folder
        people_dir.mkdir(parents=True, exist_ok=True)
        
        # Create person page
        person_file_name = name.replace(' ', '_') + '.md'
        person_file = people_dir / person_file_name
        
        # Don't overwrite existing
        if person_file.exists():
            return False
        
        content = f"""# {name}

**Email:** {email}
**Type:** {'Internal' if is_internal else 'External'}

## Context

*Automatically created during onboarding as a frequent meeting contact*

## Meeting History

## Action Items

## Notes
"""
        
        person_file.write_text(content)
        return True
    except Exception as e:
        logger.error(f"Failed to create person page for {contact.get('name', 'unknown')}: {e}")
        return False

def get_recent_granola_meetings(days: int = 7) -> List[Dict]:
    """Get recent meetings from Granola"""
    try:
        granola_server_path = BASE_DIR / 'core' / 'mcp' / 'granola_server.py'
        if not granola_server_path.exists():
            logger.warning("granola_server.py not found")
            return []
        
        # Dynamic import
        import importlib.util
        spec = importlib.util.spec_from_file_location("granola_server", granola_server_path)
        granola_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(granola_module)
        
        # Get recent meetings
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=days)
        meetings = granola_module.get_meetings_since(cutoff)
        return meetings if meetings else []
    except Exception as e:
        logger.warning(f"Failed to get Granola meetings: {e}")
        return []

def count_unique_people(meetings: List[Dict]) -> int:
    """Count unique people across meetings"""
    people = set()
    for meeting in meetings:
        for attendee in meeting.get('attendees', []):
            email = attendee.get('email', '')
            if email:
                people.add(email)
    return len(people)

def count_external_companies(meetings: List[Dict], email_domain: str) -> int:
    """Count unique external companies based on email domains"""
    internal_domains = set(d.strip() for d in email_domain.split(','))
    external_domains = set()
    
    for meeting in meetings:
        for attendee in meeting.get('attendees', []):
            email = attendee.get('email', '')
            if '@' in email:
                domain = email.split('@')[1]
                if domain not in internal_domains:
                    external_domains.add(domain)
    
    return len(external_domains)

# ============================================================================
# MCP SERVER SETUP
# ============================================================================

app = Server("dex-onboarding-mcp")

logger.info("Starting Dex Onboarding MCP Server")
logger.info(f"Vault path: {BASE_DIR}")

# ============================================================================
# TOOL DEFINITIONS
# ============================================================================

@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available onboarding tools"""
    return [
        types.Tool(
            name="start_onboarding_session",
            description="Initialize or resume an onboarding session. Returns session state with completed steps.",
            inputSchema={
                "type": "object",
                "properties": {
                    "force_new": {
                        "type": "boolean",
                        "description": "Force create a new session even if one exists",
                        "default": False
                    }
                }
            }
        ),
        types.Tool(
            name="validate_and_save_step",
            description="Validate and save data for a specific onboarding step. Enforces validation rules.",
            inputSchema={
                "type": "object",
                "properties": {
                    "step_number": {
                        "type": "integer",
                        "description": "Step number (1-6)",
                        "minimum": 1,
                        "maximum": 6
                    },
                    "step_data": {
                        "type": "object",
                        "description": "Data for the step (structure varies by step)"
                    }
                },
                "required": ["step_number", "step_data"]
            }
        ),
        types.Tool(
            name="get_onboarding_status",
            description="Get current onboarding progress and completion status",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="verify_dependencies",
            description="Check system requirements: Python packages, Calendar.app, Granola",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="finalize_onboarding",
            description="Complete onboarding: create vault structure, write configs, setup MCP. Requires all steps completed.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="check_onboarding_complete",
            description="Check if onboarding is complete and get vault age. Returns completion status and days since setup.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
    ]

# ============================================================================
# TOOL HANDLERS
# ============================================================================

@app.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[types.TextContent]:
    """Handle tool calls"""
    arguments = arguments or {}
    
    try:
        if name == "start_onboarding_session":
            force_new = arguments.get('force_new', False)
            
            session = load_session()
            
            if session and not force_new:
                result = create_success_response(
                    session,
                    f"Resuming onboarding session. Completed steps: {len(session['completed_steps'])}/6"
                )
            else:
                if session and force_new:
                    logger.info("Creating new session (force_new=True)")
                
                session = create_new_session()
                save_session(session)
                result = create_success_response(
                    session,
                    "New onboarding session created"
                )
            
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
        
        elif name == "validate_and_save_step":
            step_number = arguments.get('step_number')
            step_data = arguments.get('step_data', {})
            
            if not step_number or not isinstance(step_number, int):
                result = create_error_response("Invalid step_number", suggestion="Provide step_number as integer 1-6")
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
            
            session = load_session()
            if not session:
                result = create_error_response("No active session", suggestion="Call start_onboarding_session first")
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
            
            # Step 1: Name
            if step_number == 1:
                name_val = step_data.get('name', '').strip()
                if not name_val:
                    result = create_error_response(
                        "Name is required",
                        step=1,
                        field="name",
                        suggestion="Provide your name"
                    )
                else:
                    session['data']['name'] = name_val
                    if step_number not in session['completed_steps']:
                        session['completed_steps'].append(step_number)
                    session['current_step'] = 2
                    save_session(session)
                    result = create_success_response({"step": 1, "completed": True}, "Step 1 complete")
            
            # Step 2: Role
            elif step_number == 2:
                role = step_data.get('role', '').strip()
                role_number = step_data.get('role_number')
                
                if role_number and isinstance(role_number, int) and role_number in ROLES:
                    role, role_group = ROLES[role_number]
                    session['data']['role'] = role
                    session['data']['role_group'] = role_group
                elif role:
                    session['data']['role'] = role
                    # Best guess for role_group if custom role
                    session['data']['role_group'] = step_data.get('role_group', 'product')
                else:
                    result = create_error_response(
                        "Role is required",
                        step=2,
                        field="role",
                        suggestion="Provide role_number (1-31) or custom role"
                    )
                    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
                
                if step_number not in session['completed_steps']:
                    session['completed_steps'].append(step_number)
                session['current_step'] = 3
                save_session(session)
                result = create_success_response({"step": 2, "completed": True}, "Step 2 complete")
            
            # Step 3: Company Size
            elif step_number == 3:
                company = step_data.get('company', '').strip()
                company_size = step_data.get('company_size', '').strip()
                
                if company_size not in COMPANY_SIZES:
                    result = create_error_response(
                        f"Invalid company_size: {company_size}",
                        step=3,
                        field="company_size",
                        suggestion=f"Must be one of: {', '.join(COMPANY_SIZES)}"
                    )
                    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
                
                session['data']['company'] = company
                session['data']['company_size'] = company_size
                if step_number not in session['completed_steps']:
                    session['completed_steps'].append(step_number)
                session['current_step'] = 4
                save_session(session)
                result = create_success_response({"step": 3, "completed": True}, "Step 3 complete")
            
            # Step 4: Email Domain (CRITICAL)
            elif step_number == 4:
                email_domain = step_data.get('email_domain', '').strip()
                
                valid, error_msg = validate_email_domain(email_domain)
                if not valid:
                    result = create_error_response(
                        error_msg,
                        step=4,
                        field="email_domain",
                        suggestion="Provide domain without @ (e.g., 'pendo.io' or 'acme.com')"
                    )
                else:
                    session['data']['email_domain'] = email_domain
                    if step_number not in session['completed_steps']:
                        session['completed_steps'].append(step_number)
                    session['current_step'] = 5
                    save_session(session)
                    result = create_success_response(
                        {"step": 4, "completed": True, "email_domain": email_domain},
                        "Step 4 complete - email domain validated"
                    )
            
            # Step 5: Pillars
            elif step_number == 5:
                pillars = step_data.get('pillars', [])
                
                valid, message = validate_pillars(pillars)
                if not valid:
                    result = create_error_response(
                        message,
                        step=5,
                        field="pillars",
                        suggestion="Provide 2-3 strategic pillars as a list"
                    )
                else:
                    # Clean pillars
                    pillars = [p.strip() for p in pillars if p and p.strip()]
                    session['data']['pillars'] = pillars
                    if step_number not in session['completed_steps']:
                        session['completed_steps'].append(step_number)
                    session['current_step'] = 6
                    save_session(session)
                    
                    response_msg = "Step 5 complete"
                    if message:  # Warning about pillar count
                        response_msg += f" - {message}"
                    result = create_success_response({"step": 5, "completed": True}, response_msg)
            
            # Step 6: Communication Preferences + Obsidian Mode
            elif step_number == 6:
                comm = step_data.get('communication', {})
                
                formality = comm.get('formality', 'professional_casual')
                directness = comm.get('directness', 'balanced')
                career_level = comm.get('career_level', 'mid')
                
                # Obsidian mode is optional, default to false
                obsidian_mode = step_data.get('obsidian_mode', False)
                
                # Validate enums
                if formality not in FORMALITY_LEVELS:
                    result = create_error_response(
                        f"Invalid formality: {formality}",
                        step=6,
                        field="formality",
                        suggestion=f"Must be one of: {', '.join(FORMALITY_LEVELS)}"
                    )
                    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
                
                if directness not in DIRECTNESS_LEVELS:
                    result = create_error_response(
                        f"Invalid directness: {directness}",
                        step=6,
                        field="directness",
                        suggestion=f"Must be one of: {', '.join(DIRECTNESS_LEVELS)}"
                    )
                    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
                
                if career_level not in CAREER_LEVELS:
                    result = create_error_response(
                        f"Invalid career_level: {career_level}",
                        step=6,
                        field="career_level",
                        suggestion=f"Must be one of: {', '.join(CAREER_LEVELS)}"
                    )
                    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
                
                # Set coaching style based on career level
                coaching_style_map = {
                    'junior': 'encouraging',
                    'mid': 'collaborative',
                    'senior': 'challenging',
                    'leadership': 'challenging',
                    'c_suite': 'challenging'
                }
                coaching_style = comm.get('coaching_style', coaching_style_map.get(career_level, 'collaborative'))
                
                session['data']['communication'] = {
                    'formality': formality,
                    'directness': directness,
                    'career_level': career_level,
                    'coaching_style': coaching_style
                }
                
                # Save obsidian_mode preference
                session['data']['obsidian_mode'] = obsidian_mode
                
                if step_number not in session['completed_steps']:
                    session['completed_steps'].append(step_number)
                session['current_step'] = 7
                save_session(session)
                result = create_success_response({"step": 6, "completed": True}, "Step 6 complete")
            
            else:
                result = create_error_response(f"Invalid step number: {step_number}", suggestion="Step must be 1-6")
            
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
        
        elif name == "get_onboarding_status":
            session = load_session()
            
            if not session:
                result = create_error_response("No active session", suggestion="Call start_onboarding_session first")
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
            
            required_steps = [1, 2, 3, 4, 5, 6]
            completed = session['completed_steps']
            missing = [s for s in required_steps if s not in completed]
            
            step_names = {
                1: "Name",
                2: "Role",
                3: "Company Size",
                4: "Email Domain (CRITICAL)",
                5: "Strategic Pillars",
                6: "Communication Preferences"
            }
            
            progress = len(completed) / len(required_steps) * 100
            
            status = {
                "completed_steps": completed,
                "missing_steps": missing,
                "missing_step_names": [step_names[s] for s in missing],
                "current_step": session['current_step'],
                "progress_percent": round(progress, 1),
                "ready_to_finalize": len(missing) == 0,
                "session_data": session['data']
            }
            
            result = create_success_response(status)
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
        
        elif name == "verify_dependencies":
            deps = {
                "python_packages": check_python_packages(),
                "calendar_app": check_calendar_app(),
                "granola": check_granola()
            }
            
            # Check if all required packages installed
            packages = deps['python_packages']
            all_installed = all(p.get('installed', False) for p in packages.values())
            
            missing = [pkg for pkg, info in packages.items() if not info.get('installed')]
            
            instructions = ""
            if missing:
                instructions = f"Install missing packages:\n  pip install -r {BASE_DIR}/core/mcp/requirements.txt"
            
            result = create_success_response({
                "dependencies": deps,
                "all_required_installed": all_installed,
                "missing_packages": missing,
                "installation_instructions": instructions
            })
            
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "finalize_onboarding":
            session = load_session()
            
            if not session:
                result = create_error_response("No active session", suggestion="Call start_onboarding_session first")
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
            
            # Verify all required steps completed
            required_steps = [1, 2, 3, 4, 5, 6]
            completed = session['completed_steps']
            missing = [s for s in required_steps if s not in completed]
            
            if missing:
                step_names = {1: "Name", 2: "Role", 3: "Company Size", 4: "Email Domain", 5: "Pillars", 6: "Communication"}
                result = create_error_response(
                    f"Cannot finalize: missing steps {missing}",
                    suggestion=f"Complete these steps first: {', '.join(step_names[s] for s in missing)}"
                )
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
            
            # Critical check for Step 4
            if 4 not in completed or not session['data'].get('email_domain'):
                result = create_error_response(
                    "Cannot finalize: email_domain is required",
                    step=4,
                    field="email_domain",
                    suggestion="Go back to Step 4 and provide email domain"
                )
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
            
            # Execute finalization steps
            summary = {
                "folders_created": [],
                "files_created": [],
                "configs_updated": [],
                "errors": []
            }
            
            try:
                # 1. Create PARA structure
                logger.info("Creating PARA folder structure")
                folders = create_para_structure(BASE_DIR)
                summary['folders_created'] = folders
                
                # 2. Create initial files
                logger.info("Creating initial files")
                files = create_initial_files(BASE_DIR, session)
                summary['files_created'].extend(files)
                
                # 3. Create user-profile.yaml
                logger.info("Creating user-profile.yaml")
                if yaml and create_user_profile(session):
                    summary['files_created'].append('System/user-profile.yaml')
                else:
                    summary['errors'].append("Could not create user-profile.yaml")
                
                # 4. Create pillars.yaml
                logger.info("Creating pillars.yaml")
                if yaml and create_pillars_file(session['data']['pillars']):
                    summary['files_created'].append('System/pillars.yaml')
                else:
                    summary['errors'].append("Could not create pillars.yaml")
                
                # 5. Update CLAUDE.md
                logger.info("Updating CLAUDE.md")
                if update_claude_md(session):
                    summary['configs_updated'].append('CLAUDE.md')
                else:
                    summary['errors'].append("Could not update CLAUDE.md")
                
                # 6. Setup MCP config
                logger.info("Setting up .mcp.json")
                success, error = setup_mcp_config(BASE_DIR)
                if success:
                    summary['configs_updated'].append('System/.mcp.json')
                else:
                    summary['errors'].append(f"MCP config error: {error}")
                
                # 7. Create completion marker
                logger.info("Creating completion marker")
                marker_data = {
                    "completed_at": datetime.now().isoformat(),
                    "user_name": session['data']['name'],
                    "role": session['data']['role'],
                    "email_domain": session['data'].get('email_domain', ''),
                    "has_pillars": len(session['data'].get('pillars', [])) > 0,
                    "phase2_completed": False,
                    "pre_analysis_deferred": True  # Analysis moved to /getting-started for performance
                }
                MARKER_FILE.write_text(json.dumps(marker_data, indent=2, cls=DateTimeEncoder))
                logger.info("Completion marker created")
                
                # 8. Delete session file
                if SESSION_FILE.exists():
                    SESSION_FILE.unlink()
                    logger.info("Deleted session file")
                
                result = create_success_response(
                    summary,
                    f"Onboarding complete! Created {len(folders)} folders, {len(summary['files_created'])} files"
                )
                
            except Exception as e:
                logger.error(f"Error during finalization: {e}")
                result = create_error_response(
                    f"Finalization failed: {e}",
                    suggestion="Check logs and retry"
                )
            
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
        
        elif name == "check_onboarding_complete":
            if not MARKER_FILE.exists():
                result = create_success_response({
                    "complete": False,
                    "is_new_vault": False
                })
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
            
            try:
                marker_data = json.loads(MARKER_FILE.read_text())
                completed_at = datetime.fromisoformat(marker_data['completed_at'])
                age_days = (datetime.now() - completed_at).days
                
                result = create_success_response({
                    "complete": True,
                    "age_days": age_days,
                    "is_new_vault": age_days <= 7,
                    "phase2_completed": marker_data.get('phase2_completed', False),
                    "user_name": marker_data.get('user_name', ''),
                    "role": marker_data.get('role', '')
                })
            except Exception as e:
                logger.error(f"Error reading marker file: {e}")
                result = create_error_response(f"Could not read completion marker: {e}")
            
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
        
        else:
            result = create_error_response(f"Unknown tool: {name}")
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    
    except Exception as e:
        logger.error(f"Error handling {name}: {e}")
        result = create_error_response(f"Internal error: {e}")
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

async def _main():
    """Main entry point for the MCP server"""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-onboarding-mcp",
                server_version="1.0.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

def main():
    """Entry point wrapper"""
    import asyncio
    asyncio.run(_main())

if __name__ == "__main__":
    main()
