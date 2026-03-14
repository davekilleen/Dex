#!/usr/bin/env python3
"""
Single source of truth for all vault paths.

Usage (Python):
    from core.paths import PEOPLE_DIR, TASKS_FILE, MEETINGS_DIR

Usage (generate JSON for CJS/TS consumers):
    python3 core/paths.py
    # Writes core/paths.json
"""

import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# --- Vault root ---
_vault_path = os.environ.get('VAULT_PATH')
if not _vault_path:
    logging.warning(
        "VAULT_PATH not set — falling back to cwd(). "
        "Task ID generation may produce duplicates."
    )
VAULT_ROOT = Path(_vault_path) if _vault_path else Path.cwd()

# --- PARA directories (numbered prefixes) ---
INBOX_DIR = VAULT_ROOT / '00-Inbox'
QUARTER_GOALS_DIR = VAULT_ROOT / '01-Quarter_Goals'
WEEK_PRIORITIES_DIR = VAULT_ROOT / '02-Week_Priorities'
TASKS_DIR = VAULT_ROOT / '03-Tasks'
PROJECTS_DIR = VAULT_ROOT / '04-Projects'
AREAS_DIR = VAULT_ROOT / '05-Areas'
RESOURCES_DIR = VAULT_ROOT / '06-Resources'
ARCHIVES_DIR = VAULT_ROOT / '07-Archives'

# --- Derived: Inbox ---
MEETINGS_DIR = INBOX_DIR / 'Meetings'
IDEAS_DIR = INBOX_DIR / 'Ideas'
DAILY_PLANS_DIR = INBOX_DIR / 'Daily_Plans'

# --- Derived: Meetings ---
TRACKED_MEETINGS_DIR = AREAS_DIR / 'Meetings'
MEETING_DAILY_LOGS_DIR = TRACKED_MEETINGS_DIR / 'Daily_Log'
LEGACY_MEETINGS_DIR = MEETINGS_DIR

# --- Derived: Tasks & Goals ---
TASKS_FILE = TASKS_DIR / 'Tasks.md'
QUARTER_GOALS_FILE = QUARTER_GOALS_DIR / 'Quarter_Goals.md'
WEEK_PRIORITIES_FILE = WEEK_PRIORITIES_DIR / 'Week_Priorities.md'
GOALS_FILE = VAULT_ROOT / 'GOALS.md'  # Legacy, kept for compatibility

# --- Derived: Areas ---
PEOPLE_DIR = AREAS_DIR / 'People'
COMPANIES_DIR = AREAS_DIR / 'Companies'
CAREER_DIR = AREAS_DIR / 'Career'
EVIDENCE_DIR = CAREER_DIR / 'Evidence'
RESUME_DIR = CAREER_DIR / 'Resume'
SESSIONS_DIR = RESUME_DIR / 'Sessions'

# --- Derived: Resources ---
INTEL_DIR = RESOURCES_DIR / 'Intel'
MEETING_INTEL_DIR = INTEL_DIR / 'Meeting_Intel'
LEARNINGS_DIR = RESOURCES_DIR / 'Learnings'

# --- System ---
SYSTEM_DIR = VAULT_ROOT / 'System'
DEX_RUNTIME_DIR = SYSTEM_DIR / '.dex'
PILLARS_FILE = SYSTEM_DIR / 'pillars.yaml'
USER_PROFILE_FILE = SYSTEM_DIR / 'user-profile.yaml'
SKILL_RATINGS_FILE = SYSTEM_DIR / 'Skill_Ratings' / 'ratings.jsonl'
PEOPLE_INDEX_FILE = SYSTEM_DIR / 'People_Index.json'
MEETING_CACHE_FILE = SYSTEM_DIR / 'Memory' / 'meeting-cache.json'
DEMO_DIR = SYSTEM_DIR / 'Demo'
STATE_FILE = SYSTEM_DIR / '.demo-mode-state.json'
SESSION_FILE = SYSTEM_DIR / '.onboarding-session.json'
MARKER_FILE = SYSTEM_DIR / '.onboarding-complete'
USER_PROFILE_TEMPLATE = SYSTEM_DIR / 'user-profile-template.yaml'
CLAUDE_MD = VAULT_ROOT / 'CLAUDE.md'
MCP_CONFIG_EXAMPLE = SYSTEM_DIR / '.mcp.json.example'
MCP_CONFIG_TARGET = SYSTEM_DIR / '.mcp.json'
COMMITMENT_QUEUE_FILE = SYSTEM_DIR / 'commitment_queue.json'
OBSIDIAN_SYNC_LOG = SYSTEM_DIR / 'obsidian-sync.log'
RITUAL_INTELLIGENCE_DB_FILE = DEX_RUNTIME_DIR / 'ritual-intelligence.db'


def export_json(output_path: str | Path | None = None) -> dict:
    """Export all paths as a JSON-serializable dict (strings).

    If output_path is given, writes to that file.
    Returns the dict either way.
    """
    # Collect every module-level Path variable
    data = {}
    for name, value in globals().items():
        if name.startswith('_') or not isinstance(value, Path):
            continue
        data[name] = str(value)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2) + '\n')
        logger.info("Wrote %s", out)

    return data


if __name__ == '__main__':
    # Generate core/paths.json for CJS/TS consumers
    out_path = Path(__file__).parent / 'paths.json'
    export_json(out_path)
    print(f"Generated {out_path}")
