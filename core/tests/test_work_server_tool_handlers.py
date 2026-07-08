"""End-to-end tests for work_server's handle_call_tool dispatch.

The earlier suite (test_work_server_sync.py) pins the parsing/sync internals;
this one exercises the MCP tool surface the assistant actually calls —
list/update tasks, quarterly goals, the people index, and error paths.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from core.mcp import work_server

TASK_ID = "task-20260601-001"


def _call(name, arguments=None):
    result = asyncio.run(work_server.handle_call_tool(name, arguments or {}))
    return result[0].text


def _call_json(name, arguments=None):
    return json.loads(_call(name, arguments))


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Minimal vault wired into work_server's module globals."""
    root = tmp_path / "vault"
    (root / "03-Tasks").mkdir(parents=True)
    (root / "People/External").mkdir(parents=True)
    (root / "People/Internal").mkdir(parents=True)

    tasks_file = root / "03-Tasks/Tasks.md"
    tasks_file.write_text(
        "\n".join(
            [
                "# Tasks",
                "",
                "## P1 - Important (max 5)",
                f"- [ ] Send proposal to John Doe | People/External/John_Doe.md ^{TASK_ID}",
                "- [ ] Waiting on vendor pricing ^task-20260601-002",
                "- [x] Archive old quotes ^task-20260601-003",
                "",
            ]
        )
    )
    (root / "People/External/John_Doe.md").write_text(
        "\n".join(
            [
                "# John Doe",
                "| **Company** | Acme Corp |",
                "| **Role** | VP of Operations |",
                "| **Email** | john@acme.com |",
                "",
                f"- [ ] Send proposal to John Doe ^{TASK_ID}",
                "",
            ]
        )
    )

    monkeypatch.setattr(work_server, "BASE_DIR", root)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: root / "02-Week_Priorities/none.md")
    monkeypatch.setattr(work_server, "get_people_dir", lambda: root / "People")
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", root / "01-Quarter_Goals/Quarter_Goals.md")
    monkeypatch.setattr(work_server, "PEOPLE_INDEX_FILE", root / "System/People_Index.json")
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", root / "System/user-profile.yaml")
    monkeypatch.setattr(work_server, "MEETING_CACHE_FILE", root / "System/Memory/meeting-cache.json")
    monkeypatch.setattr(
        work_server, "PILLARS",
        {"pillar_1": {"name": "Pipeline", "description": "", "keywords": ["proposal", "quote"]}},
    )
    monkeypatch.setattr(work_server, "HAS_QMD", False)
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *a, **k: None)
    return root


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------


def test_list_tasks_excludes_done_by_default(vault):
    payload = _call_json("list_tasks")
    assert payload["count"] == 2
    assert all(not t["completed"] for t in payload["tasks"])


def test_list_tasks_include_done_and_priority_filter(vault):
    payload = _call_json("list_tasks", {"include_done": True})
    assert payload["count"] == 3

    p1_only = _call_json("list_tasks", {"priority": "P1"})
    assert p1_only["count"] == 2  # section header priority applies to open tasks


# ---------------------------------------------------------------------------
# update_task_status
# ---------------------------------------------------------------------------


def test_update_task_status_by_id_completes_and_syncs(vault):
    payload = _call_json("update_task_status", {"task_id": TASK_ID, "status": "d"})

    assert payload["success"] is True
    assert payload["instances_found"] == 2
    assert "People/External/John_Doe.md" in payload["related_tasks_synced"]
    person = (vault / "People/External/John_Doe.md").read_text()
    assert "- [x]" in person
    assert "## Related Tasks" in person


def test_update_task_status_by_title_fuzzy_match(vault):
    payload = _call_json("update_task_status", {"task_title": "send proposal", "status": "d"})
    assert payload["success"] is True
    assert TASK_ID in (vault / "03-Tasks/Tasks.md").read_text()
    line = next(
        ln for ln in (vault / "03-Tasks/Tasks.md").read_text().split("\n") if TASK_ID in ln
    )
    assert line.strip().startswith("- [x]")


