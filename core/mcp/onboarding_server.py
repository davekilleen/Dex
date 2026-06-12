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
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None

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
from core.paths import (
    CLAUDE_MD,
    MARKER_FILE,
    MCP_CONFIG_EXAMPLE,
    MCP_CONFIG_TARGET,
    PILLARS_FILE,
    SESSION_FILE,
    USER_PROFILE_FILE,
    USER_PROFILE_TEMPLATE,
)
from core.paths import (
    VAULT_ROOT as BASE_DIR,
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
    """Check if Granola is installed (auto-detects latest cache version)"""
    import re as _re

    def _find_latest(granola_dir):
        candidates = sorted(
            granola_dir.glob("cache-v*.json"),
            key=lambda p: int(_re.search(r'v(\d+)', p.name).group(1))
            if _re.search(r'v(\d+)', p.name) else 0,
            reverse=True
        )
        for c in candidates:
            if c.exists():
                return c
        return None

    # Check common Granola cache locations
    if platform.system() == 'Darwin':
        granola_dir = Path.home() / 'Library' / 'Application Support' / 'Granola'
    elif platform.system() == 'Windows':
        appdata = os.getenv('APPDATA') or os.getenv('LOCALAPPDATA')
        if appdata:
            granola_dir = Path(appdata) / 'Granola'
        else:
            granola_dir = None
    else:  # Linux
        granola_dir = Path.home() / '.config' / 'Granola'

    if granola_dir:
        cache_path = _find_latest(granola_dir)
        if cache_path:
            return {"installed": True, "cache_found": True, "path": str(cache_path)}

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

def _profile_value_missing(value) -> bool:
    """True when a profile value is absent or empty (None or empty string)"""
    return value is None or value == ''

def create_user_profile(session_data: Dict) -> tuple[bool, str]:
    """Create user-profile.yaml from session data.

    Existing profiles are preserved: a pre-populated vault (for example one
    adopted from Dex Desktop) keeps its file byte-identical. Fields that are
    missing or empty in the existing profile are filled in additively from
    session data; existing values are never overwritten or dropped.

    Returns (success, outcome) where outcome is 'created', 'preserved',
    or 'merged: <fields>'.
    """
    try:
        data = session_data['data']
        comm = data.get('communication', {})
        session_fields = {
            'name': data.get('name', ''),
            'role': data.get('role', ''),
            'role_group': data.get('role_group', ''),
            'company': data.get('company', ''),
            'company_size': data.get('company_size', ''),
            'email_domain': data.get('email_domain', ''),
        }
        session_communication = {
            'formality': comm.get('formality', 'professional_casual'),
            'directness': comm.get('directness', 'balanced'),
            'career_level': comm.get('career_level', 'mid'),
            'coaching_style': comm.get('coaching_style', 'collaborative'),
        }

        if USER_PROFILE_FILE.exists():
            if not yaml:
                logger.warning("yaml unavailable, preserving existing user-profile.yaml as-is")
                return True, 'preserved'

            with open(USER_PROFILE_FILE, 'r') as f:
                existing = yaml.safe_load(f)
            if not isinstance(existing, dict):
                # Unreadable or non-mapping profile: never overwrite it
                logger.warning("Existing user-profile.yaml is not a mapping, preserving as-is")
                return True, 'preserved'

            # Additive merge: only fill fields the existing profile lacks
            merged_fields = []
            for key, value in session_fields.items():
                if _profile_value_missing(existing.get(key)) and not _profile_value_missing(value):
                    existing[key] = value
                    merged_fields.append(key)
            if data.get('obsidian_mode') and _profile_value_missing(existing.get('obsidian_mode')):
                existing['obsidian_mode'] = True
                merged_fields.append('obsidian_mode')
            existing_comm = existing.get('communication')
            if isinstance(existing_comm, dict):
                for key, value in session_communication.items():
                    if _profile_value_missing(existing_comm.get(key)):
                        existing_comm[key] = value
                        merged_fields.append(f'communication.{key}')
            elif _profile_value_missing(existing_comm):
                existing['communication'] = session_communication
                merged_fields.append('communication')

            if not merged_fields:
                # Nothing to add: leave the file byte-identical
                return True, 'preserved'

            with open(USER_PROFILE_FILE, 'w') as f:
                yaml.dump(existing, f, default_flow_style=False, sort_keys=False)
            return True, 'merged: ' + ', '.join(merged_fields)

        # Fresh vault: create from template
        if not yaml:
            logger.error("yaml unavailable, cannot create user-profile.yaml")
            return False, 'error'
        if not USER_PROFILE_TEMPLATE.exists():
            logger.error("user-profile-template.yaml not found")
            return False, 'error'

        with open(USER_PROFILE_TEMPLATE, 'r') as f:
            profile = yaml.safe_load(f)

        profile.update(session_fields)

        # Update Obsidian mode (defaults to false)
        profile['obsidian_mode'] = data.get('obsidian_mode', False)

        # Update communication preferences
        if 'communication' not in profile:
            profile['communication'] = {}
        profile['communication'].update(session_communication)

        with open(USER_PROFILE_FILE, 'w') as f:
            yaml.dump(profile, f, default_flow_style=False, sort_keys=False)

        return True, 'created'
    except Exception as e:
        logger.error(f"Error creating user profile: {e}")
        return False, 'error'

def create_pillars_file(pillars: List[str]) -> tuple[bool, str]:
    """Create pillars.yaml from pillar list.

    An existing pillars.yaml is preserved byte-identical: an adopted vault's
    pillars are authoritative and never overwritten.

    Returns (success, outcome) where outcome is 'created' or 'preserved'.
    """
    try:
        if PILLARS_FILE.exists():
            return True, 'preserved'

        if not yaml:
            logger.error("yaml unavailable, cannot create pillars.yaml")
            return False, 'error'

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

        return True, 'created'
    except Exception as e:
        logger.error(f"Error creating pillars file: {e}")
        return False, 'error'

# Explicit markers bounding the CLAUDE.md region onboarding owns.
# Content outside these markers is never touched.
CLAUDE_MD_PROFILE_START = '<!-- DEX_USER_PROFILE_START -->'
CLAUDE_MD_PROFILE_END = '<!-- DEX_USER_PROFILE_END -->'

def build_claude_md_profile_section(session_data: Dict) -> str:
    """Build the marker-bounded User Profile section for CLAUDE.md"""
    data = session_data['data']
    lines = [
        CLAUDE_MD_PROFILE_START,
        '## User Profile',
        '',
        '<!-- Updated during onboarding -->',
        f"**Name:** {data.get('name', 'Not configured')}",
        f"**Role:** {data.get('role', 'Not configured')}",
        f"**Company Size:** {data.get('company_size', 'Not configured')}",
        f"**Working Style:** {data.get('communication', {}).get('formality', 'Not configured')}",
        '**Pillars:**',
    ]
    for pillar in data.get('pillars', []):
        lines.append(f"- {pillar}")
    lines.append(CLAUDE_MD_PROFILE_END)
    return '\n'.join(lines)

def update_claude_md(session_data: Dict) -> bool:
    """Update the CLAUDE.md User Profile section.

    The replaced region is bounded by explicit marker comments, so user
    content outside the markers is never touched. A file without markers
    (legacy template or user-edited) gets markers added around only the
    replaced or inserted region. A missing CLAUDE.md is created.
    """
    try:
        profile_section = build_claude_md_profile_section(session_data)

        if not CLAUDE_MD.exists():
            logger.info("CLAUDE.md not found, creating it with the profile section")
            CLAUDE_MD.write_text(
                "# Dex - Your Personal Knowledge System\n\n" + profile_section + "\n\n---\n"
            )
            return True

        content = CLAUDE_MD.read_text()

        if CLAUDE_MD_PROFILE_START in content and CLAUDE_MD_PROFILE_END in content:
            # Marker-bounded replacement: only the marked region changes
            pattern = re.escape(CLAUDE_MD_PROFILE_START) + r'.*?' + re.escape(CLAUDE_MD_PROFILE_END)
            content = re.sub(pattern, lambda _m: profile_section, content, count=1, flags=re.DOTALL)
        elif re.search(r'## User Profile.*?\n---', content, flags=re.DOTALL):
            # Legacy template section without markers: replace it once and
            # add markers around only the inserted region
            content = re.sub(
                r'## User Profile.*?\n---',
                lambda _m: profile_section + '\n\n---',
                content,
                count=1,
                flags=re.DOTALL,
            )
        else:
            # No recognizable profile region: append a marker-bounded section,
            # leaving every existing line untouched
            if content and not content.endswith('\n'):
                content += '\n'
            content += '\n' + profile_section + '\n'

        CLAUDE_MD.write_text(content)
        return True
    except Exception as e:
        logger.error(f"Error updating CLAUDE.md: {e}")
        return False

def setup_mcp_config(vault_path: Path) -> tuple[bool, Optional[str], Dict]:
    """Setup System/.mcp.json from the example template.

    A missing target is created from the example with {{VAULT_PATH}}
    substituted. An existing target is merged additively: server entries the
    user already has are never overwritten, only example servers that are
    missing get added. The returned report states exactly what happened:
    action is 'created', 'merged', or 'unchanged'.
    """
    report = {"action": "none", "merged_servers": [], "preserved_servers": []}
    try:
        if not MCP_CONFIG_EXAMPLE.exists():
            return False, ".mcp.json.example not found", report

        # Read example and replace {{VAULT_PATH}} with actual path
        with open(MCP_CONFIG_EXAMPLE, 'r') as f:
            config_content = f.read()
        config_content = config_content.replace('{{VAULT_PATH}}', str(vault_path))

        # Validate JSON
        try:
            example_config = json.loads(config_content)
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON after substitution: {e}", report

        if not MCP_CONFIG_TARGET.exists():
            with open(MCP_CONFIG_TARGET, 'w') as f:
                f.write(config_content)
            report["action"] = "created"
            return True, None, report

        # Existing config: merge additively, never blind-overwrite
        try:
            existing_config = json.loads(MCP_CONFIG_TARGET.read_text())
        except json.JSONDecodeError as e:
            return False, f"Existing System/.mcp.json is not valid JSON, left untouched: {e}", report
        if not isinstance(existing_config, dict):
            return False, "Existing System/.mcp.json is not a JSON object, left untouched", report

        existing_servers = existing_config.setdefault('mcpServers', {})
        for server_name, server_config in example_config.get('mcpServers', {}).items():
            if server_name in existing_servers:
                report["preserved_servers"].append(server_name)
            else:
                existing_servers[server_name] = server_config
                report["merged_servers"].append(server_name)

        if not report["merged_servers"]:
            # Nothing to add: leave the file byte-identical
            report["action"] = "unchanged"
            return True, None, report

        with open(MCP_CONFIG_TARGET, 'w') as f:
            json.dump(existing_config, f, indent=2)
            f.write('\n')
        report["action"] = "merged"
        return True, None, report
    except Exception as e:
        return False, str(e), report

def vault_is_adopted() -> bool:
    """Check whether the completion marker carries the adopted flag.

    The adopt-existing-vault path writes the marker with "adopted": true.
    Proactive Phase 2 vault writes are suppressed on adopted vaults.
    """
    try:
        if MARKER_FILE.exists():
            marker_data = json.loads(MARKER_FILE.read_text())
            return bool(marker_data.get('adopted', False))
    except Exception as e:
        logger.warning(f"Could not read completion marker for adopted flag: {e}")
    return False

def _prefill_pillars_from_file() -> List[str]:
    """Read pillar names from an existing System/pillars.yaml, if usable."""
    try:
        if yaml and PILLARS_FILE.exists():
            data = yaml.safe_load(PILLARS_FILE.read_text())
            if isinstance(data, dict):
                names = [
                    p.get('name')
                    for p in data.get('pillars', [])
                    if isinstance(p, dict) and isinstance(p.get('name'), str) and p.get('name').strip()
                ]
                return [n.strip() for n in names]
    except Exception as e:
        logger.warning(f"Could not read pillars.yaml for pre-fill: {e}")
    return []

def prefill_session_from_existing_config() -> Optional[Dict]:
    """Build a pre-filled onboarding session from existing System config.

    Used on adopted vaults (the completion marker carries "adopted": true,
    written by the adopt-existing-vault path) so the user is never
    re-interviewed for answers their vault already holds. Steps whose answers
    exist in System/user-profile.yaml (and pillars in System/pillars.yaml)
    are marked complete; anything genuinely missing stays open so the
    standard interview asks only those questions.

    Returns None when System/user-profile.yaml is absent or unreadable; the
    caller then falls back to the standard interview. The adopted flag in the
    marker keeps gating Phase 2 writes in both cases.
    """
    if not yaml or not USER_PROFILE_FILE.exists():
        return None
    try:
        profile = yaml.safe_load(USER_PROFILE_FILE.read_text())
    except Exception as e:
        logger.warning(f"Could not read user-profile.yaml for pre-fill: {e}")
        return None
    if not isinstance(profile, dict):
        return None

    session = create_new_session()
    session['prefilled'] = True
    session['prefill_source'] = 'System/user-profile.yaml'
    data = session['data']
    completed = session['completed_steps']

    if not _profile_value_missing(profile.get('name')):
        data['name'] = str(profile['name'])
        completed.append(1)
    if not _profile_value_missing(profile.get('role')):
        data['role'] = str(profile['role'])
        data['role_group'] = str(profile.get('role_group') or 'product')
        completed.append(2)
    if not _profile_value_missing(profile.get('company_size')):
        # Existing values are authoritative even when they use a different
        # vocabulary than the interview enums; the profile file itself is
        # preserved untouched by finalize either way.
        data['company'] = str(profile.get('company') or '')
        data['company_size'] = str(profile['company_size'])
        completed.append(3)
    email_domain = profile.get('email_domain')
    if not _profile_value_missing(email_domain) and validate_email_domain(str(email_domain))[0]:
        data['email_domain'] = str(email_domain)
        completed.append(4)
    pillars = _prefill_pillars_from_file()
    if validate_pillars(pillars)[0]:
        data['pillars'] = pillars
        completed.append(5)
    # Communication preferences default sensibly; an adopted user is never
    # re-asked about formality. The existing profile values win when present.
    comm = profile.get('communication')
    comm = comm if isinstance(comm, dict) else {}
    data['communication'] = {
        'formality': comm.get('formality', 'professional_casual'),
        'directness': comm.get('directness', 'balanced'),
        'career_level': comm.get('career_level', 'mid'),
        'coaching_style': comm.get('coaching_style', 'collaborative'),
    }
    data['obsidian_mode'] = bool(profile.get('obsidian_mode', False))
    completed.append(6)

    remaining = [s for s in (1, 2, 3, 4, 5, 6) if s not in completed]
    session['current_step'] = remaining[0] if remaining else 7
    return session

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
    
    content += "\n## Meeting Overview\n\n"
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

def write_weekly_plan(content: str, force: bool = False) -> bool:
    """Write weekly plan to file.

    On adopted vaults this proactive Phase 2 write is suppressed unless
    force=True: propose the plan to the user and write only on approval.
    """
    if vault_is_adopted() and not force:
        logger.info("Adopted vault: weekly plan write suppressed, propose it to the user instead")
        return False
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

def create_person_page(contact: Dict, email_domain: str, force: bool = False) -> bool:
    """Create a person page, routing to Internal or External based on email domain.

    On adopted vaults this proactive Phase 2 write is suppressed unless
    force=True: propose each page to the user and create only on approval.
    """
    if vault_is_adopted() and not force:
        logger.info(
            f"Adopted vault: person page for {contact.get('name', 'unknown')} suppressed, propose it instead"
        )
        return False
    try:
        email = contact['email']
        name = contact['name']
        
        # Determine if internal or external
        contact_domain = email.split('@')[1] if '@' in email else ''
        is_internal = contact_domain in email_domain.split(',')
        
        # Create appropriate folder
        folder = 'Internal' if is_internal else 'External'
        from core.paths import PEOPLE_DIR
        people_dir = PEOPLE_DIR / folder
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
            description="Complete onboarding: create vault structure, write configs, setup MCP. Requires all steps completed. Use dry_run=true to preview what would be created without making changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {
                        "type": "boolean",
                        "description": "If true, show what would be created without actually creating anything. Used for QA testing.",
                        "default": False
                    },
                    "adopted": {
                        "type": "boolean",
                        "description": "Mark this vault as adopted from an existing setup (for example Dex Desktop). Recorded in the completion marker and suppresses proactive Phase 2 writes.",
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
                    f"Resuming onboarding session. Completed steps: {len(session['completed_steps'])}/6"
                )
            else:
                if session and force_new:
                    logger.info("Creating new session (force_new=True)")

                prefilled = None
                if vault_is_adopted():
                    # Existing-vault path: pre-fill from System config so the
                    # user is not re-interviewed. Falls back to the standard
                    # interview when that config is absent; the adopted flag
                    # in the marker keeps gating Phase 2 writes either way.
                    prefilled = prefill_session_from_existing_config()

                if prefilled:
                    session = prefilled
                    save_session(session)
                    completed_count = len(session['completed_steps'])
                    if completed_count == 6:
                        guidance = (
                            "Adopted vault detected: onboarding pre-filled from "
                            "System/user-profile.yaml. All 6 steps are complete. Do not "
                            "re-interview; show the user what was found, confirm it still "
                            "looks right, then call finalize_onboarding (existing config "
                            "files are preserved)."
                        )
                    else:
                        guidance = (
                            f"Adopted vault detected: onboarding pre-filled from "
                            f"System/user-profile.yaml ({completed_count}/6 steps). Ask "
                            f"only the missing steps, then finalize as normal."
                        )
                    result = create_success_response(session, guidance)
                else:
                    session = create_new_session()
                    save_session(session)
                    if vault_is_adopted():
                        result = create_success_response(
                            session,
                            "New onboarding session created. This vault is adopted but has "
                            "no readable System/user-profile.yaml, so run the standard "
                            "interview; the adopted flag still applies at finalize."
                        )
                    else:
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
            dry_run = arguments.get('dry_run', False)
            # The adopted flag comes from the adopt-existing-vault path, either
            # as an explicit argument or already present in a pre-written marker
            adopted = bool(arguments.get('adopted', False)) or vault_is_adopted()
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

            # ---- DRY RUN MODE ----
            if dry_run:
                logger.info("Finalize (DRY RUN) - previewing what would be created")

                # Compute folders that would be created
                para_folders = [
                    "04-Projects", "05-Areas/People/Internal", "05-Areas/People/External",
                    "05-Areas/Companies", "00-Inbox/Meetings", "00-Inbox/Ideas",
                    "06-Resources/Learnings", "06-Resources/Quarterly_Reviews",
                    "07-Archives/04-Projects", "07-Archives/Plans", "07-Archives/Reviews",
                    "System/Templates", "01-Quarter_Goals", "03-Tasks", "02-Week_Priorities"
                ]
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

                # Config files are preserved when they already exist, so the
                # dry run must report them truthfully
                if USER_PROFILE_FILE.exists():
                    already_exist_files.append('System/user-profile.yaml')
                else:
                    would_create_files.append('System/user-profile.yaml')
                if PILLARS_FILE.exists():
                    already_exist_files.append('System/pillars.yaml')
                else:
                    would_create_files.append('System/pillars.yaml')

                # Configs that would be updated
                if CLAUDE_MD.exists():
                    would_update_configs = ['CLAUDE.md (User Profile section)']
                else:
                    would_update_configs = ['CLAUDE.md (create with User Profile section)']
                if MCP_CONFIG_EXAMPLE.exists():
                    if MCP_CONFIG_TARGET.exists():
                        would_update_configs.append('System/.mcp.json (merge missing servers into existing)')
                    else:
                        would_update_configs.append('System/.mcp.json')

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
                    'communication': data.get('communication', {})
                }

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
                    'pre_analysis_deferred': True,
                    'adopted': adopted
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
                "files_preserved": [],
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

                # 3. Create or preserve user-profile.yaml
                logger.info("Creating user-profile.yaml")
                profile_ok, profile_outcome = create_user_profile(session)
                if profile_ok:
                    if profile_outcome == 'created':
                        summary['files_created'].append('System/user-profile.yaml')
                    else:
                        summary['files_preserved'].append(f"System/user-profile.yaml ({profile_outcome})")
                else:
                    summary['errors'].append("Could not create user-profile.yaml")

                # 4. Create or preserve pillars.yaml
                logger.info("Creating pillars.yaml")
                pillars_ok, pillars_outcome = create_pillars_file(session['data']['pillars'])
                if pillars_ok:
                    if pillars_outcome == 'created':
                        summary['files_created'].append('System/pillars.yaml')
                    else:
                        summary['files_preserved'].append(f"System/pillars.yaml ({pillars_outcome})")
                else:
                    summary['errors'].append("Could not create pillars.yaml")

                # 5. Update CLAUDE.md
                logger.info("Updating CLAUDE.md")
                if update_claude_md(session):
                    summary['configs_updated'].append('CLAUDE.md')
                else:
                    summary['errors'].append("Could not update CLAUDE.md")

                # 6. Setup MCP config (create, or merge into an existing one)
                logger.info("Setting up .mcp.json")
                success, error, mcp_report = setup_mcp_config(BASE_DIR)
                if success:
                    if mcp_report['action'] == 'merged':
                        merged = ', '.join(mcp_report['merged_servers'])
                        summary['configs_updated'].append(f"System/.mcp.json (merged: {merged})")
                    elif mcp_report['action'] == 'unchanged':
                        summary['files_preserved'].append('System/.mcp.json (already configured)')
                    else:
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
                    "pre_analysis_deferred": True,  # Analysis moved to /getting-started for performance
                    "adopted": adopted  # True when this vault was adopted, gates Phase 2 writes
                }
                MARKER_FILE.write_text(json.dumps(marker_data, indent=2, cls=DateTimeEncoder))
                logger.info("Completion marker created")

                # 8. Delete session file
                if SESSION_FILE.exists():
                    SESSION_FILE.unlink()
                    logger.info("Deleted session file")

                completion_message = (
                    f"Onboarding complete! Created {len(folders)} folders, {len(summary['files_created'])} files"
                )
                if summary['files_preserved']:
                    completion_message += f", preserved {len(summary['files_preserved'])} existing files"
                result = create_success_response(summary, completion_message)
                
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
                completed_at_raw = marker_data.get('completed_at')
                if completed_at_raw:
                    completed_at = datetime.fromisoformat(completed_at_raw)
                    age_days = (datetime.now() - completed_at).days
                else:
                    # Tolerate a minimal marker (for example one written by
                    # the adopt-existing-vault path before finalize runs)
                    age_days = 0

                result = create_success_response({
                    "complete": True,
                    "age_days": age_days,
                    "is_new_vault": age_days <= 7,
                    "phase2_completed": marker_data.get('phase2_completed', False),
                    "adopted": marker_data.get('adopted', False),
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
