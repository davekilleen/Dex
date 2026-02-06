#!/usr/bin/env python3
"""
MCP Server for Dex Work Management System
Manages the complete planning hierarchy: quarterly goals → weekly priorities → daily tasks.

Provides deterministic operations through structured tools with:
- Schema validation
- Deduplication
- Ambiguity detection
- Priority limits
- Pillar alignment (loaded from System/pillars.yaml)
- Progress tracking and rollup across planning levels
"""

import os
import sys
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta, date
from collections import Counter
from difflib import SequenceMatcher

try:
    import yaml
except ImportError:
    yaml = None  # Will fall back to defaults if yaml not available

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Set up logging first (before any imports that might use it)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add grandparent directory to path for 'core.utils' imports
# The script is at core/mcp/work_server.py, so we need to add the vault root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import reference formatter for Obsidian wiki link support
try:
    from core.utils.reference_formatter import (
        format_person_reference,
        format_project_reference,
        format_company_reference,
        format_meeting_reference,
        format_task_reference,
        get_obsidian_mode
    )
    HAS_REFERENCE_FORMATTER = True
except ImportError:
    logger.warning("Reference formatter not available - wiki links disabled")
    HAS_REFERENCE_FORMATTER = False

# Custom JSON encoder for handling date/datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

# Configuration - Vault paths
BASE_DIR = Path(os.environ.get('VAULT_PATH', Path.cwd()))
TASKS_FILE = BASE_DIR / '03-Tasks/Tasks.md'
WEEK_PRIORITIES_FILE = BASE_DIR / 'Inbox' / 'Week Priorities.md'
QUARTER_GOALS_FILE = BASE_DIR / '01-Quarter_Goals/Quarter_Goals.md'
GOALS_FILE = BASE_DIR / 'GOALS.md'  # Legacy, kept for compatibility
INBOX_DIR = BASE_DIR / 'Inbox'
PILLARS_FILE = BASE_DIR / 'System' / 'pillars.yaml'
COMPANIES_DIR = BASE_DIR / 'Active' / 'Relationships' / 'Companies'
PEOPLE_DIR = BASE_DIR / 'People'
MEETINGS_DIR = BASE_DIR / 'Inbox' / 'Meetings'

# Demo Mode Configuration
USER_PROFILE_FILE = BASE_DIR / 'System' / 'user-profile.yaml'
DEMO_DIR = BASE_DIR / 'System' / 'Demo'

def is_demo_mode() -> bool:
    """Check if demo mode is enabled in user-profile.yaml"""
    if not USER_PROFILE_FILE.exists() or yaml is None:
        return False
    
    try:
        content = USER_PROFILE_FILE.read_text()
        data = yaml.safe_load(content)
        return bool(data.get('demo_mode', False))
    except Exception as e:
        logger.error(f"Error checking demo mode: {e}")
        return False

def get_tasks_file() -> Path:
    """Get the appropriate 03-Tasks/Tasks.md file based on demo mode"""
    if is_demo_mode():
        return DEMO_DIR / '03-Tasks/Tasks.md'
    return TASKS_FILE

def get_pillars_file() -> Path:
    """Get the appropriate pillars.yaml file based on demo mode"""
    if is_demo_mode():
        demo_pillars = DEMO_DIR / 'pillars.yaml'
        if demo_pillars.exists():
            return demo_pillars
    return PILLARS_FILE

def get_week_priorities_file() -> Path:
    """Get the appropriate Week Priorities file based on demo mode"""
    if is_demo_mode():
        return DEMO_DIR / 'Inbox' / 'Week Priorities.md'
    return WEEK_PRIORITIES_FILE

def get_people_dir() -> Path:
    """Get the appropriate People directory based on demo mode"""
    if is_demo_mode():
        return DEMO_DIR / 'People'
    return PEOPLE_DIR

def get_meetings_dir() -> Path:
    """Get the appropriate Meetings directory based on demo mode"""
    if is_demo_mode():
        return DEMO_DIR / 'Inbox' / 'Meetings'
    return MEETINGS_DIR


# Default pillars (used if pillars.yaml doesn't exist or can't be loaded)
DEFAULT_PILLARS = {
    'pillar_1': {
        'name': 'Pillar 1',
        'description': 'Your first strategic focus area',
        'keywords': ['focus', 'priority', 'main']
    },
    'pillar_2': {
        'name': 'Pillar 2',
        'description': 'Your second strategic focus area',
        'keywords': ['secondary', 'support']
    },
    'pillar_3': {
        'name': 'Pillar 3',
        'description': 'Your third strategic focus area',
        'keywords': ['growth', 'learning']
    }
}

# Default priority limits
DEFAULT_PRIORITY_LIMITS = {
    'P0': 3,   # Critical/urgent - max 3 at a time
    'P1': 5,   # Important - max 5 at a time
    'P2': 10,  # Normal - suggested limit
}

def load_pillars_from_yaml() -> Dict[str, Dict]:
    """Load pillars configuration from System/pillars.yaml"""
    if not get_pillars_file().exists():
        logger.info(f"Pillars file not found at {get_pillars_file()}, using defaults")
        return DEFAULT_PILLARS
    
    if yaml is None:
        logger.warning("PyYAML not installed, using default pillars")
        return DEFAULT_PILLARS
    
    try:
        content = get_pillars_file().read_text()
        data = yaml.safe_load(content)
        
        if not data or 'pillars' not in data:
            logger.warning("No pillars found in YAML, using defaults")
            return DEFAULT_PILLARS
        
        pillars = {}
        for pillar in data['pillars']:
            pillar_id = pillar.get('id', f"pillar_{len(pillars)+1}")
            pillars[pillar_id] = {
                'name': pillar.get('name', pillar_id),
                'description': pillar.get('description', ''),
                'keywords': pillar.get('keywords', [])
            }
        
        if not pillars:
            logger.warning("Empty pillars list in YAML, using defaults")
            return DEFAULT_PILLARS
            
        logger.info(f"Loaded {len(pillars)} pillars from {get_pillars_file()}")
        return pillars
        
    except Exception as e:
        logger.error(f"Error loading pillars from YAML: {e}")
        return DEFAULT_PILLARS

def load_priority_limits_from_yaml() -> Dict[str, int]:
    """Load priority limits from System/pillars.yaml"""
    if not get_pillars_file().exists() or yaml is None:
        return DEFAULT_PRIORITY_LIMITS
    
    try:
        content = get_pillars_file().read_text()
        data = yaml.safe_load(content)
        
        if data and 'priority_limits' in data:
            return {
                'P0': data['priority_limits'].get('P0', 3),
                'P1': data['priority_limits'].get('P1', 5),
                'P2': data['priority_limits'].get('P2', 10),
            }
    except Exception as e:
        logger.error(f"Error loading priority limits: {e}")
    
    return DEFAULT_PRIORITY_LIMITS

# Load configuration at startup
PILLARS = load_pillars_from_yaml()
PRIORITY_LIMITS = load_priority_limits_from_yaml()

# Priority configuration
PRIORITIES = ['P0', 'P1', 'P2', 'P3']

# Status codes
STATUS_CODES = {
    'n': 'not_started',
    's': 'started',
    'b': 'blocked',
    'd': 'done'
}

# Deduplication configuration
DEDUP_CONFIG = {
    "similarity_threshold": 0.6,
    "check_keywords": True,
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def extract_keywords(text: str) -> set:
    """Extract meaningful keywords from text"""
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                  'with', 'from', 'up', 'out', 'is', 'are', 'was', 'were', 'be', 'been',
                  'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
                  'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
                  'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they'}
    words = re.findall(r'\b\w+\b', text.lower())
    return {w for w in words if w not in stop_words and len(w) > 2}

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two strings (0-1 score)"""
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

def guess_pillar(item: str) -> Optional[str]:
    """Guess which pillar a task belongs to based on keywords"""
    item_lower = item.lower()
    item_keywords = extract_keywords(item)
    
    best_match = None
    best_score = 0
    
    for pillar_id, pillar_info in PILLARS.items():
        score = 0
        for keyword in pillar_info['keywords']:
            if keyword in item_lower:
                score += 2
            if keyword in item_keywords:
                score += 1
        
        if score > best_score:
            best_score = score
            best_match = pillar_id
    
    return best_match if best_score > 0 else None

def guess_priority(item: str) -> str:
    """Guess priority based on task text"""
    item_lower = item.lower()
    
    # P0 indicators
    if any(word in item_lower for word in ['urgent', 'critical', 'today', 'asap', 'eod', 'immediately']):
        return 'P0'
    
    # P1 indicators
    if any(word in item_lower for word in ['this week', 'important', 'deadline', 'due', 'follow up']):
        return 'P1'
    
    # P3 indicators (low priority)
    if any(word in item_lower for word in ['someday', 'maybe', 'explore', 'consider', 'idea']):
        return 'P3'
    
    # Default
    return 'P2'

def generate_task_id() -> str:
    """Generate a unique task ID in format: task-YYYYMMDD-XXX"""
    date_str = datetime.now().strftime('%Y%m%d')
    
    # Find existing task IDs for today to get next sequential number
    existing_ids = []
    for md_file in BASE_DIR.rglob('*.md'):
        try:
            content = md_file.read_text()
            pattern = f'\\^task-{date_str}-(\\d{{3}})'
            matches = re.findall(pattern, content)
            existing_ids.extend([int(m) for m in matches])
        except Exception:
            continue
    
    # Get next available number
    next_num = max(existing_ids, default=0) + 1
    return f"task-{date_str}-{next_num:03d}"

def extract_task_id(line: str) -> Optional[str]:
    """Extract task ID from a line"""
    match = re.search(r'\^(task-\d{8}-\d{3})', line)
    return match.group(1) if match else None

def find_task_by_id(task_id: str) -> List[Dict[str, Any]]:
    """Find all instances of a task ID across all markdown files"""
    instances = []
    
    for md_file in BASE_DIR.rglob('*.md'):
        try:
            content = md_file.read_text()
            lines = content.split('\n')
            
            for i, line in enumerate(lines):
                if f'^{task_id}' in line and ('- [ ]' in line or '- [x]' in line):
                    # Extract task title
                    title_match = re.match(r'-\s*\[[x ]\]\s*\*?\*?(.+?)\*?\*?\s*\^', line.strip())
                    title = title_match.group(1).strip() if title_match else line.strip()
                    
                    instances.append({
                        'file': str(md_file),
                        'line_number': i + 1,
                        'line_content': line,
                        'title': title,
                        'completed': '- [x]' in line
                    })
        except Exception as e:
            logger.error(f"Error reading {md_file}: {e}")
            continue
    
    return instances

def update_task_status_everywhere(task_id: str, completed: bool) -> Dict[str, Any]:
    """Update task status for all instances of a task ID across all files"""
    instances = find_task_by_id(task_id)
    
    if not instances:
        return {
            'success': False,
            'error': f'No task found with ID: {task_id}'
        }
    
    updated_files = []
    completion_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    for instance in instances:
        try:
            filepath = Path(instance['file'])
            content = filepath.read_text()
            lines = content.split('\n')
            
            line_idx = instance['line_number'] - 1
            old_line = lines[line_idx]
            
            # Update checkbox and add/remove completion timestamp
            if completed:
                new_line = old_line.replace('- [ ]', '- [x]')
                
                # Add completion timestamp after task ID if not already present
                # Remove any existing timestamp first
                new_line = re.sub(r'\s*✅\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}', '', new_line)
                
                # Find position after task ID to insert timestamp
                task_id_match = re.search(r'\^' + re.escape(task_id), new_line)
                if task_id_match:
                    insert_pos = task_id_match.end()
                    new_line = new_line[:insert_pos] + f' ✅ {completion_timestamp}' + new_line[insert_pos:]
            else:
                # Uncompleting: change checkbox and remove timestamp
                new_line = old_line.replace('- [x]', '- [ ]')
                new_line = re.sub(r'\s*✅\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}', '', new_line)
            
            if new_line != old_line:
                lines[line_idx] = new_line
                filepath.write_text('\n'.join(lines))
                updated_files.append({
                    'file': str(filepath),
                    'line': instance['line_number']
                })
        except Exception as e:
            logger.error(f"Error updating {instance['file']}: {e}")
            continue
    
    return {
        'success': True,
        'task_id': task_id,
        'title': instances[0]['title'] if instances else '',
        'status': 'completed' if completed else 'not_completed',
        'completed_at': completion_timestamp if completed else None,
        'updated_files': updated_files,
        'instances_found': len(instances)
    }

def get_pillar_ids() -> List[str]:
    """Get list of valid pillar IDs"""
    return list(PILLARS.keys())

# ============================================================================
# AMBIGUITY DETECTION
# ============================================================================

VAGUE_PATTERNS = [
    r'^(fix|update|improve|check|review|look at|work on)\s+(the|a|an)?\s*\w+$',
    r'^\w+\s+(stuff|thing|issue|problem)$',
    r'^(follow up|reach out|contact|email)$',
    r'^(investigate|research|explore)\s*\w{0,20}$',
]

def is_ambiguous(item: str) -> bool:
    """Check if an item is too vague or ambiguous"""
    item_lower = item.lower().strip()
    
    # Check if too short
    if len(item_lower.split()) <= 2:
        return True
    
    # Check vague patterns
    for pattern in VAGUE_PATTERNS:
        if re.match(pattern, item_lower):
            return True
    
    return False

def generate_clarification_questions(item: str) -> List[str]:
    """Generate clarification questions for ambiguous items"""
    questions = []
    item_lower = item.lower()
    
    if any(word in item_lower for word in ['fix', 'bug', 'error', 'issue']):
        questions.append("Which specific bug or error? Can you provide more details?")
        questions.append("What component or feature is affected?")
    
    if any(word in item_lower for word in ['update', 'improve', 'refactor']):
        questions.append("What specific aspects need updating/improvement?")
        questions.append("What's the success criteria for this task?")
    
    if any(word in item_lower for word in ['email', 'contact', 'reach out', 'follow up']):
        questions.append("Who should be contacted?")
        questions.append("What's the purpose or goal of this outreach?")
    
    if any(word in item_lower for word in ['research', 'investigate', 'explore']):
        questions.append("What specific questions need to be answered?")
        questions.append("What decisions will this research inform?")
    
    if not questions:
        questions.append("Can you provide more specific details about what needs to be done?")
        questions.append("What's the expected outcome or deliverable?")
    
    return questions

# ============================================================================
# RELATED TASKS SYNC FUNCTIONS
# ============================================================================

def extract_file_refs_from_task(task_line: str) -> List[str]:
    """Extract file path references from a task line
    
    Detects:
    - Direct file paths (People/External/John_Doe.md)
    - Active/Relationships paths
    - Any .md file references
    """
    refs = []
    
    # Match file path patterns like People/External/John_Doe.md or Active/Relationships/...
    path_pattern = r'(?:People|Active)/[A-Za-z0-9_/-]+(?:\.md)?'
    refs.extend(re.findall(path_pattern, task_line))
    
    # Also match explicit markdown file references
    md_pattern = r'(?<!\[)\b([A-Za-z0-9_/-]+\.md)\b(?!\])'
    refs.extend(re.findall(md_pattern, task_line))
    
    return list(set(refs))

def find_tasks_for_page(page_path: str) -> List[Dict[str, Any]]:
    """Find all tasks in 03-Tasks/Tasks.md that reference a given page"""
    if not get_tasks_file().exists():
        return []
    
    content = get_tasks_file().read_text()
    lines = content.split('\n')
    
    # Normalize page path for matching
    page_name = Path(page_path).stem.lower()
    page_path_lower = page_path.lower()
    
    matching_tasks = []
    current_section = None
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Track section headers
        if line.startswith('# ') or line.startswith('## '):
            current_section = line.lstrip('#').strip()
            i += 1
            continue
        
        # Check if this is a task line
        if line.strip().startswith('- [ ]') or line.strip().startswith('- [x]'):
            completed = line.strip().startswith('- [x]')
            
            # Check if this task references the page
            file_refs = extract_file_refs_from_task(line)
            task_mentions_page = any(
                page_name in ref.lower() or page_path_lower in ref.lower()
                for ref in file_refs
            )
            
            # Also check if page name appears in task text
            if not task_mentions_page:
                task_mentions_page = page_name in line.lower()
            
            if task_mentions_page:
                # Extract title
                title_match = re.match(r'-\s*\[[x ]\]\s*\*?\*?(.+?)\*?\*?(?:\s*\|.*)?$', line.strip())
                title = title_match.group(1).strip() if title_match else line.strip()[6:]
                
                # Clean title of file references for display
                clean_title = re.sub(r'\s*\|\s*(?:People|Active)/[^\s]+', '', title)
                clean_title = re.sub(r'\s+\.md\b', '', clean_title)
                clean_title = re.sub(r'\s*\|.*$', '', clean_title)  # Remove trailing | refs
                
                # Look for context/priority in following lines
                priority = 'P2'
                j = i + 1
                while j < len(lines) and lines[j].strip().startswith('\t-'):
                    if 'Priority:' in lines[j]:
                        priority_match = re.search(r'Priority:\s*(P[0-3])', lines[j])
                        if priority_match:
                            priority = priority_match.group(1)
                    j += 1
                
                matching_tasks.append({
                    'title': clean_title,
                    'completed': completed,
                    'priority': priority,
                    'section': current_section,
                    'line_number': i + 1
                })
        
        i += 1
    
    return matching_tasks

def update_related_tasks_section(page_path: str, tasks: List[Dict[str, Any]]) -> bool:
    """Update the Related Tasks section in a page"""
    filepath = BASE_DIR / page_path
    if not page_path.endswith('.md'):
        filepath = BASE_DIR / f"{page_path}.md"
    
    if not filepath.exists():
        logger.warning(f"Page not found: {filepath}")
        return False
    
    content = filepath.read_text()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # Build the new Related Tasks section
    section_content = f"## Related Tasks\n*Synced from 03-Tasks/Tasks.md — {timestamp}*\n\n"
    
    if tasks:
        section_content += "| Status | Task | Priority |\n"
        section_content += "|--------|------|----------|\n"
        for task in tasks:
            status = "✅" if task['completed'] else "⏳"
            section_content += f"| {status} | {task['title']} | {task['priority']} |\n"
    else:
        section_content += "*No related tasks*\n"
    
    # Check if section already exists
    section_pattern = r'## Related Tasks\n.*?(?=\n## |\n# |\Z)'
    if re.search(section_pattern, content, re.DOTALL):
        # Replace existing section
        new_content = re.sub(section_pattern, section_content.rstrip(), content, flags=re.DOTALL)
    else:
        # Add section before any existing ## sections or at the end
        # Find the best place to insert (after frontmatter and intro, before other sections)
        lines = content.split('\n')
        insert_idx = len(lines)
        
        # Find first ## that's not "Related Tasks"
        for i, line in enumerate(lines):
            if line.startswith('## ') and not line.startswith('## Related Tasks'):
                insert_idx = i
                break
        
        lines.insert(insert_idx, '\n' + section_content)
        new_content = '\n'.join(lines)
    
    filepath.write_text(new_content)
    return True

def sync_task_refs_for_page(page_path: str) -> Dict[str, Any]:
    """Sync Related Tasks section for a page by reading 03-Tasks/Tasks.md"""
    tasks = find_tasks_for_page(page_path)
    success = update_related_tasks_section(page_path, tasks)
    
    return {
        "success": success,
        "page": page_path,
        "tasks_found": len(tasks),
        "tasks": tasks
    }

def propagate_task_status_to_refs(task_title: str, completed: bool) -> List[str]:
    """Update task status in all referenced pages' Related Tasks sections"""
    updated_pages = []
    
    # Find all pages that might reference this task
    # Look for WikiLinks in the task line
    if not get_tasks_file().exists():
        return updated_pages
    
    content = get_tasks_file().read_text()
    
    # Find the task line
    for line in content.split('\n'):
        if task_title.lower() in line.lower() and ('- [ ]' in line or '- [x]' in line):
            file_refs = extract_file_refs_from_task(line)
            for ref in file_refs:
                result = sync_task_refs_for_page(ref)
                if result['success']:
                    updated_pages.append(ref)
            break
    
    return updated_pages

