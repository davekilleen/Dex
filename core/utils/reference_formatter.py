#!/usr/bin/env python3
"""
Reference formatting utilities for Dex
Handles conditional wiki link formatting based on obsidian_mode
"""
import os
import re
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None

BASE_DIR = Path(os.environ.get('VAULT_PATH', Path.cwd()))
USER_PROFILE = BASE_DIR / 'System' / 'user-profile.yaml'

def get_obsidian_mode() -> bool:
    """Check if Obsidian mode is enabled"""
    if not USER_PROFILE.exists() or yaml is None:
        return False
    
    try:
        content = USER_PROFILE.read_text()
        data = yaml.safe_load(content)
        return bool(data.get('obsidian_mode', False))
    except Exception:
        return False

def format_person_reference(name: str, full_path: Optional[str] = None) -> str:
    """Format person reference (e.g., John_Doe or [[John_Doe]])"""
    if get_obsidian_mode():
        if full_path:
            return f"[[{full_path}|{name.replace('_', ' ')}]]"
        return f"[[{name}]]"
    return name.replace('_', ' ')

def format_project_reference(project_path: str) -> str:
    """Format project reference"""
    if get_obsidian_mode():
        return f"[[{project_path}]]"
    # Extract just the name
    return project_path.split('/')[-1].replace('_', ' ')

def format_company_reference(company_name: str, full_path: Optional[str] = None) -> str:
    """Format company reference"""
    if get_obsidian_mode():
        if full_path:
            return f"[[{full_path}|{company_name}]]"
        return f"[[{company_name}]]"
    return company_name

def format_meeting_reference(meeting_file: str) -> str:
    """Format meeting reference (e.g., 2026-01-28 - API Review)"""
    if get_obsidian_mode():
        return f"[[{meeting_file}]]"
    return meeting_file

def format_task_reference(task_id: str) -> str:
    """Format task ID reference"""
    if get_obsidian_mode():
        return f"[[^{task_id}]]"
    return f"^{task_id}"
