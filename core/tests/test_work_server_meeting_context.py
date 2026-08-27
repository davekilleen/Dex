"""Meeting-context behavior at the public Work MCP boundary."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.mcp import work_server


def _call_meeting_context(attendee: str) -> dict:
    result = asyncio.run(
        work_server.handle_call_tool(
            "get_meeting_context",
            {
                "meeting_title": "Reliability review",
                "attendees": [attendee],
            },
        )
    )
    return json.loads(result[0].text)


@pytest.fixture
def meeting_context_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Path]:
    people_dir = tmp_path / "05-Areas" / "People"
    companies_dir = tmp_path / "05-Areas" / "Companies"
    tasks_file = tmp_path / "03-Tasks" / "Tasks.md"
    cache_file = tmp_path / "System" / "Memory" / "meeting-cache.json"

    people_dir.mkdir(parents=True)
    companies_dir.mkdir(parents=True)
    tasks_file.parent.mkdir(parents=True)
    tasks_file.write_text("# Tasks\n", encoding="utf-8")

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: people_dir)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "COMPANIES_DIR", companies_dir)
    monkeypatch.setattr(work_server, "MEETING_CACHE_FILE", cache_file)
    monkeypatch.setattr(work_server, "HAS_QMD", False)

    return {
        "people": people_dir,
        "tasks": tasks_file,
    }


def test_meeting_context_surfaces_open_items_from_the_attendee_page(
    meeting_context_vault: dict[str, Path],
) -> None:
    person = meeting_context_vault["people"] / "External" / "Ada_Lovelace.md"
    person.parent.mkdir(parents=True)
    person.write_text(
        "# Ada Lovelace\n\n"
        "## Action Items Involving Them\n\n"
        "- [ ] Send Ada the reliability brief ^task-20260827-001\n"
        "- [ ] {{Action item}}\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("Ada Lovelace")

    assert result["outstanding_tasks"] == [
        {
            "title": "Send Ada the reliability brief",
            "related_to": "Ada Lovelace",
        }
    ]


def test_meeting_context_matches_underscored_person_links_in_the_task_list(
    meeting_context_vault: dict[str, Path],
) -> None:
    person = meeting_context_vault["people"] / "Internal" / "Ada_Lovelace.md"
    person.parent.mkdir(parents=True)
    person.write_text("# Ada Lovelace\n", encoding="utf-8")
    meeting_context_vault["tasks"].write_text(
        "# Tasks\n\n"
        "- [ ] Share the review with [[Ada_Lovelace]] ^task-20260827-002\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("Ada Lovelace")

    assert result["outstanding_tasks"] == [
        {
            "title": "Share the review with [[Ada_Lovelace]]",
            "related_to": "Ada Lovelace",
        }
    ]


def test_meeting_context_ignores_non_open_task_lines_that_mention_an_attendee(
    meeting_context_vault: dict[str, Path],
) -> None:
    person = meeting_context_vault["people"] / "External" / "Ada_Lovelace.md"
    person.parent.mkdir(parents=True)
    person.write_text("# Ada Lovelace\n", encoding="utf-8")
    meeting_context_vault["tasks"].write_text(
        "# Tasks\n\n"
        "- [x] Closed item for [[Ada_Lovelace]] that mentions - [ ] a template\n"
        "Meeting notes for [[Ada_Lovelace]] mention - [ ] a possible follow-up\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("Ada Lovelace")

    assert result["outstanding_tasks"] == []


def test_meeting_context_does_not_match_a_longer_underscored_person_name(
    meeting_context_vault: dict[str, Path],
) -> None:
    person = meeting_context_vault["people"] / "Internal" / "Chris_Kim.md"
    person.parent.mkdir(parents=True)
    person.write_text("# Chris Kim\n", encoding="utf-8")
    meeting_context_vault["tasks"].write_text(
        "# Tasks\n\n"
        "- [ ] Send the review to [[Chris_Kimball]] ^task-20260827-003\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("Chris Kim")

    assert result["outstanding_tasks"] == []


def test_meeting_context_does_not_resolve_a_longer_person_page_name(
    meeting_context_vault: dict[str, Path],
) -> None:
    person = meeting_context_vault["people"] / "External" / "Chris_Kimball.md"
    person.parent.mkdir(parents=True)
    person.write_text(
        "# Chris Kimball\n\n- [ ] Send Chris Kimball the review\n",
        encoding="utf-8",
    )

    result = _call_meeting_context("Chris Kim")

    assert result["attendee_details"] == []
    assert result["outstanding_tasks"] == []