def test_update_task_status_requires_id_or_title(vault):
    payload = _call_json("update_task_status", {"status": "d"})
    assert payload["success"] is False
    assert "task_id or task_title" in payload["error"]


def test_update_task_status_unknown_title_errors(vault):
    payload = _call_json("update_task_status", {"task_title": "no such task", "status": "d"})
    assert payload["success"] is False


# ---------------------------------------------------------------------------
# Blocked tasks
# ---------------------------------------------------------------------------


def test_get_blocked_tasks_flags_waiting_keywords(vault):
    payload = _call_json("get_blocked_tasks")
    assert payload["count"] == 1
    assert "Waiting on vendor pricing" in payload["blocked_tasks"][0]["title"]


# ---------------------------------------------------------------------------
# Quarterly goals
# ---------------------------------------------------------------------------


def test_create_quarterly_goal_rejects_unknown_pillar(vault):
    payload = _call_json(
        "create_quarterly_goal",
        {"title": "X", "pillar": "nonexistent", "success_criteria": "Y"},
    )
    assert payload["success"] is False
    assert "Invalid pillar" in payload["error"]


def test_create_then_read_quarterly_goal_roundtrip(vault):
    created = _call_json(
        "create_quarterly_goal",
        {
            "title": "Advance Tier-1 pipeline",
            "pillar": "pillar_1",
            "success_criteria": "Three deals in quoting",
            # One schema-shaped milestone and one bare string: LLM callers
            # send both forms and neither may crash the server.
            "milestones": [{"title": "Discovery calls"}, "First quotes"],
            "quarter": "Q3 2026",
        },
    )
    assert created["success"] is True
    goal_id = created["goal_id"]
    assert goal_id.startswith("Q3-2026-goal-")

    listed = _call_json("get_quarterly_goals", {"quarter": "Q3 2026"})
    assert listed["count"] == 1
    goal = listed["goals"][0]
    assert goal["goal_id"] == goal_id
    assert goal["title"] == "Advance Tier-1 pipeline"
    assert [m["title"] for m in goal["milestones"]] == ["Discovery calls", "First quotes"]

    status = _call_json("get_goal_status", {"goal_id": goal_id})
    assert status["goal_id"] == goal_id
    assert status["stalled"] is True  # no linked weekly priorities yet


def test_get_goal_status_unknown_goal_errors(vault):
    payload = _call_json("get_goal_status", {"goal_id": "Q1-2020-goal-9"})
    assert payload["success"] is False
    assert "not found" in payload["error"].lower()


# ---------------------------------------------------------------------------
# People index + lookup
# ---------------------------------------------------------------------------


def test_build_people_index_and_lookup_person(vault):
    built = _call_json("build_people_index")
    assert built["success"] is True
    assert built["total"] == 1
    assert (vault / "System/People_Index.json").exists()

    exact = _call_json("lookup_person", {"name": "John Doe"})
    assert exact["total_matches"] == 1
    assert exact["matches"][0]["company"] == "Acme Corp"

    fuzzy = _call_json("lookup_person", {"name": "jon doe"})
    assert fuzzy["total_matches"] >= 1

    filtered = _call_json("lookup_person", {"name": "John Doe", "company": "Globex"})
    assert filtered["total_matches"] == 0


# ---------------------------------------------------------------------------
# Meeting cache + unknown tool
# ---------------------------------------------------------------------------


def test_query_meeting_cache_without_cache_gives_guidance(vault):
    payload = _call_json("query_meeting_cache", {"attendee": "John"})
    assert payload["cache_available"] is False
    assert "meeting cache" in payload["guidance"].lower()


def test_unknown_tool_returns_explicit_error(vault):
    assert "Unknown tool: not_a_tool" in _call("not_a_tool")
