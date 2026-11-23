"""DEX-279: get_commitments_due lists only open Action Items.

Acceptance coverage for structured extraction, fallback, dedupe, the 14-day
window, dated-subfolder recursion, and a replay shaped like Ben Freeman's notes.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from core.mcp import work_server

SYNC_NOTE = """# Sync

## Key Discussion Points

I'll send something over

## Action Items

### For Me
- [ ] Send Ben the pricing deck - by Friday
  - > "I'll send the deck over by Friday"
- [x] Book the room
- [ ] Draft the Q1 plan

### For Others
- [ ] @Sam: Share the contract

## Transcript

I'll send something over
I'll draft the Q1 plan
"""

TEST_PILLARS = {
    "pillar_1": {
        "name": "Test Pillar",
        "description": "Neutral test work",
        "keywords": ["test"],
    },
}


def _decode(result) -> dict:
    return json.loads(result[0].text)


def _call(name: str, arguments: dict | None = None) -> dict:
    return _decode(asyncio.run(work_server.handle_call_tool(name, arguments or {})))


def _user_commitments(result: dict) -> list[dict]:
    return (
        result["commitments_due_today"]
        + result["commitments_due_this_week"]
        + result["commitments_no_date"]
    )


def _write_meeting(meetings: Path, relative: str, body: str) -> Path:
    path = meetings / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def commitments_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    tasks = tmp_path / "03-Tasks" / "Tasks.md"
    priorities = tmp_path / "02-Week_Priorities" / "Week_Priorities.md"
    goals = tmp_path / "01-Quarter_Goals" / "Quarter_Goals.md"
    profile = tmp_path / "System" / "user-profile.yaml"
    meetings = tmp_path / "00-Inbox" / "Meetings"
    people = tmp_path / "05-Areas" / "People" / "External"
    for path in (tasks, priorities, goals, profile):
        path.parent.mkdir(parents=True, exist_ok=True)
    meetings.mkdir(parents=True)
    people.mkdir(parents=True)
    tasks.write_text("# Tasks\n\n## Next Week\n", encoding="utf-8")
    profile.write_text(
        "capabilities:\n  quarter_goals:\n    enabled: true\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: priorities)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals)
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)
    monkeypatch.setattr(work_server, "get_meetings_dir", lambda: meetings)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: people.parent)
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    monkeypatch.setattr(
        work_server, "_PILLARS_SIGNATURE", work_server._pillars_file_signature()
    )
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *a, **k: None)
    monkeypatch.setattr(work_server, "refresh_search_index", lambda: None)
    monkeypatch.setattr(work_server, "_tz_today", lambda: date(2026, 11, 23))
    monkeypatch.setattr(
        work_server, "_tz_now", lambda: datetime(2026, 11, 23, 9, 58)
    )

    return {
        "root": tmp_path,
        "tasks": tasks,
        "meetings": meetings,
        "people": people,
    }


def test_structured_action_items_are_the_only_commitments(commitments_vault):
    _write_meeting(
        commitments_vault["meetings"],
        "2026-11/2026-11-20 - Sync.md",
        SYNC_NOTE,
    )

    result = _call("get_commitments_due", {"date_range": "all"})
    items = _user_commitments(result)
    by_title = {item["commitment"]: item for item in items}

    assert list(by_title) == ["Send Ben the pricing deck", "Draft the Q1 plan"]
    assert by_title["Send Ben the pricing deck"]["confidence"] == "action_item"
    assert by_title["Draft the Q1 plan"]["confidence"] == "action_item"
    assert by_title["Send Ben the pricing deck"] in result["commitments_due_this_week"]
    assert by_title["Draft the Q1 plan"] in result["commitments_no_date"]


def test_ticked_transcript_and_quote_lines_are_dropped(commitments_vault):
    _write_meeting(
        commitments_vault["meetings"],
        "2026-11/2026-11-20 - Sync.md",
        SYNC_NOTE,
    )

    result = _call("get_commitments_due", {"date_range": "all"})
    captured = [item["commitment"] for item in _user_commitments(result)]
    captured += [item["commitment"] for item in result["waiting_on_others"]]
    blob = " ".join(captured).casefold()

    assert "Book the room" not in captured
    assert "something over" not in blob
    assert "I'll send the deck over by Friday" not in blob
    assert "I'll draft the Q1 plan" not in blob
    assert not any("transcript" in item.casefold() for item in captured)


def test_waiting_on_others_uses_for_others_at_mention(commitments_vault):
    _write_meeting(
        commitments_vault["meetings"],
        "2026-11/2026-11-20 - Sync.md",
        SYNC_NOTE,
    )

    result = _call("get_commitments_due", {"date_range": "all"})
    waiting = result["waiting_on_others"]

    assert len(waiting) == 1
    assert waiting[0]["commitment"] == "Share the contract"
    assert waiting[0]["to_person"] == "Sam"
    assert waiting[0]["confidence"] == "action_item"
    assert "Share the contract" not in [
        item["commitment"] for item in _user_commitments(result)
    ]


def test_duplicate_action_items_across_notes_collapse_to_one(commitments_vault):
    meetings = commitments_vault["meetings"]
    _write_meeting(meetings, "2026-11/2026-11-19 - First.md", SYNC_NOTE)
    _write_meeting(meetings, "2026-11/2026-11-20 - Sync.md", SYNC_NOTE)

    result = _call("get_commitments_due", {"date_range": "all"})
    titles = [item["commitment"] for item in _user_commitments(result)]

    assert titles.count("Send Ben the pricing deck") == 1
    assert titles.count("Draft the Q1 plan") == 1
    deck = next(
        item
        for item in _user_commitments(result)
        if item["commitment"] == "Send Ben the pricing deck"
    )
    assert "2026-11/2026-11-19 - First.md" in deck["source"]
    assert any("2026-11-20 - Sync.md" in extra for extra in deck.get("also_in", []))


def test_fallback_ignores_transcript_and_short_captures(commitments_vault):
    _write_meeting(
        commitments_vault["meetings"],
        "2026-11/2026-11-21 - Budget.md",
        "# Budget\n\n"
        "## Key Discussion Points\n\n"
        "I'll send the revised budget to finance.\n\n"
        "## Transcript\n\n"
        "I'll send it\n",
    )

    result = _call("get_commitments_due", {"date_range": "all"})
    items = _user_commitments(result)

    assert len(items) == 1
    assert items[0]["confidence"] == "inferred"
    assert "revised budget" in items[0]["commitment"].casefold()
    blob = " ".join(item["commitment"] for item in items).casefold()
    assert "send it" not in blob
    assert blob.split() != ["it"]


def test_notes_older_than_14_days_are_ignored_and_dated_subfolders_are_scanned(
    commitments_vault,
):
    meetings = commitments_vault["meetings"]
    _write_meeting(
        meetings,
        "2026-11/2026-11-20 - Sync.md",
        "## Action Items\n- [ ] Send Ben the pricing deck - by Friday\n",
    )
    _write_meeting(
        meetings,
        "2026-10/2026-10-01 - Old.md",
        "## Action Items\n- [ ] Ancient follow-up from October\n",
    )
    _write_meeting(
        meetings,
        "2026-11-22 - Flat.md",
        "## Action Items\n- [ ] Draft the Q1 plan\n",
    )

    result = _call("get_commitments_due", {"date_range": "all"})
    titles = [item["commitment"] for item in _user_commitments(result)]
    sources = " ".join(result["sources_scanned"])

    assert "Send Ben the pricing deck" in titles
    assert "Draft the Q1 plan" in titles
    assert "Ancient follow-up from October" not in titles
    assert "2026-11/2026-11-20 - Sync.md" in sources
    assert "2026-11-22 - Flat.md" in sources
    assert "2026-10-01 - Old.md" not in sources


def test_ben_shaped_replay_drops_transcript_fragments_and_duplicates(commitments_vault):
    meetings = commitments_vault["meetings"]
    for index in range(19):
        day = 10 + (index % 10)
        _write_meeting(
            meetings,
            f"2026-11/2026-11-{day:02d} - Call {index:02d}.md",
            "# Call\n\n"
            "## Key Discussion Points\n\n"
            "I'll send something over\n"
            "- > \"I'll send the deck over by Friday\"\n\n"
            "## Action Items\n\n"
            "### For Me\n"
            f"- [ ] Unique follow-up {index:02d}\n"
            "- [ ] Shared follow-up across notes\n"
            "- [x] Already booked the room\n"
            "- [ ] Short done item ✅ 2026-11-20\n\n"
            "### For Others\n"
            f"- [ ] @Sam: Shared contract {index:02d}\n\n"
            "## Transcript\n\n"
            "I'll send something over\n"
            "I'll draft the Q1 plan\n",
        )
    for index in range(3):
        _write_meeting(
            meetings,
            f"2026-11/2026-11-22 - Prose {index}.md",
            "# Prose\n\n"
            "I'll send something over\n\n"
            "## Transcript\n\n"
            "I'll send it\n"
            "I'll draft the Q1 plan\n",
        )

    result = _call("get_commitments_due", {"date_range": "all"})
    items = _user_commitments(result)
    titles = [item["commitment"] for item in items]
    blob = " ".join(titles).casefold()

    assert not any(item["confidence"] == "inferred" for item in items)
    assert "something over" not in blob
    assert "send it" not in blob
    assert "I'll draft" not in blob
    assert titles.count("Shared follow-up across notes") == 1
    assert len(titles) == len(set(titles))
    assert len(result["waiting_on_others"]) == 19


@pytest.mark.parametrize("heading", ["# Action Items", "## action items", "### Action Items"])
def test_action_items_heading_matches_level_and_case(commitments_vault, heading):
    _write_meeting(
        commitments_vault["meetings"],
        "2026-11/2026-11-20 - Heading.md",
        f"{heading}\n- [ ] Keep original Casing here\n",
    )

    result = _call("get_commitments_due", {"date_range": "all"})
    titles = [item["commitment"] for item in _user_commitments(result)]
    assert titles == ["Keep original Casing here"]


def test_already_task_marks_matching_titles(commitments_vault):
    commitments_vault["tasks"].write_text(
        "# Tasks\n\n- [ ] Draft the Q1 plan ^task-20261120-001\n",
        encoding="utf-8",
    )
    _write_meeting(
        commitments_vault["meetings"],
        "2026-11/2026-11-20 - Sync.md",
        SYNC_NOTE,
    )

    result = _call("get_commitments_due", {"date_range": "all"})
    by_title = {item["commitment"]: item for item in _user_commitments(result)}

    assert by_title["Draft the Q1 plan"].get("already_task") is True
    assert "already_task" not in by_title["Send Ben the pricing deck"]
