#!/usr/bin/env python3
"""
Page generation utilities for Dex
Creates person pages, meeting notes, and other content with proper reference formatting
"""
from typing import Optional, List
from datetime import datetime
from .reference_formatter import (
    format_person_reference,
    format_company_reference,
    format_project_reference,
    format_meeting_reference,
    format_task_reference
)


def generate_person_page(
    name: str,
    role: Optional[str] = None,
    company: Optional[str] = None,
    email: Optional[str] = None,
    notes: Optional[str] = None
) -> str:
    """
    Generate person page content with proper formatting
    
    Args:
        name: Person's name (e.g., "John_Doe")
        role: Person's role/title
        company: Company name
        email: Email address
        notes: Additional notes
    
    Returns:
        Formatted markdown content
    """
    # Convert underscores to spaces for display
    display_name = name.replace('_', ' ')
    content = f"# {display_name}\n\n"
    
    if role:
        content += f"**Role:** {role}\n"
    
    if company:
        # Format company reference based on obsidian_mode
        company_ref = format_company_reference(
            company, 
            full_path=f"05-Areas/Companies/{company}"
        )
        content += f"**Company:** {company_ref}\n"
    
    if email:
        content += f"**Email:** {email}\n"
    
    content += "\n"
    
    if notes:
        content += f"## Notes\n\n{notes}\n\n"
    
    content += "## Recent Interactions\n\n"
    content += "## Related Tasks\n\n"
    content += "## Key Context\n\n"
    
    return content


def generate_meeting_note(
    title: str,
    date: Optional[datetime] = None,
    attendees: Optional[List[str]] = None,
    projects: Optional[List[str]] = None,
    notes: Optional[str] = None,
    action_items: Optional[List[str]] = None
) -> str:
    """
    Generate meeting note content with proper formatting
    
    Args:
        title: Meeting title
        date: Meeting date (defaults to now)
        attendees: List of attendee names (e.g., ["John_Doe", "Jane_Smith"])
        projects: List of related project paths
        notes: Meeting notes/discussion
        action_items: List of action items
    
    Returns:
        Formatted markdown content
    """
    if date is None:
        date = datetime.now()
    
    content = f"# {title}\n\n"
    content += f"**Date:** {date.strftime('%Y-%m-%d')}\n"
    
    if date.hour != 0:  # If time is specified
        content += f"**Time:** {date.strftime('%H:%M')}\n"
    
    content += "\n"
    
    if attendees:
        content += "**Attendees:**\n"
        for person in attendees:
            person_ref = format_person_reference(person)
            content += f"- {person_ref}\n"
        content += "\n"
    
    if projects:
        content += "**Related Projects:**\n"
        for project in projects:
            proj_ref = format_project_reference(project)
            content += f"- {proj_ref}\n"
        content += "\n"
    
    if notes:
        content += "## Discussion\n\n"
        content += f"{notes}\n\n"
    
    if action_items:
        content += "## Action Items\n\n"
        for item in action_items:
            content += f"- [ ] {item}\n"
        content += "\n"
    
    content += "## Decisions\n\n"
    content += "## Next Steps\n\n"
    
    return content


def generate_project_page(
    name: str,
    description: Optional[str] = None,
    stakeholders: Optional[List[str]] = None,
    status: Optional[str] = None,
    timeline: Optional[str] = None
) -> str:
    """
    Generate project page content with proper formatting
    
    Args:
        name: Project name
        description: Project description
        stakeholders: List of stakeholder names
        status: Project status (e.g., "In Progress", "Planning")
        timeline: Timeline description
    
    Returns:
        Formatted markdown content
    """
    content = f"# {name}\n\n"
    
    if description:
        content += f"{description}\n\n"
    
    content += "## Status\n\n"
    if status:
        content += f"**Current Status:** {status}\n\n"
    
    if timeline:
        content += f"**Timeline:** {timeline}\n\n"
    
    if stakeholders:
        content += "## Stakeholders\n\n"
        for person in stakeholders:
            person_ref = format_person_reference(person)
            content += f"- {person_ref}\n"
        content += "\n"
    
    content += "## Objectives\n\n"
    content += "## Next Actions\n\n"
    content += "## Milestones\n\n"
    content += "## Resources\n\n"
    
    return content


def generate_company_page(
    name: str,
    industry: Optional[str] = None,
    website: Optional[str] = None,
    key_contacts: Optional[List[str]] = None,
    notes: Optional[str] = None
) -> str:
    """
    Generate company page content with proper formatting
    
    Args:
        name: Company name
        industry: Industry/sector
        website: Company website
        key_contacts: List of key contact names
        notes: Additional notes about the company
    
    Returns:
        Formatted markdown content
    """
    content = f"# {name}\n\n"
    
    if industry:
        content += f"**Industry:** {industry}\n"
    
    if website:
        content += f"**Website:** {website}\n"
    
    content += "\n"
    
    if notes:
        content += f"## Overview\n\n{notes}\n\n"
    
    if key_contacts:
        content += "## Key Contacts\n\n"
        for person in key_contacts:
            person_ref = format_person_reference(person)
            content += f"- {person_ref}\n"
        content += "\n"
    
    content += "## Relationship History\n\n"
    content += "## Projects & Engagements\n\n"
    content += "## Notes\n\n"
    
    return content
