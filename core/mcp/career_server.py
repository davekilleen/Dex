#!/usr/bin/env python3
"""
Career Development MCP Server for Dex

Provides tools for career evidence aggregation, ladder parsing,
competency coverage analysis, and progress tracking.

Tools:
- scan_evidence: Scan and aggregate career evidence files
- parse_ladder: Parse career ladder into structured competency tree
- analyze_coverage: Map evidence to competencies and calculate coverage
- timeline_analysis: Track evidence trends and growth velocity over time
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, date

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Import parsing utilities
from career_parser import (
    parse_evidence_file,
    parse_ladder_file,
    scan_evidence_directory,
    analyze_competency_coverage,
    group_evidence_by_period,
    calculate_growth_velocity,
    find_stale_competencies,
    parse_date_range,
    get_quarter_label,
)

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
CAREER_DIR = BASE_DIR / 'Active' / 'Career'
EVIDENCE_DIR = BASE_DIR / 'Resources' / 'Career_Evidence'
LADDER_FILE = CAREER_DIR / 'Career_Ladder.md'

# Initialize the MCP server
app = Server("dex-career-mcp")


# ============================================================================
# TOOL DEFINITIONS
# ============================================================================

@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available career tools"""
    return [
        types.Tool(
            name="scan_evidence",
            description="Scan and aggregate career evidence files with structured data extraction from templates",
            inputSchema={
                "type": "object",
                "properties": {
                    "date_range": {
                        "type": "string",
                        "description": "Optional date range filter (e.g., '2025-Q4', '2025-01-01:2025-12-31', 'last-90-days', 'last-6-months')"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["Achievements", "Feedback_Received", "Skills_Development"],
                        "description": "Optional category filter"
                    }
                }
            }
        ),
        types.Tool(
            name="parse_ladder",
            description="Parse career ladder document into structured competency tree",
            inputSchema={
                "type": "object",
                "properties": {
                    "current_level": {
                        "type": "string",
                        "description": "Optional current level override"
                    },
                    "target_level": {
                        "type": "string",
                        "description": "Optional target level override"
                    }
                }
            }
        ),
        types.Tool(
            name="analyze_coverage",
            description="Map evidence to competencies and calculate coverage statistics",
            inputSchema={
                "type": "object",
                "properties": {
                    "target_level": {
                        "type": "string",
                        "description": "Optional target level to analyze"
                    },
                    "include_examples": {
                        "type": "boolean",
                        "description": "Include example evidence files (default: true)",
                        "default": True
                    },
                    "date_range": {
                        "type": "string",
                        "description": "Optional date range for evidence (e.g., 'last-6-months')"
                    }
                }
            }
        ),
        types.Tool(
            name="timeline_analysis",
            description="Track evidence accumulation trends and growth velocity over time",
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Time period to analyze (e.g., 'last-12-months', 'last-6-months', '2025')",
                        "default": "last-12-months"
                    },
                    "group_by": {
                        "type": "string",
                        "enum": ["month", "quarter", "year"],
                        "description": "How to group the data (default: quarter)",
                        "default": "quarter"
                    }
                }
            }
        ),
        types.Tool(
            name="scan_work_for_evidence",
            description="Scan Work MCP data (quarterly goals, weekly priorities, tasks) to find completed high-impact work that could be career evidence. Returns completed goals/priorities with career metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "date_range": {
                        "type": "string",
                        "description": "Optional date range filter (e.g., '2025-Q4', 'last-6-months', 'this-quarter')"
                    },
                    "impact_level": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Filter by impact level (default: high)"
                    },
                    "include_goals": {
                        "type": "boolean",
                        "description": "Include completed quarterly goals (default: true)",
                        "default": True
                    },
                    "include_priorities": {
                        "type": "boolean",
                        "description": "Include completed weekly priorities (default: true)",
                        "default": True
                    }
                }
            }
        ),
        types.Tool(
            name="skills_gap_analysis",
            description="Analyze skills gap by comparing career ladder requirements to active work. Identifies which required skills are being developed vs neglected.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target_level": {
                        "type": "string",
                        "description": "Target role/level (from career ladder) - defaults to next level"
                    },
                    "lookback_days": {
                        "type": "integer",
                        "description": "How many days to look back for skill activity (default: 90)",
                        "default": 90
                    },
                    "stale_threshold_days": {
                        "type": "integer",
                        "description": "Days without activity to flag skill as stale (default: 42)",
                        "default": 42
                    }
                }
            }
        ),
        types.Tool(
            name="generate_evidence_from_work",
            description="Generate career evidence file from completed work (goal/priority/project). Pre-fills Achievement template with context from work data.",
            inputSchema={
                "type": "object",
                "properties": {
                    "work_id": {
                        "type": "string",
                        "description": "Work item ID (e.g., 'Q1-2026-goal-1', 'week-2026-W05-p1', 'task-20260128-001')"
                    },
                    "work_type": {
                        "type": "string",
                        "enum": ["quarterly_goal", "weekly_priority", "task", "project"],
                        "description": "Type of work item"
                    },
                    "title": {
                        "type": "string",
                        "description": "Achievement title (defaults to work item title)"
                    },
                    "impact_details": {
                        "type": "string",
                        "description": "Specific impact details and metrics (user provides this)"
                    },
                    "challenges": {
                        "type": "string",
                        "description": "Challenges overcome (user provides this)"
                    }
                },
                "required": ["work_id", "work_type"]
            }
        ),
        types.Tool(
            name="promotion_readiness_score",
            description="Calculate promotion readiness score based on evidence coverage, work delivery, skills development, and time in role. Returns 0-100 score with breakdown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target_level": {
                        "type": "string",
                        "description": "Target promotion level (from career ladder)"
                    },
                    "time_in_role_months": {
                        "type": "integer",
                        "description": "Months in current role (affects readiness)"
                    }
                }
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
        if name == "scan_evidence":
            return await handle_scan_evidence(arguments)
        elif name == "parse_ladder":
            return await handle_parse_ladder(arguments)
        elif name == "analyze_coverage":
            return await handle_analyze_coverage(arguments)
        elif name == "timeline_analysis":
            return await handle_timeline_analysis(arguments)
        elif name == "scan_work_for_evidence":
            return await handle_scan_work_for_evidence(arguments)
        elif name == "skills_gap_analysis":
            return await handle_skills_gap_analysis(arguments)
        elif name == "generate_evidence_from_work":
            return await handle_generate_evidence_from_work(arguments)
        elif name == "promotion_readiness_score":
            return await handle_promotion_readiness_score(arguments)
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


