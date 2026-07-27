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

import json
import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Custom JSON encoder for handling date/datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

# Configuration - Vault paths (centralized in core.paths)
_repo_root = str(Path(__file__).parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.append(_repo_root)
from core import capabilities as capability_rooms
from core.paths import (
    MARKER_FILE,
    MCP_CONFIG_EXAMPLE,
    SESSION_FILE,
)
from core.paths import (
    VAULT_ROOT as BASE_DIR,
)

GRANOLA_APP_PATH = Path("/Applications/Granola.app")
ONBOARDING_STEPS = 7
PROVISION_CONTRACT = json.loads(
    (Path(__file__).parent.parent / "provision-contract.json").read_text(encoding="utf-8")
)

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

ROLE_AREAS = {
    "Product": (1, 8, 22, 28),
    "Sales": (2, 7, 20),
    "Marketing": (3, 19),
    "Engineering / Data / IT": (4, 10, 14, 21, 23, 24),
    "Design": (5,),
    "Customer Success": (6, 27),
    "Operations / Finance / People / Legal": (9, 11, 12, 13, 17, 18, 25, 26),
    "Leadership / Exec / Advisory": (15, 16, 29, 30, 31),
}

COMPANY_SIZES = ["startup", "scaling", "enterprise", "large_enterprise"]
FORMALITY_LEVELS = ["formal", "professional_casual", "casual"]
DIRECTNESS_LEVELS = ["very_direct", "balanced", "supportive"]
CAREER_LEVELS = ["junior", "mid", "senior", "leadership", "c_suite"]
ROLE_EMAIL_LOCALS = {
    "accounts",
    "admin",
    "administrator",
    "billing",
    "careers",
    "contact",
    "customerservice",
    "enquiries",
    "enquiry",
    "events",
    "finance",
    "hello",
    "help",
    "hr",
    "info",
    "jobs",
    "legal",
    "mail",
    "marketing",
    "media",
    "noreply",
    "notifications",
    "office",
    "partners",
    "partnerships",
    "people",
    "press",
    "privacy",
    "recruiting",
    "recruitment",
    "sales",
    "security",
    "service",
    "support",
    "team",
}

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

def validate_email_domain(domain: str) -> tuple[bool, Optional[str], str]:
    """Validate and normalize email domains separated by commas"""
    if not domain or not domain.strip():
        return False, "Email domain cannot be empty", ""

    domains = []
    for raw_domain in domain.split(','):
        d = raw_domain.strip()
        if not d:
            continue

        if d.startswith('@'):
            d = d[1:]
        if '@' in d:
            d = d.rsplit('@', 1)[1]
        d = d.strip()

        if not d or '@' in d:
            return False, f"Could not determine a domain from '{raw_domain.strip()}'", ""

        # Check for at least one dot (basic domain validation)
        if '.' not in d:
            return False, f"Domain '{d}' should include at least one dot (e.g., 'acme.com')", ""

        # Check for valid characters (alphanumeric, dots, hyphens)
        if not re.match(r'^[a-zA-Z0-9\-\.]+$', d):
            return False, f"Domain '{d}' contains invalid characters", ""

        domains.append(d)

    if not domains:
        return False, "Email domain cannot be empty", ""

    return True, None, ", ".join(domains)


def derive_identity_from_email(address: str) -> Dict[str, Optional[str]]:
    """Return only identity details that are safe to offer for confirmation."""
    empty_identity = {"name": None, "domain": None}
    if not isinstance(address, str):
        return empty_identity

    cleaned = address.strip()
    if cleaned.count("@") != 1:
        return empty_identity

    local_part, domain = cleaned.split("@", 1)
    if (
        not local_part
        or local_part.startswith(".")
        or local_part.endswith(".")
        or ".." in local_part
        or re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+", local_part) is None
    ):
        return empty_identity

    valid_domain, _, normalized_domain = validate_email_domain(domain)
    if not valid_domain:
        return empty_identity

    first_token = local_part.split(".", 1)[0].lower()
    name = None
    if (
        len(first_token) >= 3
        and first_token.isalpha()
        and first_token not in ROLE_EMAIL_LOCALS
    ):
        name = first_token.title()

    return {"name": name, "domain": normalized_domain.lower()}


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
    """Check whether the Granola desktop application is installed."""
    if platform.system() == 'Darwin' and GRANOLA_APP_PATH.exists():
        return {
            "installed": True,
            "app_found": True,
            "path": str(GRANOLA_APP_PATH),
            "setup": "/granola-setup",
        }

    return {
        "installed": False,
        "app_found": False,
        "optional": True,
        "setup": "/granola-setup",
    }

def _capability_states(
    selected: Dict[str, bool] | None = None,
) -> Dict[str, bool]:
    selected = selected or {}
    states: Dict[str, bool] = {}
    for room in capability_rooms.room_ids():
        if room in selected:
            states[room] = selected[room] is True
            continue
        default = capability_rooms.surfaces_for(room).get("default_enabled", False)
        states[room] = default if isinstance(default, bool) else False
    return states


def _provision_folders(capability_states: Dict[str, bool] | None = None) -> List[str]:
    folders = list(PROVISION_CONTRACT["para_directories"])
    states = _capability_states(capability_states)
    for room in capability_rooms.room_ids():
        if states[room] is True:
            folders.extend(capability_rooms.surfaces_for(room).get("folders", []))
    return list(dict.fromkeys(folders))


def _finalize_through_provisioner(session: Dict) -> Dict[str, Any]:
    """Collect onboarding inputs and let the sanctioned provisioner mutate."""
    data = dict(session["data"])
    data["pillars"] = [
        {"name": pillar, "description": ""}
        for pillar in data.get("pillars", [])
    ]
    selected = _capability_states(data.get("capabilities"))
    data["capabilities"] = {
        room: {"enabled": selected[room]}
        for room in capability_rooms.room_ids()
    }
    profile_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="dex-onboarding-profile-",
            suffix=".json",
            delete=False,
        ) as profile:
            profile_path = Path(profile.name)
            json.dump(data, profile, cls=DateTimeEncoder)
            profile.write("\n")
        provisioner = Path(__file__).parent.parent / "provision.cjs"
        node = os.environ.get("DEX_PROVISION_NODE", "node")
        completed = subprocess.run(
            [
                node,
                str(provisioner),
                "--path",
                str(BASE_DIR),
                "--profile",
                str(profile_path),
                "--onboard",
                "--session-file",
                str(SESSION_FILE),
                "--json",
            ],
            cwd=Path(__file__).parent.parent.parent,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env={**os.environ, "DEX_LIFECYCLE_PYTHON": sys.executable},
        )
        try:
            receipt = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("Provisioner returned an invalid receipt") from error
        if completed.returncode != 0 or receipt.get("ok") is not True:
            detail = "; ".join(receipt.get("errors", [])) or completed.stderr.strip()
            raise RuntimeError(detail or "Provisioner refused onboarding")
        created = receipt.get("created", [])
        folders = [relative for relative in created if (BASE_DIR / relative).is_dir()]
        files = [relative for relative in created if (BASE_DIR / relative).is_file()]
        return {
            "executor": "core/provision.cjs",
            "lifecycle_executor": receipt.get("lifecycle_executor"),
            "folders_created": folders,
            "files_created": files,
            "configs_updated": [
                relative for relative in ("CLAUDE.md", ".mcp.json") if relative in created
            ],
            "errors": [],
            "receipt": receipt,
        }
    finally:
        if profile_path is not None:
            profile_path.unlink(missing_ok=True)

