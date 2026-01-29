#!/usr/bin/env python3
"""
MCP Server for Dex Improvements Backlog System

Provides tools for capturing and managing Dex system improvement ideas with:
- Quick capture from any context
- Idea storage with metadata
- List and filter capabilities
- Implementation tracking
"""

import os
import sys
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime, date
from difflib import SequenceMatcher

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
BACKLOG_FILE = BASE_DIR / 'System' / 'Dex_Backlog.md'
SYSTEM_DIR = BASE_DIR / 'System'

# Valid categories for ideas
CATEGORIES = [
    'workflows',      # daily/weekly/quarterly routines
    'automation',     # scripts, hooks, MCP
    'relationships',  # people, companies, meetings
    'tasks',          # capture, management, prioritization
    'projects',       # tracking, health, planning
    'knowledge',      # capture, synthesis, retrieval
    'system'          # configuration, structure, tooling
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
    """Find ideas similar to the given title/description"""
    if not BACKLOG_FILE.exists():
        return []
    
    similar = []
    ideas = parse_backlog_file()
    
    for idea in ideas:
        title_similarity = calculate_similarity(title, idea['title'])
        desc_similarity = calculate_similarity(description, idea.get('description', ''))
        
        # Combined score (title weighted more heavily)
        similarity_score = (title_similarity * 0.7) + (desc_similarity * 0.3)
        
        if similarity_score >= 0.6:
            similar.append({
                'id': idea['id'],
                'title': idea['title'],
                'similarity': round(similarity_score, 2)
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
    """Add a new idea to the Dex backlog file"""
    if not BACKLOG_FILE.exists():
        initialize_backlog_file()
    
    content = BACKLOG_FILE.read_text()
    
    # Create the idea entry
    captured_date = datetime.now().strftime('%Y-%m-%d')
    
    idea_entry = f"""- **[{idea_id}]** {title}
  - **Score:** 0 (not yet ranked - run `/dex-backlog` to calculate)
  - **Category:** {category}
  - **Captured:** {captured_date}
  - **Description:** {description}

"""
    
    # Find the "Low Priority" section and add the idea there
    # Ideas start unranked and get scored during review
    low_priority_pattern = r'(### 💡 Low Priority \(Score: <60\)\s*\n\s*(?:\*.*?\*\s*\n\s*)?)'
    
    match = re.search(low_priority_pattern, content)
    if match:
        insert_pos = match.end()
        new_content = content[:insert_pos] + '\n' + idea_entry + content[insert_pos:]
    else:
        # Fallback: add before Archive section
        archive_pattern = r'(## Archive \(Implemented\))'
        match = re.search(archive_pattern, content)
        if match:
            insert_pos = match.start()
            new_content = content[:insert_pos] + idea_entry + '\n' + content[insert_pos:]
        else:
            # Last resort: append to end
            new_content = content + '\n' + idea_entry
    
    BACKLOG_FILE.write_text(new_content)
    return True

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
        )
    ]

@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    
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
                "message": f"Idea captured successfully! Run `/dex-backlog` to see it ranked against other ideas.",
                "next_steps": [
                    "Run `/dex-backlog` to see AI-powered ranking",
                    "Run `/dex-improve \"{title}\"` to workshop this idea",
                    "Check `System/Dex_Backlog.md` to see all your ideas"
                ]
            }
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
            "note": "Run `/dex-backlog` to update scores based on current system state"
        }
        
        return [types.TextContent(type="text", text=json.dumps(result, indent=2, cls=DateTimeEncoder))]
    
    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

async def _main():
    """Async main entry point for the MCP server"""
    logger.info(f"Starting Dex Improvements MCP Server")
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