# ============================================================================
# COMPANY AGGREGATION FUNCTIONS
# ============================================================================

def parse_person_page(filepath: Path) -> Dict[str, Any]:
    """Parse a person page and extract key fields"""
    if not filepath.exists():
        return {}
    
    content = filepath.read_text()
    person = {
        'name': filepath.stem.replace('_', ' '),
        'filepath': str(filepath),
        'company': None,
        'company_page': None,
        'role': None,
        'email': None,
        'last_interaction': None
    }
    
    # Parse table fields
    for line in content.split('\n'):
        if '**Company**' in line and '|' in line:
            parts = line.split('|')
            if len(parts) >= 3:
                person['company'] = parts[2].strip()
        elif '**Company Page**' in line and '|' in line:
            parts = line.split('|')
            if len(parts) >= 3:
                person['company_page'] = parts[2].strip()
        elif '**Role**' in line and '|' in line:
            parts = line.split('|')
            if len(parts) >= 3:
                person['role'] = parts[2].strip()
        elif '**Email**' in line and '|' in line:
            parts = line.split('|')
            if len(parts) >= 3:
                person['email'] = parts[2].strip()
        elif '**Last interaction:**' in line:
            person['last_interaction'] = line.split('**Last interaction:**')[1].strip()
    
    return person

def find_people_at_company(company_name: str) -> List[Dict[str, Any]]:
    """Find all people pages that reference a company"""
    people = []
    company_name_lower = company_name.lower().replace('_', ' ')
    company_name_underscore = company_name.replace(' ', '_')
    
    # Search through People directories
    for subdir in ['External', 'Internal']:
        people_subdir = get_people_dir() / subdir
        if not people_subdir.exists():
            continue
        
        for person_file in people_subdir.glob('*.md'):
            person = parse_person_page(person_file)
            
            # Match by company name or company page path
            matches = False
            if person.get('company'):
                if company_name_lower in person['company'].lower():
                    matches = True
            if person.get('company_page'):
                if company_name_underscore in person['company_page'] or company_name_lower in person['company_page'].lower():
                    matches = True
            
            if matches:
                people.append(person)
    
    return people

def get_company_domains(company_filepath: Path) -> List[str]:
    """Extract domains from a company page"""
    if not company_filepath.exists():
        return []
    
    content = company_filepath.read_text()
    domains = []
    
    for line in content.split('\n'):
        if '**Domains**' in line and '|' in line:
            parts = line.split('|')
            if len(parts) >= 3:
                domain_str = parts[2].strip()
                # Parse comma-separated domains
                domains = [d.strip() for d in domain_str.split(',') if d.strip()]
                break
    
    return domains

def find_meetings_for_company(company_name: str, domains: List[str]) -> List[Dict[str, Any]]:
    """Find meetings that involve people from a company"""
    meetings = []
    
    if not get_meetings_dir().exists():
        return meetings
    
    company_name_lower = company_name.lower()
    
    for meeting_file in get_meetings_dir().glob('*.md'):
        content = meeting_file.read_text()
        content_lower = content.lower()
        
        # Check if company name or any domain appears in meeting
        matches = company_name_lower in content_lower
        if not matches:
            for domain in domains:
                if domain.lower() in content_lower:
                    matches = True
                    break
        
        if matches:
            # Extract meeting info
            lines = content.split('\n')
            title = lines[0].lstrip('#').strip() if lines else meeting_file.stem
            date = meeting_file.stem[:10] if len(meeting_file.stem) >= 10 else ''
            
            meetings.append({
                'date': date,
                'title': title,
                'filepath': str(meeting_file)
            })
    
    # Sort by date descending
    meetings.sort(key=lambda x: x['date'], reverse=True)
    return meetings[:10]  # Return last 10 meetings

def refresh_company_page(company_path: str) -> Dict[str, Any]:
    """Refresh all aggregated sections on a company page"""
    
    # Normalize path
    if not company_path.endswith('.md'):
        company_path += '.md'
    
    if company_path.startswith('Active/'):
        filepath = BASE_DIR / company_path
    else:
        filepath = COMPANIES_DIR / Path(company_path).name
    
    if not filepath.exists():
        return {
            'success': False,
            'error': f'Company page not found: {filepath}'
        }
    
    content = filepath.read_text()
    company_name = filepath.stem.replace('_', ' ')
    
    # Get domains for meeting matching
    domains = get_company_domains(filepath)
    
    # Find people at this company
    people = find_people_at_company(company_name)
    
    # Find related meetings
    meetings = find_meetings_for_company(company_name, domains)
    
    # Find related tasks
    tasks = find_tasks_for_page(company_path)
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # Build Key Contacts section
    contacts_section = "## Key Contacts\n\n"
    contacts_section += f"<!-- Auto-populated from People pages with company: {company_name} -->\n\n"
    if people:
        contacts_section += "| Name | Role | Last Interaction |\n"
        contacts_section += "|------|------|------------------|\n"
        for person in people:
            name_link = f"[{person['name']}]({person['filepath']})"
            role = person.get('role') or '-'
            last = person.get('last_interaction') or '-'
            contacts_section += f"| {name_link} | {role} | {last} |\n"
    else:
        contacts_section += "*No contacts found. Add Company Page field to Person pages to link them here.*\n"
    contacts_section += f"\n*Updated: {timestamp}*"
    
    # Build Meeting History section
    meetings_section = "## Meeting History\n\n"
    meetings_section += "<!-- Auto-populated from meetings where attendee emails match domains -->\n\n"
    if meetings:
        meetings_section += "| Date | Topic | Link |\n"
        meetings_section += "|------|-------|------|\n"
        for meeting in meetings:
            meetings_section += f"| {meeting['date']} | {meeting['title']} | [{meeting['date']}]({meeting['filepath']}) |\n"
    else:
        meetings_section += "*No meetings found. Add domains to this company page for automatic matching.*\n"
    meetings_section += f"\n*Meetings detected by email domain matching*"
    
    # Build Related Tasks section
    tasks_section = "## Related Tasks\n\n"
    tasks_section += "<!-- Synced from 03-Tasks/Tasks.md via task MCP -->\n\n"
    tasks_section += f"*Synced from 03-Tasks/Tasks.md — {timestamp}*\n\n"
    if tasks:
        tasks_section += "| Status | Task | Priority |\n"
        tasks_section += "|--------|------|----------|\n"
        for task in tasks:
            status = "✅" if task['completed'] else "⏳"
            tasks_section += f"| {status} | {task['title']} | {task['priority']} |\n"
    else:
        tasks_section += "*No related tasks*\n"
    
    # Replace sections in content
    # Key Contacts
    contacts_pattern = r'## Key Contacts\n.*?(?=\n## |\Z)'
    if re.search(contacts_pattern, content, re.DOTALL):
        content = re.sub(contacts_pattern, contacts_section, content, flags=re.DOTALL)
    
    # Meeting History
    meetings_pattern = r'## Meeting History\n.*?(?=\n## |\Z)'
    if re.search(meetings_pattern, content, re.DOTALL):
        content = re.sub(meetings_pattern, meetings_section, content, flags=re.DOTALL)
    
    # Related Tasks
    tasks_pattern = r'## Related Tasks\n.*?(?=\n## |\Z)'
    if re.search(tasks_pattern, content, re.DOTALL):
        content = re.sub(tasks_pattern, tasks_section, content, flags=re.DOTALL)
    
    # Update the Updated timestamp at the bottom
    content = re.sub(r'\*Updated: .*?\*', f'*Updated: {timestamp}*', content)
    
    filepath.write_text(content)
    
    return {
        'success': True,
        'company': company_name,
        'contacts_found': len(people),
        'meetings_found': len(meetings),
        'tasks_found': len(tasks),
        'filepath': str(filepath)
    }

def list_companies() -> List[Dict[str, Any]]:
    """List all company pages"""
    companies = []
    
    if not COMPANIES_DIR.exists():
        return companies
    
    for company_file in COMPANIES_DIR.glob('*.md'):
        content = company_file.read_text()
        
        # Extract basic info
        company = {
            'name': company_file.stem.replace('_', ' '),
            'filepath': str(company_file),
            'stage': None,
            'industry': None
        }
        
        for line in content.split('\n'):
            if '**Stage**' in line and '|' in line:
                parts = line.split('|')
                if len(parts) >= 3:
                    company['stage'] = parts[2].strip()
            elif '**Industry**' in line and '|' in line:
                parts = line.split('|')
                if len(parts) >= 3:
                    company['industry'] = parts[2].strip()
        
        # Count related items
        company['contacts'] = len(find_people_at_company(company['name']))
        
        companies.append(company)
    
    return companies

