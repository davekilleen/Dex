"""Fixture tests for career_parser — pure text parsing, previously 8% covered.

Run with: pytest core/mcp/tests/test_career_parser.py -v
"""

import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core" / "mcp"))

import career_parser  # noqa: E402

EVIDENCE_MD = """# Led API Migration

## Project
Platform Modernization

## Skills Demonstrated
- System Design
- [x] Stakeholder Management
- [Cross-team collaboration](https://example.com/doc)

## Impact
- Cut deploy time by 40%

## Stakeholders
- Jane Roe

## Ladder Alignment
**Maps to:** Technical Depth
"""

LADDER_MD = """# Career Ladder

**Company:** Acme Corp
**Current Level:** Senior
**Target Level:** Staff
**Last Updated:** 2026-01-15

## Target Level: Staff

### Technical Depth
- Designs systems spanning multiple teams
- Sets technical direction

### Influence
- Mentors senior engineers

### Notes
- not a competency
"""


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def test_extract_date_from_filename():
    assert career_parser.extract_date_from_filename("2025-12-15 - Led API Migration.md") == "2025-12-15"
    assert career_parser.extract_date_from_filename("No date here.md") is None


def test_parse_date_range_quarter():
    assert career_parser.parse_date_range("2025-Q4") == (date(2025, 10, 1), date(2025, 12, 31))
    assert career_parser.parse_date_range("2025-Q1") == (date(2025, 1, 1), date(2025, 3, 31))


def test_parse_date_range_year_and_explicit():
    assert career_parser.parse_date_range("2025") == (date(2025, 1, 1), date(2025, 12, 31))
    assert career_parser.parse_date_range("2025-01-01:2025-06-30") == (date(2025, 1, 1), date(2025, 6, 30))


def test_parse_date_range_relative():
    start, end = career_parser.parse_date_range("last-90-days")
    assert end == date.today()
    assert (end - start).days == 90


def test_parse_date_range_invalid_returns_none_pair():
    assert career_parser.parse_date_range("not-a-range") == (None, None)
    assert career_parser.parse_date_range("2025-01-01:bogus") == (None, None)


def test_get_quarter_label():
    assert career_parser.get_quarter_label(date(2026, 7, 7)) == "2026-Q3"
    assert career_parser.get_quarter_label(date(2026, 1, 1)) == "2026-Q1"


# ---------------------------------------------------------------------------
# Markdown extraction
# ---------------------------------------------------------------------------


def test_extract_title():
    assert career_parser.extract_title(EVIDENCE_MD) == "Led API Migration"
    assert career_parser.extract_title("no heading") == "Untitled"


def test_extract_field_bold_and_table_formats():
    assert career_parser.extract_field(LADDER_MD, "Current Level") == "Senior"
    table_md = "| **Company** | Acme Corp |\n"
    assert career_parser.extract_field(table_md, "Company") == "Acme Corp"
    assert career_parser.extract_field(table_md, "Missing") == ""


def test_extract_section_list_cleans_markers_and_links():
    skills = career_parser.extract_section_list(EVIDENCE_MD, "Skills Demonstrated")
    assert skills == ["System Design", "Stakeholder Management", "Cross-team collaboration"]
    assert career_parser.extract_section_list(EVIDENCE_MD, "Nonexistent") == []


def test_extract_section_value_plain_and_field():
    assert career_parser.extract_section_value(EVIDENCE_MD, "Project") == "Platform Modernization"
    assert career_parser.extract_section_value(EVIDENCE_MD, "Ladder Alignment", "Maps to") == "Technical Depth"


def test_find_competency_headings_skips_notes():
    headings = career_parser.find_competency_headings(LADDER_MD)
    assert "Technical Depth" in headings
    assert "Influence" in headings
    assert "Notes" not in headings


def test_extract_bullet_list_under_heading():
    bullets = career_parser.extract_bullet_list_under_heading(LADDER_MD, "Technical Depth")
    assert bullets == ["Designs systems spanning multiple teams", "Sets technical direction"]


# ---------------------------------------------------------------------------
# File-level parsing
# ---------------------------------------------------------------------------


def test_parse_evidence_file_full_template(tmp_path):
    evidence_dir = tmp_path / "Career/Evidence/Achievements"
    evidence_dir.mkdir(parents=True)
    f = evidence_dir / "2025-12-15 - Led API Migration.md"
    f.write_text(EVIDENCE_MD)

    parsed = career_parser.parse_evidence_file(f)

    assert parsed["date"] == "2025-12-15"
    assert parsed["title"] == "Led API Migration"
    assert parsed["category"] == "Achievements"
    assert parsed["project"] == "Platform Modernization"
    assert parsed["ladder_alignment"] == "Technical Depth"
    assert "System Design" in parsed["skills"]
    assert parsed["impact"] == ["Cut deploy time by 40%"]


def test_scan_evidence_directory_filters_and_sorts(tmp_path):
    achievements = tmp_path / "Evidence/Achievements"
    feedback = tmp_path / "Evidence/Feedback_Received"
    achievements.mkdir(parents=True)
    feedback.mkdir(parents=True)
    (achievements / "2025-10-01 - Old win.md").write_text("# Old win\n")
    (achievements / "2025-12-15 - New win.md").write_text("# New win\n")
    (feedback / "2025-11-01 - Manager praise.md").write_text("# Manager praise\n")
    (achievements / "README.md").write_text("# ignore me\n")

    all_files = career_parser.scan_evidence_directory(tmp_path / "Evidence")
    assert [e["title"] for e in all_files] == ["New win", "Manager praise", "Old win"]

    only_achievements = career_parser.scan_evidence_directory(
        tmp_path / "Evidence", category="Achievements"
    )
    assert {e["title"] for e in only_achievements} == {"Old win", "New win"}

    q4_only = career_parser.scan_evidence_directory(
        tmp_path / "Evidence", date_range=(date(2025, 12, 1), date(2025, 12, 31))
    )
    assert [e["title"] for e in q4_only] == ["New win"]

    assert career_parser.scan_evidence_directory(tmp_path / "nope") == []


def test_parse_ladder_file(tmp_path):
    ladder = tmp_path / "Career_Ladder.md"
    ladder.write_text(LADDER_MD)

    parsed = career_parser.parse_ladder_file(ladder)

    assert parsed["company"] == "Acme Corp"
    assert parsed["current_level"] == "Senior"
    assert parsed["target_level"] == "Staff"
    assert parsed["competency_count"] == 2
    names = [c["category"] for c in parsed["competencies"]]
    assert names == ["Technical Depth", "Influence"]

    missing = career_parser.parse_ladder_file(tmp_path / "ghost.md")
    assert "error" in missing
    assert missing["competencies"] == []


# ---------------------------------------------------------------------------
# Competency matching
# ---------------------------------------------------------------------------


def test_match_evidence_to_competency_scoring_tiers():
    # Explicit ladder alignment wins outright
    assert career_parser.match_evidence_to_competency([], "Technical Depth", "Technical Depth") == 1.0
    # Skill name containment
    assert career_parser.match_evidence_to_competency(
        ["System Design work"], "", "System Design"
    ) == 0.8
    # Keyword overlap gives a partial score
    partial = career_parser.match_evidence_to_competency(
        ["Designed the system architecture"], "", "System Architecture Vision"
    )
    assert 0 < partial <= 0.6
    # No relation at all
    assert career_parser.match_evidence_to_competency(["Baking"], "", "System Design") == 0.0
