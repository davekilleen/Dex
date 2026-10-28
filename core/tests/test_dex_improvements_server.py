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
    monkeypatch.setattr(
        improvements, "SESSION_LEARNINGS_DIR", system_dir / "Session_Learnings"
    )
    monkeypatch.setattr(
        improvements, "SYNTHESIS_STATE_FILE", system_dir / ".synthesis-state.json"
    )
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


def test_parse_session_learnings_accepts_old_and_new_shapes(backlog_file: Path):
    _write_learning(
        backlog_file,
        "2026-07-12",
        "## 09:15 - Correction\n\n"
        "**What was said:**\n\n> stop over inferring from timesheet codes\n\n"
        "**Status:** pending\n\n---\n\n"
        "## 10:00 - I prefer summaries in bullet points\n\n"
        "**Kind:** Preference\n\n"
        "**What was said:**\n\n> I prefer summaries in bullet points\n\n"
        "**Status:** pending\n\n---\n",
    )

    parsed = improvements.parse_session_learnings("2026-07-01")

    assert len(parsed) == 2
    assert parsed[0]["title"] == "Correction"
    assert parsed[0]["kind"] == "Correction"
    assert parsed[1]["title"] == "I prefer summaries in bullet points"
    assert parsed[1]["kind"] == "Preference"


def _write_learning(backlog_file: Path, day: str, body: str) -> Path:
    folder = backlog_file.parent / "Session_Learnings"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day}.md"
    path.write_text(f"# Session Learnings - {day}\n\n---\n\n{body}", encoding="utf-8")
    return path


def test_synthesize_learnings_does_not_collapse_generic_titles(backlog_file: Path):
    bodies = (
        "stop over inferring from timesheet codes when planning the day",
        "the daily-plan skill skipped step 5.8 entirely this morning",
        "don't invent folders at the top of the vault next to Projects",
        "treat ordinary messages that say no as ordinary work not lessons",
        "keep Apple Mail search current while the app stays open",
    )
    blocks = []
    for index, body in enumerate(bodies, start=9):
        blocks.append(
            f"## {index:02d}:15 - Correction\n\n"
            f"**What was said:**\n\n> {body}\n\n"
            "**Suggested fix:** confirm during /daily-review and route to "
            "`Mistake_Patterns.md`\n"
            "**Status:** pending\n"
        )
    _write_learning(backlog_file, "2026-07-12", "\n---\n\n".join(blocks) + "\n---\n")

    result = _call_tool("synthesize_learnings", {"days_back": 30})

    assert result["success"] is True
    assert result["ideas_created"] == 5
    assert result["ideas_enriched"] == 0
    titles = [idea["title"] for idea in improvements.parse_backlog_file()]
    assert all(title != "Fix: Correction" for title in titles)
    assert all("Correction" not in title for title in titles)


def test_synthesize_learnings_keeps_unrelated_corrections_apart(backlog_file: Path):
    path = _write_learning(
        backlog_file,
        "2026-07-12",
        "## 09:15 - Correction\n\n"
        "**What was said:**\n\n"
        "> stop over inferring from timesheet codes\n\n"
        "**Suggested fix:** write a rule that timesheet codes are not meetings\n"
        "**Status:** pending\n\n---\n\n"
        "## 11:40 - Correction\n\n"
        "**What was said:**\n\n"
        "> the daily-plan skill skipped step 5.8 entirely\n\n"
        "**Suggested fix:** run step 5.8 even when the calendar looks empty\n"
        "**Status:** pending\n\n---\n",
    )

    result = _call_tool("synthesize_learnings", {"days_back": 30})
    text = path.read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["ideas_created"] == 2
    assert result["ideas_enriched"] == 0
    assert "## 09:15 - Correction" not in text
    assert "## 11:40 - Correction" not in text
    ideas = improvements.parse_backlog_file()
    titles = [idea["title"] for idea in ideas]
    assert all("Correction" not in title for title in titles)
    assert any(
        "timesheet" in idea["title"].lower() or "timesheet" in idea["description"].lower()
        for idea in ideas
    )
    assert any(
        "daily-plan" in idea["title"].lower() or "5.8" in idea["description"]
        for idea in ideas
    )


def test_synthesize_learnings_merges_only_when_content_matches(backlog_file: Path):
    _write_learning(
        backlog_file,
        "2026-07-12",
        "## 09:15 - Correction\n\n"
        "**What was said:**\n\n"
        "> stop over inferring from timesheet codes\n\n"
        "**Suggested fix:** write a rule that timesheet codes are not meetings\n"
        "**Status:** pending\n\n---\n",
    )
    first = _call_tool("synthesize_learnings", {"days_back": 30})
    assert first["ideas_created"] == 1

    _write_learning(
        backlog_file,
        "2026-07-13",
        "## 10:00 - Correction\n\n"
        "**What was said:**\n\n"
        "> stop over inferring from timesheet codes while planning the day\n\n"
        "**Suggested fix:** write a rule that timesheet codes are not meetings\n"
        "**Status:** pending\n\n---\n",
    )
    second = _call_tool("synthesize_learnings", {"days_back": 30})

    assert second["ideas_created"] == 0
    assert second["ideas_enriched"] == 1
    ideas = [idea for idea in improvements.parse_backlog_file() if idea["status"] == "active"]
    assert len(ideas) == 1