def create_company_page(name: str, website: str = '', industry: str = '', 
                       size: str = '', stage: str = 'Prospect', 
                       domains: List[str] = None) -> Dict[str, Any]:
    """Create a new company page from template"""
    
    # Ensure directory exists
    COMPANIES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Sanitize filename
    filename = name.replace(' ', '_').replace('/', '_')
    filepath = COMPANIES_DIR / f"{filename}.md"
    
    if filepath.exists():
        return {
            'success': False,
            'error': f'Company page already exists: {filepath}'
        }
    
    # Build domains string
    if not domains:
        # Extract domain from website
        if website:
            domain = website.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
            domains = [domain]
        else:
            domains = []
    
    domains_str = ', '.join(domains) if domains else '{{company.com}}'
    
    timestamp = datetime.now().strftime('%Y-%m-%d')
    
    content = f"""# {name}

## Overview

| Field | Value |
|-------|-------|
| **Website** | {website or '{{company.com}}'} |
| **Industry** | {industry or '{{Industry}}'} |
| **Size** | {size or '{{Startup / Scale-up / Enterprise}}'} |
| **Stage** | {stage} |
| **Domains** | {domains_str} |

---

## Key Contacts

<!-- Auto-populated from People pages with company: {name} -->

| Name | Role | Last Interaction |
|------|------|------------------|

*Run refresh_company to update from People pages*

---

## Projects

<!-- Projects involving this company -->

---

## Meeting History

<!-- Auto-populated from meetings where attendee emails match domains -->

| Date | Topic | Link |
|------|-------|------|

*Meetings detected by email domain matching*

---

## Related Tasks

<!-- Synced from 03-Tasks/Tasks.md via task MCP -->

*Synced from 03-Tasks/Tasks.md — never*

| Status | Task | Priority |
|--------|------|----------|

---

## Notes



---

*Created: {timestamp}*
*Updated: {timestamp}*
"""
    
    filepath.write_text(content)
    
    return {
        'success': True,
        'company': name,
        'filepath': str(filepath),
        'message': f"Created company page: {filepath}"
    }


# ============================================================================
# QUARTERLY GOAL MANAGEMENT
# ============================================================================

