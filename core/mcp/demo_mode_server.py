#!/usr/bin/env python3
"""
MCP Server for Demo Mode — Deterministic redaction of sensitive data.

Provides tools for:
- Checking demo mode status (call at session start)
- Redacting text before writing files or passing to other MCPs
- Managing blocked terms (add/remove on the fly)
- Toggling demo mode on/off

The agent calls `get_demo_status()` at session start. If active, it calls
`redact_text()` on ALL output before writing files, chat responses, or
MCP tool parameters that might contain sensitive data.

The PTY wrapper (launch.py) remains as a safety net for terminal output,
but this MCP is the PRIMARY defense — filtering at the source.
"""

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Set

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

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

# Configuration (centralized in core.paths)
_repo_root = str(Path(__file__).parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.append(_repo_root)
from core.paths import STATE_FILE
from core.paths import VAULT_ROOT as BASE_DIR

# Minimum character length for name parts (avoid false positives)
MIN_TERM_LENGTH = 3

# These terms are NEVER redacted (public information)
DEFAULT_ALLOWLIST = {
    'Dave', 'Killeen', 'Dave Killeen',
    'Pendo',
    'Dex',
    'Claude', 'Anthropic', 'Claude Code', 'Cursor', 'Obsidian',
    'Aakash', 'Gupta', 'Aakash Gupta',
    'README', 'CLAUDE', 'Active', 'System', 'Demo',
}


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Load demo mode state from file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        'active': False,
        'extra_terms': [],
        'allowlist_additions': [],
        'last_toggled': None,
    }