# ============================================================================
# PRE-ANALYSIS HELPER FUNCTIONS
# ============================================================================

def _load_first_week_profile() -> Dict[str, Any]:
    """Load finalized or in-progress profile data for calendar analysis."""
    profile = {}
    profile_path = BASE_DIR / 'System' / 'user-profile.yaml'
    if profile_path.exists():
        try:
            import yaml
            profile = yaml.safe_load(profile_path.read_text(encoding='utf-8')) or {}
        except Exception as e:
            logger.warning(f"Failed to load user profile for first-week analysis: {e}")

    session = load_session()
    if session and isinstance(session.get('data'), dict):
        profile.update(session['data'])
    return profile


def _calendar_event_datetime(value: Any) -> Optional[datetime]:
    """Return a timed calendar value as datetime; date-only values are all-day."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return None
    if not isinstance(value, str):
        return None

    cleaned = value.strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', cleaned):
        return None
    try:
        return datetime.fromisoformat(
            cleaned.replace('Z', '+00:00').replace(' +0000', '+00:00')
        )
    except ValueError:
        return None


def _timed_calendar_events(events: List[Dict]) -> List[Dict]:
    """Exclude all-day and malformed events from meeting analysis."""
    timed_events = []
    for event in events:
        if event.get('all_day') is True:
            continue
        if (
            _calendar_event_datetime(event.get('start')) is None
            or _calendar_event_datetime(event.get('end')) is None
        ):
            continue
        timed_events.append(event)
    return timed_events


def _meeting_attendees(meeting: Dict) -> List[Dict]:
    """Return participants from Calendar or Granola's normalized shapes."""
    return meeting.get('attendees') or meeting.get('participants') or []


