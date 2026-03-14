#!/usr/bin/env python3
"""
MCP Server for Dex Improvements Backlog System

Provides tools for capturing and managing Dex system improvement ideas with:
- Quick capture from any context
- Idea storage with metadata
- List and filter capabilities
- Implementation tracking
- AI-powered synthesis from changelogs and session learnings
- Idea enrichment with new evidence
"""

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# QMD semantic search (optional - gracefully degrade if not available)
try:
    from utils.qmd_query import is_qmd_available, vault_search
    HAS_QMD = True
except ImportError:
    HAS_QMD = False

# Analytics helper (optional - gracefully degrade if not available)
try:
    from analytics_helper import fire_event as _fire_analytics_event
    HAS_ANALYTICS = True
except ImportError:
    HAS_ANALYTICS = False
    def _fire_analytics_event(event_name, properties=None):
        return {'fired': False, 'reason': 'analytics_not_available'}

# Health system — error queue and health reporting
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from core.utils.dex_logger import log_error as _log_health_error
    from core.utils.dex_logger import mark_healthy as _mark_healthy
    _HAS_HEALTH = True
except ImportError:
    _HAS_HEALTH = False

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
BACKLOG_FILE = BASE_DIR / 'System' / 'Dex_Backlog.md'
SYSTEM_DIR = BASE_DIR / 'System'
CHANGELOG_FILE = BASE_DIR / '06-Resources' / 'Claude_Code_Docs' / 'changelog-log.md'
SESSION_LEARNINGS_DIR = BASE_DIR / 'System' / 'Session_Learnings'
SYNTHESIS_STATE_FILE = BASE_DIR / 'System' / '.synthesis-state.json'

# Valid categories for ideas
CATEGORIES = [
    'workflows',      # daily/weekly/quarterly routines
    'automation',     # scripts, hooks, MCP
    'relationships',  # people, companies, meetings
    'tasks',          # capture, management, prioritization
    'projects',       # tracking, health, planning
    'knowledge',      # capture, synthesis, retrieval
    'system',         # configuration, structure, tooling
    'ux',             # user experience improvements
    'integration',    # external service integrations
    'performance',    # speed and efficiency
    'intelligence',   # proactive insights and discovery
]