def save_state(state: dict):
    """Persist demo mode state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, default=str),
        encoding='utf-8'
    )


# ---------------------------------------------------------------------------
# Vault Scanning (ported from launch.py)
# ---------------------------------------------------------------------------

def scan_people() -> Set[str]:
    """Extract person names from People/ folder filenames."""
    terms = set()
    from core.paths import PEOPLE_DIR as _people_dir
    people_dir = _people_dir
    if not people_dir.exists():
        return terms

    for md_file in people_dir.rglob('*.md'):
        if md_file.name == 'README.md':
            continue

        name = md_file.stem.strip('()')
        full_name = name.replace('_', ' ').replace('-', ' ').strip()

        if not full_name or len(full_name) < MIN_TERM_LENGTH:
            continue

        terms.add(full_name)
        for part in full_name.split():
            if len(part) >= MIN_TERM_LENGTH:
                terms.add(part)

    return terms


def scan_companies() -> Set[str]:
    """Extract company names from Key_Accounts/ and Companies/ folders."""
    terms = set()

    search_dirs = [
        BASE_DIR / '05-Areas' / 'Relationships' / 'Key_Accounts',
        BASE_DIR / '05-Areas' / 'Companies',
    ]

    structural_dirs = {
        'EMEA', 'US', 'APAC', 'Key_Accounts', 'Companies',
        'Relationships', '_original',
    }

    skip_prefixes = (
        'opp-', 'Deal_Analysis', 'Call_Prep', 'Financial',
        'Strategic', 'Momentum', 'Deep_Dive', 'Action_Plan',
        'Pre-Meeting', 'Comparable', 'Whitepaper', 'Conference',
        'Liselle', 'HiBob_Deal', 'Pendo_Executive', 'Ocado_',
        'Norstella_Account', 'S1_S2', 'Customer_Success',
        'Global_Support', 'exports', 'synced',
    )
    skip_date_pattern = re.compile(r'^\d{4}[-_]')

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue

        for item in search_dir.rglob('*'):
            if item.is_dir() and item.name not in structural_dirs:
                name = item.name.replace('_', ' ').replace('-', ' ').strip().strip('()')
                if len(name) >= MIN_TERM_LENGTH:
                    terms.add(name)
                    for suffix in (' Ltd', ' Ltd.', ' Inc', ' Inc.', ' GmbH',
                                   ' AG', ' SE', ' SpA', ' B.V.', ' Plc',
                                   ' AB', ' A S', ' Group'):
                        if name.endswith(suffix):
                            base = name[:-len(suffix)].strip()
                            if len(base) >= MIN_TERM_LENGTH:
                                terms.add(base)

            elif item.is_file() and item.suffix == '.md':
                if item.name == 'README.md':
                    continue
                stem = item.stem
                if any(stem.startswith(p) for p in skip_prefixes):
                    continue
                if skip_date_pattern.match(stem):
                    continue

                name = stem.replace('_', ' ').replace('-', ' ').strip().strip('()')
                name = re.sub(r'\s+\d{4}\s+\d{2}\s+\d{2}.*$', '', name)
                name = re.sub(r'\s+\d{4}\-\d{2}\-\d{2}.*$', '', name)

                if len(name.split()) > 4:
                    continue
                if len(name) >= MIN_TERM_LENGTH:
                    terms.add(name)

    return terms


def scan_tasks_for_extra_terms() -> Set[str]:
    """Extract terms from WikiLinks in Tasks.md."""
    terms = set()
    tasks_file = BASE_DIR / '03-Tasks' / 'Tasks.md'
    if not tasks_file.exists():
        return terms

    try:
        content = tasks_file.read_text(encoding='utf-8')
        for match in re.finditer(r'\[\[([^\]]+)\]\]', content):
            link = match.group(1)
            if re.match(r'^[A-Z]', link) and '/' not in link:
                name = link.replace('_', ' ').strip()
                if len(name) >= MIN_TERM_LENGTH:
                    terms.add(name)
    except Exception:
        pass

    return terms


# Common English words that appear capitalised in planning/career files.
# These MUST NOT be treated as person/company names.
COMMON_WORDS = {
    'the', 'this', 'that', 'with', 'from', 'for', 'and', 'but', 'not',
    'you', 'your', 'our', 'they', 'their', 'his', 'her', 'its',
    'who', 'what', 'when', 'where', 'how', 'why', 'which', 'all',
    'any', 'each', 'every', 'both', 'few', 'more', 'most', 'some',
    'such', 'than', 'too', 'very', 'can', 'will', 'just', 'should',
    'now', 'also', 'into', 'over', 'after', 'before', 'between',
    'through', 'during', 'about', 'under', 'above', 'other', 'new',
    'use', 'used', 'using',
    'team', 'teams', 'build', 'built', 'goal', 'goals', 'plan',
    'plans', 'week', 'weekly', 'daily', 'quarter', 'quarterly',
    'annual', 'year', 'month', 'day', 'time', 'next', 'last',
    'current', 'target', 'level', 'role', 'title', 'area', 'areas',
    'career', 'growth', 'skill', 'skills', 'track', 'tracking',
    'progress', 'status', 'update', 'updated', 'review', 'action',
    'actions', 'key', 'value', 'impact', 'evidence', 'capture',
    'system', 'systems', 'process', 'workflow', 'function',
    'summary', 'section', 'milestone', 'milestones', 'project',
    'projects', 'initiative', 'priority', 'priorities', 'task',
    'tasks', 'complete', 'completed', 'pending', 'blocked',
    'success', 'metrics', 'measure', 'outcome', 'outcomes',
    'strategy', 'strategic', 'technical', 'technology',
    'product', 'market', 'customer', 'enterprise', 'global',
    'revenue', 'sales', 'support', 'feedback', 'insight',
    'intelligence', 'competitive', 'innovation', 'operational',
    'executive', 'leadership', 'management', 'development',
    'enablement', 'engagement', 'delivery', 'design', 'thinking',
    'systematic', 'cross', 'functional', 'authority', 'presence',
    'excellence', 'influence', 'judgment', 'building', 'engineering',
    'vision', 'roadmap', 'pipeline', 'expansion', 'rollout',
    'validation', 'program', 'workshop', 'series', 'session',
    'sessions', 'conference', 'dinner', 'breakfast', 'event',
    'internal', 'external', 'transfer', 'radar', 'tree',
    'pillar', 'pillars', 'theme', 'themes', 'weights', 'wins',
    'three', 'third', 'first', 'second', 'primary',
    'must', 'should', 'could', 'would', 'might',
    'field', 'board', 'meeting', 'meetings', 'prep',
    'report', 'reporting', 'data', 'analysis', 'approach',
    'attribution', 'evangelism', 'facilitation', 'group', 'user',
    'transitioning', 'embed', 'seek', 'deliver', 'land',
    'ceo', 'cfo', 'cpo', 'cro', 'cmo', 'cto', 'cio', 'ciso',
    'svp', 'evp', 'vp', 'avp', 'gm', 'md',
    'aes', 'sdr', 'sdrs', 'bdr', 'bdrs', 'csm', 'csms',
    'linkedin', 'slack', 'youtube', 'twitter', 'github',
    'notion', 'figma', 'jira', 'asana', 'airtable',
    'salesforce', 'hubspot', 'gartner', 'forrester',
    'google', 'microsoft', 'amazon', 'apple',
    'overview', 'notes', 'details', 'description', 'context',
    'challenges', 'overcome', 'alignment', 'position', 'start',
    'date', 'end', 'did', 'authored', 'designed', 'designing',
    'own', 'expanded', 'scope', 'moved', 'moving', 'record',
    'configure', 'configured', 'setup', 'install', 'installed',
    'balancing', 'positioned', 'branding', 'personal',
    'architecture', 'automation', 'model', 'operating',
    'partnership', 'marketing', 'consulting', 'solutions',
    'playbook', 'asset', 'company', 'job', 'ladder', 'promotion',
    'align', 'podcast', 'phantom', 'buster', 'clay',
}

# Compound phrases that appear in planning/career files — skip as a unit.
PLANNING_SKIP_PHRASES = {
    'Field CPO', 'Senior PM', 'Staff PM', 'Product Manager',
    'Principal PM', 'General Manager',
    'Chief Product Officer', 'Chief Revenue Officer',
    'Chief Technology Officer', 'Chief Executive Officer',
    'Deal Support', 'Thought Leadership', 'Product Feedback',
    'Key Account', 'Key Accounts', 'Career Goal', 'Career Goals',
    'Quarter Goals', 'Week Priorities', 'Daily Plan', 'Daily Plans',
    'Growth Goals', 'Career Ladder', 'Current Role', 'Career Coach',
    'Quarter Objectives', 'Key Meetings', 'Pillar Check',
    'Revenue Impact', 'Executive Presence', 'Market Intelligence',
    'Sales Enablement', 'Competitive Intelligence', 'Market Authority',
    'Team Building', 'Organizational Design', 'Technical Judgment',
    'Team Development', 'Product Strategy', 'Execution Excellence',
    'Customer Insight', 'Cross Functional', 'Innovation Engine',
    'Operational Excellence', 'Strategic Influence',
    'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
    'Saturday', 'Sunday',
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
    'Must Complete', 'Should Complete', 'If Time', 'Time Permits',
    'Success Metrics', 'Key Actions', 'Evidence Capture',
    'Skill Development', 'Key Milestones',
    'EMEA', 'APAC', 'Americas', 'Europe', 'Global',
    'Enterprise', 'Internal', 'External',
    'Agent Analytics', 'Career MCP', 'Vibe PM',
}


def _is_name_like(text: str) -> bool:
    """Return True if text looks like a person/company name, not a common word."""
    for part in text.split():
        if part.lower() in COMMON_WORDS:
            return False
    return True


def scan_planning_and_career_files() -> Set[str]:
    """Extract person/company names from planning, career, and evidence files.

    Catches names that only appear in goals, priorities, career docs, or
    evidence files — even if those people/companies don't have their own
    People or Key_Accounts page.

    Unlike scan_people(), this does NOT split matches into individual parts
    to avoid contaminating the term list with common words.
    """
    terms: Set[str] = set()

    files_to_scan = [
        BASE_DIR / '01-Quarter_Goals' / 'Quarter_Goals.md',
        BASE_DIR / '02-Week_Priorities' / 'Week_Priorities.md',
        BASE_DIR / '05-Areas' / 'Career' / 'Growth_Goals.md',
        BASE_DIR / '05-Areas' / 'Career' / 'Current_Role.md',
        BASE_DIR / '05-Areas' / 'Career' / 'Career_Ladder.md',
    ]

    evidence_dirs = [
        BASE_DIR / '05-Areas' / 'Career' / 'Evidence',
        BASE_DIR / '05-Areas' / 'Career' / 'Evidence',
    ]
    for edir in evidence_dirs:
        if edir.exists():
            for f in edir.rglob('*.md'):
                files_to_scan.append(f)

    skip_lower = (
        {t.lower() for t in PLANNING_SKIP_PHRASES}
        | {t.lower() for t in DEFAULT_ALLOWLIST}
    )

    for file_path in files_to_scan:
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text(encoding='utf-8')
        except Exception:
            continue

        # 1. WikiLinks
        for match in re.finditer(r'\[\[([^\]]+)\]\]', content):
            link = match.group(1)
            if re.match(r'^[A-Z]', link) and '/' not in link:
                name = link.replace('_', ' ').strip()
                if len(name) >= MIN_TERM_LENGTH and name.lower() not in skip_lower:
                    if _is_name_like(name):
                        terms.add(name)

        # 2. "First Last" person-name patterns (single line only)
        for match in re.finditer(
            r'\b([A-Z][a-z]{2,})[ ]+([A-Z][a-z]{2,})(?:[ ]+([A-Z][a-z]{2,}))?\b',
            content
        ):
            full = match.group(0).strip()
            if (full.lower() not in skip_lower
                    and len(full) >= MIN_TERM_LENGTH
                    and _is_name_like(full)):
                terms.add(full)

        # 3. Meeting table rows
        for match in re.finditer(
            r'\|\s*\w{2,3}\s*\|\s*[\d:]+[^|]*\|\s*([^|]+)\|', content
        ):
            cell = match.group(1).strip()
            for name_match in re.finditer(
                r'([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})', cell
            ):
                candidate = name_match.group(1).strip()
                if candidate.lower() not in skip_lower and _is_name_like(candidate):
                    terms.add(candidate)

        # 4. "— Name" stakeholder patterns
        for match in re.finditer(
            r'—\s*([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})', content
        ):
            candidate = match.group(1).strip()
            if candidate.lower() not in skip_lower and _is_name_like(candidate):
                terms.add(candidate)

        # 5. Company names after "at/from/for/with/to"
        for match in re.finditer(
            r'\b(?:at|from|for|with|to)\s+([A-Z][A-Za-z]{2,}(?:\s+[A-Z][A-Za-z]{2,}){0,2})\b',
            content
        ):
            candidate = match.group(1).strip()
            if (candidate.lower() not in skip_lower
                    and _is_name_like(candidate)
                    and len(candidate) >= MIN_TERM_LENGTH):
                terms.add(candidate)

    return terms


# ---------------------------------------------------------------------------
# Redaction Engine
# ---------------------------------------------------------------------------

def get_all_terms(state: dict) -> Set[str]:
    """Collect all terms from vault scan + extra manual terms."""
    allowlist = DEFAULT_ALLOWLIST | set(state.get('allowlist_additions', []))

    people = scan_people()
    companies = scan_companies()
    tasks = scan_tasks_for_extra_terms()
    planning = scan_planning_and_career_files()
    manual = {t['term'] for t in state.get('extra_terms', [])}

    all_terms = (people | companies | tasks | planning | manual) - allowlist
    return all_terms


def build_term_regex(terms: Set[str]):
    """Compile terms into a single regex, longest first."""
    if not terms:
        return None
    sorted_terms = sorted(terms, key=len, reverse=True)
    escaped = [re.escape(t) for t in sorted_terms]
    pattern = r'\b(' + '|'.join(escaped) + r')\b'
    return re.compile(pattern, re.IGNORECASE)


def build_pattern_rules():
    """Regex rules for structured sensitive data."""
    return [
        (re.compile(r'\b[\w.+-]+@[\w.-]+\.\w{2,}\b'), '[email]'),
        (re.compile(r'[$\u20ac\u00a3][\d,]+\.?\d*[KkMmBb]?\b'), '[amount]'),
    ]


def redact(text: str, term_regex, pattern_rules) -> str:
    """Apply all redaction rules to text."""
    # Step 1: Replace emails first
    for regex, replacement in pattern_rules:
        text = regex.sub(replacement, text)

    # Step 2: Replace named terms
    if term_regex:
        # Find terms in clean text
        found_terms = set()
        for match in term_regex.finditer(text):
            found_terms.add(match.group(0))

        # Replace longest first to avoid partial replacements
        for term in sorted(found_terms, key=len, reverse=True):
            block = '\u2588' * min(len(term), 8)
            text = re.sub(re.escape(term), block, text, flags=re.IGNORECASE)

    return text


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

server = Server("demo-mode-mcp")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_demo_status",
            description="Check if demo mode is active. Call this at session start to determine if redaction is needed. When active, ALL output (files, chat, MCP parameters) must be redacted.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="redact_text",
            description="Redact sensitive data from text. Call this BEFORE writing files, outputting chat text, or passing data to other MCP tools when demo mode is active. Returns the redacted version.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to redact. Can be any length — file contents, chat messages, MCP parameters, etc."
                    },
                },
                "required": ["text"],
            },
        ),
        types.Tool(
            name="toggle_demo_mode",
            description="Turn demo mode on or off. When turned on, scans the vault for sensitive terms.",
            inputSchema={
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "True to enable demo mode, false to disable."
                    },
                },
                "required": ["enabled"],
            },
        ),
        types.Tool(
            name="add_blocked_term",
            description="Add a term to the redaction list on the fly. Use when you notice a name or company that should be redacted but wasn't caught by the vault scan.",
            inputSchema={
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "The term to block (e.g., 'Mastercard', 'John Smith')."
                    },
                    "category": {
                        "type": "string",
                        "enum": ["person", "company", "other"],
                        "description": "Category of the term.",
                        "default": "other",
                    },
                },
                "required": ["term"],
            },
        ),
        types.Tool(
            name="remove_blocked_term",
            description="Remove a manually added term from the redaction list.",
            inputSchema={
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "The term to unblock."
                    },
                },
                "required": ["term"],
            },
        ),
        types.Tool(
            name="add_to_allowlist",
            description="Add a term to the allowlist so it is NEVER redacted (e.g., public names that should always be visible).",
            inputSchema={
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "The term to allow (e.g., 'Aakash Gupta')."
                    },
                },
                "required": ["term"],
            },
        ),
        types.Tool(
            name="list_redaction_terms",
            description="List all terms that will be redacted, grouped by source (people, companies, planning/career, manual). Useful for auditing what gets blocked.",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["all", "people", "companies", "planning", "manual", "allowlist"],
                        "description": "Which category to list. Default: all.",
                        "default": "all",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        return await _handle_call_tool_inner(name, arguments)
    except Exception as e:
        if _HAS_HEALTH:
            _log_health_error(
                source="demo-mode-mcp",
                message=str(e),
                human_message=f"Demo mode tool '{name}' failed",
                context={"tool": name}
            )
        raise

async def _handle_call_tool_inner(name: str, arguments: dict) -> list[types.TextContent]:
    state = load_state()

    if name == "get_demo_status":
        if state['active']:
            all_terms = get_all_terms(state)
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "active": True,
                    "terms_count": len(all_terms),
                    "manual_terms_count": len(state.get('extra_terms', [])),
                    "last_toggled": state.get('last_toggled'),
                    "instructions": (
                        "Demo mode is ACTIVE. You MUST redact all sensitive data before: "
                        "(1) writing files, (2) outputting chat text with names/companies/amounts, "
                        "(3) passing data to other MCP tools. Call redact_text() on any text "
                        "that might contain person names, company names, email addresses, or "
                        "dollar amounts. The PTY wrapper is a safety net — you are the primary filter."
                    ),
                }, indent=2)
            )]
        else:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "active": False,
                    "instructions": "Demo mode is OFF. No redaction needed.",
                }, indent=2)
            )]

    elif name == "redact_text":
        text = arguments.get('text', '')
        if not state['active']:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "warning": "Demo mode is not active. Returning text unchanged.",
                    "redacted_text": text,
                })
            )]

        all_terms = get_all_terms(state)
        term_regex = build_term_regex(all_terms)
        pattern_rules = build_pattern_rules()
        redacted = redact(text, term_regex, pattern_rules)

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "redacted_text": redacted,
                "terms_applied": len(all_terms),
            })
        )]

    elif name == "toggle_demo_mode":
        enabled = arguments.get('enabled', False)
        state['active'] = enabled
        state['last_toggled'] = datetime.now().isoformat()
        save_state(state)

        if enabled:
            all_terms = get_all_terms(state)
            people = scan_people()
            companies = scan_companies()
            planning = scan_planning_and_career_files()
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "active": True,
                    "people_terms": len(people),
                    "company_terms": len(companies),
                    "planning_career_terms": len(planning),
                    "manual_terms": len(state.get('extra_terms', [])),
                    "total_terms": len(all_terms),
                    "message": f"Demo mode ON. {len(all_terms)} terms will be redacted (including planning/career files).",
                }, indent=2)
            )]
        else:
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "success": True,
                    "active": False,
                    "message": "Demo mode OFF. No redaction applied.",
                }, indent=2)
            )]

    elif name == "add_blocked_term":
        term = arguments.get('term', '').strip()
        category = arguments.get('category', 'other')

        if not term:
            return [types.TextContent(type="text", text=json.dumps({"error": "Term cannot be empty."}))]

        extra = state.get('extra_terms', [])
        existing = {t['term'].lower() for t in extra}
        if term.lower() in existing:
            return [types.TextContent(type="text", text=json.dumps({
                "warning": f"'{term}' is already in the blocked list.",
            }))]

        extra.append({'term': term, 'category': category, 'added': datetime.now().isoformat()})
        state['extra_terms'] = extra
        save_state(state)

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "term": term,
                "category": category,
                "total_manual_terms": len(extra),
                "message": f"Added '{term}' to blocked terms. It will now be redacted in all output.",
            })
        )]

    elif name == "remove_blocked_term":
        term = arguments.get('term', '').strip()
        extra = state.get('extra_terms', [])
        before = len(extra)
        extra = [t for t in extra if t['term'].lower() != term.lower()]
        state['extra_terms'] = extra
        save_state(state)

        removed = before - len(extra)
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": removed > 0,
                "removed": removed,
                "message": f"Removed '{term}'." if removed else f"'{term}' was not in the manual blocked list.",
            })
        )]

    elif name == "add_to_allowlist":
        term = arguments.get('term', '').strip()
        additions = state.get('allowlist_additions', [])
        if term not in additions:
            additions.append(term)
            state['allowlist_additions'] = additions
            save_state(state)

        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "term": term,
                "message": f"'{term}' added to allowlist — it will never be redacted.",
            })
        )]

    elif name == "list_redaction_terms":
        category = arguments.get('category', 'all')
        allowlist = DEFAULT_ALLOWLIST | set(state.get('allowlist_additions', []))

        result = {}

        if category in ('all', 'people'):
            people = scan_people() - allowlist
            result['people'] = sorted(people)[:50]
            result['people_count'] = len(people)

        if category in ('all', 'companies'):
            companies = scan_companies() - allowlist
            result['companies'] = sorted(companies)[:50]
            result['companies_count'] = len(companies)

        if category in ('all', 'planning'):
            planning = scan_planning_and_career_files() - allowlist
            result['planning_career'] = sorted(planning)[:50]
            result['planning_career_count'] = len(planning)

        if category in ('all', 'manual'):
            result['manual'] = state.get('extra_terms', [])

        if category in ('all', 'allowlist'):
            result['allowlist'] = sorted(allowlist)

        return [types.TextContent(
            type="text",
            text=json.dumps(result, indent=2)
        )]

    return [types.TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    if _HAS_HEALTH:
        _mark_healthy("demo-mode-mcp")
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="demo-mode-mcp",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