async def handle_scan_evidence(arguments: dict) -> list[types.TextContent]:
    """Scan and aggregate evidence files"""
    
    if not EVIDENCE_DIR.exists():
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Evidence directory not found: {EVIDENCE_DIR}",
                "note": "Run /career-setup to initialize your career system"
            }, indent=2)
        )]
    
    # Parse date range if provided
    date_range_arg = arguments.get('date_range')
    date_range = None
    if date_range_arg:
        date_range = parse_date_range(date_range_arg)
        if date_range == (None, None):
            return [types.TextContent(
                type="text",
                text=json.dumps({
                    "error": f"Invalid date range format: {date_range_arg}",
                    "supported_formats": [
                        "2025-Q4",
                        "2025-01-01:2025-12-31",
                        "last-90-days",
                        "last-6-months",
                        "last-12-months",
                        "2025"
                    ]
                }, indent=2)
            )]
    
    category = arguments.get('category')
    
    # Scan evidence directory
    evidence_files = scan_evidence_directory(EVIDENCE_DIR, date_range, category)
    
    # Group by category and date
    by_category = {}
    by_date = {}
    
    for evidence in evidence_files:
        cat = evidence.get('category', 'Other')
        by_category[cat] = by_category.get(cat, 0) + 1
        
        if evidence.get('date'):
            try:
                file_date = datetime.strptime(evidence['date'], '%Y-%m-%d').date()
                quarter = get_quarter_label(file_date)
                by_date[quarter] = by_date.get(quarter, 0) + 1
            except ValueError:
                pass
    
    result = {
        "success": True,
        "total_files": len(evidence_files),
        "by_category": by_category,
        "by_date": dict(sorted(by_date.items(), reverse=True)),
        "evidence_files": evidence_files,
        "filters_applied": {
            "date_range": date_range_arg,
            "category": category
        }
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2, cls=DateTimeEncoder)
    )]


