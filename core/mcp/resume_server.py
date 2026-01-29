#!/usr/bin/env python3
"""
Resume Builder MCP Server for Dex

Provides stateful, deterministic resume building with validation,
formatting, and career evidence integration.

Tools:
- start_session: Initialize resume building session
- list_sessions: List available sessions
- load_session: Resume previous session
- save_session: Explicitly save session
- add_role: Add professional role
- extract_achievements: Add validated achievements
- pull_career_evidence: Auto-pull from career evidence
- generate_role_writeup: Format role bullets
- compile_resume: Generate 2-page resume
- generate_linkedin: Create LinkedIn profile
- validate_metrics: Validate achievement metrics
- export_resume: Export to file
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Import resume utilities
from resume_parser import (
    ResumeSession,
    Role,
    Achievement,
    Metric,
    Education,
    PhaseEnum,
    MetricType,
    validate_date_format,
    validate_achievement_metrics,
    extract_metrics_from_text,
    calculate_bullet_quality_score,
    suggest_improvements,
    format_role_bullets,
    format_resume,
    format_linkedin_headline,
    format_linkedin_about,
    format_linkedin_experience,
    find_relevant_evidence,
    map_evidence_to_achievement,
    calculate_ats_score,
    calculate_estimated_pages,
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Custom JSON encoder for handling datetime objects and dataclasses
class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)

# Configuration - Vault paths
BASE_DIR = Path(os.environ.get('VAULT_PATH', Path.cwd()))
CAREER_DIR = BASE_DIR / 'Active' / 'Career'
RESUME_DIR = CAREER_DIR / 'Resume'
SESSIONS_DIR = RESUME_DIR / 'Sessions'
EVIDENCE_DIR = BASE_DIR / 'Resources' / 'Career_Evidence'

# Ensure directories exist
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory session storage
sessions: Dict[str, ResumeSession] = {}

# Initialize the MCP server
app = Server("dex-resume-mcp")


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

def generate_session_id() -> str:
    """Generate unique session ID."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"resume_{timestamp}"


def auto_save_session(session: ResumeSession):
    """Automatically save session to disk after state changes."""
    session.last_modified = datetime.now().isoformat()
    
    session_file = SESSIONS_DIR / f"{session.session_id}.json"
    
    try:
        with open(session_file, 'w') as f:
            json.dump(session.to_dict(), f, indent=2, cls=EnhancedJSONEncoder)
        logger.info(f"Auto-saved session: {session.session_id}")
    except Exception as e:
        logger.error(f"Failed to auto-save session: {e}")


def load_session_from_disk(session_id: str) -> Optional[ResumeSession]:
    """Load session from disk."""
    session_file = SESSIONS_DIR / f"{session_id}.json"
    
    if not session_file.exists():
        return None
    
    try:
        with open(session_file, 'r') as f:
            data = json.load(f)
        
        session = ResumeSession.from_dict(data)
        logger.info(f"Loaded session from disk: {session_id}")
        return session
    except Exception as e:
        logger.error(f"Failed to load session: {e}")
        return None


def list_available_sessions() -> List[Dict[str, Any]]:
    """List all saved sessions with metadata."""
    session_summaries = []
    
    for session_file in SESSIONS_DIR.glob("resume_*.json"):
        try:
            with open(session_file, 'r') as f:
                data = json.load(f)
            
            summary = {
                "session_id": data['session_id'],
                "created_at": data['created_at'],
                "last_modified": data['last_modified'],
                "phase": data['phase'],
                "roles_count": len(data.get('roles', [])),
                "approach": data.get('approach', 'unknown')
            }
            session_summaries.append(summary)
        except Exception as e:
            logger.error(f"Failed to read session file {session_file}: {e}")
            continue
    
    # Sort by last_modified (most recent first)
    session_summaries.sort(key=lambda x: x['last_modified'], reverse=True)
    
    return session_summaries


# ============================================================================
# TOOL DEFINITIONS
# ============================================================================

