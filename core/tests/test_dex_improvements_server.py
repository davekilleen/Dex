"""Regression coverage for the data-mutating Dex improvements backlog."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from core.mcp import dex_improvements_server as improvements


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 7, 13, 9, 30, tzinfo=tz)


def _call_tool(name: str, arguments: dict) -> dict:
    result = asyncio.run(improvements.handle_call_tool(name, arguments))
    return json.loads(result[0].text)


@pytest.fixture
def backlog_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    system_dir = tmp_path / "System"
    path = system_dir / "Dex_Backlog.md"

    monkeypatch.setattr(improvements, "BASE_DIR", tmp_path)
    monkeypatch.setattr(improvements, "SYSTEM_DIR", system_dir)
    monkeypatch.setattr(improvements, "BACKLOG_FILE", path)
    monkeypatch.setattr(improvements, "datetime", _FixedDateTime)
    monkeypatch.setattr(improvements, "HAS_QMD", False)
    monkeypatch.setattr(improvements, "_fire_analytics_event", lambda *_args: None)
    return path


def test_capture_idea_persists_fields_and_parser_round_trips_them(
    backlog_file: Path,
):
    result = _call_tool(
        "capture_idea",
        {
            "title": "Surface stale meeting follow-ups",
            "description": (
                "Show unresolved meeting commitments before the weekly review."
            ),
            "category": "automation",
        },
    )

    assert result == {
        "success": True,
        "idea_id": "idea-001",
        "title": "Surface stale meeting follow-ups",
        "category": "automation",
        "message": (
            "Idea captured successfully! Run `/dex-backlog` to see it ranked "
            "against other ideas."
        ),
        "next_steps": [
            "Run `/dex-backlog` to see AI-powered ranking",
            'Run `/dex-improve "{title}"` to workshop this idea',
            "Check `System/Dex_Backlog.md` to see all your ideas",
        ],
    }
    content = backlog_file.read_text(encoding="utf-8")
    assert "### 💡 Low Priority (Score: <60)" in content
    assert content.count("- **[idea-001]** Surface stale meeting follow-ups") == 1
    assert "  - **Score:** 0 (not yet ranked" in content
    assert "  - **Category:** automation" in content
    assert "  - **Captured:** 2026-07-13" in content
    assert (
        "  - **Description:** Show unresolved meeting commitments before the "
        "weekly review."
    ) in content

    assert improvements.parse_backlog_file() == [
        {
            "id": "idea-001",
            "title": "Surface stale meeting follow-ups",
            "score": 0,
            "category": "automation",
            "captured": "2026-07-13",
            "description": (
                "Show unresolved meeting commitments before the weekly review."
            ),
            "status": "active",
        }
    ]


def test_find_similar_ideas_detects_near_duplicate_but_not_different_idea(
    backlog_file: Path,
):
    _call_tool(
        "capture_idea",
        {
            "title": "Surface stale meeting follow-ups",
            "description": (
                "Show unresolved meeting commitments before the weekly review."
            ),
            "category": "automation",
        },
    )

    near_duplicate = improvements.find_similar_ideas(
        "Surface stale meeting followup",
        "Show unresolved meeting commitments ahead of the weekly review.",
    )
    clearly_different = improvements.find_similar_ideas(
        "Add company logo colour themes",
        "Let users customise exported PDF colours for each company brand.",
    )

    assert near_duplicate
    assert near_duplicate[0]["id"] == "idea-001"
    assert near_duplicate[0]["similarity"] >= 0.5
    assert clearly_different == []
    assert backlog_file.exists()


@pytest.mark.parametrize(
    ("score", "expected_heading"),
    [
        (91, "### 🔥 High Priority (Score: 85+)"),
        (72, "### ⚡ Medium Priority (Score: 60-84)"),
        (40, "### 💡 Low Priority (Score: <60)"),
    ],
)
def test_queue_insertion_routes_idea_to_score_band(
    backlog_file: Path,
    score: int,
    expected_heading: str,
):
    improvements.initialize_backlog_file()

    assert improvements.insert_idea_into_priority_queue(
        f"idea-{score:03d}",
        f"Scored idea {score}",
        "A scored queue entry.",
        "system",
        score=score,
    )

    content = backlog_file.read_text(encoding="utf-8")
    heading_pos = content.index(expected_heading)
    idea_pos = content.index(f"- **[idea-{score:03d}]** Scored idea {score}")
    next_heading_pos = content.find("\n### ", heading_pos + 1)
    if next_heading_pos == -1:
        next_heading_pos = content.index("\n---", heading_pos)
    assert heading_pos < idea_pos < next_heading_pos
    [parsed] = improvements.parse_backlog_file()
    assert parsed["score"] == score


def test_queue_insertion_keeps_descending_score_order_within_band(
    backlog_file: Path,
):
    improvements.initialize_backlog_file()
    improvements.insert_idea_into_priority_queue(
        "idea-080",
        "Higher medium idea",
        "Higher-ranked existing idea.",
        "system",
        score=80,
    )

    improvements.insert_idea_into_priority_queue(
        "idea-065",
        "Lower medium idea",
        "Lower-ranked new idea.",
        "system",
        score=65,
    )

    medium_ideas = [
        idea
        for idea in improvements.parse_backlog_file()
        if 60 <= idea["score"] < 85
    ]
    assert [idea["id"] for idea in medium_ideas] == ["idea-080", "idea-065"]
    assert backlog_file.read_text(encoding="utf-8").index("idea-080") < (
        backlog_file.read_text(encoding="utf-8").index("idea-065")
    )


@pytest.mark.xfail(
    reason=(
        "BUG: mark_idea_implemented appends the implementation suffix to the "
        "stored title, so parsing the archive no longer round-trips the title"
    ),
    strict=False,
)
def test_mark_implemented_moves_idea_to_archive_without_changing_title(
    backlog_file: Path,
):
    _call_tool(
        "capture_idea",
        {
            "title": "Surface stale meeting follow-ups",
            "description": "Show unresolved meeting commitments.",
            "category": "automation",
        },
    )

    result = _call_tool(
        "mark_implemented",
        {"idea_id": "idea-001", "implementation_date": "2026-07-13"},
    )

    assert result["success"] is True
    [archived] = improvements.parse_backlog_file()
    assert archived == {
        "id": "idea-001",
        "title": "Surface stale meeting follow-ups",
        "score": 0,
        "category": "system",
        "captured": "2026-07-13",
        "description": "",
        "status": "implemented",
    }
    content = backlog_file.read_text(encoding="utf-8")
    assert content.index("## Archive (Implemented)") < content.index("idea-001")