def get_quarter_info(quarter_date: Optional[date] = None) -> Dict[str, Any]:
    """Calculate quarter information based on q1_start_month from user profile"""
    if quarter_date is None:
        quarter_date = date.today()
    
    # Read q1_start_month from user profile
    q1_start_month = 1  # Default to January
    if USER_PROFILE_FILE.exists() and yaml:
        try:
            content = USER_PROFILE_FILE.read_text()
            data = yaml.safe_load(content)
            if data and 'quarterly_planning' in data:
                q1_start_month = data['quarterly_planning'].get('q1_start_month', 1)
        except Exception as e:
            logger.error(f"Error reading q1_start_month: {e}")
    
    # Calculate which quarter we're in based on q1_start_month
    month = quarter_date.month
    year = quarter_date.year
    
    # Calculate quarter number (1-4)
    months_since_q1_start = (month - q1_start_month) % 12
    quarter_num = (months_since_q1_start // 3) + 1
    
    # Calculate quarter start/end dates
    q_start_month = ((quarter_num - 1) * 3 + q1_start_month - 1) % 12 + 1
    q_start_year = year if q_start_month >= q1_start_month or month >= q1_start_month else year - 1
    
    quarter_start = date(q_start_year, q_start_month, 1)
    
    # Calculate end month
    q_end_month = (q_start_month + 2) % 12
    if q_end_month == 0:
        q_end_month = 12
    q_end_year = q_start_year if q_end_month > q_start_month else q_start_year + 1
    
    # Last day of end month
    import calendar
    last_day = calendar.monthrange(q_end_year, q_end_month)[1]
    quarter_end = date(q_end_year, q_end_month, last_day)
    
    return {
        'quarter': f"Q{quarter_num} {year}",
        'quarter_num': quarter_num,
        'year': year,
        'start_date': quarter_start,
        'end_date': quarter_end,
        'weeks_remaining': ((quarter_end - date.today()).days // 7) if quarter_end >= date.today() else 0
    }

def generate_goal_id(quarter: str, existing_goals: List[Dict]) -> str:
    """Generate unique goal ID like Q1-2026-goal-1"""
    # Extract quarter and year from quarter string like "Q1 2026"
    parts = quarter.split()
    q_num = parts[0]  # e.g., "Q1"
    year = parts[1] if len(parts) > 1 else str(date.today().year)
    
    # Find highest existing goal number for this quarter
    max_num = 0
    prefix = f"{q_num}-{year}-goal-"
    for goal in existing_goals:
        if 'goal_id' in goal and goal['goal_id'].startswith(prefix):
            try:
                num = int(goal['goal_id'].split('-')[-1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                continue
    
    return f"{prefix}{max_num + 1}"

def extract_goal_id(text: str) -> Optional[str]:
    """Extract goal ID from text like ^Q1-2026-goal-1"""
    match = re.search(r'\^(Q\d+-\d{4}-goal-\d+)', text)
    return match.group(1) if match else None

def parse_quarterly_goals(filepath: Path) -> List[Dict[str, Any]]:
    """Parse quarterly goals from 01-Quarter_Goals/Quarter_Goals.md"""
    if not filepath.exists():
        return []
    
    content = filepath.read_text()
    goals = []
    
    # Parse frontmatter if present
    quarter_info = {}
    if content.startswith('---'):
        try:
            end_idx = content.find('---', 3)
            if end_idx > 0 and yaml:
                frontmatter = content[3:end_idx]
                quarter_info = yaml.safe_load(frontmatter) or {}
        except Exception as e:
            logger.error(f"Error parsing frontmatter: {e}")
    
    # Parse goal sections (### 1. Goal Title — **Pillar** ^goal-id)
    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Match goal headers like ### 1. Launch Product v2.0 — **Growth** ^Q1-2026-goal-1
        goal_match = re.match(r'###\s+(\d+)\.\s+(.+?)\s+—\s+\*\*(.+?)\*\*(?:\s+\^(Q\d+-\d{4}-goal-\d+))?', line)
        if goal_match:
            goal_num = int(goal_match.group(1))
            title = goal_match.group(2).strip()
            pillar = goal_match.group(3).strip()
            goal_id = goal_match.group(4) if goal_match.group(4) else None
            
            # Extract success criteria and milestones from following lines
            success_criteria = ''
            milestones = []
            progress = 0
            last_updated = None
            career_goal_id = None
            skills_developed = []
            impact_level = None
            
            j = i + 1
            while j < len(lines) and not lines[j].startswith('###'):
                if '**What success looks like:**' in lines[j]:
                    # Read next non-empty line
                    k = j + 1
                    while k < len(lines) and lines[k].strip() and not lines[k].startswith('**') and not lines[k].strip().startswith('-'):
                        success_criteria += lines[k].strip() + ' '
                        k += 1
                elif lines[j].strip().startswith('- [ ]') or lines[j].strip().startswith('- [x]'):
                    milestone_match = re.match(r'-\s*\[([x ])\]\s*(.+)', lines[j].strip())
                    if milestone_match:
                        milestones.append({
                            'title': milestone_match.group(2).strip(),
                            'completed': milestone_match.group(1) == 'x'
                        })
                elif '**Progress:**' in lines[j]:
                    progress_match = re.search(r'(\d+)%', lines[j])
                    if progress_match:
                        progress = int(progress_match.group(1))
                elif '**Career goal:**' in lines[j]:
                    career_match = re.search(r'\*\*Career goal:\*\*\s*(.+)', lines[j])
                    if career_match:
                        career_goal_id = career_match.group(1).strip()
                elif '**Skills developing:**' in lines[j]:
                    skills_match = re.search(r'\*\*Skills developing:\*\*\s*(.+)', lines[j])
                    if skills_match:
                        skills_developed = [s.strip() for s in skills_match.group(1).split(',')]
                elif '**Impact level:**' in lines[j]:
                    impact_match = re.search(r'\*\*Impact level:\*\*\s*(low|medium|high)', lines[j])
                    if impact_match:
                        impact_level = impact_match.group(1)
                j += 1
            
            goals.append({
                'goal_id': goal_id,
                'goal_num': goal_num,
                'title': title,
                'pillar': pillar,
                'success_criteria': success_criteria.strip(),
                'milestones': milestones,
                'progress': progress,
                'last_updated': last_updated,
                'quarter': quarter_info.get('quarter', ''),
                'line_number': i + 1,
                'career_goal_id': career_goal_id,
                'skills_developed': skills_developed,
                'impact_level': impact_level
            })
        
        i += 1
    
    return goals

def get_goal_by_id(goal_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific goal by its ID"""
    goals_file = QUARTER_GOALS_FILE
    if is_demo_mode():
        goals_file = DEMO_DIR / '01-Quarter_Goals/Quarter_Goals.md'
    
    goals = parse_quarterly_goals(goals_file)
    for goal in goals:
        if goal.get('goal_id') == goal_id:
            return goal
    return None

def find_linked_priorities(goal_id: str) -> List[Dict[str, Any]]:
    """Find all weekly priorities linked to a goal"""
    priorities_file = get_week_priorities_file()
    if not priorities_file.exists():
        return []
    
    content = priorities_file.read_text()
    lines = content.split('\n')
    
    linked_priorities = []
    for i, line in enumerate(lines):
        # Look for lines that mention the goal_id
        if goal_id in line:
            # Check if this is a priority line
            if '**' in line and ('- [ ]' in line or '- [x]' in line or line.strip().startswith('1.') or line.strip().startswith('2.') or line.strip().startswith('3.')):
                completed = '- [x]' in line
                
                # Extract priority ID
                priority_id = extract_priority_id(line)
                
                # Extract title
                title_match = re.search(r'(?:\d+\.\s+)?(.+?)\s+—', line)
                if not title_match:
                    title_match = re.search(r'\*\*(.+?)\*\*', line)
                title = title_match.group(1).strip() if title_match else line.strip()
                
                linked_priorities.append({
                    'priority_id': priority_id,
                    'title': title,
                    'completed': completed,
                    'line_number': i + 1
                })
    
    return linked_priorities

def calculate_goal_progress(goal_id: str) -> Dict[str, Any]:
    """Calculate goal progress based on linked weekly priorities"""
    priorities = find_linked_priorities(goal_id)
    
    if not priorities:
        return {
            'progress': 0,
            'total_priorities': 0,
            'completed_priorities': 0,
            'calculation_method': 'no_linked_priorities'
        }
    
    completed = sum(1 for p in priorities if p['completed'])
    total = len(priorities)
    progress = int((completed / total) * 100) if total > 0 else 0
    
    return {
        'progress': progress,
        'total_priorities': total,
        'completed_priorities': completed,
        'calculation_method': 'automatic'
    }

def update_goal_in_file(goal_id: str, updates: Dict[str, Any]) -> bool:
    """Update a goal's fields in 01-Quarter_Goals/Quarter_Goals.md"""
    goals_file = QUARTER_GOALS_FILE
    if is_demo_mode():
        goals_file = DEMO_DIR / '01-Quarter_Goals/Quarter_Goals.md'
    
    if not goals_file.exists():
        return False
    
    content = goals_file.read_text()
    lines = content.split('\n')
    
    # Find the goal
    goal_line_idx = None
    for i, line in enumerate(lines):
        if f'^{goal_id}' in line:
            goal_line_idx = i
            break
    
    if goal_line_idx is None:
        return False
    
    # Update progress if specified
    if 'progress' in updates:
        progress = updates['progress']
        # Find the Progress line after the goal header
        for i in range(goal_line_idx, min(goal_line_idx + 30, len(lines))):
            if '**Progress:**' in lines[i]:
                # Update progress percentage and emoji
                emoji = '🟢' if progress >= 75 else '🟡' if progress >= 40 else '🔴'
                lines[i] = f"**Progress:** {progress}% {emoji}"
                break
    
    # Write back
    goals_file.write_text('\n'.join(lines))
    return True

def create_quarterly_goal_in_file(goal_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new quarterly goal in 01-Quarter_Goals/Quarter_Goals.md"""
    goals_file = QUARTER_GOALS_FILE
    if is_demo_mode():
        goals_file = DEMO_DIR / '01-Quarter_Goals/Quarter_Goals.md'
    
    # Ensure file exists
    if not goals_file.exists():
        # Create new file with frontmatter
        quarter_info = get_quarter_info()
        goals_file.parent.mkdir(parents=True, exist_ok=True)
        content = f"""---
quarter: {quarter_info['quarter']}
start_date: {quarter_info['start_date']}
end_date: {quarter_info['end_date']}
created: {datetime.now().strftime('%Y-%m-%d')}
---

# {quarter_info['quarter']} Goals

**{quarter_info['start_date']} - {quarter_info['end_date']}**

---

## 🎯 Quarter Objectives

"""
        goals_file.write_text(content)
    
    # Read existing goals to generate ID
    existing_goals = parse_quarterly_goals(goals_file)
    goal_id = generate_goal_id(goal_data['quarter'], existing_goals)
    
    # Build goal section
    goal_num = len(existing_goals) + 1
    milestones_md = '\n'.join([f"- [ ] {m['title']}" for m in goal_data.get('milestones', [])])
    
    goal_section = f"""
### {goal_num}. {goal_data['title']} — **{goal_data['pillar']}** ^{goal_id}

**What success looks like:**
{goal_data.get('success_criteria', '[Define success criteria]')}

**Key milestones:**
{milestones_md if milestones_md else '- [ ] [Milestone 1]'}

**Progress:** 0% 🔴
"""
    
    # Add career metadata if provided
    career_metadata = []
    if goal_data.get('career_goal_id'):
        career_metadata.append(f"- **Career goal:** {goal_data['career_goal_id']}")
    if goal_data.get('skills_developed'):
        skills_list = ', '.join(goal_data['skills_developed'])
        career_metadata.append(f"- **Skills developing:** {skills_list}")
    if goal_data.get('impact_level'):
        impact_emoji = {"high": "🔥", "medium": "⭐", "low": "📋"}
        emoji = impact_emoji.get(goal_data['impact_level'], "")
        career_metadata.append(f"- **Impact level:** {goal_data['impact_level']} {emoji}")
    
    if career_metadata:
        goal_section += "\n" + '\n'.join(career_metadata) + "\n"
    
    goal_section += "\n---\n"
    
    # Insert before "## 📊 Pillar Alignment" or at end
    content = goals_file.read_text()
    
    insert_marker = "## 📊 Pillar Alignment"
    if insert_marker in content:
        content = content.replace(insert_marker, goal_section + "\n" + insert_marker)
    else:
        content += goal_section
    
    goals_file.write_text(content)
    
    return {
        'success': True,
        'goal_id': goal_id,
        'goal_num': goal_num,
        'title': goal_data['title']
    }

# ============================================================================
# WEEKLY PRIORITY MANAGEMENT
# ============================================================================

def extract_priority_id(text: str) -> Optional[str]:
    """Extract priority ID from text like ^week-2026-W05-p1"""
    match = re.search(r'\^(week-\d{4}-W\d{2}-p\d+)', text)
    return match.group(1) if match else None

def generate_priority_id(week_date: date, existing_priorities: List[Dict]) -> str:
    """Generate unique priority ID like week-2026-W05-p1"""
    # Get ISO week number
    year, week_num, _ = week_date.isocalendar()
    
    # Find highest existing priority number for this week
    max_num = 0
    prefix = f"week-{year}-W{week_num:02d}-p"
    for priority in existing_priorities:
        if 'priority_id' in priority and priority['priority_id'].startswith(prefix):
            try:
                num = int(priority['priority_id'].split('-p')[-1])
                max_num = max(max_num, num)
            except (ValueError, IndexError):
                continue
    
    return f"{prefix}{max_num + 1}"

def parse_weekly_priorities(filepath: Path) -> List[Dict[str, Any]]:
    """Parse weekly priorities from Week Priorities.md"""
    if not filepath.exists():
        return []
    
    content = filepath.read_text()
    priorities = []
    
    lines = content.split('\n')
    for i, line in enumerate(lines):
        # Match priority lines like:
        # 1. Priority Title — **Pillar** ^week-2026-W05-p1
        # Or task-style: - [ ] **Priority Title** ^week-2026-W05-p1
        
        priority_match = re.match(r'(\d+)\.\s+(.+?)\s+—\s+\*\*(.+?)\*\*(?:\s+\^(week-\d{4}-W\d{2}-p\d+))?', line)
        if priority_match:
            priority_num = int(priority_match.group(1))
            title = priority_match.group(2).strip()
            pillar = priority_match.group(3).strip()
            priority_id = priority_match.group(4) if priority_match.group(4) else None
            
            # Look for linked goal in following lines
            linked_goal_id = None
            j = i + 1
            if j < len(lines) and 'Quarterly goal:' in lines[j]:
                goal_match = re.search(r'\[(Q\d+-\d{4}-goal-\d+)\]', lines[j])
                if goal_match:
                    linked_goal_id = goal_match.group(1)
            
            # Check completion (look for checkmark or completion note)
            completed = False  # For now, will enhance later
            
            priorities.append({
                'priority_id': priority_id,
                'priority_num': priority_num,
                'title': title,
                'pillar': pillar,
                'linked_goal_id': linked_goal_id,
                'completed': completed,
                'line_number': i + 1
            })
    
    return priorities

def find_linked_tasks(priority_id: str) -> List[Dict[str, Any]]:
    """Find all tasks linked to a weekly priority"""
    tasks_file = get_tasks_file()
    if not tasks_file.exists():
        return []
    
    content = tasks_file.read_text()
    lines = content.split('\n')
    
    linked_tasks = []
    for i, line in enumerate(lines):
        # Look for tasks that mention the priority_id
        if priority_id in line and ('- [ ]' in line or '- [x]' in line):
            completed = '- [x]' in line
            task_id = extract_task_id(line)
            
            # Extract title
            title_match = re.match(r'-\s*\[[x ]\]\s*\*?\*?(.+?)\*?\*?(?:\s*\^task-|\s*\|)', line.strip())
            title = title_match.group(1).strip() if title_match else line.strip()
            
            linked_tasks.append({
                'task_id': task_id,
                'title': title,
                'completed': completed,
                'line_number': i + 1
            })
    
    return linked_tasks

# ============================================================================
# TASK PARSING AND MANAGEMENT
# ============================================================================

def parse_tasks_file(filepath: Path) -> List[Dict[str, Any]]:
    """Parse tasks from a markdown file"""
    tasks = []
    if not filepath.exists():
        return tasks
    
    content = filepath.read_text()
    lines = content.split('\n')
    
    current_section = None
    task_counter = 0
    
    for i, line in enumerate(lines):
        # Track section headers
        if line.startswith('# ') or line.startswith('## '):
            current_section = line.lstrip('#').strip()
            continue
        
        # Parse task lines
        if line.strip().startswith('- [ ]') or line.strip().startswith('- [x]'):
            task_counter += 1
            completed = line.strip().startswith('- [x]')
            
            # Extract task ID if present
            task_id = extract_task_id(line)
            
            # Extract task title (remove the checkbox and task ID)
            title_match = re.match(r'-\s*\[[x ]\]\s*\*?\*?(.+?)\*?\*?(?:\s*\^task-\d{8}-\d{3})?\s*$', line.strip())
            title = title_match.group(1).strip() if title_match else line.strip()[6:]
            
            # Clean title - remove file path references for display
            clean_title = re.sub(r'\s*\|\s*(?:People|Active)/[^\s]+', '', title)
            clean_title = re.sub(r'\s+\.md\b', '', clean_title)
            clean_title = re.sub(r'\s*\^task-\d{8}-\d{3}\s*', '', clean_title)  # Remove task ID
            
            # Determine status
            status = 'd' if completed else 'n'
            
            tasks.append({
                'id': task_id or f'temp-{task_counter}',
                'task_id': task_id,  # The actual ^task-YYYYMMDD-XXX ID
                'title': clean_title,
                'raw_title': title,
                'section': current_section,
                'completed': completed,
                'status': status,
                'line_number': i + 1,
                'source_file': str(filepath),
                'pillar': guess_pillar(clean_title),
                'priority': guess_priority(clean_title),
            })
    
    return tasks

def get_all_tasks() -> List[Dict[str, Any]]:
    """Get all tasks from 03-Tasks/Tasks.md and Week Priorities"""
    all_tasks = []
    
    # 03-Tasks/Tasks.md
    if get_tasks_file().exists():
        tasks = parse_tasks_file(get_tasks_file())
        for t in tasks:
            t['source'] = 'tasks'
        all_tasks.extend(tasks)
    
    # Week Priorities
    if get_week_priorities_file().exists():
        tasks = parse_tasks_file(get_week_priorities_file())
        for t in tasks:
            t['source'] = 'week_priorities'
        all_tasks.extend(tasks)
    
    return all_tasks

def find_similar_tasks(item: str, existing_tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find tasks similar to the given item"""
    similar = []
    item_keywords = extract_keywords(item)
    
    for task in existing_tasks:
        # Skip completed tasks
        if task.get('completed') or task.get('status') == 'd':
            continue
        
        title = task.get('title', '')
        title_similarity = calculate_similarity(item, title)
        
        # Calculate keyword overlap
        task_keywords = extract_keywords(title)
        if item_keywords and task_keywords:
            keyword_overlap = len(item_keywords & task_keywords) / len(item_keywords | task_keywords)
        else:
            keyword_overlap = 0
        
        # Combined score
        similarity_score = (title_similarity * 0.7) + (keyword_overlap * 0.3)
        
        if similarity_score >= DEDUP_CONFIG['similarity_threshold']:
            similar.append({
                'title': title,
                'section': task.get('section', ''),
                'source': task.get('source', ''),
                'similarity_score': round(similarity_score, 2)
            })
    
    similar.sort(key=lambda x: x['similarity_score'], reverse=True)
    return similar[:3]

# ============================================================================
# MIGRATION HELPERS
# ============================================================================

def migrate_quarterly_goals() -> Dict[str, Any]:
    """Add IDs to existing quarterly goals that don't have them"""
    goals_file = QUARTER_GOALS_FILE
    if is_demo_mode():
        goals_file = DEMO_DIR / '01-Quarter_Goals/Quarter_Goals.md'
    
    if not goals_file.exists():
        return {
            'success': False,
            'message': 'No 01-Quarter_Goals/Quarter_Goals.md file found'
        }
    
    content = goals_file.read_text()
    lines = content.split('\n')
    
    # Parse existing goals
    existing_goals = parse_quarterly_goals(goals_file)
    goals_updated = 0
    
    # Find goals without IDs and add them
    for i, line in enumerate(lines):
        # Match goal headers without IDs
        goal_match = re.match(r'(###\s+\d+\.\s+.+?\s+—\s+\*\*.*?\*\*)(?!\s+\^)', line)
        if goal_match:
            # This goal doesn't have an ID, add one
            goal_header = goal_match.group(1)
            
            # Generate ID
            quarter_match = re.search(r'quarter:\s+(.+)', content[:content.find(line)])
            quarter = quarter_match.group(1) if quarter_match else get_quarter_info()['quarter']
            
            goal_id = generate_goal_id(quarter, existing_goals)
            lines[i] = f"{goal_header} ^{goal_id}"
            
            # Add this goal to existing_goals so next ID is incremented
            existing_goals.append({'goal_id': goal_id})
            goals_updated += 1
    
    if goals_updated > 0:
        goals_file.write_text('\n'.join(lines))
    
    return {
        'success': True,
        'goals_updated': goals_updated,
        'message': f"Added IDs to {goals_updated} quarterly goals"
    }

def migrate_weekly_priorities() -> Dict[str, Any]:
    """Add IDs to existing weekly priorities that don't have them"""
    priorities_file = get_week_priorities_file()
    
    if not priorities_file.exists():
        return {
            'success': False,
            'message': 'No Week Priorities file found'
        }
    
    content = priorities_file.read_text()
    lines = content.split('\n')
    
    # Determine week date
    week_match = re.search(r'\*\*Week of:\*\*\s+(\d{4}-\d{2}-\d{2})', content)
    if week_match:
        week_date = datetime.strptime(week_match.group(1), '%Y-%m-%d').date()
    else:
        today = date.today()
        week_date = today - timedelta(days=today.weekday())
    
    # Parse existing priorities
    existing_priorities = parse_weekly_priorities(priorities_file)
    priorities_updated = 0
    
    # Find priorities without IDs and add them
    for i, line in enumerate(lines):
        # Match priority lines without IDs (numbered 1-3)
        priority_match = re.match(r'(\d+\.\s+.+?\s+—\s+\*\*.*?\*\*)(?!\s+\^)', line)
        if priority_match:
            # This priority doesn't have an ID, add one
            priority_header = priority_match.group(1)
            
            priority_id = generate_priority_id(week_date, existing_priorities)
            lines[i] = f"{priority_header} ^{priority_id}"
            
            # Add to existing so next ID is incremented
            existing_priorities.append({'priority_id': priority_id})
            priorities_updated += 1
    
    if priorities_updated > 0:
        priorities_file.write_text('\n'.join(lines))
    
    return {
        'success': True,
        'priorities_updated': priorities_updated,
        'message': f"Added IDs to {priorities_updated} weekly priorities"
    }

# ============================================================================
# TASK EFFORT CLASSIFICATION
# ============================================================================

# Keywords for classifying task effort
EFFORT_KEYWORDS = {
    'deep_work': {
        'keywords': ['write', 'draft', 'design', 'strategy', 'plan', 'create', 'build', 
                     'develop', 'analyze', 'architect', 'spec', 'proposal', 'document',
                     'framework', 'vision', 'roadmap', 'presentation', 'deck'],
        'duration_range': (120, 240),  # 2-4 hours
        'description': 'Requires sustained focus and creative thinking'
    },
    'medium': {
        'keywords': ['review', 'prepare', 'research', 'organize', 'update', 'refine',
                     'edit', 'revise', 'compile', 'summarize', 'meet', 'discuss',
                     'prep', 'feedback', 'assess'],
        'duration_range': (45, 120),  # 45 min - 2 hours
        'description': 'Focused work but more structured'
    },
    'quick': {
        'keywords': ['email', 'send', 'reply', 'schedule', 'check', 'confirm', 
                     'follow up', 'ping', 'slack', 'message', 'book', 'approve',
                     'forward', 'share', 'quick', 'brief'],
        'duration_range': (10, 30),  # 10-30 min
        'description': 'Short tasks that can fit in gaps'
    }
}

def classify_task_effort(title: str, context: str = '') -> Dict[str, Any]:
    """Classify a task's effort level based on keywords and patterns"""
    text = f"{title} {context}".lower()
    
    scores = {'deep_work': 0, 'medium': 0, 'quick': 0}
    
    for effort_type, config in EFFORT_KEYWORDS.items():
        for keyword in config['keywords']:
            if keyword in text:
                scores[effort_type] += 1
    
    # Default to medium if no strong signals
    if max(scores.values()) == 0:
        effort_type = 'medium'
    else:
        effort_type = max(scores, key=scores.get)
    
    config = EFFORT_KEYWORDS[effort_type]
    
    return {
        'effort_type': effort_type,
        'estimated_duration_min': config['duration_range'],
        'description': config['description'],
        'confidence': 'high' if max(scores.values()) >= 2 else 'medium' if max(scores.values()) == 1 else 'low'
    }

def classify_all_tasks_effort(tasks: List[Dict]) -> List[Dict]:
    """Add effort classification to a list of tasks"""
    for task in tasks:
        effort = classify_task_effort(task.get('title', ''), task.get('context', ''))
        task['effort'] = effort
    return tasks


# ============================================================================
# WEEK PROGRESS TRACKING
# ============================================================================

def get_week_progress_data() -> Dict[str, Any]:
    """Get comprehensive progress data for the current week"""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday
    day_of_week = today.strftime('%A')
    days_remaining = (week_end - today).days
    days_elapsed = today.weekday()  # 0=Monday
    
    # Get weekly priorities
    priorities_file = get_week_priorities_file()
    priorities = parse_weekly_priorities(priorities_file) if priorities_file.exists() else []
    
    # Enrich priorities with task data
    priorities_detail = []
    for priority in priorities:
        priority_data = {
            'priority_id': priority.get('priority_id'),
            'title': priority.get('title'),
            'pillar': priority.get('pillar'),
            'status': 'not_started',
            'tasks_done': 0,
            'tasks_total': 0,
            'warning': None
        }
        
        # Find linked tasks
        if priority.get('priority_id'):
            linked_tasks = find_linked_tasks(priority['priority_id'])
            priority_data['tasks_total'] = len(linked_tasks)
            priority_data['tasks_done'] = sum(1 for t in linked_tasks if t.get('completed'))
            
            if priority_data['tasks_total'] > 0:
                if priority_data['tasks_done'] == priority_data['tasks_total']:
                    priority_data['status'] = 'complete'
                elif priority_data['tasks_done'] > 0:
                    priority_data['status'] = 'in_progress'
        
        # Add warnings for priorities with no activity
        if priority_data['status'] == 'not_started' and days_elapsed >= 2:
            priority_data['warning'] = f"No activity yet - {days_remaining} days left this week"
        
        priorities_detail.append(priority_data)
    
    # Calculate completion stats
    completed_priorities = sum(1 for p in priorities_detail if p['status'] == 'complete')
    in_progress_priorities = sum(1 for p in priorities_detail if p['status'] == 'in_progress')
    not_started_priorities = sum(1 for p in priorities_detail if p['status'] == 'not_started')
    
    # Get tasks completed this week
    all_tasks = get_all_tasks()
    tasks_completed_this_week = 0
    for task in all_tasks:
        if task.get('completed'):
            # Check if completed this week by looking at the task line for timestamp
            # This is a simplified check - would need completion timestamps
            tasks_completed_this_week += 1  # Placeholder
    
    return {
        'date': today.isoformat(),
        'day_of_week': day_of_week,
        'week_start': week_start.isoformat(),
        'week_end': week_end.isoformat(),
        'days_elapsed': days_elapsed,
        'days_remaining': days_remaining,
        'priorities': priorities_detail,
        'summary': {
            'total': len(priorities_detail),
            'complete': completed_priorities,
            'in_progress': in_progress_priorities,
            'not_started': not_started_priorities
        },
        'tasks_completed_this_week': tasks_completed_this_week,
        'warnings': [p['warning'] for p in priorities_detail if p.get('warning')]
    }


# ============================================================================
# MEETING INTELLIGENCE
# ============================================================================

def find_project_for_meeting(attendees: List[str], meeting_title: str) -> Optional[Dict[str, Any]]:
    """Find a related project based on meeting attendees or title"""
    projects_dir = BASE_DIR / '04-Projects'
    if not projects_dir.exists():
        return None
    
    # Normalize attendees and title for matching
    search_terms = [a.lower().replace(' ', '_') for a in attendees]
    search_terms.append(meeting_title.lower())
    
    best_match = None
    best_score = 0
    
    for project_file in projects_dir.glob('**/*.md'):
        if project_file.name.startswith('.'):
            continue
            
        try:
            content = project_file.read_text()
            content_lower = content.lower()
            
            score = 0
            for term in search_terms:
                if term in content_lower or term in project_file.stem.lower():
                    score += 1
            
            if score > best_score:
                best_score = score
                
                # Extract project status
                status = 'Unknown'
                if 'status:' in content_lower:
                    status_match = re.search(r'status:\s*(.+?)(?:\n|$)', content_lower)
                    if status_match:
                        status = status_match.group(1).strip()
                
                best_match = {
                    'path': str(project_file.relative_to(BASE_DIR)),
                    'name': project_file.stem.replace('_', ' '),
                    'status': status,
                    'match_score': score
                }
        except Exception:
            continue
    
    return best_match if best_score > 0 else None

def find_company_for_attendees(attendees: List[str], domains: List[str] = None) -> Optional[Dict[str, Any]]:
    """Find a company page based on attendees or email domains"""
    if not COMPANIES_DIR.exists():
        return None
    
    search_terms = []
    for attendee in attendees:
        search_terms.append(attendee.lower())
        # Extract potential company name from email
        if '@' in attendee:
            domain = attendee.split('@')[1].split('.')[0]
            search_terms.append(domain)
    
    if domains:
        search_terms.extend([d.lower() for d in domains])
    
    for company_file in COMPANIES_DIR.glob('*.md'):
        try:
            content = company_file.read_text()
            content_lower = content.lower()
            company_name = company_file.stem.lower().replace('_', ' ')
            
            for term in search_terms:
                if term in company_name or term in content_lower:
                    # Extract company domains
                    company_domains = get_company_domains(company_file)
                    
                    return {
                        'path': str(company_file.relative_to(BASE_DIR)),
                        'name': company_file.stem.replace('_', ' '),
                        'domains': company_domains
                    }
        except Exception:
            continue
    
    return None

def get_meeting_context_data(meeting_title: str = None, attendees: List[str] = None) -> Dict[str, Any]:
    """Get comprehensive context for a meeting based on attendees and title"""
    result = {
        'meeting_title': meeting_title,
        'attendees': attendees or [],
        'related_project': None,
        'related_company': None,
        'attendee_details': [],
        'outstanding_tasks': [],
        'recent_meetings': [],
        'prep_suggestions': []
    }
    
    if not attendees:
        return result
    
    # Find related project
    if meeting_title or attendees:
        result['related_project'] = find_project_for_meeting(attendees, meeting_title or '')
    
    # Find related company
    result['related_company'] = find_company_for_attendees(attendees)
    
    # Get attendee details from People directory
    for attendee in attendees:
        attendee_normalized = attendee.lower().replace(' ', '_')
        
        # Check both Internal and External directories
        for subdir in ['External', 'Internal']:
            people_subdir = get_people_dir() / subdir
            if not people_subdir.exists():
                continue
            
            for person_file in people_subdir.glob('*.md'):
                if attendee_normalized in person_file.stem.lower():
                    person_data = parse_person_page(person_file)
                    result['attendee_details'].append(person_data)
                    break
    
    # Find outstanding tasks related to attendees
    tasks_file = get_tasks_file()
    if tasks_file.exists():
        content = tasks_file.read_text()
        for attendee in attendees:
            attendee_lower = attendee.lower()
            for line in content.split('\n'):
                if '- [ ]' in line and attendee_lower in line.lower():
                    # Extract task title
                    title_match = re.match(r'-\s*\[ \]\s*\*?\*?(.+?)\*?\*?(?:\s*\^|\s*$)', line.strip())
                    if title_match:
                        result['outstanding_tasks'].append({
                            'title': title_match.group(1).strip(),
                            'related_to': attendee
                        })
    
    # Generate prep suggestions
    if result['outstanding_tasks']:
        result['prep_suggestions'].append(f"Review {len(result['outstanding_tasks'])} outstanding tasks with attendees")
    
    if result['related_project']:
        result['prep_suggestions'].append(f"Check status of project: {result['related_project']['name']}")
    
    if result['related_company']:
        result['prep_suggestions'].append(f"Review company page: {result['related_company']['name']}")
    
    return result


# ============================================================================
# COMMITMENT TRACKING
# ============================================================================

COMMITMENT_PATTERNS = [
    r"i['']ll\s+(?:get back to|send|share|follow up|email|schedule|prepare|review|draft)\s+(.+?)(?:\s+by\s+(\w+))?",
    r"will\s+(?:send|share|follow up|provide|deliver|complete)\s+(.+?)(?:\s+by\s+(\w+))?",
    r"owe\s+(?:you|them|him|her)\s+(.+)",
    r"need to\s+(?:send|share|get back|follow up)\s+(.+?)(?:\s+by\s+(\w+))?",
    r"action\s*item[s]?:\s*(.+)",
    r"follow.?up:\s*(.+)",
]

def extract_commitments_from_text(text: str, source: str = '', date_context: str = '') -> List[Dict[str, Any]]:
    """Extract commitment patterns from text"""
    commitments = []
    text_lower = text.lower()
    
    for pattern in COMMITMENT_PATTERNS:
        matches = re.finditer(pattern, text_lower)
        for match in matches:
            commitment_text = match.group(1).strip() if match.lastindex >= 1 else match.group(0)
            due_date = match.group(2) if match.lastindex >= 2 else None
            
            commitments.append({
                'commitment': commitment_text,
                'due_date': due_date,
                'source': source,
                'date_context': date_context
            })
    
    return commitments

def get_commitments_due_data(date_range: str = 'today') -> Dict[str, Any]:
    """Scan meeting notes and person pages for commitments due"""
    today = date.today()
    
    result = {
        'commitments_due_today': [],
        'commitments_due_this_week': [],
        'commitments_no_date': [],
        'sources_scanned': []
    }
    
    # Scan recent meeting notes
    meetings_dir = get_meetings_dir()
    if meetings_dir.exists():
        # Look at meetings from last 14 days
        for meeting_file in meetings_dir.glob('*.md'):
            try:
                # Extract date from filename (assuming YYYY-MM-DD prefix)
                filename = meeting_file.stem
                date_match = re.match(r'(\d{4}-\d{2}-\d{2})', filename)
                if date_match:
                    meeting_date_str = date_match.group(1)
                    meeting_date = datetime.strptime(meeting_date_str, '%Y-%m-%d').date()
                    
                    # Only look at recent meetings
                    if (today - meeting_date).days > 14:
                        continue
                
                content = meeting_file.read_text()
                commitments = extract_commitments_from_text(
                    content, 
                    source=str(meeting_file.relative_to(BASE_DIR)),
                    date_context=meeting_date_str if date_match else ''
                )
                
                for c in commitments:
                    if c['due_date']:
                        due_lower = c['due_date'].lower()
                        if due_lower in ['today', today.strftime('%A').lower()]:
                            result['commitments_due_today'].append(c)
                        elif due_lower in ['tomorrow', 'this week', 'friday', 'thursday', 'wednesday', 'tuesday', 'monday']:
                            result['commitments_due_this_week'].append(c)
                        else:
                            result['commitments_no_date'].append(c)
                    else:
                        result['commitments_no_date'].append(c)
                
                result['sources_scanned'].append(str(meeting_file.name))
                
            except Exception as e:
                logger.error(f"Error scanning {meeting_file}: {e}")
                continue
    
    # Scan person pages for "owe" or "follow up" mentions
    for subdir in ['External', 'Internal']:
        people_subdir = get_people_dir() / subdir
        if not people_subdir.exists():
            continue
        
        for person_file in people_subdir.glob('*.md'):
            try:
                content = person_file.read_text()
                
                # Look for "Open Items" or "Action Items" sections
                open_items_match = re.search(r'(?:## Open Items|## Action Items|## Follow-?ups?)\n(.*?)(?:\n##|\Z)', content, re.DOTALL)
                if open_items_match:
                    section_content = open_items_match.group(1)
                    # Extract uncompleted items
                    for line in section_content.split('\n'):
                        if '- [ ]' in line:
                            item_text = re.sub(r'-\s*\[\s*\]\s*', '', line).strip()
                            result['commitments_no_date'].append({
                                'commitment': item_text,
                                'due_date': None,
                                'source': f"Person: {person_file.stem.replace('_', ' ')}",
                                'to_person': person_file.stem.replace('_', ' ')
                            })
            except Exception:
                continue
    
    return result


# ============================================================================
# CALENDAR CAPACITY ANALYSIS
# ============================================================================

def analyze_day_capacity(events: List[Dict], target_date: date) -> Dict[str, Any]:
    """Analyze a single day's calendar capacity"""
    day_name = target_date.strftime('%A')
    
    # Calculate total meeting time
    total_meeting_minutes = 0
    meeting_count = len(events)
    
    for event in events:
        # Estimate duration from event data
        duration = event.get('duration_minutes', 60)  # Default 1 hour
        total_meeting_minutes += duration
    
    meeting_hours = round(total_meeting_minutes / 60, 1)
    
    # Classify day type
    if meeting_count >= 6 or meeting_hours >= 5:
        day_type = 'stacked'
    elif meeting_count >= 3 or meeting_hours >= 2.5:
        day_type = 'moderate'
    else:
        day_type = 'open'
    
    # Calculate free blocks (simplified - assumes 8am-6pm workday)
    work_start = 8  # 8am
    work_end = 18   # 6pm
    total_work_minutes = (work_end - work_start) * 60
    free_minutes = total_work_minutes - total_meeting_minutes
    
    # Estimate largest block (simplified)
    if day_type == 'stacked':
        largest_block = 30
    elif day_type == 'moderate':
        largest_block = 90
    else:
        largest_block = 180
    
    # Recommendations
    if day_type == 'stacked':
        recommendation = "Quick tasks only - too fragmented for deep work"
    elif day_type == 'moderate':
        recommendation = "Medium tasks, meeting prep, and some focused work"
    else:
        recommendation = "Great day for deep work - protect your focus time"
    
    return {
        'date': target_date.isoformat(),
        'day_name': day_name,
        'meeting_count': meeting_count,
        'meeting_hours': meeting_hours,
        'day_type': day_type,
        'free_minutes': max(0, free_minutes),
        'largest_block_estimate': largest_block,
        'recommendation': recommendation
    }

def get_calendar_capacity_data(days_ahead: int = 5) -> Dict[str, Any]:
    """Analyze calendar capacity for upcoming days
    
    Note: This requires calendar data to be passed in or fetched.
    The skill should call the calendar MCP first, then pass events to this.
    For now, returns structure for manual population.
    """
    today = date.today()
    
    result = {
        'analysis_date': today.isoformat(),
        'days': [],
        'week_summary': {
            'stacked_days': 0,
            'moderate_days': 0,
            'open_days': 0,
            'deep_work_opportunities': []
        },
        'note': 'Calendar events should be provided by calendar MCP for accurate analysis'
    }
    
    # Generate structure for each day
    for i in range(days_ahead):
        target_date = today + timedelta(days=i)
        if target_date.weekday() >= 5:  # Skip weekends
            continue
        
        day_data = {
            'date': target_date.isoformat(),
            'day_name': target_date.strftime('%A'),
            'events': [],  # To be populated with calendar data
            'day_type': 'unknown',
            'recommendation': 'Calendar data needed for analysis'
        }
        result['days'].append(day_data)
    
    return result


# ============================================================================
# SMART SCHEDULING SUGGESTIONS
# ============================================================================

def generate_scheduling_suggestions(
    tasks: List[Dict],
    calendar_capacity: Dict[str, Any]
) -> Dict[str, Any]:
    """Match tasks to available time slots based on effort classification"""
    
    suggestions = []
    warnings = []
    
    # Classify tasks by effort
    deep_work_tasks = []
    medium_tasks = []
    quick_tasks = []
    
    for task in tasks:
        if task.get('completed'):
            continue
        
        effort = classify_task_effort(task.get('title', ''))
        task['effort'] = effort
        
        if effort['effort_type'] == 'deep_work':
            deep_work_tasks.append(task)
        elif effort['effort_type'] == 'medium':
            medium_tasks.append(task)
        else:
            quick_tasks.append(task)
    
    # Find available slots from calendar capacity
    days = calendar_capacity.get('days', [])
    deep_work_slots = []
    medium_slots = []
    
    for day in days:
        day_type = day.get('day_type', 'unknown')
        if day_type == 'open':
            deep_work_slots.append({
                'day': day['day_name'],
                'date': day['date'],
                'block_size': 'large (2-4 hours)'
            })
        elif day_type == 'moderate':
            medium_slots.append({
                'day': day['day_name'],
                'date': day['date'],
                'block_size': 'medium (1-2 hours)'
            })
    
    # Generate suggestions for deep work tasks
    for i, task in enumerate(deep_work_tasks):
        if i < len(deep_work_slots):
            slot = deep_work_slots[i]
            suggestions.append({
                'task': task.get('title'),
                'task_id': task.get('task_id'),
                'effort': 'deep_work',
                'estimated_duration': '2-3 hours',
                'suggested_slot': {
                    'day': slot['day'],
                    'date': slot['date'],
                    'reason': f"{slot['day']} is your best day for deep work this week"
                },
                'action_prompt': f"Block time on {slot['day']} for this?"
            })
        else:
            warnings.append(f"Deep work task '{task.get('title')}' has no suitable slot this week")
    
    # Generate suggestions for medium tasks
    for i, task in enumerate(medium_tasks[:5]):  # Limit to 5
        suggestions.append({
            'task': task.get('title'),
            'task_id': task.get('task_id'),
            'effort': 'medium',
            'estimated_duration': '1-2 hours',
            'suggested_slot': {
                'reason': 'Fit into 1-2 hour gaps between meetings'
            },
            'action_prompt': None
        })
    
    # Quick tasks don't need scheduling
    if quick_tasks:
        suggestions.append({
            'summary': f"{len(quick_tasks)} quick tasks",
            'effort': 'quick',
            'estimated_duration': '10-30 min each',
            'suggested_slot': {
                'reason': 'Batch these between meetings or at end of day'
            },
            'action_prompt': None
        })
    
    # Check for capacity issues
    if len(deep_work_tasks) > len(deep_work_slots):
        warnings.append(f"You have {len(deep_work_tasks)} deep work tasks but only {len(deep_work_slots)} suitable slots this week")
    
    return {
        'suggestions': suggestions,
        'warnings': warnings,
        'task_summary': {
            'deep_work': len(deep_work_tasks),
            'medium': len(medium_tasks),
            'quick': len(quick_tasks)
        },
        'capacity_summary': {
            'deep_work_slots': len(deep_work_slots),
            'moderate_days': len(medium_slots)
        }
    }


# ============================================================================
# MCP SERVER
# ============================================================================

app = Server("dex-work-mcp")

@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available tools"""
    pillar_ids = get_pillar_ids()
    pillar_description = ", ".join(pillar_ids)
    
    return [
        types.Tool(
            name="list_tasks",
            description="List tasks with optional filters (pillar, priority, status, source)",
            inputSchema={
                "type": "object",
                "properties": {
                    "pillar": {"type": "string", "description": f"Filter by pillar ({pillar_description})"},
                    "priority": {"type": "string", "description": "Filter by priority (P0, P1, P2, P3)"},
                    "status": {"type": "string", "description": "Filter by status (n, s, b, d)"},
                    "source": {"type": "string", "description": "Filter by source (tasks, week_priorities)"},
                    "include_done": {"type": "boolean", "description": "Include completed tasks", "default": False}
                }
            }
        ),
        types.Tool(
            name="create_task",
            description="Create a new task with schema validation. Requires title and pillar alignment. Optionally link to weekly priority, account, or people pages.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title (be specific, not vague)"},
                    "pillar": {"type": "string", "enum": pillar_ids, "description": f"Which strategic pillar this supports ({pillar_description})"},
                    "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"], "default": "P2"},
                    "context": {"type": "string", "description": "Additional context or sub-tasks"},
                    "section": {"type": "string", "description": "Which section in 03-Tasks/Tasks.md to add to", "default": "Next Week"},
                    "weekly_priority_id": {"type": "string", "description": "Link to weekly priority (e.g., 'week-2026-W05-p1') - task contributes to this priority"},
                    "account": {"type": "string", "description": "Path to account page to link"},
                    "people": {"type": "array", "items": {"type": "string"}, "description": "List of paths to people pages to link"}
                },
                "required": ["title", "pillar"]
            }
        ),
        types.Tool(
            name="update_task_status",
            description="Update task status everywhere it appears (03-Tasks/Tasks.md, meeting notes, person pages). Provide task_id for guaranteed sync across all locations, or task_title for search-based update.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Unique task ID (e.g., task-20260128-001) for precise multi-location sync"},
                    "task_title": {"type": "string", "description": "Task title to search for (used if task_id not provided)"},
                    "status": {"type": "string", "enum": ["n", "s", "b", "d"], "description": "New status (d=done)"}
                },
                "required": ["status"]
            }
        ),
        types.Tool(
            name="get_system_status",
            description="Get comprehensive system status: task counts, priority distribution, pillar balance, blocked items",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="check_priority_limits",
            description=f"Check if priority limits are exceeded (P0: max {PRIORITY_LIMITS['P0']}, P1: max {PRIORITY_LIMITS['P1']}, P2: max {PRIORITY_LIMITS['P2']})",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="process_inbox_with_dedup",
            description="Process a list of items with duplicate detection and ambiguity checking",
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of items to process"
                    },
                    "auto_create": {
                        "type": "boolean",
                        "description": "Automatically create non-duplicate, non-ambiguous tasks",
                        "default": False
                    }
                },
                "required": ["items"]
            }
        ),
        types.Tool(
            name="get_blocked_tasks",
            description="List all tasks that are currently blocked",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="suggest_focus",
            description="Suggest top 3 tasks to focus on based on priorities and pillar balance",
            inputSchema={
                "type": "object",
                "properties": {
                    "max_tasks": {"type": "integer", "description": "Maximum tasks to suggest", "default": 3}
                }
            }
        ),
        types.Tool(
            name="get_pillar_summary",
            description="Get task distribution across your strategic pillars",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="sync_task_refs",
            description="Refresh the Related Tasks section on an account or people page by reading from 03-Tasks/Tasks.md",
            inputSchema={
                "type": "object",
                "properties": {
                    "page_path": {"type": "string", "description": "Path to the page to sync"}
                },
                "required": ["page_path"]
            }
        ),
        types.Tool(
            name="refresh_company",
            description="Refresh all aggregated sections on a company page (contacts, meetings, tasks)",
            inputSchema={
                "type": "object",
                "properties": {
                    "company_path": {"type": "string", "description": "Path to company page (e.g., 'Acme_Corp' or 'Active/Relationships/Companies/Acme_Corp.md')"}
                },
                "required": ["company_path"]
            }
        ),
        types.Tool(
            name="list_companies",
            description="List all company pages with basic info and contact counts",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="create_company",
            description="Create a new company page",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Company name"},
                    "website": {"type": "string", "description": "Company website URL"},
                    "industry": {"type": "string", "description": "Industry/sector"},
                    "size": {"type": "string", "description": "Company size (Startup / Scale-up / Enterprise)"},
                    "stage": {"type": "string", "enum": ["Prospect", "Customer", "Partner", "Churned"], "default": "Prospect"},
                    "domains": {"type": "array", "items": {"type": "string"}, "description": "Email domains for matching (e.g., ['acme.com', 'acme.io'])"}
                },
                "required": ["name"]
            }
        ),
        types.Tool(
            name="create_quarterly_goal",
            description="Create a new quarterly goal with automatic ID generation and progress tracking. Optionally link to career goals for promotion tracking.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Goal title (specific, outcome-focused)"},
                    "pillar": {"type": "string", "enum": pillar_ids, "description": f"Which strategic pillar this supports ({pillar_description})"},
                    "success_criteria": {"type": "string", "description": "What 'done' looks like - specific, measurable outcome"},
                    "milestones": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}}}, "description": "Key milestones toward the goal"},
                    "quarter": {"type": "string", "description": "Quarter (e.g., 'Q1 2026') - defaults to current quarter"},
                    "career_goal_id": {"type": "string", "description": "Career goal this advances (optional, from 05-Areas/Career/Growth_Goals.md)"},
                    "skills_developed": {"type": "array", "items": {"type": "string"}, "description": "Skills this goal develops (e.g., ['System Design', 'Technical Leadership'])"},
                    "impact_level": {"type": "string", "enum": ["low", "medium", "high"], "description": "Promotion relevance: high=major evidence for next level, medium=solid contribution, low=tactical work"}
                },
                "required": ["title", "pillar", "success_criteria"]
            }
        ),
        types.Tool(
            name="get_quarterly_goals",
            description="List all quarterly goals for a quarter with progress and linked priorities",
            inputSchema={
                "type": "object",
                "properties": {
                    "quarter": {"type": "string", "description": "Quarter (e.g., 'Q1 2026') - defaults to current quarter"},
                    "include_completed": {"type": "boolean", "description": "Include completed goals", "default": True}
                }
            }
        ),
        types.Tool(
            name="get_goal_status",
            description="Get detailed status for a specific goal including progress, linked priorities, and activity",
            inputSchema={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string", "description": "Goal ID (e.g., 'Q1-2026-goal-1')"}
                },
                "required": ["goal_id"]
            }
        ),
        types.Tool(
            name="update_goal_progress",
            description="Update a goal's progress percentage (can be automatic based on priorities or manual)",
            inputSchema={
                "type": "object",
                "properties": {
                    "goal_id": {"type": "string", "description": "Goal ID (e.g., 'Q1-2026-goal-1')"},
                    "progress_pct": {"type": "integer", "description": "Progress percentage (0-100)"},
                    "notes": {"type": "string", "description": "Optional notes about progress"}
                },
                "required": ["goal_id", "progress_pct"]
            }
        ),
        types.Tool(
            name="create_weekly_priority",
            description="Create a weekly priority with optional link to quarterly goal",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Priority title (specific outcome)"},
                    "pillar": {"type": "string", "enum": pillar_ids, "description": f"Which strategic pillar ({pillar_description})"},
                    "quarterly_goal_id": {"type": "string", "description": "Goal ID this priority advances (optional, use 'operational' for non-goal work)"},
                    "success_criteria": {"type": "string", "description": "What success looks like for this priority"},
                    "week_date": {"type": "string", "description": "Monday of target week (YYYY-MM-DD) - defaults to current week"}
                },
                "required": ["title", "pillar"]
            }
        ),
        types.Tool(
            name="get_week_priorities",
            description="Get weekly priorities with completion status and linked tasks/goals",
            inputSchema={
                "type": "object",
                "properties": {
                    "week_date": {"type": "string", "description": "Monday of target week (YYYY-MM-DD) - defaults to current week"}
                }
            }
        ),
        types.Tool(
            name="complete_weekly_priority",
            description="Mark a weekly priority as complete and update linked quarterly goal progress",
            inputSchema={
                "type": "object",
                "properties": {
                    "priority_id": {"type": "string", "description": "Priority ID (e.g., 'week-2026-W05-p1')"}
                },
                "required": ["priority_id"]
            }
        ),
        types.Tool(
            name="get_work_summary",
            description="Get comprehensive work summary: quarterly goals, weekly priorities, daily tasks with warnings",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="check_goal_alignment",
            description="Check alignment between tasks, priorities, and goals - identify orphaned work",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="get_quarter_velocity",
            description="Calculate quarterly progress velocity and projected completion rate",
            inputSchema={
                "type": "object",
                "properties": {
                    "quarter": {"type": "string", "description": "Quarter (e.g., 'Q1 2026') - defaults to current quarter"}
                }
            }
        ),
        types.Tool(
            name="migrate_quarterly_goals",
            description="Add IDs to existing quarterly goals that don't have them (one-time migration)",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="migrate_weekly_priorities",
            description="Add IDs to existing weekly priorities that don't have them (one-time migration)",
            inputSchema={"type": "object", "properties": {}}
        ),
        # ========== NEW PLANNING INTELLIGENCE TOOLS ==========
        types.Tool(
            name="get_week_progress",
            description="Get midweek progress on weekly priorities. Shows which priorities are complete, in progress, or not started, with warnings for priorities that haven't been touched.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="get_meeting_context",
            description="Get comprehensive context for an upcoming meeting: related project, company, attendee details, outstanding tasks with attendees, and prep suggestions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "meeting_title": {"type": "string", "description": "Title of the meeting"},
                    "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee names or emails"}
                }
            }
        ),
        types.Tool(
            name="get_commitments_due",
            description="Scan meeting notes and person pages for commitments and follow-ups that are due today or this week.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date_range": {"type": "string", "enum": ["today", "this_week", "all"], "default": "today", "description": "Which commitments to return"}
                }
            }
        ),
        types.Tool(
            name="classify_task_effort",
            description="Classify a task's effort level (quick: 15-30min, medium: 1-2hrs, deep_work: 2-4hrs) based on keywords and patterns.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title"},
                    "context": {"type": "string", "description": "Additional context about the task"}
                },
                "required": ["title"]
            }
        ),
        types.Tool(
            name="analyze_calendar_capacity",
            description="Analyze calendar capacity for upcoming days. Identifies day types (stacked/moderate/open), estimates free blocks, and finds deep work opportunities. Pass calendar events for accurate analysis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "default": 5, "description": "Number of days to analyze"},
                    "events": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "string", "description": "Event date (YYYY-MM-DD)"},
                                "title": {"type": "string"},
                                "start_time": {"type": "string"},
                                "end_time": {"type": "string"},
                                "duration_minutes": {"type": "integer"}
                            }
                        },
                        "description": "List of calendar events (from calendar MCP)"
                    }
                }
            }
        ),
        types.Tool(
            name="suggest_task_scheduling",
            description="Match tasks to available time slots based on effort classification. Returns scheduling suggestions for deep work, medium, and quick tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_all_tasks": {"type": "boolean", "default": False, "description": "Include all open tasks or just P0/P1"},
                    "calendar_events": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Calendar events for capacity analysis (from calendar MCP)"
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
    
    if name == "list_tasks":
        tasks = get_all_tasks()
        
        if arguments:
            if not arguments.get('include_done', False):
                tasks = [t for t in tasks if not t.get('completed')]
            
            if arguments.get('pillar'):
                tasks = [t for t in tasks if t.get('pillar') == arguments['pillar']]
            
            if arguments.get('priority'):
                tasks = [t for t in tasks if t.get('priority') == arguments['priority']]
            
            if arguments.get('status'):
                tasks = [t for t in tasks if t.get('status') == arguments['status']]
            
            if arguments.get('source'):
                tasks = [t for t in tasks if t.get('source') == arguments['source']]
        else:
            tasks = [t for t in tasks if not t.get('completed')]
        
        result = {
            "tasks": tasks,
            "count": len(tasks),
            "filters_applied": arguments or {}
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "create_task":
        title = arguments['title']
        pillar = arguments['pillar']
        priority = arguments.get('priority', 'P2')
        context = arguments.get('context', '')
        section = arguments.get('section', 'Next Week')
        weekly_priority_id = arguments.get('weekly_priority_id', '')
        account = arguments.get('account', '')
        people = arguments.get('people', [])
        
        # Validate pillar
        if pillar not in PILLARS:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Invalid pillar '{pillar}'. Must be one of: {list(PILLARS.keys())}"
            }, indent=2))]
        
        # Validate priority
        if priority not in PRIORITIES:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Invalid priority '{priority}'. Must be one of: {PRIORITIES}"
            }, indent=2))]
        
        # Check ambiguity
        if is_ambiguous(title):
            questions = generate_clarification_questions(title)
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "Task is too vague",
                "title": title,
                "clarification_needed": questions,
                "suggestion": "Please provide more specific details before creating this task"
            }, indent=2))]
        
        # Check for duplicates
        existing_tasks = get_all_tasks()
        similar = find_similar_tasks(title, existing_tasks)
        if similar:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "Potential duplicate detected",
                "title": title,
                "similar_tasks": similar,
                "suggestion": "Review these similar tasks. If still unique, rephrase the title to be more distinct."
            }, indent=2))]
        
        # Check priority limits
        active_tasks = [t for t in existing_tasks if not t.get('completed')]
        priority_counts = Counter(t.get('priority', 'P2') for t in active_tasks)
        
        if priority in PRIORITY_LIMITS and priority_counts.get(priority, 0) >= PRIORITY_LIMITS[priority]:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Priority limit exceeded for {priority}",
                "current_count": priority_counts.get(priority, 0),
                "limit": PRIORITY_LIMITS[priority],
                "suggestion": f"You have too many {priority} tasks. Complete or deprioritize some before adding more."
            }, indent=2))]
        
        # Generate unique task ID
        task_id = generate_task_id()
        
        # Build file references for account/people
        file_refs = []
        if account:
            # Use plain file path reference
            file_refs.append(account if account.endswith('.md') else f"{account}.md")
        for person in people:
            file_refs.append(person if person.endswith('.md') else f"{person}.md")
        
        # Create the task entry with plain file references and task ID
        pillar_name = PILLARS[pillar]['name']
        task_line = f"- [ ] **{title}**"
        if file_refs:
            task_line += " | " + " ".join(file_refs)
        task_line += f" ^{task_id}"
        
        task_entry = task_line
        if context:
            task_entry += f"\n\t- {context}"
        task_entry += f"\n\t- Pillar: {pillar_name} | Priority: {priority}"
        if weekly_priority_id:
            task_entry += f" | Weekly priority: [{weekly_priority_id}]"
        
        # Add to 03-Tasks/Tasks.md under the appropriate section
        if get_tasks_file().exists():
            content = get_tasks_file().read_text()
        else:
            content = "# Tasks\n\n"
        
        # Find the section and add the task
        section_header = f"## {section}"
        if section_header in content:
            # Add after section header
            parts = content.split(section_header)
            new_content = parts[0] + section_header + "\n" + task_entry + "\n" + parts[1]
        else:
            # Create new section at the top
            lines = content.split('\n')
            insert_idx = 1  # After the first header
            for i, line in enumerate(lines):
                if line.startswith('# '):
                    insert_idx = i + 1
                    break
            lines.insert(insert_idx, f"\n{section_header}\n{task_entry}\n")
            new_content = '\n'.join(lines)
        
        get_tasks_file().write_text(new_content)
        
        # Sync Related Tasks sections in referenced pages
        synced_pages = []
        if account:
            result_sync = sync_task_refs_for_page(account)
            if result_sync['success']:
                synced_pages.append(account)
        for person in people:
            result_sync = sync_task_refs_for_page(person)
            if result_sync['success']:
                synced_pages.append(person)
        
        result = {
            "success": True,
            "task": {
                "title": title,
                "task_id": task_id,
                "pillar": pillar_name,
                "priority": priority,
                "section": section,
                "weekly_priority_id": weekly_priority_id if weekly_priority_id else None,
                "account": account if account else None,
                "people": people if people else None
            },
            "synced_pages": synced_pages,
            "message": f"Task '{title}' created successfully under {section} with ID: {task_id}"
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "update_task_status":
        task_id = arguments.get('task_id')
        task_title = arguments.get('task_title')
        new_status = arguments['status']
        completed = (new_status == 'd')
        
        # If task_id provided, use it directly
        if task_id:
            result = update_task_status_everywhere(task_id, completed)
            if not result['success']:
                return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
            
            # Also sync Related Tasks sections
            synced_pages = propagate_task_status_to_refs(result['title'], completed)
            result['related_tasks_synced'] = synced_pages
            
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
        
        # If task_title provided, find the task and get its ID
        elif task_title:
            all_tasks = get_all_tasks()
            matching = [t for t in all_tasks if task_title.lower() in t['title'].lower()]
            
            if not matching:
                return [types.TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"No task found matching '{task_title}'"
                }, indent=2))]
            
            task = matching[0]
            
            # If task has an ID, use the sync function
            if task.get('task_id'):
                result = update_task_status_everywhere(task['task_id'], completed)
                
                # Also sync Related Tasks sections
                synced_pages = propagate_task_status_to_refs(task['title'], completed)
                result['related_tasks_synced'] = synced_pages
                
                return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
            
            # Legacy support: task without ID, update only in source file
            else:
                filepath = Path(task['source_file'])
                content = filepath.read_text()
                lines = content.split('\n')
                
                line_idx = task['line_number'] - 1
                old_line = lines[line_idx]
                
                # Update checkbox based on status
                if new_status == 'd':
                    new_line = old_line.replace('- [ ]', '- [x]')
                else:
                    new_line = old_line.replace('- [x]', '- [ ]')
                
                lines[line_idx] = new_line
                filepath.write_text('\n'.join(lines))
                
                # Propagate status change to referenced pages
                synced_pages = propagate_task_status_to_refs(task['title'], completed)
                
                status_name = STATUS_CODES.get(new_status, new_status)
                result = {
                    "success": True,
                    "task": task['title'],
                    "new_status": status_name,
                    "source_file": task['source_file'],
                    "synced_pages": synced_pages,
                    "note": "Task has no ID - only updated in source file. Create new tasks with IDs for multi-location sync."
                }
                return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
        
        else:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "Must provide either task_id or task_title"
            }, indent=2))]
    
    elif name == "get_system_status":
        all_tasks = get_all_tasks()
        active_tasks = [t for t in all_tasks if not t.get('completed')]
        
        priority_counts = Counter(t.get('priority', 'P2') for t in active_tasks)
        pillar_counts = Counter(t.get('pillar') or 'unassigned' for t in active_tasks)
        source_counts = Counter(t.get('source', 'unknown') for t in active_tasks)
        
        # Check priority limits
        alerts = []
        for priority, limit in PRIORITY_LIMITS.items():
            count = priority_counts.get(priority, 0)
            if count > limit:
                alerts.append(f"{priority} has {count} tasks (limit: {limit})")
        
        # Time insights
        now = datetime.now()
        hour = now.hour
        time_insights = []
        if 6 <= hour < 12:
            time_insights.append("Morning - ideal for deep work and complex tasks")
        elif 12 <= hour < 14:
            time_insights.append("Midday - good for meetings and collaboration")
        elif 14 <= hour < 17:
            time_insights.append("Afternoon - suitable for admin and follow-ups")
        else:
            time_insights.append("End of day - consider quick wins or planning")
        
        result = {
            "total_tasks": len(all_tasks),
            "active_tasks": len(active_tasks),
            "completed_tasks": len(all_tasks) - len(active_tasks),
            "by_priority": dict(priority_counts),
            "by_pillar": dict(pillar_counts),
            "by_source": dict(source_counts),
            "priority_alerts": alerts,
            "balanced": len(alerts) == 0,
            "time_insights": time_insights,
            "timestamp": now.isoformat()
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "check_priority_limits":
        tasks = [t for t in get_all_tasks() if not t.get('completed')]
        priority_counts = Counter(t.get('priority', 'P2') for t in tasks)
        
        alerts = []
        for priority, limit in PRIORITY_LIMITS.items():
            count = priority_counts.get(priority, 0)
            if count > limit:
                alerts.append({
                    "priority": priority,
                    "current": count,
                    "limit": limit,
                    "exceeded_by": count - limit
                })
        
        result = {
            "priority_counts": dict(priority_counts),
            "limits": PRIORITY_LIMITS,
            "alerts": alerts,
            "balanced": len(alerts) == 0
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "process_inbox_with_dedup":
        items = arguments.get('items', [])
        auto_create = arguments.get('auto_create', False)
        
        if not items:
            return [types.TextContent(type="text", text=json.dumps({
                "error": "No items provided to process"
            }, indent=2))]
        
        existing_tasks = get_all_tasks()
        
        result = {
            "new_tasks": [],
            "potential_duplicates": [],
            "needs_clarification": [],
            "auto_created": [],
            "summary": {}
        }
        
        for item in items:
            # Check for duplicates
            similar_tasks = find_similar_tasks(item, existing_tasks)
            
            if similar_tasks:
                result["potential_duplicates"].append({
                    "item": item,
                    "similar_tasks": similar_tasks,
                    "recommended_action": "merge" if similar_tasks[0]['similarity_score'] > 0.8 else "review"
                })
            elif is_ambiguous(item):
                result["needs_clarification"].append({
                    "item": item,
                    "questions": generate_clarification_questions(item),
                    "suggestions": [
                        "Add more specific details",
                        "Include success criteria",
                        "Specify scope or boundaries"
                    ]
                })
            else:
                guessed_pillar = guess_pillar(item)
                guessed_priority = guess_priority(item)
                
                result["new_tasks"].append({
                    "item": item,
                    "suggested_pillar": guessed_pillar,
                    "suggested_priority": guessed_priority,
                    "ready_to_create": True
                })
        
        result["summary"] = {
            "total_items": len(items),
            "new_tasks": len(result["new_tasks"]),
            "duplicates_found": len(result["potential_duplicates"]),
            "needs_clarification": len(result["needs_clarification"]),
            "recommendations": []
        }
        
        if result["potential_duplicates"]:
            result["summary"]["recommendations"].append(
                f"Review {len(result['potential_duplicates'])} potential duplicates before creating tasks"
            )
        
        if result["needs_clarification"]:
            result["summary"]["recommendations"].append(
                f"Clarify {len(result['needs_clarification'])} ambiguous items for better task definition"
            )
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_blocked_tasks":
        # In this system, blocked tasks would be marked somehow
        # For now, we look for keywords indicating blocked status
        all_tasks = get_all_tasks()
        blocked = []
        
        for task in all_tasks:
            if task.get('completed'):
                continue
            title_lower = task['title'].lower()
            if any(word in title_lower for word in ['waiting', 'blocked', 'pending', 'waiting on']):
                blocked.append(task)
        
        result = {
            "blocked_tasks": blocked,
            "count": len(blocked)
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "suggest_focus":
        max_tasks = arguments.get('max_tasks', 3) if arguments else 3
        all_tasks = get_all_tasks()
        active_tasks = [t for t in all_tasks if not t.get('completed')]
        
        # Score tasks: P0 > P1 > P2 > P3
        priority_scores = {'P0': 100, 'P1': 75, 'P2': 50, 'P3': 25}
        
        for task in active_tasks:
            task['score'] = priority_scores.get(task.get('priority', 'P2'), 50)
        
        # Sort by score
        active_tasks.sort(key=lambda x: x['score'], reverse=True)
        
        suggestions = active_tasks[:max_tasks]
        
        result = {
            "suggested_focus": [
                {
                    "title": t['title'],
                    "priority": t.get('priority', 'P2'),
                    "pillar": PILLARS.get(t.get('pillar'), {}).get('name', 'Unassigned'),
                    "reason": f"{'Critical priority' if t.get('priority') == 'P0' else 'High priority' if t.get('priority') == 'P1' else 'Standard priority'}"
                }
                for t in suggestions
            ],
            "total_active_tasks": len(active_tasks)
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_pillar_summary":
        all_tasks = get_all_tasks()
        active_tasks = [t for t in all_tasks if not t.get('completed')]
        
        pillar_summary = {}
        for pillar_id, pillar_info in PILLARS.items():
            pillar_tasks = [t for t in active_tasks if t.get('pillar') == pillar_id]
            pillar_summary[pillar_id] = {
                "name": pillar_info['name'],
                "description": pillar_info['description'],
                "task_count": len(pillar_tasks),
                "by_priority": dict(Counter(t.get('priority', 'P2') for t in pillar_tasks))
            }
        
        unassigned = [t for t in active_tasks if not t.get('pillar')]
        
        result = {
            "pillars": pillar_summary,
            "unassigned_tasks": len(unassigned),
            "total_active": len(active_tasks),
            "balance_assessment": "Consider balancing" if any(
                pillar_summary[p]['task_count'] == 0 for p in pillar_summary
            ) else "Balanced across pillars"
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "sync_task_refs":
        page_path = arguments['page_path']
        
        result = sync_task_refs_for_page(page_path)
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "refresh_company":
        company_path = arguments['company_path']
        
        result = refresh_company_page(company_path)
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "list_companies":
        companies = list_companies()
        
        result = {
            "companies": companies,
            "count": len(companies)
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "create_company":
        name_arg = arguments['name']
        website = arguments.get('website', '')
        industry = arguments.get('industry', '')
        size = arguments.get('size', '')
        stage = arguments.get('stage', 'Prospect')
        domains = arguments.get('domains', [])
        
        result = create_company_page(
            name=name_arg,
            website=website,
            industry=industry,
            size=size,
            stage=stage,
            domains=domains
        )
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "create_quarterly_goal":
        title = arguments['title']
        pillar = arguments['pillar']
        success_criteria = arguments['success_criteria']
        milestones = arguments.get('milestones', [])
        quarter = arguments.get('quarter')
        career_goal_id = arguments.get('career_goal_id')
        skills_developed = arguments.get('skills_developed', [])
        impact_level = arguments.get('impact_level')
        
        # Validate pillar
        if pillar not in PILLARS:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Invalid pillar '{pillar}'. Must be one of: {list(PILLARS.keys())}"
            }, indent=2))]
        
        # Determine quarter if not provided
        if not quarter:
            quarter_info = get_quarter_info()
            quarter = quarter_info['quarter']
        
        # Create the goal
        goal_data = {
            'title': title,
            'pillar': pillar,
            'success_criteria': success_criteria,
            'milestones': milestones,
            'quarter': quarter,
            'career_goal_id': career_goal_id,
            'skills_developed': skills_developed,
            'impact_level': impact_level
        }
        
        result = create_quarterly_goal_in_file(goal_data)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_quarterly_goals":
        quarter = arguments.get('quarter') if arguments else None
        include_completed = arguments.get('include_completed', True) if arguments else True
        
        # Determine quarter if not provided
        if not quarter:
            quarter_info = get_quarter_info()
            quarter = quarter_info['quarter']
        
        # Read goals
        goals_file = QUARTER_GOALS_FILE
        if is_demo_mode():
            goals_file = DEMO_DIR / '01-Quarter_Goals/Quarter_Goals.md'
        
        goals = parse_quarterly_goals(goals_file)
        
        # Filter by quarter and completion
        filtered_goals = []
        for goal in goals:
            if goal['quarter'] == quarter or not goal['quarter']:
                if include_completed or goal['progress'] < 100:
                    # Enrich with linked priorities
                    linked_priorities = find_linked_priorities(goal['goal_id']) if goal['goal_id'] else []
                    goal['linked_priorities'] = linked_priorities
                    goal['linked_priorities_count'] = len(linked_priorities)
                    filtered_goals.append(goal)
        
        result = {
            "quarter": quarter,
            "goals": filtered_goals,
            "count": len(filtered_goals)
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_goal_status":
        goal_id = arguments['goal_id']
        
        goal = get_goal_by_id(goal_id)
        if not goal:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Goal not found: {goal_id}"
            }, indent=2))]
        
        # Get linked priorities
        linked_priorities = find_linked_priorities(goal_id)
        
        # Calculate progress
        progress_info = calculate_goal_progress(goal_id)
        
        # Check for stalls (no activity in >2 weeks)
        # For now, simplified - would need to track last activity dates
        stalled = len(linked_priorities) == 0
        
        result = {
            "goal_id": goal_id,
            "title": goal['title'],
            "pillar": goal['pillar'],
            "progress": progress_info['progress'],
            "progress_method": progress_info['calculation_method'],
            "linked_priorities": linked_priorities,
            "linked_priorities_count": len(linked_priorities),
            "completed_priorities": progress_info['completed_priorities'],
            "total_priorities": progress_info['total_priorities'],
            "stalled": stalled,
            "warning": "No linked priorities yet" if stalled else None
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "update_goal_progress":
        goal_id = arguments['goal_id']
        progress_pct = arguments['progress_pct']
        notes = arguments.get('notes', '')
        
        # Validate progress
        if not (0 <= progress_pct <= 100):
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "Progress must be between 0 and 100"
            }, indent=2))]
        
        # Update the goal
        success = update_goal_in_file(goal_id, {'progress': progress_pct})
        
        if not success:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Could not find goal: {goal_id}"
            }, indent=2))]
        
        result = {
            "success": True,
            "goal_id": goal_id,
            "progress": progress_pct,
            "notes": notes,
            "updated_at": datetime.now().isoformat()
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "create_weekly_priority":
        title = arguments['title']
        pillar = arguments['pillar']
        quarterly_goal_id = arguments.get('quarterly_goal_id')
        success_criteria = arguments.get('success_criteria', '')
        week_date_str = arguments.get('week_date')
        
        # Validate pillar
        if pillar not in PILLARS:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Invalid pillar '{pillar}'. Must be one of: {list(PILLARS.keys())}"
            }, indent=2))]
        
        # Determine week date
        if week_date_str:
            week_date = datetime.strptime(week_date_str, '%Y-%m-%d').date()
        else:
            today = date.today()
            week_date = today - timedelta(days=today.weekday())  # Monday of current week
        
        # Parse existing priorities to generate ID
        priorities_file = get_week_priorities_file()
        existing_priorities = parse_weekly_priorities(priorities_file) if priorities_file.exists() else []
        priority_id = generate_priority_id(week_date, existing_priorities)
        
        # Build priority entry
        priority_num = len([p for p in existing_priorities if p.get('priority_num', 0) <= 3]) + 1
        if priority_num > 3:
            priority_num = 3  # Cap at 3 for Top 3
        
        pillar_name = PILLARS[pillar]['name']
        priority_line = f"{priority_num}. {title} — **{pillar_name}** ^{priority_id}"
        
        priority_entry = priority_line
        if success_criteria:
            priority_entry += f"\n   - Success criteria: {success_criteria}"
        if quarterly_goal_id and quarterly_goal_id != 'operational':
            priority_entry += f"\n   - Quarterly goal: [{quarterly_goal_id}]"
        
        # Add to Week Priorities.md
        if priorities_file.exists():
            content = priorities_file.read_text()
        else:
            # Create new file
            priorities_file.parent.mkdir(parents=True, exist_ok=True)
            content = f"# Week Priorities\n\n**Week of:** {week_date}\n\n---\n\n## 🎯 Top 3 This Week\n\n"
        
        # Insert after "## 🎯 Top 3 This Week" section
        top3_marker = "## 🎯 Top 3 This Week"
        if top3_marker in content:
            parts = content.split(top3_marker)
            new_content = parts[0] + top3_marker + "\n\n" + priority_entry + "\n" + parts[1]
        else:
            content += "\n" + priority_entry + "\n"
            new_content = content
        
        priorities_file.write_text(new_content)
        
        result = {
            "success": True,
            "priority_id": priority_id,
            "title": title,
            "pillar": pillar_name,
            "week_date": week_date.isoformat(),
            "linked_goal": quarterly_goal_id if quarterly_goal_id != 'operational' else None,
            "message": f"Created weekly priority: {title}"
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_week_priorities":
        week_date_str = arguments.get('week_date') if arguments else None
        
        # Determine week date
        if week_date_str:
            week_date = datetime.strptime(week_date_str, '%Y-%m-%d').date()
        else:
            today = date.today()
            week_date = today - timedelta(days=today.weekday())
        
        # Parse priorities
        priorities_file = get_week_priorities_file()
        priorities = parse_weekly_priorities(priorities_file) if priorities_file.exists() else []
        
        # Enrich with linked tasks
        for priority in priorities:
            if priority.get('priority_id'):
                linked_tasks = find_linked_tasks(priority['priority_id'])
                priority['linked_tasks'] = linked_tasks
                priority['linked_tasks_count'] = len(linked_tasks)
                priority['completed_tasks'] = sum(1 for t in linked_tasks if t['completed'])
        
        result = {
            "week_date": week_date.isoformat(),
            "priorities": priorities,
            "count": len(priorities)
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "complete_weekly_priority":
        priority_id = arguments['priority_id']
        
        # Find the priority in Week Priorities.md
        priorities_file = get_week_priorities_file()
        if not priorities_file.exists():
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": "Week Priorities file not found"
            }, indent=2))]
        
        priorities = parse_weekly_priorities(priorities_file)
        priority = None
        for p in priorities:
            if p.get('priority_id') == priority_id:
                priority = p
                break
        
        if not priority:
            return [types.TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Priority not found: {priority_id}"
            }, indent=2))]
        
        # Mark as completed (for now, just return success)
        # In full implementation, would update the file
        
        # If linked to a goal, recalculate goal progress
        goal_progress = None
        if priority.get('linked_goal_id'):
            progress_info = calculate_goal_progress(priority['linked_goal_id'])
            # Update goal progress
            update_goal_in_file(priority['linked_goal_id'], {'progress': progress_info['progress']})
            goal_progress = progress_info
        
        result = {
            "success": True,
            "priority_id": priority_id,
            "title": priority['title'],
            "completed": True,
            "linked_goal_updated": goal_progress is not None,
            "goal_progress": goal_progress
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_work_summary":
        # Get current quarter info
        quarter_info = get_quarter_info()
        quarter = quarter_info['quarter']
        
        # Get quarterly goals
        goals_file = QUARTER_GOALS_FILE
        if is_demo_mode():
            goals_file = DEMO_DIR / '01-Quarter_Goals/Quarter_Goals.md'
        
        goals = parse_quarterly_goals(goals_file) if goals_file.exists() else []
        
        # Get weekly priorities
        priorities_file = get_week_priorities_file()
        priorities = parse_weekly_priorities(priorities_file) if priorities_file.exists() else []
        
        # Get tasks
        all_tasks = get_all_tasks()
        active_tasks = [t for t in all_tasks if not t.get('completed')]
        
        # Calculate warnings
        warnings = []
        
        # Check for stalled goals
        for goal in goals:
            if goal.get('goal_id'):
                linked_priorities = find_linked_priorities(goal['goal_id'])
                if len(linked_priorities) == 0:
                    warnings.append({
                        'type': 'stalled_goal',
                        'message': f"Goal '{goal['title']}' has no linked priorities",
                        'goal_id': goal['goal_id']
                    })
        
        # Check for orphaned tasks (not linked to any priority)
        # For now, simplified
        
        result = {
            "quarter": quarter,
            "quarter_info": quarter_info,
            "quarterly_summary": {
                "total_goals": len(goals),
                "avg_progress": sum(g['progress'] for g in goals) / len(goals) if goals else 0,
                "goals": goals
            },
            "weekly_summary": {
                "total_priorities": len(priorities),
                "completed": sum(1 for p in priorities if p.get('completed')),
                "priorities": priorities
            },
            "daily_summary": {
                "total_tasks": len(active_tasks),
                "by_priority": dict(Counter(t.get('priority', 'P2') for t in active_tasks))
            },
            "warnings": warnings
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "check_goal_alignment":
        # Get all goals, priorities, and tasks
        goals_file = QUARTER_GOALS_FILE
        if is_demo_mode():
            goals_file = DEMO_DIR / '01-Quarter_Goals/Quarter_Goals.md'
        
        goals = parse_quarterly_goals(goals_file) if goals_file.exists() else []
        priorities_file = get_week_priorities_file()
        priorities = parse_weekly_priorities(priorities_file) if priorities_file.exists() else []
        all_tasks = get_all_tasks()
        active_tasks = [t for t in all_tasks if not t.get('completed')]
        
        # Find orphaned work
        priorities_with_no_goal = [p for p in priorities if not p.get('linked_goal_id')]
        tasks_with_no_priority = []  # Simplified for now
        goals_with_no_priorities = []
        
        for goal in goals:
            if goal.get('goal_id'):
                linked_priorities = find_linked_priorities(goal['goal_id'])
                if len(linked_priorities) == 0:
                    goals_with_no_priorities.append(goal)
        
        result = {
            "priorities_without_goal": {
                "count": len(priorities_with_no_goal),
                "items": priorities_with_no_goal
            },
            "tasks_without_priority": {
                "count": len(tasks_with_no_priority),
                "items": tasks_with_no_priority
            },
            "goals_without_priorities": {
                "count": len(goals_with_no_priorities),
                "items": goals_with_no_priorities
            },
            "recommendations": []
        }
        
        if len(priorities_with_no_goal) > 0:
            result['recommendations'].append(f"Consider linking {len(priorities_with_no_goal)} priorities to quarterly goals or mark as operational")
        
        if len(goals_with_no_priorities) > 0:
            result['recommendations'].append(f"{len(goals_with_no_priorities)} goals have no weekly priorities - create priorities to advance them")
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_quarter_velocity":
        quarter = arguments.get('quarter') if arguments else None
        
        # Determine quarter if not provided
        if not quarter:
            quarter_info = get_quarter_info()
            quarter = quarter_info['quarter']
        else:
            quarter_info = get_quarter_info()  # Still get for weeks remaining
        
        # Get quarterly goals
        goals_file = QUARTER_GOALS_FILE
        if is_demo_mode():
            goals_file = DEMO_DIR / '01-Quarter_Goals/Quarter_Goals.md'
        
        goals = parse_quarterly_goals(goals_file) if goals_file.exists() else []
        
        # Calculate metrics
        total_goals = len(goals)
        completed_goals = sum(1 for g in goals if g['progress'] >= 100)
        avg_progress = sum(g['progress'] for g in goals) / total_goals if total_goals > 0 else 0
        weeks_remaining = quarter_info['weeks_remaining']
        
        # Calculate velocity (progress per week)
        # Simplified - would need historical data for accuracy
        weeks_elapsed = 13 - weeks_remaining  # Rough estimate (13 weeks per quarter)
        velocity = avg_progress / weeks_elapsed if weeks_elapsed > 0 else 0
        
        # Projected completion
        projected_progress = avg_progress + (velocity * weeks_remaining)
        
        # Assessment
        if projected_progress >= 90:
            assessment = "On pace to complete goals"
        elif projected_progress >= 70:
            assessment = "Moderate pace - some goals may not complete"
        else:
            assessment = "Behind pace - need acceleration or scope adjustment"
        
        result = {
            "quarter": quarter,
            "total_goals": total_goals,
            "completed_goals": completed_goals,
            "avg_progress": round(avg_progress, 1),
            "weeks_remaining": weeks_remaining,
            "velocity_per_week": round(velocity, 1),
            "projected_completion": round(projected_progress, 1),
            "assessment": assessment,
            "recommendations": []
        }
        
        if projected_progress < 70:
            result['recommendations'].append("Consider reducing goal scope or increasing focus on key goals")
        if any(g['progress'] == 0 for g in goals):
            result['recommendations'].append("Some goals have not started - prioritize or defer")
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "migrate_quarterly_goals":
        result = migrate_quarterly_goals()
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "migrate_weekly_priorities":
        result = migrate_weekly_priorities()
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    # ========== NEW PLANNING INTELLIGENCE HANDLERS ==========
    
    elif name == "get_week_progress":
        result = get_week_progress_data()
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_meeting_context":
        meeting_title = arguments.get('meeting_title') if arguments else None
        attendees = arguments.get('attendees', []) if arguments else []
        
        result = get_meeting_context_data(meeting_title, attendees)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_commitments_due":
        date_range = arguments.get('date_range', 'today') if arguments else 'today'
        
        result = get_commitments_due_data(date_range)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "classify_task_effort":
        title = arguments['title']
        context = arguments.get('context', '') if arguments else ''
        
        result = classify_task_effort(title, context)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "analyze_calendar_capacity":
        days_ahead = arguments.get('days_ahead', 5) if arguments else 5
        events = arguments.get('events', []) if arguments else []
        
        # If events provided, analyze them; otherwise return structure for manual use
        if events:
            today = date.today()
            days_data = []
            
            # Group events by date
            events_by_date = {}
            for event in events:
                event_date = event.get('date', today.isoformat())
                if event_date not in events_by_date:
                    events_by_date[event_date] = []
                events_by_date[event_date].append(event)
            
            # Analyze each day
            for i in range(days_ahead):
                target_date = today + timedelta(days=i)
                if target_date.weekday() >= 5:  # Skip weekends
                    continue
                
                date_str = target_date.isoformat()
                day_events = events_by_date.get(date_str, [])
                
                day_analysis = analyze_day_capacity(day_events, target_date)
                days_data.append(day_analysis)
            
            # Summarize
            stacked_days = sum(1 for d in days_data if d['day_type'] == 'stacked')
            moderate_days = sum(1 for d in days_data if d['day_type'] == 'moderate')
            open_days = sum(1 for d in days_data if d['day_type'] == 'open')
            
            deep_work_opportunities = [
                {'day': d['day_name'], 'date': d['date'], 'available_hours': round(d['largest_block_estimate'] / 60, 1)}
                for d in days_data if d['day_type'] == 'open'
            ]
            
            result = {
                'analysis_date': today.isoformat(),
                'days': days_data,
                'week_summary': {
                    'stacked_days': stacked_days,
                    'moderate_days': moderate_days,
                    'open_days': open_days,
                    'deep_work_opportunities': deep_work_opportunities
                }
            }
        else:
            result = get_calendar_capacity_data(days_ahead)
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "suggest_task_scheduling":
        include_all = arguments.get('include_all_tasks', False) if arguments else False
        calendar_events = arguments.get('calendar_events', []) if arguments else []
        
        # Get tasks
        all_tasks = get_all_tasks()
        active_tasks = [t for t in all_tasks if not t.get('completed')]
        
        # Filter by priority if not including all
        if not include_all:
            active_tasks = [t for t in active_tasks if t.get('priority', 'P2') in ['P0', 'P1']]
        
        # Get calendar capacity (use events if provided, otherwise use basic structure)
        if calendar_events:
            today = date.today()
            days_data = []
            
            events_by_date = {}
            for event in calendar_events:
                event_date = event.get('date', today.isoformat())
                if event_date not in events_by_date:
                    events_by_date[event_date] = []
                events_by_date[event_date].append(event)
            
            for i in range(5):
                target_date = today + timedelta(days=i)
                if target_date.weekday() >= 5:
                    continue
                
                date_str = target_date.isoformat()
                day_events = events_by_date.get(date_str, [])
                day_analysis = analyze_day_capacity(day_events, target_date)
                days_data.append(day_analysis)
            
            calendar_capacity = {'days': days_data}
        else:
            calendar_capacity = get_calendar_capacity_data(5)
        
        result = generate_scheduling_suggestions(active_tasks, calendar_capacity)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

async def _main():
    """Async main entry point for the MCP server"""
    logger.info(f"Starting Dex Work MCP Server")
    logger.info(f"Vault path: {BASE_DIR}")
    logger.info(f"Tasks file: {get_tasks_file()}")
    logger.info(f"Pillars loaded: {list(PILLARS.keys())}")
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-work-mcp",
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