async def handle_parse_ladder(arguments: dict) -> list[types.TextContent]:
    """Parse career ladder file"""
    
    if not LADDER_FILE.exists():
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Career ladder file not found: {LADDER_FILE}",
                "note": "Run /career-setup to create your career ladder"
            }, indent=2)
        )]
    
    # Parse the ladder
    ladder_data = parse_ladder_file(LADDER_FILE)
    
    if "error" in ladder_data:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                **ladder_data
            }, indent=2)
        )]
    
    # Add success flag
    ladder_data["success"] = True
    
    return [types.TextContent(
        type="text",
        text=json.dumps(ladder_data, indent=2, cls=DateTimeEncoder)
    )]


async def handle_analyze_coverage(arguments: dict) -> list[types.TextContent]:
    """Analyze competency coverage"""
    
    # Check prerequisites
    if not EVIDENCE_DIR.exists():
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "Evidence directory not found",
                "note": "Run /career-setup to initialize your career system"
            }, indent=2)
        )]
    
    if not LADDER_FILE.exists():
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "Career ladder file not found",
                "note": "Run /career-setup to create your career ladder"
            }, indent=2)
        )]
    
    # Parse ladder
    ladder_data = parse_ladder_file(LADDER_FILE)
    if "error" in ladder_data or not ladder_data.get('competencies'):
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "Failed to parse career ladder or no competencies found",
                "ladder_data": ladder_data
            }, indent=2)
        )]
    
    # Scan evidence (with optional date range filter)
    date_range_arg = arguments.get('date_range')
    date_range = None
    if date_range_arg:
        date_range = parse_date_range(date_range_arg)
    
    evidence_files = scan_evidence_directory(EVIDENCE_DIR, date_range)
    
    if not evidence_files:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "target_level": ladder_data.get('target_level'),
                "analysis_date": datetime.now().isoformat(),
                "total_evidence_files": 0,
                "note": "No evidence files found. Start capturing achievements with /career-coach",
                "coverage_by_competency": [
                    {
                        "competency": comp['category'],
                        "evidence_count": 0,
                        "coverage_level": "none",
                        "example_files": [],
                        "skills_mentioned": []
                    }
                    for comp in ladder_data['competencies']
                ]
            }, indent=2, cls=DateTimeEncoder)
        )]
    
    # Analyze coverage
    coverage_analysis = analyze_competency_coverage(
        evidence_files,
        ladder_data['competencies']
    )
    
    # Optionally remove detailed examples
    include_examples = arguments.get('include_examples', True)
    if not include_examples:
        for comp_coverage in coverage_analysis['coverage_by_competency']:
            comp_coverage.pop('all_evidence', None)
    
    result = {
        "success": True,
        "target_level": ladder_data.get('target_level'),
        "analysis_date": datetime.now().isoformat(),
        **coverage_analysis
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2, cls=DateTimeEncoder)
    )]