@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available resume builder tools"""
    return [
        types.Tool(
            name="start_session",
            description="Initialize a new resume building session with state tracking",
            inputSchema={
                "type": "object",
                "properties": {
                    "approach": {
                        "type": "string",
                        "enum": ["from_scratch", "improve_existing"],
                        "description": "Start fresh or improve existing resume"
                    },
                    "existing_resume_path": {
                        "type": "string",
                        "description": "Path to existing resume (if improve_existing)"
                    },
                    "target_role": {
                        "type": "string",
                        "description": "Optional target role to optimize for"
                    }
                },
                "required": ["approach"]
            }
        ),
        types.Tool(
            name="list_sessions",
            description="List all available resume building sessions",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="load_session",
            description="Load and resume a previous resume building session",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to load"
                    }
                },
                "required": ["session_id"]
            }
        ),
        types.Tool(
            name="save_session",
            description="Explicitly save current session (auto-save also happens after state changes)",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to save"
                    }
                },
                "required": ["session_id"]
            }
        ),
        types.Tool(
            name="add_role",
            description="Add a professional role to the resume with date validation",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "start_date": {
                        "type": "string",
                        "pattern": "^\\d{4}-(0[1-9]|1[0-2])$",
                        "description": "Format: YYYY-MM"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Format: YYYY-MM or 'present'"
                    },
                    "responsibilities": {
                        "type": "string",
                        "description": "Brief description of responsibilities"
                    }
                },
                "required": ["session_id", "title", "company", "start_date", "end_date"]
            }
        ),
        types.Tool(
            name="extract_achievements",
            description="Add achievements with enforced metric validation",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "role_id": {"type": "string"},
                    "achievements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "metrics": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "type": {
                                                "type": "string",
                                                "enum": ["percentage", "dollar", "count", "time"]
                                            },
                                            "value": {"type": "string"},
                                            "context": {"type": "string"}
                                        }
                                    }
                                },
                                "impact": {"type": "string"},
                                "skills": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "timeline": {"type": "string"}
                            },
                            "required": ["description", "impact"]
                        }
                    }
                },
                "required": ["session_id", "role_id", "achievements"]
            }
        ),
        types.Tool(
            name="pull_career_evidence",
            description="Automatically pull achievements from Career Evidence system",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "role_id": {"type": "string"}
                },
                "required": ["session_id", "role_id"]
            }
        ),
        types.Tool(
            name="generate_role_writeup",
            description="Generate professional bullet points for a role with quality scoring",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "role_id": {"type": "string"},
                    "max_bullets": {
                        "type": "number",
                        "description": "Maximum bullets to generate (default 5)",
                        "default": 5
                    }
                },
                "required": ["session_id", "role_id"]
            }
        ),
        types.Tool(
            name="compile_resume",
            description="Generate complete 2-page resume with enforced constraint",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "education": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "degree": {"type": "string"},
                                "field": {"type": "string"},
                                "school": {"type": "string"},
                                "graduation_year": {"type": "string"},
                                "honors": {"type": "string"},
                                "gpa": {"type": "string"}
                            },
                            "required": ["degree", "school", "graduation_year"]
                        }
                    },
                    "skills": {
                        "type": "object",
                        "description": "Skills grouped by category",
                        "additionalProperties": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "user_info": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "location": {"type": "string"},
                            "email": {"type": "string"},
                            "phone": {"type": "string"},
                            "linkedin": {"type": "string"}
                        }
                    }
                },
                "required": ["session_id"]
            }
        ),
        types.Tool(
            name="generate_linkedin",
            description="Generate LinkedIn profile from session data with character limits",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"}
                },
                "required": ["session_id"]
            }
        ),
        types.Tool(
            name="validate_metrics",
            description="Validate that achievement has quantifiable metrics",
            inputSchema={
                "type": "object",
                "properties": {
                    "achievement_text": {
                        "type": "string",
                        "description": "Achievement description to validate"
                    }
                },
                "required": ["achievement_text"]
            }
        ),
        types.Tool(
            name="export_resume",
            description="Export resume to file in specified format",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "format": {
                        "type": "string",
                        "enum": ["markdown", "plain_text", "json"],
                        "default": "markdown"
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional custom filename (without extension)"
                    }
                },
                "required": ["session_id"]
            }
        )
    ]


# ============================================================================
# TOOL HANDLERS
# ============================================================================

@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    
    arguments = arguments or {}
    
    try:
        if name == "start_session":
            return await handle_start_session(arguments)
        elif name == "list_sessions":
            return await handle_list_sessions(arguments)
        elif name == "load_session":
            return await handle_load_session(arguments)
        elif name == "save_session":
            return await handle_save_session(arguments)
        elif name == "add_role":
            return await handle_add_role(arguments)
        elif name == "extract_achievements":
            return await handle_extract_achievements(arguments)
        elif name == "pull_career_evidence":
            return await handle_pull_career_evidence(arguments)
        elif name == "generate_role_writeup":
            return await handle_generate_role_writeup(arguments)
        elif name == "compile_resume":
            return await handle_compile_resume(arguments)
        elif name == "generate_linkedin":
            return await handle_generate_linkedin(arguments)
        elif name == "validate_metrics":
            return await handle_validate_metrics(arguments)
        elif name == "export_resume":
            return await handle_export_resume(arguments)
        else:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown tool: {name}"}, indent=2)
            )]
    except Exception as e:
        logger.error(f"Error in {name}: {e}", exc_info=True)
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "error": f"Tool execution failed: {str(e)}",
                "tool": name
            }, indent=2)
        )]


async def handle_start_session(arguments: dict) -> list[types.TextContent]:
    """Initialize new resume building session"""
    
    approach = arguments.get('approach')
    target_role = arguments.get('target_role')
    
    # Generate session ID
    session_id = generate_session_id()
    
    # Create session
    session = ResumeSession(
        session_id=session_id,
        created_at=datetime.now().isoformat(),
        last_modified=datetime.now().isoformat(),
        phase=PhaseEnum.SETUP,
        approach=approach,
        target_role=target_role
    )
    
    # Store in memory
    sessions[session_id] = session
    
    # Save to disk
    auto_save_session(session)
    
    result = {
        "success": True,
        "session_id": session_id,
        "phase": session.phase.value,
        "approach": approach,
        "target_role": target_role,
        "message": "Session started. Ready to add professional roles."
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_list_sessions(arguments: dict) -> list[types.TextContent]:
    """List available sessions"""
    
    session_summaries = list_available_sessions()
    
    result = {
        "success": True,
        "sessions": session_summaries,
        "total_count": len(session_summaries)
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_load_session(arguments: dict) -> list[types.TextContent]:
    """Load previous session"""
    
    session_id = arguments.get('session_id')
    
    # Try memory first
    session = sessions.get(session_id)
    
    # Try disk if not in memory
    if not session:
        session = load_session_from_disk(session_id)
    
    if not session:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Session not found: {session_id}"
            }, indent=2)
        )]
    
    # Store in memory
    sessions[session_id] = session
    
    result = {
        "success": True,
        "session": session.to_dict(),
        "message": f"Session loaded. Currently in {session.phase.value} phase with {len(session.roles)} roles."
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2, cls=EnhancedJSONEncoder)
    )]


async def handle_save_session(arguments: dict) -> list[types.TextContent]:
    """Explicitly save session"""
    
    session_id = arguments.get('session_id')
    
    session = sessions.get(session_id)
    if not session:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Session not found: {session_id}"
            }, indent=2)
        )]
    
    auto_save_session(session)
    
    result = {
        "success": True,
        "session_id": session_id,
        "message": "Session saved successfully"
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_add_role(arguments: dict) -> list[types.TextContent]:
    """Add professional role"""
    
    session_id = arguments.get('session_id')
    session = sessions.get(session_id)
    
    if not session:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Session not found: {session_id}"
            }, indent=2)
        )]
    
    # Validate dates
    start_date = arguments.get('start_date')
    end_date = arguments.get('end_date')
    
    if not validate_date_format(start_date):
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Invalid start_date format: {start_date}. Use YYYY-MM"
            }, indent=2)
        )]
    
    if not validate_date_format(end_date):
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Invalid end_date format: {end_date}. Use YYYY-MM or 'present'"
            }, indent=2)
        )]
    
    # Create role
    role_id = f"role_{len(session.roles) + 1:03d}"
    
    role = Role(
        role_id=role_id,
        title=arguments.get('title'),
        company=arguments.get('company'),
        start_date=start_date,
        end_date=end_date,
        responsibilities=arguments.get('responsibilities', '')
    )
    
    # Add to session
    session.roles.append(role)
    session.phase = PhaseEnum.ROLES
    
    # Auto-save
    auto_save_session(session)
    
    result = {
        "success": True,
        "role_id": role_id,
        "roles_count": len(session.roles),
        "validation": {
            "date_format": "valid",
            "required_fields": "complete"
        },
        "message": f"Role added. Call extract_achievements with role_id '{role_id}' to add accomplishments."
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_extract_achievements(arguments: dict) -> list[types.TextContent]:
    """Extract achievements with metric validation"""
    
    session_id = arguments.get('session_id')
    role_id = arguments.get('role_id')
    achievements_data = arguments.get('achievements', [])
    
    session = sessions.get(session_id)
    if not session:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Session not found: {session_id}"
            }, indent=2)
        )]
    
    # Find role
    role = next((r for r in session.roles if r.role_id == role_id), None)
    if not role:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Role not found: {role_id}"
            }, indent=2)
        )]
    
    # Process achievements
    validation_results = []
    achievements_added = 0
    
    for ach_data in achievements_data:
        # Create metrics
        metrics = []
        for metric_data in ach_data.get('metrics', []):
            metrics.append(Metric(
                type=MetricType(metric_data['type']),
                value=metric_data['value'],
                context=metric_data.get('context', '')
            ))
        
        # If no explicit metrics, try to extract from text
        if not metrics:
            all_text = f"{ach_data['description']} {ach_data.get('impact', '')}"
            metrics = extract_metrics_from_text(all_text)
        
        # Create achievement
        achievement = Achievement(
            description=ach_data['description'],
            metrics=metrics,
            impact=ach_data.get('impact', ''),
            skills=ach_data.get('skills', []),
            timeline=ach_data.get('timeline')
        )
        
        # Validate
        validation = validate_achievement_metrics(achievement)
        achievement.validation_score = validation.score
        
        validation_results.append({
            "description": ach_data['description'][:50] + "...",
            "validation": validation.to_dict()
        })
        
        if validation.is_valid:
            role.achievements.append(achievement)
            achievements_added += 1
        else:
            logger.warning(f"Achievement failed validation: {validation.errors}")
    
    session.phase = PhaseEnum.EXTRACTION
    
    # Auto-save
    auto_save_session(session)
    
    result = {
        "success": True,
        "achievements_added": achievements_added,
        "validation_results": validation_results,
        "total_achievements": len(role.achievements),
        "message": f"Added {achievements_added} validated achievements to {role.title}"
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_pull_career_evidence(arguments: dict) -> list[types.TextContent]:
    """Pull achievements from Career Evidence system"""
    
    session_id = arguments.get('session_id')
    role_id = arguments.get('role_id')
    
    session = sessions.get(session_id)
    if not session:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Session not found: {session_id}"
            }, indent=2)
        )]
    
    # Find role
    role = next((r for r in session.roles if r.role_id == role_id), None)
    if not role:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Role not found: {role_id}"
            }, indent=2)
        )]
    
    # Check if Career Evidence exists
    if not EVIDENCE_DIR.exists():
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "Career Evidence directory not found",
                "note": "Run /career-setup to initialize career system"
            }, indent=2)
        )]
    
    # Find relevant evidence
    evidence_files = find_relevant_evidence(
        EVIDENCE_DIR,
        role.start_date,
        role.end_date,
        role.company
    )
    
    if not evidence_files:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "evidence_found": 0,
                "message": "No career evidence found for this role timeframe"
            }, indent=2)
        )]
    
    # Convert to achievements
    pulled_achievements = []
    for evidence in evidence_files:
        achievement = map_evidence_to_achievement(evidence)
        pulled_achievements.append({
            "title": evidence.get('title'),
            "date": evidence.get('date'),
            "impact": evidence.get('impact'),
            "skills": evidence.get('skills'),
            "validation_score": achievement.validation_score
        })
    
    result = {
        "success": True,
        "evidence_found": len(evidence_files),
        "achievements": pulled_achievements,
        "message": f"Found {len(evidence_files)} achievements from Career Evidence. Review and add using extract_achievements."
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_generate_role_writeup(arguments: dict) -> list[types.TextContent]:
    """Generate professional bullet points"""
    
    session_id = arguments.get('session_id')
    role_id = arguments.get('role_id')
    max_bullets = arguments.get('max_bullets', 5)
    
    session = sessions.get(session_id)
    if not session:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Session not found: {session_id}"
            }, indent=2)
        )]
    
    # Find role
    role = next((r for r in session.roles if r.role_id == role_id), None)
    if not role:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Role not found: {role_id}"
            }, indent=2)
        )]
    
    if not role.achievements:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "No achievements found for this role. Call extract_achievements first."
            }, indent=2)
        )]
    
    # Generate bullets
    bullets = format_role_bullets(role, max_bullets)
    
    # Calculate quality scores
    quality_scores = []
    suggestions_list = []
    
    for bullet in bullets:
        quality = calculate_bullet_quality_score(bullet)
        quality_scores.append(quality.overall)
        
        bullet_suggestions = suggest_improvements(bullet)
        if bullet_suggestions:
            suggestions_list.append({
                "bullet": bullet[:50] + "...",
                "suggestions": bullet_suggestions
            })
    
    session.phase = PhaseEnum.WRITEUP
    auto_save_session(session)
    
    result = {
        "success": True,
        "role": {
            "title": role.title,
            "company": role.company
        },
        "bullets": bullets,
        "quality_scores": quality_scores,
        "average_quality": round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else 0,
        "suggestions": suggestions_list,
        "message": "Role writeup generated. Review bullets and confirm."
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_compile_resume(arguments: dict) -> list[types.TextContent]:
    """Compile complete 2-page resume"""
    
    session_id = arguments.get('session_id')
    
    session = sessions.get(session_id)
    if not session:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Session not found: {session_id}"
            }, indent=2)
        )]
    
    # Add education if provided
    if arguments.get('education'):
        session.education = [Education(**edu) for edu in arguments['education']]
    
    # Add skills if provided
    if arguments.get('skills'):
        session.skills = arguments['skills']
    
    # Add user info to metadata
    if arguments.get('user_info'):
        session.metadata.update(arguments['user_info'])
    
    # Generate resume
    resume_markdown = format_resume(session, enforce_limit=True)
    
    # Calculate metadata
    estimated_pages = calculate_estimated_pages(resume_markdown)
    
    # Calculate quality score (average across all role bullets)
    all_quality_scores = []
    for role in session.roles:
        bullets = format_role_bullets(role)
        for bullet in bullets:
            quality = calculate_bullet_quality_score(bullet)
            all_quality_scores.append(quality.overall)
    
    avg_quality = sum(all_quality_scores) / len(all_quality_scores) if all_quality_scores else 0
    
    # Calculate ATS score
    target_keywords = session.metadata.get('target_keywords', [])
    ats_score = calculate_ats_score(resume_markdown, target_keywords)
    
    session.phase = PhaseEnum.COMPILATION
    auto_save_session(session)
    
    result = {
        "success": True,
        "resume_markdown": resume_markdown,
        "metadata": {
            "total_roles": len(session.roles),
            "total_bullets": sum(len(r.achievements) for r in session.roles),
            "estimated_pages": estimated_pages,
            "quality_score": round(avg_quality, 2),
            "ats_score": ats_score
        },
        "message": "Resume compiled. Use export_resume to save to file."
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_generate_linkedin(arguments: dict) -> list[types.TextContent]:
    """Generate LinkedIn profile"""
    
    session_id = arguments.get('session_id')
    
    session = sessions.get(session_id)
    if not session:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Session not found: {session_id}"
            }, indent=2)
        )]
    
    if not session.roles:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "No roles found. Add roles first."
            }, indent=2)
        )]
    
    # Generate components
    headline = format_linkedin_headline(session)
    about = format_linkedin_about(session)
    
    # Generate experience sections
    experience_sections = []
    for role in session.roles:
        exp = format_linkedin_experience(role)
        experience_sections.append({
            "role": f"{role.title} — {role.company}",
            "content": exp
        })
    
    # Extract SEO keywords
    seo_keywords = []
    if session.target_role:
        seo_keywords.append(session.target_role)
    
    for skill_category in session.skills.keys():
        seo_keywords.append(skill_category)
    
    session.phase = PhaseEnum.LINKEDIN
    auto_save_session(session)
    
    result = {
        "success": True,
        "headline": headline,
        "headline_length": len(headline),
        "about": about,
        "about_length": len(about),
        "experience": experience_sections,
        "seo_keywords": seo_keywords[:10],
        "message": "LinkedIn profile generated. Review and customize as needed."
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_validate_metrics(arguments: dict) -> list[types.TextContent]:
    """Validate metrics in achievement text"""
    
    achievement_text = arguments.get('achievement_text', '')
    
    # Extract metrics
    metrics = extract_metrics_from_text(achievement_text)
    
    # Create temporary achievement for validation
    temp_achievement = Achievement(
        description=achievement_text,
        metrics=metrics,
        impact="",
        skills=[]
    )
    
    validation = validate_achievement_metrics(temp_achievement)
    
    result = {
        "success": True,
        "validation": validation.to_dict(),
        "metrics_found": [m.to_dict() for m in metrics],
        "metric_count": len(metrics)
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_export_resume(arguments: dict) -> list[types.TextContent]:
    """Export resume to file"""
    
    session_id = arguments.get('session_id')
    format_type = arguments.get('format', 'markdown')
    custom_filename = arguments.get('filename')
    
    session = sessions.get(session_id)
    if not session:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Session not found: {session_id}"
            }, indent=2)
        )]
    
    # Generate resume
    resume_content = format_resume(session, enforce_limit=True)
    
    # Determine filename
    if custom_filename:
        filename = f"{custom_filename}.{format_type}"
    else:
        date_str = datetime.now().strftime('%Y-%m-%d')
        filename = f"{date_str} - Resume.{format_type if format_type != 'plain_text' else 'txt'}"
    
    # Ensure Resume directory exists
    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    
    filepath = RESUME_DIR / filename
    
    # Export based on format
    try:
        if format_type == 'markdown':
            with open(filepath, 'w') as f:
                f.write(resume_content)
        
        elif format_type == 'plain_text':
            # Convert markdown to plain text (remove markdown syntax)
            plain_text = resume_content
            plain_text = re.sub(r'#+ ', '', plain_text)  # Remove headers
            plain_text = re.sub(r'\*\*(.+?)\*\*', r'\1', plain_text)  # Remove bold
            plain_text = re.sub(r'---', '', plain_text)  # Remove dividers
            
            with open(filepath, 'w') as f:
                f.write(plain_text)
        
        elif format_type == 'json':
            # Export session as JSON
            with open(filepath, 'w') as f:
                json.dump(session.to_dict(), f, indent=2, cls=EnhancedJSONEncoder)
        
        session.phase = PhaseEnum.COMPLETE
        auto_save_session(session)
        
        result = {
            "success": True,
            "filepath": str(filepath.relative_to(BASE_DIR)),
            "format": format_type,
            "message": f"Resume exported to {filepath.relative_to(BASE_DIR)}"
        }
    
    except Exception as e:
        result = {
            "success": False,
            "error": f"Failed to export resume: {str(e)}"
        }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


# ============================================================================
# MAIN
# ============================================================================

async def _main():
    """Async main entry point for the MCP server"""
    logger.info("Starting Dex Resume Builder MCP Server")
    logger.info(f"Vault path: {BASE_DIR}")
    logger.info(f"Resume directory: {RESUME_DIR}")
    logger.info(f"Sessions directory: {SESSIONS_DIR}")
    logger.info(f"Evidence directory: {EVIDENCE_DIR}")
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-resume-mcp",
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