# Keywords that indicate a changelog entry is relevant to Dex
DEX_RELEVANCE_KEYWORDS = [
    'memory', 'memories', 'recall', 'remember',
    'hook', 'hooks', 'session',
    'agent', 'agents', 'sub-agent', 'teammate', 'multi-agent',
    'mcp', 'tool', 'tools', 'server',
    'task', 'tasks', 'todo',
    'skill', 'skills', 'command', 'commands', 'slash',
    'context', 'compact', 'summariz',
    'claude.md', 'additional director',
    'keybind', 'keyboard', 'shortcut',
    'oauth', 'credential', 'authentication',
    'pdf', 'document',
    'webhook', 'notification',
]

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def generate_idea_id() -> str:
    """Generate a unique idea ID in format: idea-XXX"""
    if not BACKLOG_FILE.exists():
        return "idea-001"
    
    content = BACKLOG_FILE.read_text()
    
    # Find all existing idea IDs
    pattern = r'\[idea-(\d{3})\]'
    matches = re.findall(pattern, content)
    
    if not matches:
        return "idea-001"
    
    # Get next available number
    max_num = max(int(m) for m in matches)
    next_num = max_num + 1
    
    return f"idea-{next_num:03d}"

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two strings (0-1 score)"""
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

def find_similar_ideas(title: str, description: str) -> List[Dict[str, Any]]:
    """Find ideas similar to the given title/description.
    
    Uses QMD semantic search when available for meaning-based dedup
    (e.g., "Auto-suggest meeting prep" matches "Meeting intelligence assistant").
    Falls back to SequenceMatcher when QMD is not installed.
    """
    if not BACKLOG_FILE.exists():
        return []
    
    similar = []
    ideas = parse_backlog_file()
    
    # --- QMD semantic dedup (if available) ---
    qmd_title_matches = set()
    if HAS_QMD and is_qmd_available():
        try:
            results = vault_search(
                query=f"{title} {description[:100]}",
                limit=5,
                min_score=0.3,
                fallback_glob="System/Dex_Backlog.md"
            )
            for r in results:
                snippet = r.get('snippet', '').lower()
                score = r.get('score', 0)
                if score >= 0.35:
                    qmd_title_matches.add(snippet[:100])
        except Exception:
            pass
    
    for idea in ideas:
        title_similarity = calculate_similarity(title, idea['title'])
        desc_similarity = calculate_similarity(description, idea.get('description', ''))
        
        # Check if QMD flagged this idea as semantically similar
        qmd_boost = 0.0
        if qmd_title_matches:
            idea_title_lower = idea['title'].lower()
            for qmd_snippet in qmd_title_matches:
                if idea_title_lower in qmd_snippet or any(
                    word in qmd_snippet for word in idea_title_lower.split() if len(word) > 4
                ):
                    qmd_boost = 0.15
                    break
        
        similarity_score = (title_similarity * 0.6) + (desc_similarity * 0.25) + qmd_boost
        
        if similarity_score >= 0.5:
            similar.append({
                'id': idea['id'],
                'title': idea['title'],
                'similarity': round(similarity_score, 2),
                'semantic_match': qmd_boost > 0
            })
    
    similar.sort(key=lambda x: x['similarity'], reverse=True)
    return similar[:3]

def parse_backlog_file() -> List[Dict[str, Any]]:
    """Parse the Dex backlog file and extract all ideas"""
    if not BACKLOG_FILE.exists():
        return []
    
    content = BACKLOG_FILE.read_text()
    ideas = []
    
    # Pattern to match idea entries
    # Matches: - **[idea-XXX]** Title
    idea_pattern = r'-\s*\*\*\[(idea-\d{3})\]\*\*\s*(.+?)(?:\n|$)'
    
    matches = re.finditer(idea_pattern, content)
    
    for match in matches:
        idea_id = match.group(1)
        title = match.group(2).strip()
        
        # Extract metadata for this idea (lines following the title)
        start_pos = match.end()
        
        # Find the next idea or section boundary
        next_match = re.search(r'(?:\n-\s*\*\*\[idea-|\n###|\n##)', content[start_pos:])
        if next_match:
            idea_block = content[start_pos:start_pos + next_match.start()]
        else:
            idea_block = content[start_pos:]
        
        # Parse metadata
        score_match = re.search(r'\*\*Score:\*\*\s*(\d+)', idea_block)
        category_match = re.search(r'\*\*Category:\*\*\s*(\w+)', idea_block)
        captured_match = re.search(r'\*\*Captured:\*\*\s*([\d-]+)', idea_block)
        desc_match = re.search(r'\*\*Description:\*\*\s*(.+?)(?:\n\s*-|\n\s*\*\*|$)', idea_block, re.DOTALL)
        status_match = re.search(r'\*\*Status:\*\*\s*(\w+)', idea_block)
        
        # Check if in Archive section
        is_implemented = 'Archive (Implemented)' in content[:match.start()]
        
        ideas.append({
            'id': idea_id,
            'title': title,
            'score': int(score_match.group(1)) if score_match else 0,
            'category': category_match.group(1) if category_match else 'system',
            'captured': captured_match.group(1) if captured_match else datetime.now().strftime('%Y-%m-%d'),
            'description': desc_match.group(1).strip() if desc_match else '',
            'status': 'implemented' if is_implemented else 'active'
        })
    
    return ideas

def load_synthesis_state() -> Dict[str, Any]:
    """Load the synthesis state tracking file"""
    if SYNTHESIS_STATE_FILE.exists():
        try:
            return json.loads(SYNTHESIS_STATE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "last_changelog_synthesis": None,
        "last_changelog_version_seen": None,
        "last_learnings_synthesis": None,
        "synthesis_history": []
    }

def save_synthesis_state(state: Dict[str, Any]):
    """Save the synthesis state tracking file"""
    SYNTHESIS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYNTHESIS_STATE_FILE.write_text(json.dumps(state, indent=2, cls=DateTimeEncoder))

def parse_changelog_entries(since_date: Optional[str] = None) -> List[Dict[str, str]]:
    """Parse changelog-log.md into structured entries, optionally filtered by date.
    
    Handles two formats:
    - Date headers: ## YYYY-MM-DD
    - Version headers: ### vX.X.X (under a date header)
    - Feature lines: - Feature description
    """
    if not CHANGELOG_FILE.exists():
        return []

    content = CHANGELOG_FILE.read_text()
    entries = []
    current_date = None
    current_version = None

    for line in content.splitlines():
        date_match = re.match(r'^##\s+(\d{4}-\d{2}-\d{2})\s*$', line)
        if date_match:
            current_date = date_match.group(1)
            continue

        version_match = re.match(r'^#{2,3}\s+v(\S+?)(?:\s*[-–—]\s*(\d{4}-\d{2}-\d{2}))?', line)
        if version_match:
            current_version = version_match.group(1)
            if version_match.group(2):
                current_date = version_match.group(2)
            continue

        if line.strip().startswith('- ') and current_date:
            feature_text = line.strip()[2:].strip()
            if not feature_text or len(feature_text) < 10:
                continue

            if since_date and current_date < since_date:
                continue

            entries.append({
                "date": current_date,
                "version": current_version or "",
                "feature": feature_text,
            })

    return entries

def score_changelog_relevance(feature_text: str) -> int:
    """Score how relevant a changelog entry is to Dex (0-100)"""
    text_lower = feature_text.lower()
    score = 0

    for keyword in DEX_RELEVANCE_KEYWORDS:
        if keyword in text_lower:
            score += 15

    if any(w in text_lower for w in ['added', 'new', 'support for']):
        score += 10
    if any(w in text_lower for w in ['fixed', 'improved']):
        score += 5

    if any(w in text_lower for w in ['vscode', 'ide', 'windows', 'thai', 'lao', 'japanese ime', 'zenkaku']):
        score -= 20

    return min(score, 100)

def infer_category_from_feature(feature_text: str) -> str:
    """Infer a backlog category from a changelog feature description"""
    text_lower = feature_text.lower()
    if any(w in text_lower for w in ['memory', 'memories', 'recall', 'remember', 'context', 'compact', 'summariz']):
        return 'knowledge'
    if any(w in text_lower for w in ['agent', 'sub-agent', 'teammate', 'multi-agent', 'task']):
        return 'performance'
    if any(w in text_lower for w in ['mcp', 'oauth', 'credential', 'slack', 'integration']):
        return 'integration'
    if any(w in text_lower for w in ['hook', 'automat', 'cron', 'background']):
        return 'automation'
    if any(w in text_lower for w in ['keybind', 'keyboard', 'shortcut', 'ui', 'ux']):
        return 'ux'
    if any(w in text_lower for w in ['skill', 'command', 'slash']):
        return 'workflows'
    return 'system'

def generate_idea_title_from_feature(feature_text: str) -> str:
    """Generate a concise backlog idea title from a changelog feature"""
    text = feature_text.strip()
    if text.startswith('Added '):
        text = text[6:]
    elif text.startswith('New '):
        text = text[4:]
    if len(text) > 80:
        text = text[:77] + '...'
    return f"Leverage: {text}"

def parse_session_learnings(since_date: Optional[str] = None) -> List[Dict[str, str]]:
    """Parse session learnings files for pending improvements"""
    if not SESSION_LEARNINGS_DIR.exists():
        return []

    learnings = []
    for filepath in sorted(SESSION_LEARNINGS_DIR.glob('*.md'), reverse=True):
        file_date = filepath.stem
        if since_date and file_date < since_date:
            continue

        content = filepath.read_text()
        blocks = re.split(r'\n---\n', content)

        for block in blocks:
            status_match = re.search(r'\*\*Status:\*\*\s*(\w+)', block)
            if not status_match or status_match.group(1) != 'pending':
                continue

            title_match = re.search(r'##\s*\[?\d{2}:\d{2}\]?\s*-?\s*(.+)', block)
            fix_match = re.search(r'\*\*Suggested fix:\*\*\s*(.+?)(?:\n\*\*|\n---|\Z)', block, re.DOTALL)
            what_match = re.search(r'\*\*What happened:\*\*\s*(.+?)(?:\n\*\*|\n---|\Z)', block, re.DOTALL)
            why_match = re.search(r'\*\*Why it matters:\*\*\s*(.+?)(?:\n\*\*|\n---|\Z)', block, re.DOTALL)

            if title_match:
                learnings.append({
                    "date": file_date,
                    "title": title_match.group(1).strip(),
                    "what_happened": what_match.group(1).strip() if what_match else "",
                    "why_it_matters": why_match.group(1).strip() if why_match else "",
                    "suggested_fix": fix_match.group(1).strip() if fix_match else "",
                    "file": str(filepath),
                })

    return learnings

def enrich_idea_in_backlog(idea_id: str, evidence: str, source: str) -> Dict[str, Any]:
    """Append evidence to an existing idea's entry in the backlog"""
    if not BACKLOG_FILE.exists():
        return {"success": False, "error": "Backlog file not found"}

    content = BACKLOG_FILE.read_text()
    today = datetime.now().strftime('%Y-%m-%d')

    enrichment_line = f"\n  - **🔔 Why Now? (AI-enriched {today}):** {evidence} *(Source: {source})*"

    idea_pattern = rf'(-\s*\*\*\[{re.escape(idea_id)}\]\*\*.*?)(\n\n|- \*\*\[idea-|\n###|\n##)'
    match = re.search(idea_pattern, content, re.DOTALL)

    if not match:
        return {"success": False, "error": f"Idea {idea_id} not found in backlog"}

    idea_block = match.group(1)
    boundary = match.group(2)

    if '🔔 Why Now?' in idea_block:
        last_line_end = idea_block.rfind('\n  - **🔔')
        if last_line_end == -1:
            new_block = idea_block + enrichment_line
        else:
            eol = idea_block.find('\n', last_line_end + 1)
            if eol == -1:
                eol = len(idea_block)
            old_line = idea_block[last_line_end:eol]
            new_block = idea_block[:eol] + enrichment_line
    else:
        new_block = idea_block + enrichment_line

    new_content = content[:match.start()] + new_block + boundary + content[match.end():]
    BACKLOG_FILE.write_text(new_content)

    return {"success": True, "idea_id": idea_id, "evidence_added": evidence[:100] + "..."}