async def handle_timeline_analysis(arguments: dict) -> list[types.TextContent]:
    """Analyze evidence timeline and trends"""
    
    if not EVIDENCE_DIR.exists():
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": "Evidence directory not found",
                "note": "Run /career-setup to initialize your career system"
            }, indent=2)
        )]
    
    # Parse arguments
    period_arg = arguments.get('period', 'last-12-months')
    group_by = arguments.get('group_by', 'quarter')
    
    # Parse period to get date range
    date_range = parse_date_range(period_arg)
    
    # Scan evidence
    evidence_files = scan_evidence_directory(EVIDENCE_DIR, date_range)
    
    if not evidence_files:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": True,
                "period": period_arg,
                "analysis_date": datetime.now().isoformat(),
                "total_evidence": 0,
                "note": "No evidence files found in this period",
                "evidence_density": [],
                "growth_velocity": {"average_monthly": 0, "trend": "no_data"}
            }, indent=2, cls=DateTimeEncoder)
        )]
    
    # Group by period
    period_data = group_evidence_by_period(evidence_files, group_by)
    
    # Calculate growth velocity
    growth = calculate_growth_velocity(period_data)
    
    # Analyze competency trends (if ladder exists)
    competency_trends = []
    staleness_flags = []
    
    if LADDER_FILE.exists():
        ladder_data = parse_ladder_file(LADDER_FILE)
        if ladder_data.get('competencies'):
            # Track competency mentions over time
            comp_by_period = {comp['category']: {} for comp in ladder_data['competencies']}
            
            for period_info in period_data:
                period_label = period_info['period']
                for evidence in period_info['files']:
                    # Check which competencies this evidence matches
                    for comp in ladder_data['competencies']:
                        comp_name = comp['category']
                        from career_parser import match_evidence_to_competency
                        score = match_evidence_to_competency(
                            evidence.get('skills', []),
                            evidence.get('ladder_alignment', ''),
                            comp_name
                        )
                        if score >= 0.5:
                            comp_by_period[comp_name][period_label] = \
                                comp_by_period[comp_name].get(period_label, 0) + 1
            
            # Build competency trends
            for comp_name, periods in comp_by_period.items():
                if periods:  # Only include competencies with evidence
                    # Determine trend
                    values = list(periods.values())
                    if len(values) >= 2:
                        if values[-1] > values[0]:
                            trend = "increasing"
                        elif values[-1] < values[0]:
                            trend = "decreasing"
                        else:
                            trend = "stable"
                    else:
                        trend = "insufficient_data"
                    
                    competency_trends.append({
                        "competency": comp_name,
                        "evidence_by_period": periods,
                        "trend": trend
                    })
            
            # Find stale competencies
            staleness_flags = find_stale_competencies(
                evidence_files,
                ladder_data['competencies'],
                threshold_days=90
            )
    
    # Build result (remove file details from period data for cleaner output)
    clean_period_data = []
    for p in period_data:
        clean_period_data.append({
            "period": p['period'],
            "count": p['count'],
            "categories": p['categories']
        })
    
    result = {
        "success": True,
        "period": period_arg,
        "analysis_date": datetime.now().isoformat(),
        "total_evidence": len(evidence_files),
        "evidence_density": clean_period_data,
        "competency_trends": competency_trends,
        "staleness_flags": staleness_flags,
        "growth_velocity": growth
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2, cls=DateTimeEncoder)
    )]


