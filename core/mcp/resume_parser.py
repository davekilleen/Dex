#!/usr/bin/env python3
"""
Resume Builder Parsing and Formatting Utilities

Provides data structures, validation, and formatting functions
for the Resume Builder MCP server.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, date
from dataclasses import dataclass, field, asdict
from enum import Enum
import json


# ============================================================================
# DATA STRUCTURES
# ============================================================================

class PhaseEnum(str, Enum):
    """Resume building phases"""
    SETUP = "setup"
    ROLES = "roles"
    EXTRACTION = "extraction"
    WRITEUP = "writeup"
    COMPILATION = "compilation"
    LINKEDIN = "linkedin"
    COMPLETE = "complete"


class MetricType(str, Enum):
    """Types of quantifiable metrics"""
    PERCENTAGE = "percentage"
    DOLLAR = "dollar"
    COUNT = "count"
    TIME = "time"
    MULTIPLE = "multiple"


@dataclass
class Metric:
    """A quantifiable metric in an achievement"""
    type: MetricType
    value: str
    context: str
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Achievement:
    """A professional achievement with metrics"""
    description: str
    metrics: List[Metric]
    impact: str
    skills: List[str]
    timeline: Optional[str] = None
    validation_score: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            'description': self.description,
            'metrics': [m.to_dict() for m in self.metrics],
            'impact': self.impact,
            'skills': self.skills,
            'timeline': self.timeline,
            'validation_score': self.validation_score
        }


@dataclass
class Role:
    """A professional role/position"""
    role_id: str
    title: str
    company: str
    start_date: str  # YYYY-MM format
    end_date: str    # YYYY-MM or "present"
    responsibilities: str
    achievements: List[Achievement] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'role_id': self.role_id,
            'title': self.title,
            'company': self.company,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'responsibilities': self.responsibilities,
            'achievements': [a.to_dict() for a in self.achievements]
        }


@dataclass
class Education:
    """Education entry"""
    degree: str
    field: Optional[str]
    school: str
    graduation_year: str
    honors: Optional[str] = None
    gpa: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResumeSession:
    """Resume building session state"""
    session_id: str
    created_at: str
    last_modified: str
    phase: PhaseEnum
    approach: str  # "from_scratch" or "improve_existing"
    roles: List[Role] = field(default_factory=list)
    education: List[Education] = field(default_factory=list)
    skills: Dict[str, List[str]] = field(default_factory=dict)
    target_role: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            'session_id': self.session_id,
            'created_at': self.created_at,
            'last_modified': self.last_modified,
            'phase': self.phase.value,
            'approach': self.approach,
            'roles': [r.to_dict() for r in self.roles],
            'education': [e.to_dict() for e in self.education],
            'skills': self.skills,
            'target_role': self.target_role,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ResumeSession':
        """Reconstruct session from dict"""
        return cls(
            session_id=data['session_id'],
            created_at=data['created_at'],
            last_modified=data['last_modified'],
            phase=PhaseEnum(data['phase']),
            approach=data['approach'],
            roles=[
                Role(
                    role_id=r['role_id'],
                    title=r['title'],
                    company=r['company'],
                    start_date=r['start_date'],
                    end_date=r['end_date'],
                    responsibilities=r['responsibilities'],
                    achievements=[
                        Achievement(
                            description=a['description'],
                            metrics=[Metric(**m) for m in a['metrics']],
                            impact=a['impact'],
                            skills=a['skills'],
                            timeline=a.get('timeline'),
                            validation_score=a.get('validation_score', 0.0)
                        )
                        for a in r['achievements']
                    ]
                )
                for r in data.get('roles', [])
            ],
            education=[Education(**e) for e in data.get('education', [])],
            skills=data.get('skills', {}),
            target_role=data.get('target_role'),
            metadata=data.get('metadata', {})
        )


@dataclass
class ValidationResult:
    """Result of validation check"""
    is_valid: bool
    score: float
    errors: List[str]
    suggestions: List[str]
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QualityScore:
    """Quality score for a bullet point"""
    has_action_verb: float
    has_metrics: float
    has_impact: float
    appropriate_length: float
    overall: float
    
    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_date_format(date_str: str) -> bool:
    """
    Validate date is in YYYY-MM format or "present".
    
    Returns:
        True if valid format
    """
    if date_str.lower() == "present":
        return True
    
    pattern = r'^\d{4}-(0[1-9]|1[0-2])$'
    return bool(re.match(pattern, date_str))


def extract_metrics_from_text(text: str) -> List[Metric]:
    """
    Parse text for quantifiable metrics.
    
    Detects:
    - Percentages: "34%", "increased by 50%"
    - Dollar amounts: "$2.1M", "$180K", "£50K"
    - Counts: "500+ users", "team of 12", "1000 customers"
    - Time: "6 months", "3 weeks", "2 years"
    
    Returns:
        List of Metric objects
    """
    metrics = []
    
    # Percentage pattern
    pct_pattern = r'(\d+(?:\.\d+)?%|\d+(?:\.\d+)?\s*percent)'
    for match in re.finditer(pct_pattern, text, re.IGNORECASE):
        value = match.group(1)
        # Get surrounding context (20 chars before and after)
        start = max(0, match.start() - 20)
        end = min(len(text), match.end() + 20)
        context = text[start:end].strip()
        
        metrics.append(Metric(
            type=MetricType.PERCENTAGE,
            value=value,
            context=context
        ))
    
    # Dollar amount pattern (handles $, £, €, K, M, B suffixes)
    dollar_pattern = r'[\$£€]\s*\d+(?:\.\d+)?[KMB]?(?:\s*(?:thousand|million|billion))?'
    for match in re.finditer(dollar_pattern, text, re.IGNORECASE):
        value = match.group(0)
        start = max(0, match.start() - 20)
        end = min(len(text), match.end() + 20)
        context = text[start:end].strip()
        
        metrics.append(Metric(
            type=MetricType.DOLLAR,
            value=value,
            context=context
        ))
    
    # Count pattern
    count_pattern = r'\d+[\+]?\s*(?:users?|customers?|people|employees?|team members?|projects?|products?|companies?)'
    for match in re.finditer(count_pattern, text, re.IGNORECASE):
        value = match.group(0)
        start = max(0, match.start() - 15)
        end = min(len(text), match.end() + 15)
        context = text[start:end].strip()
        
        metrics.append(Metric(
            type=MetricType.COUNT,
            value=value,
            context=context
        ))
    
    # Time pattern
    time_pattern = r'\d+\s*(?:day|week|month|quarter|year)s?'
    for match in re.finditer(time_pattern, text, re.IGNORECASE):
        value = match.group(0)
        start = max(0, match.start() - 15)
        end = min(len(text), match.end() + 15)
        context = text[start:end].strip()
        
        metrics.append(Metric(
            type=MetricType.TIME,
            value=value,
            context=context
        ))
    
    return metrics


def validate_achievement_metrics(achievement: Achievement) -> ValidationResult:
    """
    Validate that achievement has sufficient quantifiable metrics.
    
    An achievement MUST have at least one metric to be considered valid.
    Higher scores for multiple metrics and diverse metric types.
    
    Returns:
        ValidationResult with score 0-1 and feedback
    """
    errors = []
    suggestions = []
    
    if not achievement.metrics:
        # Try to extract from description and impact
        all_text = f"{achievement.description} {achievement.impact}"
        found_metrics = extract_metrics_from_text(all_text)
        
        if not found_metrics:
            return ValidationResult(
                is_valid=False,
                score=0.0,
                errors=["No quantifiable metrics found"],
                suggestions=[
                    "Add specific numbers or percentages",
                    "Include dollar amounts if applicable",
                    "Specify team sizes or user counts",
                    "Mention timeframes (e.g., 'within 6 months')"
                ]
            )
        
        # Found implicit metrics - suggest making them explicit
        suggestions.append(f"Found {len(found_metrics)} implicit metrics - consider making them more prominent")
    
    # Check diversity of metric types
    metric_types = set(m.type for m in achievement.metrics)
    
    # Scoring
    base_score = 0.5 if achievement.metrics else 0.0
    
    # Add points for number of metrics
    metric_count_bonus = min(0.3, len(achievement.metrics) * 0.1)
    
    # Add points for diversity
    diversity_bonus = min(0.2, len(metric_types) * 0.07)
    
    total_score = base_score + metric_count_bonus + diversity_bonus
    
    # Check for weak metrics
    if len(achievement.metrics) == 1 and achievement.metrics[0].type == MetricType.TIME:
        suggestions.append("Consider adding impact metrics (percentages, dollars, counts) in addition to timeframe")
    
    if total_score < 0.7:
        suggestions.append("Consider adding more quantifiable outcomes for stronger impact")
    
    return ValidationResult(
        is_valid=total_score >= 0.5,
        score=min(1.0, total_score),
        errors=errors,
        suggestions=suggestions
    )


# Strong action verbs categorized
STRONG_ACTION_VERBS = {
    "leadership": ["Led", "Directed", "Managed", "Drove", "Spearheaded", "Orchestrated", "Championed", "Guided"],
    "creation": ["Built", "Designed", "Developed", "Launched", "Created", "Architected", "Established", "Founded"],
    "improvement": ["Optimized", "Enhanced", "Improved", "Streamlined", "Transformed", "Revamped", "Modernized"],
    "achievement": ["Delivered", "Achieved", "Generated", "Increased", "Reduced", "Exceeded", "Accelerated"],
    "analysis": ["Analyzed", "Identified", "Evaluated", "Assessed", "Diagnosed", "Investigated"],
    "collaboration": ["Partnered", "Collaborated", "Coordinated", "Aligned", "Facilitated", "Engaged"]
}

WEAK_VERBS_TO_AVOID = ["helped", "worked on", "assisted", "responsible for", "involved in", "participated in"]

def check_action_verb(bullet_text: str) -> ValidationResult:
    """
    Check if bullet starts with strong action verb.
    
    Returns:
        ValidationResult with feedback
    """
    errors = []
    suggestions = []
    
    # Get first word
    first_word = bullet_text.strip().split()[0] if bullet_text.strip() else ""
    first_word_lower = first_word.lower().rstrip('.,;:')
    
    # Check if it's a weak verb
    if first_word_lower in WEAK_VERBS_TO_AVOID:
        errors.append(f"Weak action verb: '{first_word}'")
        
        # Suggest alternatives based on context
        if first_word_lower in ["helped", "assisted"]:
            suggestions.append("Use stronger verbs like: Led, Supported, Enabled, Drove")
        elif first_word_lower in ["worked on", "responsible for"]:
            suggestions.append("Use stronger verbs like: Built, Delivered, Managed, Owned")
        
        return ValidationResult(
            is_valid=False,
            score=0.3,
            errors=errors,
            suggestions=suggestions
        )
    
    # Check if it's a strong verb
    all_strong_verbs = [verb.lower() for verbs in STRONG_ACTION_VERBS.values() for verb in verbs]
    
    if first_word_lower in all_strong_verbs:
        return ValidationResult(
            is_valid=True,
            score=1.0,
            errors=[],
            suggestions=[]
        )
    
    # Not weak, but not recognized as strong
    suggestions.append("Consider starting with a strong action verb (Led, Built, Drove, etc.)")
    
    return ValidationResult(
        is_valid=True,
        score=0.7,
        errors=[],
        suggestions=suggestions
    )


def calculate_bullet_quality_score(bullet: str) -> QualityScore:
    """
    Calculate comprehensive quality score for a bullet point.
    
    Checks:
    - Has strong action verb (0-1)
    - Has quantifiable metrics (0-1)
    - Has impact statement (0-1)
    - Appropriate length (0-1)
    
    Returns:
        QualityScore object
    """
    # Check action verb
    verb_check = check_action_verb(bullet)
    action_verb_score = verb_check.score
    
    # Check for metrics
    metrics = extract_metrics_from_text(bullet)
    metrics_score = min(1.0, len(metrics) * 0.4) if metrics else 0.0
    
    # Check for impact words
    impact_keywords = [
        'increased', 'reduced', 'improved', 'generated', 'saved',
        'achieved', 'delivered', 'exceeded', 'accelerated', 'grew'
    ]
    has_impact = any(keyword in bullet.lower() for keyword in impact_keywords)
    impact_score = 1.0 if has_impact else 0.5
    
    # Check length (ideal 100-180 characters)
    length = len(bullet)
    if 100 <= length <= 180:
        length_score = 1.0
    elif 80 <= length <= 200:
        length_score = 0.8
    elif length < 80:
        length_score = 0.6  # Too short
    else:
        length_score = 0.5  # Too long
    
    # Calculate overall
    overall = (action_verb_score * 0.25 + 
               metrics_score * 0.35 +
               impact_score * 0.25 +
               length_score * 0.15)
    
    return QualityScore(
        has_action_verb=action_verb_score,
        has_metrics=metrics_score,
        has_impact=impact_score,
        appropriate_length=length_score,
        overall=overall
    )


def suggest_improvements(bullet: str) -> List[str]:
    """
    Suggest specific improvements for a bullet point.
    
    Returns:
        List of actionable suggestions
    """
    suggestions = []
    
    # Check action verb
    verb_check = check_action_verb(bullet)
    if not verb_check.is_valid:
        suggestions.extend(verb_check.suggestions)
    
    # Check metrics
    metrics = extract_metrics_from_text(bullet)
    if not metrics:
        suggestions.append("Add quantifiable metrics (numbers, percentages, dollar amounts)")
    elif len(metrics) == 1:
        suggestions.append("Consider adding additional metrics to show broader impact")
    
    # Check impact
    impact_keywords = ['increased', 'reduced', 'improved', 'generated', 'saved']
    if not any(keyword in bullet.lower() for keyword in impact_keywords):
        suggestions.append("Add an impact statement (how it helped the business/users)")
    
    # Check length
    length = len(bullet)
    if length < 80:
        suggestions.append("Expand with more context or additional impact details")
    elif length > 200:
        suggestions.append("Consider shortening for better readability")
    
    return suggestions


# ============================================================================
# FORMATTING FUNCTIONS
# ============================================================================

def format_role_bullets(role: Role, max_bullets: int = 5) -> List[str]:
    """
    Format achievements into professional bullet points.
    
    Args:
        role: Role object with achievements
        max_bullets: Maximum bullets to generate (default 5)
    
    Returns:
        List of formatted bullet points
    """
    bullets = []
    
    # Sort achievements by validation score
    sorted_achievements = sorted(
        role.achievements,
        key=lambda a: a.validation_score,
        reverse=True
    )
    
    for achievement in sorted_achievements[:max_bullets]:
        # Build bullet from achievement components
        description = achievement.description
        
        # Ensure it starts with action verb
        verb_check = check_action_verb(description)
        if not verb_check.is_valid and achievement.skills:
            # Try to infer action verb from skills
            skill = achievement.skills[0].lower()
            if 'leadership' in skill or 'led' in skill:
                verb = "Led"
            elif 'built' in skill or 'develop' in skill:
                verb = "Developed"
            else:
                verb = "Drove"
            
            # Prepend if description doesn't start with verb
            if not description[0].isupper() or description.split()[0].lower() in WEAK_VERBS_TO_AVOID:
                description = f"{verb} {description.lower()}"
        
        # Add metrics inline if not already present
        metric_text = ""
        if achievement.metrics:
            # Check if metrics are already in description
            has_metrics_inline = any(m.value in description for m in achievement.metrics)
            
            if not has_metrics_inline:
                # Add primary metric
                primary_metric = achievement.metrics[0]
                metric_text = f", {primary_metric.context}"
        
        # Add impact if not redundant
        impact_addition = ""
        if achievement.impact and achievement.impact.lower() not in description.lower():
            impact_addition = f", {achievement.impact}"
        
        # Add timeline if present
        timeline_addition = ""
        if achievement.timeline:
            timeline_addition = f" {achievement.timeline}"
        
        # Construct bullet
        bullet = f"{description}{metric_text}{impact_addition}{timeline_addition}"
        
        # Clean up
        bullet = bullet.strip().rstrip('.')
        
        bullets.append(bullet)
    
    return bullets


def format_date_range(start_date: str, end_date: str) -> str:
    """Format date range for display."""
    # Convert YYYY-MM to Month YYYY
    def format_date(date_str: str) -> str:
        if date_str.lower() == "present":
            return "Present"
        
        try:
            dt = datetime.strptime(date_str, '%Y-%m')
            return dt.strftime('%B %Y')
        except ValueError:
            return date_str
    
    return f"{format_date(start_date)} — {format_date(end_date)}"


def calculate_estimated_pages(text: str) -> float:
    """
    Estimate page count based on character count and structure.
    
    Rough estimate: ~3000 characters per page with standard formatting.
    """
    char_count = len(text)
    estimated_pages = char_count / 3000
    return round(estimated_pages, 1)


def enforce_page_limit(session: ResumeSession, max_pages: int = 2) -> ResumeSession:
    """
    Adjust bullet counts to fit page limit.
    
    Strategy:
    - Most recent role: 5 bullets max
    - 2nd most recent: 4 bullets
    - 3rd most recent: 3 bullets  
    - Older roles: 2 bullets
    
    If still over limit, truncate education and skills.
    """
    # Calculate current estimate
    draft_resume = format_resume(session, enforce_limit=False)
    estimated_pages = calculate_estimated_pages(draft_resume)
    
    if estimated_pages <= max_pages:
        return session  # Already fits
    
    # Adjust bullet counts per role
    bullet_allocations = [5, 4, 3, 2, 2]
    
    for idx, role in enumerate(session.roles):
        max_bullets = bullet_allocations[idx] if idx < len(bullet_allocations) else 2
        
        # Keep only top achievements
        if len(role.achievements) > max_bullets:
            role.achievements = sorted(
                role.achievements,
                key=lambda a: a.validation_score,
                reverse=True
            )[:max_bullets]
    
    # Re-check
    draft_resume = format_resume(session, enforce_limit=False)
    estimated_pages = calculate_estimated_pages(draft_resume)
    
    # If still over, truncate education details
    if estimated_pages > max_pages:
        for edu in session.education:
            edu.honors = None
            edu.gpa = None
    
    return session


def format_resume(session: ResumeSession, enforce_limit: bool = True) -> str:
    """
    Generate complete resume markdown.
    
    Args:
        session: Resume session with all data
        enforce_limit: Whether to enforce 2-page limit
    
    Returns:
        Complete resume in markdown format
    """
    if enforce_limit:
        session = enforce_page_limit(session, max_pages=2)
    
    lines = []
    
    # Header (placeholder - would need user info)
    user_name = session.metadata.get('name', '[Your Name]')
    user_location = session.metadata.get('location', '[City, State]')
    user_email = session.metadata.get('email', '[email@example.com]')
    user_phone = session.metadata.get('phone', '[Phone]')
    user_linkedin = session.metadata.get('linkedin', '[LinkedIn URL]')
    
    lines.append(f"# {user_name}")
    lines.append(f"{user_location} | {user_email} | {user_phone} | {user_linkedin}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Professional Summary (generate if target role specified)
    if session.target_role:
        lines.append("## Professional Summary")
        lines.append("")
        lines.append(f"[2-3 sentences about your experience and fit for {session.target_role}]")
        lines.append("")
        lines.append("---")
        lines.append("")
    
    # Professional Experience
    lines.append("## Professional Experience")
    lines.append("")
    
    for role in session.roles:
        date_range = format_date_range(role.start_date, role.end_date)
        lines.append(f"### {role.title} — {role.company}")
        lines.append(f"**{date_range}**")
        lines.append("")
        
        # Format bullets
        bullets = format_role_bullets(role)
        for bullet in bullets:
            lines.append(f"- {bullet}")
        
        lines.append("")
    
    lines.append("---")
    lines.append("")
    
    # Education
    if session.education:
        lines.append("## Education")
        lines.append("")
        
        for edu in session.education:
            degree_line = f"**{edu.degree}**"
            if edu.field:
                degree_line += f" — {edu.field}"
            lines.append(degree_line)
            
            school_line = f"{edu.school} — {edu.graduation_year}"
            lines.append(school_line)
            
            if edu.honors:
                lines.append(f"*{edu.honors}*")
            
            if edu.gpa:
                lines.append(f"GPA: {edu.gpa}")
            
            lines.append("")
        
        lines.append("---")
        lines.append("")
    
    # Skills
    if session.skills:
        lines.append("## Skills & Expertise")
        lines.append("")
        
        for category, skill_list in session.skills.items():
            skills_str = ", ".join(skill_list)
            lines.append(f"**{category}:** {skills_str}")
        
        lines.append("")
        lines.append("---")
        lines.append("")
    
    lines.append("*Resume optimized for ATS systems and 2-page constraint*")
    
    return "\n".join(lines)


def format_linkedin_headline(session: ResumeSession, max_chars: int = 220) -> str:
    """
    Generate LinkedIn headline.
    
    Format: [Current Role] | [Value Prop] | [Notable Element]
    """
    if not session.roles:
        return ""
    
    current_role = session.roles[0]
    headline = f"{current_role.title}"
    
    # Add value prop from target role or skills
    if session.target_role:
        headline += f" | {session.target_role}"
    elif session.skills:
        top_skill_category = list(session.skills.keys())[0]
        headline += f" | {top_skill_category} Expert"
    
    # Add notable element (company or achievement)
    headline += f" | {current_role.company}"
    
    # Truncate if needed
    if len(headline) > max_chars:
        headline = headline[:max_chars-3] + "..."
    
    return headline


def format_linkedin_about(session: ResumeSession, max_chars: int = 2600) -> str:
    """
    Generate LinkedIn about section.
    
    Format:
    - Para 1: Current role and expertise
    - Para 2: Notable achievements with metrics
    - Para 3: Approach/philosophy
    - Para 4: What drives you
    - Para 5: Call to action
    """
    if not session.roles:
        return ""
    
    paragraphs = []
    
    # Paragraph 1: Current role
    current_role = session.roles[0]
    para1 = f"I'm a {current_role.title} at {current_role.company}, focused on "
    
    if session.skills:
        top_skills = list(session.skills.values())[0][:3]
        para1 += f"{', '.join(top_skills).lower()}."
    else:
        para1 += f"{current_role.responsibilities[:100]}..."
    
    paragraphs.append(para1)
    
    # Paragraph 2: Achievements (pick top 3 across all roles)
    all_achievements = []
    for role in session.roles[:3]:  # Top 3 roles
        all_achievements.extend(role.achievements[:2])  # Top 2 achievements each
    
    if all_achievements:
        sorted_achievements = sorted(all_achievements, key=lambda a: a.validation_score, reverse=True)[:3]
        
        para2 = "Over my career, I've "
        achievement_texts = []
        for ach in sorted_achievements:
            # Extract key metric
            if ach.metrics:
                metric = ach.metrics[0]
                achievement_texts.append(f"{ach.description} ({metric.value})")
        
        para2 += ", ".join(achievement_texts) + "."
        paragraphs.append(para2)
    
    # Paragraph 3: Approach (template - would ideally be personalized)
    para3 = "My approach combines data-driven decision making with user-centric design. I believe the best products come from deep understanding of customer needs and cross-functional collaboration."
    paragraphs.append(para3)
    
    # Paragraph 4: What drives you (template)
    para4 = "What excites me most is solving complex problems that have real impact on users and businesses."
    paragraphs.append(para4)
    
    # Paragraph 5: CTA
    para5 = f"Let's connect if you're interested in {session.target_role or 'collaborating'}."
    paragraphs.append(para5)
    
    about = "\n\n".join(paragraphs)
    
    # Truncate if needed
    if len(about) > max_chars:
        about = about[:max_chars-3] + "..."
    
    return about


def format_linkedin_experience(role: Role) -> str:
    """
    Format role for LinkedIn (more detailed than resume).
    """
    lines = []
    
    # Opening sentence about the role
    lines.append(f"{role.responsibilities}")
    lines.append("")
    lines.append("**Key Achievements:**")
    
    # Use more bullets than resume (can be longer on LinkedIn)
    bullets = format_role_bullets(role, max_bullets=7)
    for bullet in bullets:
        lines.append(f"- {bullet}")
    
    return "\n".join(lines)


# ============================================================================
# CAREER EVIDENCE INTEGRATION
# ============================================================================

def find_relevant_evidence(
    evidence_dir: Path,
    role_start: str,
    role_end: str,
    company: str
) -> List[Dict]:
    """
    Find career evidence files matching role timeframe and company.
    
    Args:
        evidence_dir: Path to 05-Areas/Career/Evidence/
        role_start: Role start date (YYYY-MM)
        role_end: Role end date (YYYY-MM or "present")
        company: Company name
    
    Returns:
        List of relevant evidence file data
    """
    from career_parser import scan_evidence_directory, parse_date_range
    
    if not evidence_dir.exists():
        return []
    
    # Convert role dates to date range
    try:
        start_date = datetime.strptime(role_start, '%Y-%m').date()
        
        if role_end.lower() == "present":
            end_date = date.today()
        else:
            end_date = datetime.strptime(role_end, '%Y-%m').date()
        
        date_range = (start_date, end_date)
    except ValueError:
        return []
    
    # Scan evidence with date filter
    all_evidence = scan_evidence_directory(evidence_dir, date_range)
    
    # Further filter by company if mentioned in evidence
    relevant = []
    for evidence in all_evidence:
        # Check if company name appears in the evidence
        evidence_text = f"{evidence.get('title', '')} {evidence.get('project', '')}"
        if company.lower() in evidence_text.lower():
            relevant.append(evidence)
        else:
            # Include anyway if in date range (might be relevant)
            relevant.append(evidence)
    
    return relevant


def map_evidence_to_achievement(evidence: Dict) -> Achievement:
    """
    Convert career evidence file to Achievement object.
    
    Args:
        evidence: Parsed evidence dict from career_parser
    
    Returns:
        Achievement object
    """
    description = evidence.get('title', 'Untitled Achievement')
    impact_list = evidence.get('impact', [])
    impact = " | ".join(impact_list) if impact_list else ""
    skills = evidence.get('skills', [])
    
    # Extract metrics from impact statements
    all_text = f"{description} {impact}"
    metrics = extract_metrics_from_text(all_text)
    
    achievement = Achievement(
        description=description,
        metrics=metrics,
        impact=impact,
        skills=skills,
        timeline=None,
        validation_score=0.0
    )
    
    # Calculate validation score
    validation = validate_achievement_metrics(achievement)
    achievement.validation_score = validation.score
    
    return achievement


# ============================================================================
# ATS OPTIMIZATION
# ============================================================================

def calculate_ats_score(resume_text: str, target_keywords: List[str]) -> float:
    """
    Calculate ATS (Applicant Tracking System) optimization score.
    
    Checks:
    - Keyword presence
    - Standard section headers
    - No graphics/tables (already markdown, so OK)
    - Clean formatting
    
    Returns:
        Score 0-1
    """
    score = 0.0
    
    # Check keyword presence (0-0.4)
    if target_keywords:
        keywords_found = sum(1 for kw in target_keywords if kw.lower() in resume_text.lower())
        keyword_score = (keywords_found / len(target_keywords)) * 0.4
        score += keyword_score
    else:
        score += 0.4  # No keywords to check
    
    # Check standard headers (0-0.3)
    required_headers = ['Experience', 'Education', 'Skills']
    headers_found = sum(1 for header in required_headers if header in resume_text)
    header_score = (headers_found / len(required_headers)) * 0.3
    score += header_score
    
    # Check for clean formatting (0-0.3)
    # Penalize if too many special characters
    special_char_ratio = sum(1 for c in resume_text if not c.isalnum() and not c.isspace()) / len(resume_text)
    if special_char_ratio < 0.15:
        score += 0.3
    elif special_char_ratio < 0.25:
        score += 0.2
    else:
        score += 0.1
    
    return round(score, 2)