def get_calendar_events_for_week() -> List[Dict]:
    """
    Get calendar events for the current week by importing and calling calendar MCP.
    Raises with an honest reason when Calendar is unavailable; an empty list means
    the query succeeded and the user genuinely has no meetings this week.
    """
    if platform.system() != 'Darwin':
        raise RuntimeError(
            "First-week calendar analysis is currently available only on macOS."
        )

    try:
        calendar_server_path = BASE_DIR / 'core' / 'mcp' / 'calendar_server.py'
        if not calendar_server_path.exists():
            raise RuntimeError("Calendar support is not installed in this vault.")

        profile = _load_first_week_profile()
        calendar_config = profile.get('calendar', {})
        if calendar_config.get('permissions_pending') is True:
            raise RuntimeError("Calendar access was skipped or permission is not available.")
        
        import importlib.util
        spec = importlib.util.spec_from_file_location("calendar_server", calendar_server_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Calendar support could not be loaded.")
        calendar_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(calendar_module)
        
        from datetime import timedelta
        today = datetime.now()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=7)

        calendar_name = (
            calendar_config.get('work_calendar')
            or profile.get('work_email')
            or calendar_module.DEFAULT_WORK_CALENDAR
        )
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_offset = (
            start.replace(hour=0, minute=0, second=0, microsecond=0) - midnight
        ).days
        end_offset = (
            end.replace(hour=0, minute=0, second=0, microsecond=0) - midnight
        ).days
        success, output = calendar_module.run_shell_script(
            "calendar_eventkit.py",
            "attendees",
            calendar_name,
            str(start_offset),
            str(end_offset),
        )
        if not success:
            raise RuntimeError(output or "Calendar data could not be read.")

        events = json.loads(output)
        if not isinstance(events, list):
            raise RuntimeError("Calendar returned an invalid event list.")
        return events
    except Exception as e:
        logger.warning(f"Failed to get calendar events: {e}")
        if isinstance(e, RuntimeError):
            raise
        raise RuntimeError(str(e) or "Calendar data could not be read.") from e