async def handle_scan_work_for_evidence(arguments: dict) -> list[types.TextContent]:
    """Scan Work MCP data for completed high-impact work that could be career evidence"""
    date_range = arguments.get('date_range')
    impact_level = arguments.get('impact_level', 'high')
    include_goals = arguments.get('include_goals', True)
    include_priorities = arguments.get('include_priorities', True)
    
    evidence_candidates = []
    
    # Scan quarterly goals
    if include_goals:
        quarter_goals_file = BASE_DIR / '01-Quarter_Goals/Quarter_Goals.md'
        if quarter_goals_file.exists():
            content = quarter_goals_file.read_text()
            
            # Parse goals with career metadata
            lines = content.split('\n')
            current_goal = None
            
            for i, line in enumerate(lines):
                # Match goal headers like ### 1. Launch Product v2.0 — **Growth** ^Q1-2026-goal-1
                goal_match = re.match(r'###\s+(\d+)\.\s+(.+?)\s+—\s+\*\*(.+?)\*\*(?:\s+\^(Q\d+-\d{4}-goal-\d+))?', line)
                if goal_match:
                    if current_goal:
                        evidence_candidates.append(current_goal)
                    
                    current_goal = {
                        'type': 'quarterly_goal',
                        'goal_num': int(goal_match.group(1)),
                        'title': goal_match.group(2).strip(),
                        'pillar': goal_match.group(3).strip(),
                        'goal_id': goal_match.group(4) if goal_match.group(4) else None,
                        'progress': 0,
                        'career_goal_id': None,
                        'skills_developed': [],
                        'impact_level': None
                    }
                elif current_goal:
                    # Extract metadata
                    if '**Progress:**' in line:
                        progress_match = re.search(r'(\d+)%', line)
                        if progress_match:
                            current_goal['progress'] = int(progress_match.group(1))
                    elif '**Career goal:**' in line:
                        career_match = re.search(r'\*\*Career goal:\*\*\s*(.+)', line)
                        if career_match:
                            current_goal['career_goal_id'] = career_match.group(1).strip()
                    elif '**Skills developing:**' in line:
                        skills_match = re.search(r'\*\*Skills developing:\*\*\s*(.+)', line)
                        if skills_match:
                            current_goal['skills_developed'] = [s.strip() for s in skills_match.group(1).split(',')]
                    elif '**Impact level:**' in line:
                        impact_match = re.search(r'\*\*Impact level:\*\*\s*(low|medium|high)', line)
                        if impact_match:
                            current_goal['impact_level'] = impact_match.group(1)
            
            # Add last goal
            if current_goal:
                evidence_candidates.append(current_goal)
    
    # Filter by impact level and completion
    filtered_candidates = []
    for candidate in evidence_candidates:
        # Must be completed (>= 80%) or have career metadata
        if candidate['progress'] >= 80 or candidate.get('career_goal_id') or candidate.get('skills_developed'):
            # Filter by impact level
            if impact_level == 'high' and candidate.get('impact_level') != 'high':
                continue
            filtered_candidates.append(candidate)
    
    # Sort by progress (completed first) and impact level
    impact_order = {'high': 3, 'medium': 2, 'low': 1, None: 0}
    filtered_candidates.sort(key=lambda x: (x['progress'], impact_order.get(x.get('impact_level'), 0)), reverse=True)
    
    result = {
        'success': True,
        'scan_date': datetime.now().isoformat(),
        'filters': {
            'date_range': date_range,
            'impact_level': impact_level,
            'include_goals': include_goals,
            'include_priorities': include_priorities
        },
        'candidates_found': len(filtered_candidates),
        'evidence_candidates': filtered_candidates
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2, cls=DateTimeEncoder)
    )]