def insert_idea_into_priority_queue(idea_id: str, title: str, description: str, category: str, score: int = 0, author: str = None, source: str = None) -> bool:
    """Insert an idea into the correct priority section based on score.
    
    Works for both user-captured and AI-discovered ideas. Ideas are placed
    in High (85+), Medium (60-84), or Low (<60) priority sections.
    """
    if not BACKLOG_FILE.exists():
        initialize_backlog_file()

    content = BACKLOG_FILE.read_text()
    captured_date = datetime.now().strftime('%Y-%m-%d')

    lines = [f"- **[{idea_id}]** {title}"]
    if author:
        lines.append(f"  - **Author:** {author}")
    lines.append(f"  - **Score:** {score}{'' if score > 0 else ' (not yet ranked - run `/dex-backlog` to calculate)'}")
    lines.append(f"  - **Category:** {category}")
    lines.append(f"  - **Captured:** {captured_date}")
    if source:
        lines.append(f"  - **Source:** {source}")
    lines.append(f"  - **Description:** {description}")
    lines.append("")

    idea_entry = "\n".join(lines) + "\n"

    if score >= 85:
        section_pattern = r'(### 🔥 High Priority \(Score: 85\+\)\s*\n(?:\s*\*[^*]+\*\s*\n)?)'
    elif score >= 60:
        section_pattern = r'(### ⚡ Medium Priority \(Score: 60-84\)\s*\n(?:\s*\*[^*]+\*\s*\n)?)'
    else:
        section_pattern = r'(### 💡 (?:Low|Lower) Priority \(Score: <60\)\s*\n(?:\s*\*[^*]+\*\s*\n)?)'

    match = re.search(section_pattern, content)
    if match:
        insert_pos = match.end()
        new_content = content[:insert_pos] + "\n" + idea_entry + content[insert_pos:]
    else:
        fallback = re.search(r'(## Archive|## Summary|---\s*$)', content)
        if fallback:
            insert_pos = fallback.start()
            new_content = content[:insert_pos] + idea_entry + "\n" + content[insert_pos:]
        else:
            new_content = content + "\n" + idea_entry

    BACKLOG_FILE.write_text(new_content)
    return True


def add_ai_idea_to_backlog(idea_id: str, title: str, description: str, category: str, source: str, score: int = 0) -> bool:
    """Add an AI-discovered idea to the backlog, routed by score into the priority queue."""
    return insert_idea_into_priority_queue(
        idea_id, title, description, category,
        score=score, author=f"AI ({source})", source=source
    )


# ============================================================================
# BACKLOG HYGIENE — Redundancy & Staleness Detection
# ============================================================================

BACKLOG_TARGET_MAX = 20
STALE_THRESHOLD_DAYS = 90
AI_SHELF_LIFE_DAYS = 30
AI_LOW_CONVICTION_SCORE = 55

def _scan_skill_names() -> List[Dict[str, str]]:
    """Scan .claude/skills/ for available skill names and descriptions."""
    skills = []
    skills_dir = BASE_DIR / '.claude' / 'skills'
    if not skills_dir.exists():
        return skills
    for skill_dir in skills_dir.iterdir():
        if not skill_dir.is_dir() or skill_dir.name.startswith(('_', '.')):
            continue
        skill_file = skill_dir / 'SKILL.md'
        if not skill_file.exists():
            continue
        try:
            content = skill_file.read_text()
            desc_match = re.search(r'^description:\s*(.+)$', content, re.MULTILINE)
            desc = desc_match.group(1).strip() if desc_match else ''
            skills.append({'name': skill_dir.name, 'description': desc})
        except Exception:
            skills.append({'name': skill_dir.name, 'description': ''})
    return skills