def analyze_calendar_events(events: List[Dict]) -> Dict:
    """Analyze calendar events to extract insights"""
    timed_events = _timed_calendar_events(events)
    
    # Count meetings
    total = len(timed_events)

    total_seconds = 0.0
    for event in timed_events:
        start = _calendar_event_datetime(event.get('start'))
        end = _calendar_event_datetime(event.get('end'))
        try:
            total_seconds += max(0.0, (end - start).total_seconds())
        except (TypeError, AttributeError):
            continue
    
    # Count 1:1s (events with 2 attendees)
    one_on_ones = sum(1 for e in timed_events if len(_meeting_attendees(e)) == 2)
    
    # Find busiest day
    day_counts = {}
    for event in timed_events:
        day = _calendar_event_datetime(event.get('start')).strftime('%A')
        day_counts[day] = day_counts.get(day, 0) + 1
    busiest_day = max(day_counts.items(), key=lambda x: x[1]) if day_counts else ('', 0)
    
    # Get frequent attendees (excluding self)
    attendee_counts = {}
    for event in timed_events:
        for attendee in _meeting_attendees(event):
            if attendee.get('is_current_user') is True:
                continue
            email = attendee.get('email', '')
            name = attendee.get('name', email)
            if email and name:
                attendee_counts[email] = attendee_counts.get(email, 0) + 1
    
    # Top 3 people
    top_people = sorted(attendee_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    
    return {
        'total_meetings': total,
        'meeting_hours': round(total_seconds / 3600, 2),
        'one_on_ones': one_on_ones,
        'busiest_day': busiest_day[0],
        'busiest_day_count': busiest_day[1],
        'top_people': [{'email': email, 'count': count} for email, count in top_people]
    }


def build_pillar_evidence(events: List[Dict], email_domain: str) -> Dict[str, Any]:
    """Summarize timed calendar evidence without inferring strategic pillars."""
    timed_events = _timed_calendar_events(events)
    calendar_analysis = analyze_calendar_events(timed_events)

    calendar_series = {}
    for event in timed_events:
        provider_series_id = event.get('provider_series_id')
        if not provider_series_id:
            continue

        title = (event.get('title') or 'Untitled meeting').strip()
        commitment = calendar_series.setdefault(
            str(provider_series_id),
            {
                'title': title,
                'meeting_count': 0,
                'meeting_seconds': 0.0,
            },
        )
        commitment['meeting_count'] += 1
        start = _calendar_event_datetime(event.get('start'))
        end = _calendar_event_datetime(event.get('end'))
        commitment['meeting_seconds'] += max(0.0, (end - start).total_seconds())

    recurring_commitments = [
        {
            'title': commitment['title'],
            'meeting_count': commitment['meeting_count'],
            'meeting_hours': round(commitment['meeting_seconds'] / 3600, 2),
        }
        for commitment in sorted(
            (
                commitment
                for commitment in calendar_series.values()
                if commitment['meeting_count'] > 1
            ),
            key=lambda item: (
                -item['meeting_count'],
                -item['meeting_seconds'],
                item['title'].casefold(),
            ),
        )[:3]
    ]

    internal_domains = {
        domain.strip().lower()
        for domain in email_domain.split(',')
        if domain.strip()
    }
    meeting_split = {
        'internal_meeting_count': 0,
        'external_meeting_count': 0,
        'unknown_meeting_count': 0,
    }
    for event in timed_events:
        attendee_domains = []
        for attendee in _meeting_attendees(event):
            if attendee.get('is_current_user') is True:
                continue
            email = attendee.get('email', '')
            if '@' in email:
                attendee_domains.append(email.rsplit('@', 1)[1].lower())

        if not attendee_domains:
            meeting_split['unknown_meeting_count'] += 1
        elif internal_domains and all(
            domain in internal_domains for domain in attendee_domains
        ):
            meeting_split['internal_meeting_count'] += 1
        else:
            meeting_split['external_meeting_count'] += 1

    total_meetings = calendar_analysis['total_meetings']
    observations = []
    if calendar_analysis['busiest_day']:
        count = calendar_analysis['busiest_day_count']
        meeting_label = 'timed meeting' if count == 1 else 'timed meetings'
        observations.append(
            f"{calendar_analysis['busiest_day']} is your busiest day, "
            f"with {count} {meeting_label}."
        )

    one_on_ones = calendar_analysis['one_on_ones']
    if one_on_ones:
        meeting_label = 'timed meeting' if total_meetings == 1 else 'timed meetings'
        verb = 'is' if one_on_ones == 1 else 'are'
        observations.append(
            f"{one_on_ones} of your {total_meetings} {meeting_label} "
            f"{verb} {'a 1:1' if one_on_ones == 1 else '1:1s'}."
        )
    elif total_meetings:
        meeting_label = 'timed meeting takes' if total_meetings == 1 else 'timed meetings take'
        observations.append(
            f"Your {total_meetings} {meeting_label} "
            f"{calendar_analysis['meeting_hours']:g} hours this week."
        )

    return {
        'recurring_commitments': recurring_commitments,
        'internal_external_split': meeting_split,
        'observations': observations[:2],
    }


def generate_weekly_plan(events: List[Dict], pillars: List[str], role: str) -> str:
    """Generate weekly plan markdown content from calendar events"""
    from datetime import timedelta
    timed_events = _timed_calendar_events(events)
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
    
    content += "\n## Meeting Overview\n\n"
    content += f"You have **{len(timed_events)} meetings** scheduled this week.\n\n"
    
    # Group by day
    days = {}
    for event in timed_events:
        day = _calendar_event_datetime(event.get('start')).strftime('%A')
        if day not in days:
            days[day] = []
        days[day].append(event)
    
    content += "### Key Meetings\n\n"
    for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
        if day in days:
            content += f"**{day}** ({len(days[day])} meetings)\n"
            for event in days[day][:3]:  # Show first 3
                time = _calendar_event_datetime(event.get('start')).strftime('%I:%M %p')
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

def get_frequent_attendees(events: List[Dict], limit: int = 3) -> List[Dict]:
    """Get most frequent meeting attendees"""
    attendee_data = {}
    
    for event in _timed_calendar_events(events):
        for attendee in _meeting_attendees(event):
            if attendee.get('is_current_user') is True:
                continue
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
        
        meetings = granola_module.get_recent_meetings(days_back=days)
        return meetings if meetings else []
    except Exception as e:
        logger.warning(f"Failed to get Granola meetings: {e}")
        return []

def count_unique_people(meetings: List[Dict]) -> int:
    """Count unique people across meetings"""
    people = set()
    for meeting in meetings:
        for attendee in _meeting_attendees(meeting):
            if attendee.get('is_current_user') is True:
                continue
            email = attendee.get('email', '')
            if email:
                people.add(email.lower())
    return len(people)

def count_external_companies(meetings: List[Dict], email_domain: str) -> int:
    """Count unique external companies based on email domains"""
    internal_domains = {
        domain.strip().lower()
        for domain in email_domain.split(',')
        if domain.strip()
    }
    external_domains = set()
    
    for meeting in meetings:
        for attendee in _meeting_attendees(meeting):
            if attendee.get('is_current_user') is True:
                continue
            email = attendee.get('email', '')
            if '@' in email:
                domain = email.rsplit('@', 1)[1].lower()
                if domain not in internal_domains:
                    external_domains.add(domain)
    
    return len(external_domains)


def run_first_week_analysis() -> Dict[str, Any]:
    """Build the honest, structured first-week reveal used after finalization."""
    try:
        events = get_calendar_events_for_week()
    except Exception as e:
        return {
            "available": False,
            "reason": str(e) or "Calendar data could not be read.",
        }

    timed_events = _timed_calendar_events(events)
    calendar_analysis = analyze_calendar_events(timed_events)
    top_contacts = get_frequent_attendees(timed_events)
    recent_meetings = get_recent_granola_meetings(days=7)
    combined_meetings = [*timed_events, *recent_meetings]

    profile = _load_first_week_profile()
    pillars = [
        pillar.get('name', '') if isinstance(pillar, dict) else str(pillar)
        for pillar in profile.get('pillars', [])
    ]
    pillars = [pillar for pillar in pillars if pillar]

    return {
        "available": True,
        "meeting_count": calendar_analysis['total_meetings'],
        "meeting_hours": calendar_analysis['meeting_hours'],
        "one_on_one_count": calendar_analysis['one_on_ones'],
        "busiest_day": {
            "day": calendar_analysis['busiest_day'],
            "count": calendar_analysis['busiest_day_count'],
        },
        "top_contacts": [
            {
                "name": contact['name'],
                "email": contact['email'],
                "meeting_count": contact['count'],
            }
            for contact in top_contacts
        ],
        "unique_people_count": count_unique_people(combined_meetings),
        "external_company_count": count_external_companies(
            combined_meetings,
            profile.get('email_domain', ''),
        ),
        "recent_meeting_count": len(recent_meetings),
        "pillar_evidence": build_pillar_evidence(
            timed_events,
            profile.get('email_domain', ''),
        ),
        "draft_weekly_plan": generate_weekly_plan(
            timed_events,
            pillars,
            profile.get('role', ''),
        ),
    }

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
                        "description": "Step number (1-7)",
                        "minimum": 1,
                        "maximum": 7
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
            name="save_calendar_selection",
            description="Save the work calendar selected during onboarding, or defer calendar permission setup.",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_calendar": {
                        "type": "string",
                        "description": "Exact work calendar name returned by Calendar.app",
                        "default": ""
                    },
                    "work_email": {
                        "type": "string",
                        "description": "Work email when the selected calendar name is an email address",
                        "default": ""
                    },
                    "calendar_count": {
                        "type": "integer",
                        "description": "Number of calendars returned by Calendar.app",
                        "minimum": 0,
                        "default": 0
                    },
                    "skipped": {
                        "type": "boolean",
                        "description": "Defer calendar setup until permissions can be checked later",
                        "default": False
                    }
                }
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
            name="run_first_week_analysis",
            description="Analyze this week's timed calendar meetings and return an honest, structured onboarding reveal.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="finalize_onboarding",
            description="Complete onboarding: create vault structure, write configs, setup MCP. Requires all steps completed. Use dry_run=true to preview what would be created without making changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, show what would be created without actually creating anything. Used for QA testing.",
                        "default": False
                    }
                }
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
        types.Tool(
            name="cleanup_qa_session",
            description="Delete the QA/test onboarding session file without affecting the real onboarding marker. Use after /qa-onboarding to clean up.",
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
                    f"Resuming onboarding session. Completed steps: {len(session['completed_steps'])}/{ONBOARDING_STEPS}"
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
                result = create_error_response("Invalid step_number", suggestion="Provide step_number as integer 1-7")
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
                no_company_domain = step_data.get('no_company_domain') is True

                if not email_domain and no_company_domain:
                    valid, error_msg, normalized_domain = True, None, ""
                else:
                    valid, error_msg, normalized_domain = validate_email_domain(email_domain)

                if not valid:
                    result = create_error_response(
                        error_msg,
                        step=4,
                        field="email_domain",
                        suggestion=(
                            "Provide a domain (e.g., 'pendo.io' or 'acme.com'). "
                            "If you do not have a company domain, set no_company_domain to true."
                        )
                    )
                else:
                    session['data']['email_domain'] = normalized_domain
                    if step_number not in session['completed_steps']:
                        session['completed_steps'].append(step_number)
                    session['current_step'] = 5
                    save_session(session)
                    result = create_success_response(
                        {"step": 4, "completed": True, "email_domain": normalized_domain},
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

            # Step 7: Optional capability rooms (contract-declared defaults)
            elif step_number == 7:
                supplied = step_data.get('capabilities', {})
                if not isinstance(supplied, dict):
                    result = create_error_response(
                        "Capabilities must be an object",
                        step=7,
                        field="capabilities",
                        suggestion="Answer yes or no for each optional room",
                    )
                else:
                    selected = {}
                    invalid_field = None
                    declared_rooms = set(capability_rooms.room_ids())
                    unknown_rooms = sorted(set(supplied) - declared_rooms)
                    if unknown_rooms:
                        invalid_field = f"capabilities.{unknown_rooms[0]}"
                    for room in capability_rooms.room_ids():
                        if invalid_field:
                            break
                        if room in supplied and not isinstance(supplied[room], bool):
                            invalid_field = f"capabilities.{room}"
                            break
                    selected = _capability_states(supplied)
                    if invalid_field:
                        result = create_error_response(
                            f"{invalid_field} must be true or false",
                            step=7,
                            field=invalid_field,
                            suggestion="Answer yes or no for this room",
                        )
                    else:
                        session['data']['capabilities'] = selected
                        if step_number not in session['completed_steps']:
                            session['completed_steps'].append(step_number)
                        session['current_step'] = 8
                        save_session(session)
                        result = create_success_response(
                            {"step": 7, "completed": True, "capabilities": selected},
                            "Step 7 complete",
                        )
            
            else:
                result = create_error_response(f"Invalid step number: {step_number}", suggestion="Step must be 1-7")
            
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

        elif name == "save_calendar_selection":
            skipped = arguments.get('skipped', False)
            work_calendar = (arguments.get('work_calendar') or '').strip()
            work_email = (arguments.get('work_email') or '').strip()
            calendar_count = arguments.get('calendar_count', 0)

            session = load_session()
            if not session:
                result = create_error_response(
                    "No active session",
                    suggestion="Call start_onboarding_session first"
                )
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            if skipped:
                calendar = {"permissions_pending": True}
                session['data'].pop('work_email', None)
                session['data']['calendar'] = calendar
                save_session(session)
                result = create_success_response(
                    {"calendar": calendar},
                    "Calendar setup skipped for now. /dex-doctor will pick this up later."
                )
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            if not work_calendar:
                result = create_error_response(
                    "work_calendar is required unless calendar setup is skipped",
                    field="work_calendar",
                    suggestion="Choose a calendar name or set skipped=true"
                )
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            verification_note = ""
            try:
                from core.mcp.calendar_server import _get_calendar_list_result

                calendar_list = _get_calendar_list_result()
                if calendar_list.get("success"):
                    available_calendars = calendar_list["calendars"]
                    if work_calendar not in available_calendars:
                        result = create_error_response(
                            f"Calendar '{work_calendar}' was not found. Available calendars: "
                            f"{', '.join(available_calendars)}",
                            field="work_calendar",
                            suggestion="Choose one of the available calendar names"
                        )
                        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
                else:
                    verification_note = (
                        " Couldn't verify against your live calendars — "
                        "/dex-doctor will confirm later."
                    )
            except Exception:
                verification_note = (
                    " Couldn't verify against your live calendars — "
                    "/dex-doctor will confirm later."
                )

            calendar = {
                "work_calendar": work_calendar,
                "calendar_count": calendar_count,
                "lazy_load": True,
            }
            if work_email:
                session['data']['work_email'] = work_email
            else:
                session['data'].pop('work_email', None)
            session['data']['calendar'] = calendar
            save_session(session)

            result = create_success_response(
                {
                    "work_email": work_email,
                    "calendar": calendar,
                    "derived_identity": derive_identity_from_email(work_email),
                },
                f"Work calendar saved.{verification_note}"
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "get_onboarding_status":
            session = load_session()
            
            if not session:
                result = create_error_response("No active session", suggestion="Call start_onboarding_session first")
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
            
            # Step 7 (optional rooms) is skippable: every room defaults OFF, so an
            # unanswered step means the safe default, never a blocker.
            required_steps = [s for s in range(1, ONBOARDING_STEPS + 1) if s != 7]
            completed = session['completed_steps']
            missing = [s for s in required_steps if s not in completed]
            
            step_names = {
                1: "Name",
                2: "Role",
                3: "Company Size",
                4: "Email Domain (CRITICAL)",
                5: "Strategic Pillars",
                6: "Communication Preferences",
                7: "Optional Rooms",
            }
            
            completed_required = [s for s in completed if s in required_steps]
            progress = len(completed_required) / len(required_steps) * 100
            
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

        elif name == "run_first_week_analysis":
            result = create_success_response(run_first_week_analysis())
            return [types.TextContent(
                type="text",
                text=json.dumps(result, indent=2, cls=DateTimeEncoder),
            )]
        
        elif name == "finalize_onboarding":
            dry_run = arguments.get('dry_run', False)
            session = load_session()

            if not session:
                result = create_error_response("No active session", suggestion="Call start_onboarding_session first")
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            # Verify all required steps completed
            # Step 7 (optional rooms) is skippable: every room defaults OFF, so an
            # unanswered step means the safe default, never a blocker.
            required_steps = [s for s in range(1, ONBOARDING_STEPS + 1) if s != 7]
            completed = session['completed_steps']
            missing = [s for s in required_steps if s not in completed]

            if missing:
                step_names = {
                    1: "Name", 2: "Role", 3: "Company Size",
                    4: "Email Domain", 5: "Pillars", 6: "Communication",
                    7: "Optional Rooms",
                }
                result = create_error_response(
                    f"Cannot finalize: missing steps {missing}",
                    suggestion=f"Complete these steps first: {', '.join(step_names[s] for s in missing)}"
                )
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            # Critical check for Step 4
            if 4 not in completed:
                result = create_error_response(
                    "Cannot finalize: email_domain is required",
                    step=4,
                    field="email_domain",
                    suggestion="Go back to Step 4 and provide email domain"
                )
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

            # ---- DRY RUN MODE ----
            if dry_run:
                logger.info("Finalize (DRY RUN) - previewing what would be created")

                # Compute folders that would be created
                selected_capabilities = _capability_states(
                    session['data'].get('capabilities')
                )
                para_folders = _provision_folders(selected_capabilities)
                would_create_folders = [f for f in para_folders if not (BASE_DIR / f).exists()]
                already_exist_folders = [f for f in para_folders if (BASE_DIR / f).exists()]

                # Compute files that would be created
                would_create_files = []
                already_exist_files = []

                tasks_file = BASE_DIR / '03-Tasks' / 'Tasks.md'
                if not tasks_file.exists():
                    would_create_files.append('03-Tasks/Tasks.md')
                else:
                    already_exist_files.append('03-Tasks/Tasks.md')

                priorities_file = BASE_DIR / '02-Week_Priorities' / 'Week_Priorities.md'
                if not priorities_file.exists():
                    would_create_files.append('02-Week_Priorities/Week_Priorities.md')
                else:
                    already_exist_files.append('02-Week_Priorities/Week_Priorities.md')

                would_create_files.append('System/user-profile.yaml')
                would_create_files.append('System/pillars.yaml')

                # Configs that would be updated
                would_update_configs = ['CLAUDE.md (User Profile section)']
                if MCP_CONFIG_EXAMPLE.exists():
                    would_update_configs.append('.mcp.json')

                # Build preview of user-profile.yaml content
                data = session['data']
                profile_preview = {
                    'name': data.get('name', ''),
                    'role': data.get('role', ''),
                    'role_group': data.get('role_group', ''),
                    'company': data.get('company', ''),
                    'company_size': data.get('company_size', ''),
                    'email_domain': data.get('email_domain', ''),
                    'obsidian_mode': data.get('obsidian_mode', False),
                    'entity_creation': {'mode': 'auto'},
                    'communication': data.get('communication', {}),
                    'capabilities': {
                        room: {'enabled': selected_capabilities[room]}
                        for room in capability_rooms.room_ids()
                    },
                }
                if 'calendar' in data:
                    profile_preview['work_email'] = data.get('work_email', '')
                    profile_preview['calendar'] = data['calendar']

                # Build preview of pillars.yaml content
                pillars_preview = []
                for pillar in data.get('pillars', []):
                    pillar_id = pillar.lower().replace(' ', '-').replace('_', '-')
                    pillars_preview.append({'id': pillar_id, 'name': pillar})

                # Completion marker preview
                marker_preview = {
                    'completed_at': '(timestamp)',
                    'user_name': data.get('name', ''),
                    'role': data.get('role', ''),
                    'email_domain': data.get('email_domain', ''),
                    'has_pillars': len(data.get('pillars', [])) > 0,
                    'phase2_completed': False,
                    'pre_analysis_deferred': True
                }

                dry_run_summary = {
                    'dry_run': True,
                    'validation_passed': True,
                    'would_create_folders': would_create_folders,
                    'already_exist_folders': already_exist_folders,
                    'would_create_files': would_create_files,
                    'already_exist_files': already_exist_files,
                    'would_update_configs': would_update_configs,
                    'would_create_marker': marker_preview,
                    'would_delete_session': True,
                    'preview_user_profile': profile_preview,
                    'preview_pillars': pillars_preview,
                    'session_data_snapshot': data
                }

                result = create_success_response(
                    dry_run_summary,
                    f"DRY RUN: Would create {len(would_create_folders)} folders, {len(would_create_files)} files, update {len(would_update_configs)} configs. No changes made."
                )
                return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

            # ---- REAL FINALIZATION ----
            # Execute finalization steps
            summary = {
                "folders_created": [],
                "files_created": [],
                "configs_updated": [],
                "errors": []
            }

            try:
                logger.info("Routing onboarding finalization through the provision contract")
                summary = _finalize_through_provisioner(session)

                result = create_success_response(
                    summary,
                    f"Onboarding complete! Created {len(summary['folders_created'])} folders, {len(summary['files_created'])} files"
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
        
        elif name == "cleanup_qa_session":
            if SESSION_FILE.exists():
                SESSION_FILE.unlink()
                result = create_success_response(
                    {"session_deleted": True},
                    "QA session cleaned up. Session file deleted."
                )
            else:
                result = create_success_response(
                    {"session_deleted": False},
                    "No session file to clean up."
                )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

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