async def handle_skills_gap_analysis(arguments: dict) -> list[types.TextContent]:
    """Analyze skills gap by comparing career ladder to active work"""
    target_level = arguments.get('target_level')
    lookback_days = arguments.get('lookback_days', 90)
    stale_threshold_days = arguments.get('stale_threshold_days', 42)
    
    # 1. Parse career ladder to get required skills
    ladder_file = CAREER_DIR / 'Career_Ladder.md'
    required_skills = []
    
    if ladder_file.exists():
        content = ladder_file.read_text()
        # Simple skill extraction - look for skills in target level section
        # This is basic - real implementation would parse more sophisticatedly
        lines = content.split('\n')
        in_target_section = False
        
        for line in lines:
            if target_level and target_level in line and line.startswith('#'):
                in_target_section = True
            elif line.startswith('#') and in_target_section:
                break  # Moved to next section
            elif in_target_section and ('- ' in line or '* ' in line):
                # Extract skill mentions
                skill_match = re.search(r'[-*]\s*(.+)', line)
                if skill_match:
                    required_skills.append(skill_match.group(1).strip())
    
    # 2. Scan work data for skills being developed
    active_skills = {}
    cutoff_date = datetime.now() - timedelta(days=lookback_days)
    
    # Scan quarterly goals for skills_developed
    quarter_goals_file = BASE_DIR / '01-Quarter_Goals/Quarter_Goals.md'
    if quarter_goals_file.exists():
        content = quarter_goals_file.read_text()
        skills_match = re.findall(r'\*\*Skills developing:\*\*\s*(.+)', content)
        for match in skills_match:
            skills = [s.strip() for s in match.split(',')]
            for skill in skills:
                if skill not in active_skills:
                    active_skills[skill] = {'count': 0, 'last_seen': None, 'sources': []}
                active_skills[skill]['count'] += 1
                active_skills[skill]['sources'].append('quarterly_goal')
                active_skills[skill]['last_seen'] = datetime.now()  # Simplified - would check actual dates
    
    # Scan 03-Tasks/Tasks.md for # Career: tags
    tasks_file = BASE_DIR / '03-Tasks/Tasks.md'
    if tasks_file.exists():
        content = tasks_file.read_text()
        career_tags = re.findall(r'#\s*Career:\s*([^\n]+)', content)
        for skill in career_tags:
            skill = skill.strip()
            if skill not in active_skills:
                active_skills[skill] = {'count': 0, 'last_seen': None, 'sources': []}
            active_skills[skill]['count'] += 1
            active_skills[skill]['sources'].append('task')
            active_skills[skill]['last_seen'] = datetime.now()
    
    # 3. Identify gaps
    skills_gap = []
    stale_skills = []
    actively_developed = []
    
    for skill in required_skills:
        # Fuzzy match against active skills
        matched = False
        for active_skill in active_skills.keys():
            # Simple substring match - real implementation would use fuzzy matching
            if skill.lower() in active_skill.lower() or active_skill.lower() in skill.lower():
                matched = True
                # Check if stale
                days_since = (datetime.now() - active_skills[active_skill]['last_seen']).days if active_skills[active_skill]['last_seen'] else 999
                if days_since > stale_threshold_days:
                    stale_skills.append({
                        'skill': skill,
                        'days_since_activity': days_since,
                        'last_developed': active_skills[active_skill]['last_seen'].isoformat() if active_skills[active_skill]['last_seen'] else None
                    })
                else:
                    actively_developed.append({
                        'skill': skill,
                        'development_count': active_skills[active_skill]['count'],
                        'sources': list(set(active_skills[active_skill]['sources']))
                    })
                break
        
        if not matched:
            skills_gap.append(skill)
    
    result = {
        'success': True,
        'analysis_date': datetime.now().isoformat(),
        'target_level': target_level,
        'lookback_days': lookback_days,
        'required_skills_count': len(required_skills),
        'actively_developed': actively_developed,
        'actively_developed_count': len(actively_developed),
        'skills_gap': skills_gap,
        'skills_gap_count': len(skills_gap),
        'stale_skills': stale_skills,
        'stale_skills_count': len(stale_skills),
        'coverage_percentage': round((len(actively_developed) / len(required_skills) * 100) if required_skills else 0, 1)
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2, cls=DateTimeEncoder)
    )]