def _scan_mcp_tool_names() -> List[Dict[str, str]]:
    """Scan core/mcp/*.py for MCP tool names and descriptions."""
    tools = []
    mcp_dir = BASE_DIR / 'core' / 'mcp'
    if not mcp_dir.exists():
        mcp_dir = Path(__file__).parent
    for py_file in mcp_dir.glob('*.py'):
        if py_file.name.startswith('_'):
            continue
        try:
            content = py_file.read_text()
            for m in re.finditer(r'name="([^"]+)".*?description="([^"]*)"', content, re.DOTALL):
                tools.append({'name': m.group(1), 'description': m.group(2)[:200]})
        except Exception:
            continue
    return tools


def _scan_shipped_wip() -> List[Dict[str, str]]:
    """Parse Work_In_Progress.md for shipped/completed items."""
    shipped = []
    wip_file = BASE_DIR / 'System' / 'Work_In_Progress.md'
    if not wip_file.exists():
        return shipped
    try:
        content = wip_file.read_text()
        sections = content.split('### ')
        for section in sections[1:]:
            title_line = section.split('\n')[0].strip()
            title = re.sub(r'^[⭐🔥💡\d]+\.?\s*', '', title_line).strip()
            status_match = re.search(r'\*\*Status:\*\*\s*(.*)', section)
            status = status_match.group(1).strip() if status_match else ''
            if any(kw in status.lower() for kw in ['shipped', 'completed', '✅']):
                shipped.append({'title': title, 'status': status})
    except Exception:
        pass
    return shipped


def _scan_capabilities_done() -> List[str]:
    """Read latest capabilities report for items marked Done in the backlog table."""
    done_items = []
    reports_dir = BASE_DIR / '06-Resources' / 'Intel' / 'Claude_Code_Intel' / 'reports'
    if not reports_dir.exists():
        return done_items
    report_files = sorted(reports_dir.glob('capabilities-*.md'), reverse=True)
    if not report_files:
        return done_items
    try:
        content = report_files[0].read_text()
        for m in re.finditer(r'\|\s*(.+?)\s*\|.*?\|\s*✅\s*Done\s*\|', content):
            done_items.append(m.group(1).strip())
    except Exception:
        pass
    return done_items


def _parse_author(idea_block: str) -> Optional[str]:
    """Extract author from an idea's metadata block."""
    m = re.search(r'\*\*Author:\*\*\s*(.+?)(?:\n|$)', idea_block)
    return m.group(1).strip() if m else None


def _parse_enrichment_dates(idea_block: str) -> List[str]:
    """Extract enrichment dates from 'Why Now?' annotations."""
    return re.findall(r'AI-enriched\s+(\d{4}-\d{2}-\d{2})', idea_block)


def validate_backlog_ideas() -> Dict[str, Any]:
    """Run redundancy and staleness checks on all active backlog ideas.

    Returns a structured report with recommended actions per idea.
    """
    ideas = parse_backlog_file()
    active = [i for i in ideas if i['status'] == 'active']

    if not active:
        return {"validated": 0, "actions": [], "healthy": 0,
                "target": BACKLOG_TARGET_MAX, "over_target_by": 0}

    # Gather system state once
    skills = _scan_skill_names()
    mcp_tools = _scan_mcp_tool_names()
    shipped_wip = _scan_shipped_wip()
    cap_done = _scan_capabilities_done()

    # Build combined text corpus for matching
    skill_texts = [f"{s['name']} {s['description']}" for s in skills]
    mcp_texts = [f"{t['name']} {t['description']}" for t in mcp_tools]
    wip_texts = [s['title'] for s in shipped_wip]

    # Read raw backlog for author/enrichment parsing
    backlog_content = BACKLOG_FILE.read_text() if BACKLOG_FILE.exists() else ''

    today = datetime.now()
    actions = []

    for idea in active:
        idea_text = f"{idea['title']} {idea.get('description', '')}"
        idea_lower = idea_text.lower()

        # Extract author + enrichment dates from raw file
        idea_pattern = rf'-\s*\*\*\[{re.escape(idea["id"])}\]\*\*.*?(?=\n-\s*\*\*\[idea-|\n###|\n##|$)'
        block_match = re.search(idea_pattern, backlog_content, re.DOTALL)
        idea_block = block_match.group(0) if block_match else ''
        author = _parse_author(idea_block)
        enrichment_dates = _parse_enrichment_dates(idea_block)

        best_action = None
        best_confidence = 0.0
        best_reason = ''

        # --- Redundancy Check 1: Skill overlap ---
        for st in skill_texts:
            sim = calculate_similarity(idea_lower, st.lower())
            if sim > 0.6 and sim > best_confidence:
                skill_name = st.split(' ')[0]
                best_action = 'kill'
                best_confidence = round(sim, 2)
                best_reason = f"Skill /{skill_name} already provides this capability"

        # --- Redundancy Check 2: MCP tool overlap ---
        for mt in mcp_texts:
            sim = calculate_similarity(idea_lower, mt.lower())
            if sim > 0.6 and sim > best_confidence:
                tool_name = mt.split(' ')[0]
                best_action = 'kill'
                best_confidence = round(sim, 2)
                best_reason = f"MCP tool '{tool_name}' already provides this"

        # --- Redundancy Check 3: WIP shipped overlap ---
        for wt in wip_texts:
            sim = calculate_similarity(idea_lower, wt.lower())
            if sim > 0.55 and sim > best_confidence:
                best_action = 'kill'
                best_confidence = round(sim, 2)
                best_reason = f"Shipped in WIP: '{wt}'"

        # --- Redundancy Check 4: Capabilities report "Done" items ---
        for done_item in cap_done:
            sim = calculate_similarity(idea_lower, done_item.lower())
            if sim > 0.5:
                if sim > best_confidence:
                    best_action = 'kill'
                    best_confidence = round(sim, 2)
                    best_reason = f"Capabilities report marked done: '{done_item}'"
                elif sim > 0.35 and best_confidence < 0.5:
                    best_action = 'downrank'
                    best_confidence = round(sim, 2)
                    best_reason = f"Partially addressed by capabilities report: '{done_item}'"

        # --- Staleness Check 1: Age decay ---
        captured_date = idea.get('captured', '')
        if captured_date and not best_action:
            try:
                cap_dt = datetime.strptime(captured_date, '%Y-%m-%d')
                age_days = (today - cap_dt).days
                last_enriched = max(enrichment_dates) if enrichment_dates else captured_date
                last_enriched_dt = datetime.strptime(last_enriched, '%Y-%m-%d')
                days_since_touch = (today - last_enriched_dt).days

                if age_days >= STALE_THRESHOLD_DAYS and days_since_touch >= STALE_THRESHOLD_DAYS:
                    best_action = 'archive_stale'
                    best_confidence = round(min(0.5 + (age_days - STALE_THRESHOLD_DAYS) / 180, 0.9), 2)
                    best_reason = f"Idea is {age_days} days old with no enrichment in {days_since_touch} days"
            except ValueError:
                pass

        # --- Staleness Check 2: AI low-conviction shelf life ---
        if not best_action and author and 'AI' in author:
            try:
                cap_dt = datetime.strptime(captured_date, '%Y-%m-%d')
                age_days = (today - cap_dt).days
                if age_days >= AI_SHELF_LIFE_DAYS and idea.get('score', 0) < AI_LOW_CONVICTION_SCORE:
                    best_action = 'archive_stale'
                    best_confidence = round(0.6 + (age_days - AI_SHELF_LIFE_DAYS) / 120, 2)
                    best_reason = (f"AI-generated idea, score {idea.get('score', 0)} "
                                   f"(below {AI_LOW_CONVICTION_SCORE}), {age_days} days old")
            except ValueError:
                pass

        if best_action:
            actions.append({
                'id': idea['id'],
                'title': idea['title'],
                'score': idea.get('score', 0),
                'action': best_action,
                'reason': best_reason,
                'confidence': min(best_confidence, 0.99),
            })

    healthy = len(active) - len(actions)
    return {
        "validated": len(active),
        "actions": sorted(actions, key=lambda a: a['confidence'], reverse=True),
        "healthy": healthy,
        "target": BACKLOG_TARGET_MAX,
        "over_target_by": max(0, len(active) - BACKLOG_TARGET_MAX),
        "last_validation": today.strftime('%Y-%m-%d'),
    }


