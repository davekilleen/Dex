#!/usr/bin/env python3
"""
MCP Server for Dex Task Management System
Based on Aman Khan's personal-os approach.

Provides deterministic task operations through structured tools with:
- Schema validation
- Deduplication
- Ambiguity detection
- Priority limits
- Pillar alignment (loaded from System/pillars.yaml)
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
TASKS_FILE = BASE_DIR / '03-Tasks/Tasks.md'
WEEK_PRIORITIES_FILE = BASE_DIR / 'Inbox' / 'Week Priorities.md'
GOALS_FILE = BASE_DIR / 'GOALS.md'
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
# MCP SERVER
# ============================================================================

app = Server("dex-task-mcp")

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
            description="Create a new task with schema validation. Requires title and pillar alignment. Optionally link to account/people pages.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Task title (be specific, not vague)"},
                    "pillar": {"type": "string", "enum": pillar_ids, "description": f"Which strategic pillar this supports ({pillar_description})"},
                    "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"], "default": "P2"},
                    "context": {"type": "string", "description": "Additional context or sub-tasks"},
                    "section": {"type": "string", "description": "Which section in 03-Tasks/Tasks.md to add to", "default": "Next Week"},
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
    
    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

async def _main():
    """Async main entry point for the MCP server"""
    logger.info(f"Starting Dex Task MCP Server")
    logger.info(f"Vault path: {BASE_DIR}")
    logger.info(f"Tasks file: {get_tasks_file()}")
    logger.info(f"Pillars loaded: {list(PILLARS.keys())}")
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-task-mcp",
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