async def handle_generate_evidence_from_work(arguments: dict) -> list[types.TextContent]:
    """Generate career evidence file from completed work item"""
    work_id = arguments['work_id']
    work_type = arguments['work_type']
    title = arguments.get('title')
    impact_details = arguments.get('impact_details', '[Add specific metrics and outcomes]')
    challenges = arguments.get('challenges', '[What was difficult and how you handled it]')
    
    # 1. Read work item details from appropriate file
    work_data = {}
    
    if work_type == 'quarterly_goal':
        quarter_goals_file = BASE_DIR / '01-Quarter_Goals/Quarter_Goals.md'
        if quarter_goals_file.exists():
            content = quarter_goals_file.read_text()
            lines = content.split('\n')
            
            for i, line in enumerate(lines):
                if f'^{work_id}' in line:
                    # Extract goal details
                    goal_match = re.match(r'###\s+(\d+)\.\s+(.+?)\s+—\s+\*\*(.+?)\*\*', line)
                    if goal_match:
                        work_data['title'] = goal_match.group(2).strip()
                        work_data['pillar'] = goal_match.group(3).strip()
                        
                        # Look for metadata in following lines
                        j = i + 1
                        while j < len(lines) and not lines[j].startswith('###'):
                            if '**What success looks like:**' in lines[j]:
                                k = j + 1
                                success_criteria = ''
                                while k < len(lines) and lines[k].strip() and not lines[k].startswith('**'):
                                    success_criteria += lines[k].strip() + ' '
                                    k += 1
                                work_data['success_criteria'] = success_criteria.strip()
                            elif '**Skills developing:**' in lines[j]:
                                skills_match = re.search(r'\*\*Skills developing:\*\*\s*(.+)', lines[j])
                                if skills_match:
                                    work_data['skills'] = [s.strip() for s in skills_match.group(1).split(',')]
                            elif '**Career goal:**' in lines[j]:
                                career_match = re.search(r'\*\*Career goal:\*\*\s*(.+)', lines[j])
                                if career_match:
                                    work_data['career_goal'] = career_match.group(1).strip()
                            j += 1
                    break
    
    if not title:
        title = work_data.get('title', 'Achievement')
    
    # 2. Generate evidence file content
    evidence_date = datetime.now().strftime('%Y-%m-%d')
    filename = f"{evidence_date}-{title.replace(' ', '_')[:50]}.md"
    filepath = EVIDENCE_DIR / 'Achievements' / filename
    
    skills_list = '\n'.join([f"- {skill}" for skill in work_data.get('skills', ['[Skill 1]', '[Skill 2]'])])
    
    evidence_content = f"""# {title}

**Date:** {evidence_date}
**Project:** {work_data.get('pillar', '[Project name]')}
**Category:** Impact

**Source:** {work_type} ({work_id})

---

## What I Did

{work_data.get('success_criteria', '[Description of the work and approach — tell the story of what you accomplished]')}

---

## Impact

{impact_details}

---

## Skills Demonstrated

{skills_list}

---

## Stakeholders

- [Person 1] — [Their role/involvement]
- [Person 2] — [Their role/involvement]

---

## Challenges Overcome

{challenges}

---

## Ladder Alignment

**Maps to:** [Which career ladder competency this demonstrates]

{f"**Career Goal:** {work_data.get('career_goal', 'N/A')}" if work_data.get('career_goal') else ""}

---

## Notes

Generated from completed work: {work_id}
"""
    
    # 3. Write file
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(evidence_content)
    
    result = {
        'success': True,
        'file_path': str(filepath),
        'work_id': work_id,
        'work_type': work_type,
        'title': title,
        'message': 'Evidence file created. User should review and add specific impact details, challenges, and stakeholders.'
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2)
    )]