def initialize_backlog_file():
    """Create the Dex backlog file with initial structure"""
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    content = f"""# Dex System Improvement Backlog

*Last ranked: {timestamp}*

Welcome to your Dex system improvement backlog! This file tracks ideas for making Dex better.

## How It Works

1. **Capture ideas** anytime using the `capture_idea` MCP tool
2. **Review regularly** with `/dex-backlog` to see AI-ranked priorities
3. **Workshop ideas** by running `/dex-improve [idea title]`
4. **Mark implemented** when you build an idea

Ideas are automatically ranked on 5 dimensions:
- **Impact** (35%) - How much would this improve daily workflow?
- **Alignment** (20%) - Fits your actual usage patterns?
- **Token Efficiency** (20%) - Reduces context/token usage?
- **Memory & Learning** (15%) - Enhances persistence, self-learning, compounding knowledge?
- **Proactivity** (10%) - Enables proactive concierge behavior?

*Effort intentionally excluded - with AI coding, implementation is cheap. Focus on value.*

---

## Priority Queue

<!-- Auto-ranked by /dex-backlog command -->

### 🔥 High Priority (Score: 85+)

*No high priority ideas yet. Capture your first idea to get started!*

### ⚡ Medium Priority (Score: 60-84)

*No medium priority ideas yet.*

### 💡 Low Priority (Score: <60)

*No low priority ideas yet.*

---

## Archive (Implemented)

*Implemented ideas will appear here with completion dates.*

---

*Run `/dex-backlog` to rank your ideas based on current system state.*
"""
    
    BACKLOG_FILE.write_text(content)
    logger.info(f"Created Dex backlog file at {BACKLOG_FILE}")

def add_idea_to_backlog(idea_id: str, title: str, description: str, category: str) -> bool:
    """Add a user-captured idea to the backlog (unranked, goes to Low Priority)."""
    return insert_idea_into_priority_queue(idea_id, title, description, category, score=0)

def mark_idea_implemented(idea_id: str, implementation_date: Optional[str] = None) -> Dict[str, Any]:
    """Mark an idea as implemented and move to archive"""
    if not BACKLOG_FILE.exists():
        return {
            'success': False,
            'error': 'Dex backlog file does not exist'
        }
    
    content = BACKLOG_FILE.read_text()
    ideas = parse_backlog_file()
    
    # Find the idea
    idea = next((i for i in ideas if i['id'] == idea_id), None)
    if not idea:
        return {
            'success': False,
            'error': f'Idea {idea_id} not found'
        }
    
    if idea['status'] == 'implemented':
        return {
            'success': False,
            'error': f'Idea {idea_id} is already marked as implemented'
        }
    
    # Extract the idea block
    idea_pattern = rf'-\s*\*\*\[{idea_id}\]\*\*.*?(?=\n-\s*\*\*\[idea-|\n###|\n##|$)'
    match = re.search(idea_pattern, content, re.DOTALL)
    
    if not match:
        return {
            'success': False,
            'error': f'Could not find idea block for {idea_id}'
        }
    
    idea_block = match.group(0)
    
    # Remove from current location
    new_content = content[:match.start()] + content[match.end():]
    
    # Create archive entry
    impl_date = implementation_date or datetime.now().strftime('%Y-%m-%d')
    archive_entry = f"- **[{idea_id}]** {idea['title']} - *Implemented: {impl_date}*\n"
    
    # Add to archive section
    archive_pattern = r'(## Archive \(Implemented\)\s*\n(?:\s*\*.*?\*\s*\n)?)'
    match = re.search(archive_pattern, new_content)
    
    if match:
        insert_pos = match.end()
        final_content = new_content[:insert_pos] + '\n' + archive_entry + new_content[insert_pos:]
    else:
        # Archive section doesn't exist, create it
        final_content = new_content + f'\n## Archive (Implemented)\n\n{archive_entry}'
    
    BACKLOG_FILE.write_text(final_content)
    
    return {
        'success': True,
        'idea_id': idea_id,
        'title': idea['title'],
        'implemented_date': impl_date
    }

