#!/usr/bin/env python3
"""
Career Evidence and Ladder Parsing Utilities

Provides functions for parsing career evidence files and career ladder documents
into structured data for the Career MCP server.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date
from collections import defaultdict


# ============================================================================
# DATE PARSING
# ============================================================================

def extract_date_from_filename(filename: str) -> Optional[str]:
    """
    Extract date from filename in format YYYY-MM-DD.
    
    Examples:
        "2025-12-15 - Led API Migration.md" -> "2025-12-15"
        "Some file without date.md" -> None
    """
    match = re.match(r'^(\d{4}-\d{2}-\d{2})', filename)
    return match.group(1) if match else None


def parse_date_range(date_range: str) -> Tuple[Optional[date], Optional[date]]:
    """
    Parse various date range formats.
    
    Supported formats:
        - "2025-Q4" -> Q4 dates
        - "2025-01-01:2025-12-31" -> explicit range
        - "last-90-days" -> last 90 days from today
        - "last-6-months" -> last 6 months
        - "last-12-months" -> last 12 months
        - "2025" -> entire year
    
    Returns:
        (start_date, end_date) or (None, None) if invalid
    """
    today = date.today()
    
    # Handle "last-N-days"
    if match := re.match(r'last-(\d+)-days?', date_range):
        days = int(match.group(1))
        from datetime import timedelta
        return (today - timedelta(days=days), today)
    
    # Handle "last-N-months"
    if match := re.match(r'last-(\d+)-months?', date_range):
        months = int(match.group(1))
        from datetime import timedelta
        # Approximate: 30 days per month
        return (today - timedelta(days=months*30), today)
    
    # Handle "YYYY-QN"
    if match := re.match(r'(\d{4})-Q([1-4])', date_range):
        year = int(match.group(1))
        quarter = int(match.group(2))
        start_month = (quarter - 1) * 3 + 1
        end_month = quarter * 3
        start_date = date(year, start_month, 1)
        # Last day of quarter
        if end_month == 12:
            end_date = date(year, 12, 31)
        else:
            from datetime import timedelta
            end_date = date(year, end_month + 1, 1) - timedelta(days=1)
        return (start_date, end_date)
    
    # Handle "YYYY"
    if re.match(r'^\d{4}$', date_range):
        year = int(date_range)
        return (date(year, 1, 1), date(year, 12, 31))
    
    # Handle "YYYY-MM-DD:YYYY-MM-DD"
    if ':' in date_range:
        parts = date_range.split(':')
        if len(parts) == 2:
            try:
                start = datetime.strptime(parts[0].strip(), '%Y-%m-%d').date()
                end = datetime.strptime(parts[1].strip(), '%Y-%m-%d').date()
                return (start, end)
            except ValueError:
                return (None, None)
    
    return (None, None)


def get_quarter_label(date_obj: date) -> str:
    """Get quarter label like '2025-Q4' for a date."""
    quarter = (date_obj.month - 1) // 3 + 1
    return f"{date_obj.year}-Q{quarter}"


# ============================================================================
# MARKDOWN SECTION EXTRACTION
# ============================================================================

def extract_title(content: str) -> str:
    """
    Extract title from markdown (first # heading or filename-derived).
    """
    lines = content.split('\n')
    for line in lines:
        if line.startswith('# '):
            return line.lstrip('#').strip()
    return "Untitled"


def extract_field(content: str, field_name: str, subfield: Optional[str] = None) -> str:
    """
    Extract a field value from markdown.
    
    Supports formats:
        - **Field Name:** value
        - | **Field Name** | value |
    
    Args:
        content: Markdown content
        field_name: Field to extract (e.g., "Date", "Project", "Current Level")
        subfield: Optional subfield (e.g., "Maps to" in "**Maps to:** value")
    
    Returns:
        Field value or empty string
    """
    # Try bold field format: **Field:** value
    if subfield:
        pattern = rf'\*\*{re.escape(subfield)}:\*\*\s*(.+?)(?:\n|$)'
    else:
        pattern = rf'\*\*{re.escape(field_name)}:\*\*\s*(.+?)(?:\n|$)'
    
    match = re.search(pattern, content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    # Try table format: | **Field** | value |
    pattern = rf'\|\s*\*\*{re.escape(field_name)}\*\*\s*\|\s*(.+?)\s*\|'
    match = re.search(pattern, content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    return ""


def extract_section(content: str, heading: str) -> str:
    """
    Extract content of a markdown section.
    
    Args:
        content: Full markdown content
        heading: Section heading (e.g., "## What I Did")
    
    Returns:
        Section content (everything between this heading and next same-level heading)
    """
    # Escape special regex characters in heading
    escaped_heading = re.escape(heading)
    
    # Determine heading level (count #)
    heading_level = len(re.match(r'^#+', heading).group(0)) if heading.startswith('#') else 2
    
    # Pattern: find this heading, capture until next same-or-higher-level heading
    next_heading_pattern = rf'^#{{{1},{heading_level}}}[^#]'
    
    lines = content.split('\n')
    in_section = False
    section_lines = []
    
    for line in lines:
        if re.match(escaped_heading, line, re.IGNORECASE):
            in_section = True
            continue
        
        if in_section:
            # Check if we hit next section
            if re.match(next_heading_pattern, line):
                break
            section_lines.append(line)
    
    return '\n'.join(section_lines).strip()


def extract_section_list(content: str, section_name: str) -> List[str]:
    """
    Extract bullet list from a section.
    
    Args:
        content: Markdown content
        section_name: Section heading (e.g., "Skills Demonstrated")
    
    Returns:
        List of bullet items (cleaned)
    """
    # Try to find section by heading
    section_pattern = rf'##\s+{re.escape(section_name)}\s*\n(.*?)(?=\n##|\n---|\Z)'
    match = re.search(section_pattern, content, re.DOTALL | re.IGNORECASE)
    
    if not match:
        return []
    
    section_content = match.group(1)
    
    # Extract bullet items
    items = []
    for line in section_content.split('\n'):
        line = line.strip()
        if line.startswith('- '):
            # Remove bullet marker and clean
            item = line[2:].strip()
            # Remove checkbox markers if present
            item = re.sub(r'^\[[ x]\]\s*', '', item)
            # Remove markdown links but keep text
            item = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', item)
            if item and not item.startswith('['):  # Skip placeholders
                items.append(item)
    
    return items


def extract_section_value(content: str, section_name: str, field: Optional[str] = None) -> str:
    """
    Extract a single value from a section.
    
    Useful for sections with a single field like:
        ## Project
        Platform Modernization
    
    Or:
        ## Ladder Alignment
        **Maps to:** Technical Depth
    """
    section_pattern = rf'##\s+{re.escape(section_name)}\s*\n(.*?)(?=\n##|\n---|\Z)'
    match = re.search(section_pattern, content, re.DOTALL | re.IGNORECASE)
    
    if not match:
        return ""
    
    section_content = match.group(1).strip()
    
    # If looking for a specific field within the section
    if field:
        field_match = re.search(rf'\*\*{re.escape(field)}:\*\*\s*(.+?)(?:\n|$)', section_content)
        if field_match:
            return field_match.group(1).strip()
    
    # Otherwise return first non-empty line
    for line in section_content.split('\n'):
        line = line.strip()
        if line and not line.startswith('**') and not line.startswith('['):
            return line
    
    return ""


def find_competency_headings(content: str, level: int = 3) -> List[str]:
    """
    Find all headings at a specific level (default ### for competencies).
    
    Returns:
        List of heading text (without ### markers)
    """
    pattern = rf'^{"#" * level}\s+(.+?)$'
    headings = []
    
    for line in content.split('\n'):
        match = re.match(pattern, line)
        if match:
            heading = match.group(1).strip()
            # Skip common non-competency headings
            if heading not in ['Notes', 'References', 'Appendix']:
                headings.append(heading)
    
    return headings


def extract_bullet_list_under_heading(content: str, heading: str) -> List[str]:
    """
    Extract bullet list that appears under a specific heading.
    """
    # Find the heading
    heading_pattern = rf'###\s+{re.escape(heading)}\s*\n(.*?)(?=\n###|\n##|\Z)'
    match = re.search(heading_pattern, content, re.DOTALL)
    
    if not match:
        return []
    
    section = match.group(1)
    
    items = []
    for line in section.split('\n'):
        line = line.strip()
        if line.startswith('- '):
            item = line[2:].strip()
            if item:
                items.append(item)
    
    return items


# ============================================================================
# EVIDENCE FILE PARSING
# ============================================================================

def parse_evidence_file(filepath: Path) -> Dict[str, Any]:
    """
    Parse a career evidence file and extract structured fields.
    
    Handles both template-conforming files and free-form content.
    
    Returns:
        Dict with extracted fields or empty/partial dict if parsing fails
    """
    try:
        content = filepath.read_text()
    except Exception as e:
        return {
            "filepath": str(filepath),
            "error": f"Failed to read file: {e}",
            "date": None,
            "title": filepath.stem
        }
    
    # Extract date from filename
    file_date = extract_date_from_filename(filepath.name)
    
    # Extract title
    title = extract_title(content)
    if title == "Untitled":
        # Try to extract from filename (after date)
        name_parts = filepath.stem.split(' - ', 1)
        if len(name_parts) > 1:
            title = name_parts[1]
        else:
            title = filepath.stem
    
    # Determine category from folder structure
    category = None
    if 'Achievements' in str(filepath):
        category = 'Achievements'
    elif 'Feedback_Received' in str(filepath):
        category = 'Feedback_Received'
    elif 'Skills_Development' in str(filepath):
        category = 'Skills_Development'
    
    # Extract structured fields (gracefully handle missing sections)
    result = {
        "filepath": str(filepath.relative_to(filepath.parents[5])) if len(filepath.parents) > 5 else str(filepath),
        "date": file_date,
        "title": title,
        "category": category or extract_field(content, "Category"),
        "project": extract_section_value(content, "Project"),
        "skills": extract_section_list(content, "Skills Demonstrated"),
        "impact": extract_section_list(content, "Impact"),
        "stakeholders": extract_section_list(content, "Stakeholders"),
        "ladder_alignment": extract_section_value(content, "Ladder Alignment", "Maps to"),
        "last_modified": datetime.fromtimestamp(filepath.stat().st_mtime).isoformat(),
    }
    
    # For feedback files, extract positive and constructive feedback
    if category == 'Feedback_Received':
        result["positive_feedback"] = extract_section_list(content, "Positive Feedback")
        result["constructive_feedback"] = extract_section_list(content, "Constructive Feedback")
    
    return result


def scan_evidence_directory(evidence_dir: Path, date_range: Optional[Tuple[date, date]] = None, 
                            category: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Scan evidence directory and parse all files.
    
    Args:
        evidence_dir: Path to 05-Areas/Career/Evidence/
        date_range: Optional (start_date, end_date) tuple to filter
        category: Optional category filter (Achievements, Feedback_Received, etc.)
    
    Returns:
        List of parsed evidence dicts
    """
    if not evidence_dir.exists():
        return []
    
    evidence_files = []
    
    # Scan all subdirectories
    for md_file in evidence_dir.rglob('*.md'):
        # Skip README files
        if md_file.name.lower() == 'readme.md':
            continue
        
        parsed = parse_evidence_file(md_file)
        
        # Apply category filter
        if category and parsed.get('category') != category:
            continue
        
        # Apply date filter
        if date_range and parsed.get('date'):
            try:
                file_date = datetime.strptime(parsed['date'], '%Y-%m-%d').date()
                start, end = date_range
                if start and file_date < start:
                    continue
                if end and file_date > end:
                    continue
            except ValueError:
                pass  # Include files with unparseable dates
        
        evidence_files.append(parsed)
    
    # Sort by date (newest first)
    evidence_files.sort(key=lambda x: x.get('date') or '', reverse=True)
    
    return evidence_files


# ============================================================================
# LADDER FILE PARSING
# ============================================================================

def parse_ladder_file(filepath: Path) -> Dict[str, Any]:
    """
    Parse career ladder markdown and extract competency structure.
    
    Returns:
        Dict with ladder metadata and competencies
    """
    if not filepath.exists():
        return {
            "error": f"Ladder file not found: {filepath}",
            "filepath": str(filepath),
            "competencies": []
        }
    
    try:
        content = filepath.read_text()
    except Exception as e:
        return {
            "error": f"Failed to read ladder file: {e}",
            "filepath": str(filepath),
            "competencies": []
        }
    
    # Extract metadata
    company = extract_field(content, "Company")
    current_level = extract_field(content, "Current Level")
    target_level = extract_field(content, "Target Level")
    last_updated = extract_field(content, "Last Updated")
    
    # Find target level section
    target_section_heading = f"## Target Level: {target_level}" if target_level else "## Target Level"
    target_section = extract_section(content, target_section_heading)
    
    # Parse competencies (### headings under target level)
    competencies = []
    comp_names = find_competency_headings(target_section, level=3)
    
    for comp_name in comp_names:
        requirements = extract_bullet_list_under_heading(target_section, comp_name)
        
        if requirements:  # Only include competencies with requirements
            competencies.append({
                "category": comp_name,
                "target_level_requirements": requirements
            })
    
    return {
        "filepath": str(filepath),
        "company": company,
        "current_level": current_level,
        "target_level": target_level,
        "last_updated": last_updated,
        "competencies": competencies,
        "competency_count": len(competencies)
    }


# ============================================================================
# COMPETENCY MATCHING
# ============================================================================

def extract_keywords(text: str) -> set:
    """Extract meaningful keywords from text (lowercased)."""
    # Simple keyword extraction (can be enhanced)
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                  'with', 'from', 'by', 'as', 'is', 'was', 'are', 'were', 'been', 'be'}
    words = re.findall(r'\b\w+\b', text.lower())
    return {w for w in words if w not in stop_words and len(w) > 2}


def match_evidence_to_competency(
    evidence_skills: List[str],
    evidence_alignment: str,
    competency_name: str
) -> float:
    """
    Calculate match score between evidence and competency.
    
    Returns:
        0-1 score. Uses explicit alignment + keyword overlap.
    """
    # Check explicit ladder alignment first
    if competency_name.lower() in evidence_alignment.lower():
        return 1.0
    
    # Check if any skill mentions the competency
    competency_lower = competency_name.lower()
    for skill in evidence_skills:
        if competency_lower in skill.lower() or skill.lower() in competency_lower:
            return 0.8
    
    # Check keyword overlap
    competency_keywords = extract_keywords(competency_name)
    if not competency_keywords:
        return 0.0
    
    skills_text = ' '.join(evidence_skills).lower()
    skills_keywords = extract_keywords(skills_text)
    
    if not skills_keywords:
        return 0.0
    
    overlap = len(competency_keywords & skills_keywords)
    if overlap > 0:
        # Score based on proportion of competency keywords matched
        return min(0.6, overlap / len(competency_keywords))
    
    return 0.0


def analyze_competency_coverage(
    evidence_files: List[Dict[str, Any]],
    competencies: List[Dict[str, Any]],
    threshold: float = 0.5
) -> Dict[str, Any]:
    """
    Map evidence to competencies and calculate coverage.
    
    Args:
        evidence_files: List of parsed evidence dicts
        competencies: List of competency dicts from ladder
        threshold: Minimum match score to count as evidence (default 0.5)
    
    Returns:
        Coverage analysis dict
    """
    coverage = []
    
    for comp in competencies:
        comp_name = comp['category']
        matched_evidence = []
        skills_mentioned = set()
        
        for evidence in evidence_files:
            score = match_evidence_to_competency(
                evidence.get('skills', []),
                evidence.get('ladder_alignment', ''),
                comp_name
            )
            
            if score >= threshold:
                matched_evidence.append({
                    'filepath': evidence['filepath'],
                    'title': evidence['title'],
                    'date': evidence.get('date'),
                    'match_score': round(score, 2)
                })
                
                # Track which skills were mentioned
                skills_mentioned.update(evidence.get('skills', []))
        
        # Sort by match score and date
        matched_evidence.sort(key=lambda x: (x['match_score'], x['date'] or ''), reverse=True)
        
        # Determine coverage level
        count = len(matched_evidence)
        if count >= 5:
            level = "strong"
        elif count >= 2:
            level = "moderate"
        elif count == 1:
            level = "weak"
        else:
            level = "none"
        
        coverage.append({
            "competency": comp_name,
            "evidence_count": count,
            "coverage_level": level,
            "example_files": [e['title'] for e in matched_evidence[:3]],  # Top 3
            "skills_mentioned": list(skills_mentioned)[:5],  # Top 5
            "all_evidence": matched_evidence
        })
    
    # Calculate overall stats
    by_level = defaultdict(int)
    for c in coverage:
        by_level[c['coverage_level']] += 1
    
    under_documented = [c['competency'] for c in coverage if c['coverage_level'] in ['weak', 'none']]
    well_documented = [c['competency'] for c in coverage if c['coverage_level'] == 'strong']
    
    return {
        "coverage_by_competency": coverage,
        "overall_coverage": dict(by_level),
        "under_documented": under_documented,
        "well_documented": well_documented,
        "total_evidence_files": len(evidence_files)
    }


# ============================================================================
# TIMELINE ANALYSIS
# ============================================================================

def group_evidence_by_period(evidence_files: List[Dict[str, Any]], 
                             group_by: str = "quarter") -> List[Dict[str, Any]]:
    """
    Group evidence files by time period.
    
    Args:
        evidence_files: List of parsed evidence
        group_by: "month", "quarter", or "year"
    
    Returns:
        List of period dicts with counts
    """
    periods = defaultdict(lambda: {"count": 0, "categories": defaultdict(int), "files": []})
    
    for evidence in evidence_files:
        if not evidence.get('date'):
            continue
        
        try:
            file_date = datetime.strptime(evidence['date'], '%Y-%m-%d').date()
        except ValueError:
            continue
        
        # Determine period label
        if group_by == "month":
            period = file_date.strftime('%Y-%m')
        elif group_by == "quarter":
            period = get_quarter_label(file_date)
        else:  # year
            period = str(file_date.year)
        
        periods[period]["count"] += 1
        category = evidence.get('category', 'Other')
        periods[period]["categories"][category] += 1
        periods[period]["files"].append(evidence)
    
    # Convert to sorted list
    result = []
    for period, data in sorted(periods.items()):
        result.append({
            "period": period,
            "count": data["count"],
            "categories": dict(data["categories"]),
            "files": data["files"]
        })
    
    return result


def calculate_growth_velocity(period_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calculate evidence accumulation velocity.
    
    Returns:
        Dict with average and trend
    """
    if not period_data:
        return {"average_monthly": 0, "trend": "no_data"}
    
    counts = [p["count"] for p in period_data]
    average = sum(counts) / len(counts)
    
    # Simple trend: compare first half vs second half
    if len(counts) >= 4:
        mid = len(counts) // 2
        first_half_avg = sum(counts[:mid]) / mid
        second_half_avg = sum(counts[mid:]) / (len(counts) - mid)
        
        if second_half_avg > first_half_avg * 1.2:
            trend = "accelerating"
        elif second_half_avg < first_half_avg * 0.8:
            trend = "decelerating"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"
    
    return {
        "average_monthly": round(average, 1),
        "trend": trend
    }


def find_stale_competencies(evidence_files: List[Dict[str, Any]], 
                            competencies: List[Dict[str, Any]],
                            threshold_days: int = 90) -> List[Dict[str, Any]]:
    """
    Find competencies with no recent evidence.
    
    Returns:
        List of staleness flags
    """
    from datetime import timedelta
    today = date.today()
    
    # Track latest evidence date per competency
    latest_by_comp = {}
    
    for evidence in evidence_files:
        if not evidence.get('date'):
            continue
        
        try:
            file_date = datetime.strptime(evidence['date'], '%Y-%m-%d').date()
        except ValueError:
            continue
        
        # Check which competencies this evidence matches
        for comp in competencies:
            comp_name = comp['category']
            score = match_evidence_to_competency(
                evidence.get('skills', []),
                evidence.get('ladder_alignment', ''),
                comp_name
            )
            
            if score >= 0.5:
                if comp_name not in latest_by_comp or file_date > latest_by_comp[comp_name]:
                    latest_by_comp[comp_name] = file_date
    
    # Find stale competencies
    stale = []
    for comp in competencies:
        comp_name = comp['category']
        
        if comp_name not in latest_by_comp:
            stale.append({
                "competency": comp_name,
                "last_evidence_date": None,
                "days_since": None,
                "note": "No evidence found"
            })
        else:
            last_date = latest_by_comp[comp_name]
            days_since = (today - last_date).days
            
            if days_since > threshold_days:
                stale.append({
                    "competency": comp_name,
                    "last_evidence_date": last_date.isoformat(),
                    "days_since": days_since,
                    "note": f"No recent evidence in {days_since} days"
                })
    
    return stale