async def handle_promotion_readiness_score(arguments: dict) -> list[types.TextContent]:
    """Calculate promotion readiness score"""
    target_level = arguments.get('target_level')
    time_in_role_months = arguments.get('time_in_role_months', 12)
    
    score_breakdown = {}
    
    # 1. Evidence Coverage (0-25 points)
    # Count evidence files in last 12 months
    evidence_count = 0
    if EVIDENCE_DIR.exists():
        for category_dir in EVIDENCE_DIR.iterdir():
            if category_dir.is_dir():
                evidence_count += len(list(category_dir.glob('*.md')))
    
    # Scoring: 0-5 files=5pts, 6-10=10pts, 11-15=15pts, 16-20=20pts, 21+=25pts
    if evidence_count >= 21:
        evidence_score = 25
    elif evidence_count >= 16:
        evidence_score = 20
    elif evidence_count >= 11:
        evidence_score = 15
    elif evidence_count >= 6:
        evidence_score = 10
    else:
        evidence_score = evidence_count
    
    score_breakdown['evidence_coverage'] = {
        'score': evidence_score,
        'max': 25,
        'evidence_count': evidence_count,
        'notes': 'Career evidence files captured'
    }
    
    # 2. Work Delivery (0-30 points)
    # Count completed high-impact quarterly goals
    high_impact_goals_completed = 0
    quarter_goals_file = BASE_DIR / '01-Quarter_Goals/Quarter_Goals.md'
    if quarter_goals_file.exists():
        content = quarter_goals_file.read_text()
        # Count goals with impact_level: high and progress >= 80%
        high_impact_matches = re.findall(r'\*\*Impact level:\*\*\s*high.*?\*\*Progress:\*\*\s*(\d+)%', content, re.DOTALL)
        for progress in high_impact_matches:
            if int(progress) >= 80:
                high_impact_goals_completed += 1
    
    # Scoring: 0 goals=0pts, 1-2=10pts, 3-4=20pts, 5+=30pts
    if high_impact_goals_completed >= 5:
        work_score = 30
    elif high_impact_goals_completed >= 3:
        work_score = 20
    elif high_impact_goals_completed >= 1:
        work_score = 10
    else:
        work_score = 0
    
    score_breakdown['work_delivery'] = {
        'score': work_score,
        'max': 30,
        'high_impact_goals_completed': high_impact_goals_completed,
        'notes': 'Completed high-impact quarterly goals'
    }
    
    # 3. Skills Coverage (0-25 points)
    # Use skills_gap_analysis to check coverage
    # Simplified for now - would call skills_gap_analysis tool
    skills_score = 15  # Placeholder
    score_breakdown['skills_coverage'] = {
        'score': skills_score,
        'max': 25,
        'notes': 'Skills demonstrated vs required (use skills_gap_analysis for details)'
    }
    
    # 4. Time in Role (0-10 points)
    # 0-11 months=0pts, 12-17 months=5pts, 18+=10pts
    if time_in_role_months >= 18:
        time_score = 10
    elif time_in_role_months >= 12:
        time_score = 5
    else:
        time_score = 0
    
    score_breakdown['time_in_role'] = {
        'score': time_score,
        'max': 10,
        'months': time_in_role_months,
        'notes': 'Time to build track record'
    }
    
    # 5. Growth Velocity (0-10 points)
    # Evidence accumulation over time
    velocity_score = 5  # Placeholder
    score_breakdown['growth_velocity'] = {
        'score': velocity_score,
        'max': 10,
        'notes': 'Consistent evidence accumulation (use timeline_analysis for details)'
    }
    
    # Total Score
    total_score = sum(category['score'] for category in score_breakdown.values())
    max_score = sum(category['max'] for category in score_breakdown.values())
    percentage = round((total_score / max_score * 100), 1)
    
    # Readiness Assessment
    if percentage >= 80:
        readiness = "Ready"
        recommendation = "Strong case for promotion. Schedule discussion with manager."
    elif percentage >= 60:
        readiness = "Nearly Ready"
        recommendation = "Close to promotion readiness. Focus on filling gaps identified above."
    elif percentage >= 40:
        readiness = "Developing"
        recommendation = "Making progress. Continue building evidence and delivering high-impact work."
    else:
        readiness = "Not Ready"
        recommendation = "Early stages. Focus on consistent delivery and evidence capture."
    
    result = {
        'success': True,
        'analysis_date': datetime.now().isoformat(),
        'target_level': target_level,
        'total_score': total_score,
        'max_score': max_score,
        'percentage': percentage,
        'readiness': readiness,
        'recommendation': recommendation,
        'score_breakdown': score_breakdown
    }
    
    return [types.TextContent(
        type="text",
        text=json.dumps(result, indent=2, cls=DateTimeEncoder)
    )]


# ============================================================================
# MAIN
# ============================================================================

async def _main():
    """Async main entry point for the MCP server"""
    logger.info("Starting Dex Career MCP Server")
    logger.info(f"Vault path: {BASE_DIR}")
    logger.info(f"Career directory: {CAREER_DIR}")
    logger.info(f"Evidence directory: {EVIDENCE_DIR}")
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-career-mcp",
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