# ============================================================================
# MCP SERVER
# ============================================================================

app = Server("dex-improvements-mcp")

@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available tools"""
    return [
        types.Tool(
            name="capture_idea",
            description="Capture a new Dex system improvement idea. Always available for quick capture from any context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short, descriptive title for the idea"
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of what this idea would do and why it's valuable"
                    },
                    "category": {
                        "type": "string",
                        "enum": CATEGORIES,
                        "description": f"Category: {', '.join(CATEGORIES)}",
                        "default": "system"
                    }
                },
                "required": ["title", "description"]
            }
        ),
        types.Tool(
            name="list_ideas",
            description="List ideas from the backlog with optional filtering",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": CATEGORIES,
                        "description": "Filter by category"
                    },
                    "min_score": {
                        "type": "integer",
                        "description": "Only show ideas with score >= this value"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "implemented"],
                        "description": "Filter by implementation status",
                        "default": "active"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of ideas to return",
                        "default": 10
                    }
                }
            }
        ),
        types.Tool(
            name="get_idea_details",
            description="Get full details for a specific idea",
            inputSchema={
                "type": "object",
                "properties": {
                    "idea_id": {
                        "type": "string",
                        "description": "The idea ID (e.g., idea-001)"
                    }
                },
                "required": ["idea_id"]
            }
        ),
        types.Tool(
            name="mark_implemented",
            description="Mark an idea as implemented and move it to the archive",
            inputSchema={
                "type": "object",
                "properties": {
                    "idea_id": {
                        "type": "string",
                        "description": "The idea ID to mark as implemented"
                    },
                    "implementation_date": {
                        "type": "string",
                        "description": "Date implemented (YYYY-MM-DD). Defaults to today."
                    }
                },
                "required": ["idea_id"]
            }
        ),
        types.Tool(
            name="get_backlog_stats",
            description="Get statistics about the ideas backlog",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="synthesize_changelog",
            description="Scan Anthropic Claude Code changelog for new features relevant to Dex. Creates new backlog ideas or enriches existing ones with 'Why Now?' evidence. Call during /dex-whats-new or /daily-plan.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": "How many days back to scan the changelog (default: 30)",
                        "default": 30
                    }
                }
            }
        ),
        types.Tool(
            name="synthesize_learnings",
            description="Scan session learnings for pending improvements that could become backlog ideas. Creates new ideas or enriches existing ones.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_back": {
                        "type": "integer",
                        "description": "How many days back to scan learnings (default: 30)",
                        "default": 30
                    }
                }
            }
        ),
        types.Tool(
            name="enrich_idea",
            description="Add new evidence or a 'Why Now?' signal to an existing backlog idea. Use when a changelog feature, discovery, or learning strengthens an existing idea.",
            inputSchema={
                "type": "object",
                "properties": {
                    "idea_id": {
                        "type": "string",
                        "description": "The idea ID to enrich (e.g., idea-006)"
                    },
                    "evidence": {
                        "type": "string",
                        "description": "The new evidence or signal (e.g., 'Claude Code v2.1.32 shipped native memory support')"
                    },
                    "source": {
                        "type": "string",
                        "description": "Where this evidence came from (e.g., 'Anthropic Changelog v2.1.32')"
                    }
                },
                "required": ["idea_id", "evidence", "source"]
            }
        ),
        types.Tool(
            name="validate_backlog",
            description="Run redundancy and staleness checks on all active backlog ideas. Checks against existing skills, MCP tools, shipped WIP items, and capabilities reports. Returns flagged ideas to kill, downrank, or archive. Call before /dex-backlog scoring or after /capabilities-report.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
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
            _log_health_error(
                source="dex-improvements-mcp",
                message=str(e),
                human_message=f"Backlog tool '{name}' failed",
                context={"tool": name}
            )
        raise


async def _handle_call_tool_inner(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Inner tool handler — wrapped by handle_call_tool for health reporting."""

    if name == "capture_idea":
        title = arguments['title']
        description = arguments['description']
        category = arguments.get('category', 'system')
        
        # Validate category
        if category not in CATEGORIES:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "error": f"Invalid category '{category}'. Must be one of: {CATEGORIES}"
                }, indent=2)
            )]
        
        # Check for duplicates
        similar = find_similar_ideas(title, description)
        if similar and similar[0]['similarity'] > 0.75:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "success": False,
                    "warning": "Potential duplicate detected",
                    "title": title,
                    "similar_ideas": similar,
                    "suggestion": "Review these similar ideas. If yours is truly different, rephrase the title to be more distinct."
                }, indent=2)
            )]
        
        # Generate ID and add to Dex backlog
        idea_id = generate_idea_id()
        success = add_idea_to_backlog(idea_id, title, description, category)
        
        if success:
            result = {
                "success": True,
                "idea_id": idea_id,
                "title": title,
                "category": category,
                "message": "Idea captured successfully! Run `/dex-backlog` to see it ranked against other ideas.",
                "next_steps": [
                    "Run `/dex-backlog` to see AI-powered ranking",
                    "Run `/dex-improve \"{title}\"` to workshop this idea",
                    "Check `System/Dex_Backlog.md` to see all your ideas"
                ]
            }
            try:
                _fire_analytics_event('idea_captured', {'category': category})
            except Exception:
                pass
        else:
            result = {
                "success": False,
                "error": "Failed to add idea to Dex backlog"
            }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "list_ideas":
        ideas = parse_backlog_file()
        
        # Apply filters
        if arguments:
            if arguments.get('category'):
                ideas = [i for i in ideas if i['category'] == arguments['category']]
            
            if arguments.get('min_score') is not None:
                ideas = [i for i in ideas if i['score'] >= arguments['min_score']]
            
            if arguments.get('status'):
                ideas = [i for i in ideas if i['status'] == arguments['status']]
            
            limit = arguments.get('limit', 10)
            ideas = ideas[:limit]
        else:
            # Default: show active ideas only
            ideas = [i for i in ideas if i['status'] == 'active'][:10]
        
        result = {
            "ideas": ideas,
            "count": len(ideas),
            "filters_applied": arguments or {},
            "note": "Scores are calculated by `/dex-backlog`. Run it to get AI-powered rankings."
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_idea_details":
        idea_id = arguments['idea_id']
        ideas = parse_backlog_file()
        
        idea = next((i for i in ideas if i['id'] == idea_id), None)
        
        if not idea:
            result = {
                "success": False,
                "error": f"Idea {idea_id} not found"
            }
        else:
            result = {
                "success": True,
                "idea": idea
            }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "mark_implemented":
        idea_id = arguments['idea_id']
        impl_date = arguments.get('implementation_date')
        
        result = mark_idea_implemented(idea_id, impl_date)
        
        if result.get('success'):
            try:
                _fire_analytics_event('idea_implemented')
            except Exception:
                pass
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    elif name == "get_backlog_stats":
        ideas = parse_backlog_file()
        
        active_ideas = [i for i in ideas if i['status'] == 'active']
        implemented_ideas = [i for i in ideas if i['status'] == 'implemented']
        
        # Category breakdown
        category_counts = {}
        for cat in CATEGORIES:
            category_counts[cat] = len([i for i in active_ideas if i['category'] == cat])
        
        # Score distribution
        high_priority = len([i for i in active_ideas if i['score'] >= 85])
        medium_priority = len([i for i in active_ideas if 60 <= i['score'] < 85])
        low_priority = len([i for i in active_ideas if i['score'] < 60])
        
        # Synthesis state
        state = load_synthesis_state()

        # --- Health metrics ---
        today = datetime.now()
        backlog_content = BACKLOG_FILE.read_text() if BACKLOG_FILE.exists() else ''
        stale_count = 0
        ai_low_conviction_count = 0

        for idea in active_ideas:
            captured = idea.get('captured', '')
            if not captured:
                continue
            try:
                cap_dt = datetime.strptime(captured, '%Y-%m-%d')
                age_days = (today - cap_dt).days
            except ValueError:
                continue

            # Extract block for author + enrichment
            block_pat = rf'-\s*\*\*\[{re.escape(idea["id"])}\]\*\*.*?(?=\n-\s*\*\*\[idea-|\n###|\n##|$)'
            bm = re.search(block_pat, backlog_content, re.DOTALL)
            block = bm.group(0) if bm else ''
            enrichments = _parse_enrichment_dates(block)
            last_touch = max(enrichments) if enrichments else captured
            try:
                days_since = (today - datetime.strptime(last_touch, '%Y-%m-%d')).days
            except ValueError:
                days_since = age_days

            if age_days >= STALE_THRESHOLD_DAYS and days_since >= STALE_THRESHOLD_DAYS:
                stale_count += 1

            author = _parse_author(block)
            if author and 'AI' in author and age_days >= AI_SHELF_LIFE_DAYS and idea.get('score', 0) < AI_LOW_CONVICTION_SCORE:
                ai_low_conviction_count += 1
        
        result = {
            "total_ideas": len(ideas),
            "active_ideas": len(active_ideas),
            "implemented_ideas": len(implemented_ideas),
            "by_category": category_counts,
            "by_priority": {
                "high (85+)": high_priority,
                "medium (60-84)": medium_priority,
                "low (<60)": low_priority
            },
            "health": {
                "active_count": len(active_ideas),
                "target_max": BACKLOG_TARGET_MAX,
                "over_target_by": max(0, len(active_ideas) - BACKLOG_TARGET_MAX),
                "stale_count": stale_count,
                "ai_low_conviction_count": ai_low_conviction_count,
                "last_validation": state.get("last_validation_date"),
            },
            "last_changelog_synthesis": state.get("last_changelog_synthesis"),
            "last_learnings_synthesis": state.get("last_learnings_synthesis"),
            "note": "Run `/dex-backlog` to update scores based on current system state"
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    elif name == "synthesize_changelog":
        days_back = (arguments or {}).get('days_back', 30)
        since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

        state = load_synthesis_state()
        last_synthesis = state.get("last_changelog_synthesis")
        if last_synthesis:
            since_date = max(since_date, last_synthesis)

        entries = parse_changelog_entries(since_date)
        if not entries:
            result = {
                "success": True,
                "features_scanned": 0,
                "ideas_created": 0,
                "ideas_enriched": 0,
                "message": f"No new changelog entries found since {since_date}."
            }
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

        relevant_entries = []
        for entry in entries:
            relevance = score_changelog_relevance(entry['feature'])
            if relevance >= 20:
                entry['relevance'] = relevance
                relevant_entries.append(entry)

        relevant_entries.sort(key=lambda x: x['relevance'], reverse=True)
        relevant_entries = relevant_entries[:15]

        existing_ideas = parse_backlog_file()
        ideas_created = 0
        ideas_enriched = 0
        synthesis_details = []

        for entry in relevant_entries:
            feature_text = entry['feature']
            best_match = None
            best_similarity = 0.0

            for idea in existing_ideas:
                title_sim = calculate_similarity(feature_text, idea['title'])
                desc_sim = calculate_similarity(feature_text, idea.get('description', ''))
                combined = max(title_sim, desc_sim)
                if combined > best_similarity:
                    best_similarity = combined
                    best_match = idea

            if best_match and best_similarity > 0.4:
                version_info = entry.get('version', '')
                evidence = f"Claude Code {version_info} ({entry['date']}): {feature_text}"
                enrich_result = enrich_idea_in_backlog(best_match['id'], evidence, f"Anthropic Changelog {version_info}")
                if enrich_result.get('success'):
                    ideas_enriched += 1
                    synthesis_details.append({
                        "action": "enriched",
                        "idea_id": best_match['id'],
                        "idea_title": best_match['title'],
                        "feature": feature_text,
                        "similarity": round(best_similarity, 2)
                    })
            else:
                idea_id = generate_idea_id()
                title = generate_idea_title_from_feature(feature_text)
                category = infer_category_from_feature(feature_text)
                version_info = entry.get('version', '')
                description = (
                    f"Claude Code {version_info} ({entry['date']}) shipped: {feature_text}. "
                    f"Evaluate how Dex could leverage this for user workflows."
                )
                source = "Anthropic Changelog Synthesis"

                success = add_ai_idea_to_backlog(idea_id, title, description, category, source)
                if success:
                    ideas_created += 1
                    synthesis_details.append({
                        "action": "created",
                        "idea_id": idea_id,
                        "title": title,
                        "feature": feature_text,
                        "category": category,
                        "relevance": entry['relevance']
                    })
                    existing_ideas.append({"id": idea_id, "title": title, "description": description})

        state["last_changelog_synthesis"] = datetime.now().strftime('%Y-%m-%d')
        if relevant_entries:
            state["last_changelog_version_seen"] = relevant_entries[0].get('version', '')
        state.setdefault("synthesis_history", []).append({
            "date": datetime.now().isoformat(),
            "type": "changelog",
            "scanned": len(entries),
            "relevant": len(relevant_entries),
            "created": ideas_created,
            "enriched": ideas_enriched
        })
        save_synthesis_state(state)

        result = {
            "success": True,
            "features_scanned": len(entries),
            "relevant_features": len(relevant_entries),
            "ideas_created": ideas_created,
            "ideas_enriched": ideas_enriched,
            "details": synthesis_details[:10],
            "message": f"Scanned {len(entries)} changelog entries. {len(relevant_entries)} were relevant to Dex. Created {ideas_created} new ideas, enriched {ideas_enriched} existing ideas."
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    elif name == "synthesize_learnings":
        days_back = (arguments or {}).get('days_back', 30)
        since_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

        state = load_synthesis_state()
        last_synthesis = state.get("last_learnings_synthesis")
        if last_synthesis:
            since_date = max(since_date, last_synthesis)

        learnings = parse_session_learnings(since_date)
        if not learnings:
            result = {
                "success": True,
                "learnings_scanned": 0,
                "ideas_created": 0,
                "ideas_enriched": 0,
                "message": f"No pending session learnings found since {since_date}."
            }
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

        existing_ideas = parse_backlog_file()
        ideas_created = 0
        ideas_enriched = 0
        synthesis_details = []

        for learning in learnings:
            search_text = learning['title'] + ' ' + learning.get('suggested_fix', '')
            best_match = None
            best_similarity = 0.0

            for idea in existing_ideas:
                title_sim = calculate_similarity(search_text, idea['title'])
                desc_sim = calculate_similarity(search_text, idea.get('description', ''))
                combined = max(title_sim, desc_sim)
                if combined > best_similarity:
                    best_similarity = combined
                    best_match = idea

            if best_match and best_similarity > 0.5:
                evidence = f"Session learning ({learning['date']}): {learning['title']}. {learning.get('suggested_fix', '')}"
                enrich_result = enrich_idea_in_backlog(best_match['id'], evidence, f"Session Learning {learning['date']}")
                if enrich_result.get('success'):
                    ideas_enriched += 1
                    synthesis_details.append({
                        "action": "enriched",
                        "idea_id": best_match['id'],
                        "idea_title": best_match['title'],
                        "learning": learning['title'],
                    })
            else:
                if not learning.get('suggested_fix'):
                    continue

                idea_id = generate_idea_id()
                title = f"Fix: {learning['title']}"
                if len(title) > 80:
                    title = title[:77] + '...'
                description = (
                    f"From session learning ({learning['date']}): {learning.get('what_happened', '')} "
                    f"Suggested fix: {learning['suggested_fix']}"
                )
                category = 'system'
                source = "Session Learning Synthesis"

                similar = find_similar_ideas(title, description)
                if similar and similar[0]['similarity'] > 0.7:
                    continue

                success = add_ai_idea_to_backlog(idea_id, title, description, category, source)
                if success:
                    ideas_created += 1
                    synthesis_details.append({
                        "action": "created",
                        "idea_id": idea_id,
                        "title": title,
                        "learning": learning['title'],
                    })
                    existing_ideas.append({"id": idea_id, "title": title, "description": description})

        state["last_learnings_synthesis"] = datetime.now().strftime('%Y-%m-%d')
        state.setdefault("synthesis_history", []).append({
            "date": datetime.now().isoformat(),
            "type": "learnings",
            "scanned": len(learnings),
            "created": ideas_created,
            "enriched": ideas_enriched
        })
        save_synthesis_state(state)

        result = {
            "success": True,
            "learnings_scanned": len(learnings),
            "ideas_created": ideas_created,
            "ideas_enriched": ideas_enriched,
            "details": synthesis_details[:10],
            "message": f"Scanned {len(learnings)} pending learnings. Created {ideas_created} new ideas, enriched {ideas_enriched} existing ideas."
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    elif name == "enrich_idea":
        idea_id = arguments['idea_id']
        evidence = arguments['evidence']
        source = arguments['source']

        result = enrich_idea_in_backlog(idea_id, evidence, source)
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    elif name == "validate_backlog":
        result = validate_backlog_ideas()
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]

    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

async def _main():
    """Async main entry point for the MCP server"""
    if _HAS_HEALTH:
        _mark_healthy("dex-improvements-mcp")
    logger.info("Starting Dex Improvements MCP Server")
    logger.info(f"Vault path: {BASE_DIR}")
    logger.info(f"Backlog file: {BACKLOG_FILE}")
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-improvements-mcp",
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
