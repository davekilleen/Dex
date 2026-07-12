"""Regression coverage for honest task metadata and user-data-safe writes."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from core.mcp import work_server

TEST_PILLARS = {
    "pillar_1": {
        "name": "Test Pillar",
        "description": "Neutral test work",
        "keywords": ["test"],
    },
    "pillar_2": {
        "name": "Customer Growth",
        "description": "Customer work",
        "keywords": ["customer"],
    },
}


def _decode_tool_result(result) -> dict:
    return json.loads(result[0].text)


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    return _decode_tool_result(
        asyncio.run(work_server.handle_call_tool(name, arguments or {}))
    )


@pytest.fixture
def task_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    tasks_file = tmp_path / "03-Tasks" / "Tasks.md"
    priorities_file = tmp_path / "02-Week_Priorities" / "Week_Priorities.md"
    goals_file = tmp_path / "01-Quarter_Goals" / "Quarter_Goals.md"
    cache_file = tmp_path / "System" / "Memory" / "meeting-cache.json"
    tasks_file.parent.mkdir(parents=True)
    priorities_file.parent.mkdir(parents=True)
    goals_file.parent.mkdir(parents=True)
    tasks_file.write_text("# Tasks\n\n## Next Week\n", encoding="utf-8")

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: priorities_file)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals_file)
    monkeypatch.setattr(work_server, "MEETING_CACHE_FILE", cache_file)
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    monkeypatch.setattr(
        work_server,
        "PRIORITY_LIMITS",
        {"P0": 20, "P1": 20, "P2": 20},
    )
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(work_server, "refresh_search_index", lambda: None)

    next_id = 40

    def generate_task_id() -> str:
        nonlocal next_id
        next_id += 1
        return f"task-20260711-{next_id:03d}"

    monkeypatch.setattr(work_server, "generate_task_id", generate_task_id)

    return {
        "root": tmp_path,
        "tasks": tasks_file,
        "priorities": priorities_file,
        "goals": goals_file,
        "cache": cache_file,
    }


def test_created_task_lists_exact_pillar_key_and_explicit_p0(task_vault):
    created = _call_tool(
        "create_task",
        {
            "title": "Draft neutral launch briefing document",
            "pillar": "pillar_1",
            "priority": "P0",
        },
    )

    assert created["success"] is True
    listed = _call_tool("list_tasks")
    task = next(
        item
        for item in listed["tasks"]
        if item["task_id"] == created["task"]["task_id"]
    )
    assert task["pillar"] == "pillar_1"
    assert task["priority"] == "P0"
    assert "urgent" not in task["title"].lower()


def test_parse_tasks_reads_all_metadata_fields_and_reverse_maps_pillar_case_insensitively(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    tasks_file = tmp_path / "Tasks.md"
    tasks_file.write_text(
        "# Tasks\n\n"
        "## P2 - Normal\n"
        "- [ ] Prepare quarterly account brief ^task-20260711-042\n"
        "\t- Pillar: test pillar | Priority: P1 | Weekly priority: "
        "[week-2026-W28-p1] | Due: 2026-07-18 | Source: "
        "00-Inbox/Meetings/2026-07-11/customer.md | Project: "
        "04-Projects/Customer_Renewal.md | Goal: Q3-2026-goal-2\n",
        encoding="utf-8",
    )

    [task] = work_server.parse_tasks_file(tasks_file)

    assert task["pillar"] == "pillar_1"
    assert task["priority"] == "P1"
    assert task["weekly_priority_id"] == "week-2026-W28-p1"
    assert task["due"] == "2026-07-18"
    assert task["source"] == "00-Inbox/Meetings/2026-07-11/customer.md"
    assert task["project"] == "04-Projects/Customer_Renewal.md"
    assert task["goal"] == "Q3-2026-goal-2"


def test_task_listing_preserves_provenance_and_exposes_future_source_metadata(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Prepare meeting follow-up ^task-20260711-049\n"
        "\t- Pillar: Test Pillar | Priority: P2 | Source: "
        "00-Inbox/Meetings/2026-07-11/customer.md\n",
        encoding="utf-8",
    )

    task = next(
        item
        for item in work_server.get_all_tasks()
        if item["task_id"] == "task-20260711-049"
    )

    assert task["source"] == "tasks"
    assert task["metadata_source"] == "00-Inbox/Meetings/2026-07-11/customer.md"


def test_legacy_task_without_metadata_keeps_keyword_guesses(tmp_path, monkeypatch):
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    tasks_file = tmp_path / "Tasks.md"
    tasks_file.write_text(
        "# Tasks\n\n## Later\n"
        "- [ ] Urgent customer renewal response ^task-20260711-043\n",
        encoding="utf-8",
    )

    [task] = work_server.parse_tasks_file(tasks_file)

    assert task["pillar"] == "pillar_2"
    assert task["priority"] == "P0"
    assert task.get("weekly_priority_id") is None


def test_malformed_metadata_falls_back_silently_with_section_before_keyword(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    tasks_file = tmp_path / "Tasks.md"
    tasks_file.write_text(
        "# Tasks\n\n## P1 - Important\n"
        "- [ ] Urgent customer renewal response ^task-20260711-044\n"
        "\t- Pillar: Unknown Pillar | Priority: PX | Weekly priority: nope | "
        "Due: next Friday | Goal: quarterly-two\n",
        encoding="utf-8",
    )

    [task] = work_server.parse_tasks_file(tasks_file)

    assert task["pillar"] == "pillar_2"
    assert task["priority"] == "P1"
    assert task.get("weekly_priority_id") is None
    assert task.get("due") is None
    assert task.get("goal") is None


def test_valid_weekly_priority_link_round_trips_into_week_progress(task_vault):
    priority_id = "week-2026-W28-p1"
    task_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. Ship customer launch — **Test Pillar** ^{priority_id}\n",
        encoding="utf-8",
    )

    created = _call_tool(
        "create_task",
        {
            "title": "Prepare launch evidence package",
            "pillar": "pillar_1",
            "priority": "P1",
            "weekly_priority_id": priority_id,
        },
    )

    assert created["success"] is True
    progress = work_server.get_week_progress_data()
    linked = next(item for item in progress["priorities"] if item["priority_id"] == priority_id)
    assert linked["tasks_total"] == 1
    assert linked["tasks_done"] == 0


def test_invalid_weekly_priority_lists_available_ids_without_writing(task_vault):
    available_id = "week-2026-W28-p1"
    task_vault["priorities"].write_text(
        "# Week Priorities\n\n"
        f"1. Ship customer launch — **Test Pillar** ^{available_id}\n",
        encoding="utf-8",
    )
    before = task_vault["tasks"].read_text(encoding="utf-8")

    result = _call_tool(
        "create_task",
        {
            "title": "Prepare launch proof bundle",
            "pillar": "pillar_1",
            "weekly_priority_id": "week-2026-W28-p999",
        },
    )

    assert result["success"] is False
    assert "week-2026-W28-p999" in result["error"]
    assert available_id in result["error"]
    assert task_vault["tasks"].read_text(encoding="utf-8") == before


def test_find_linked_tasks_keeps_old_same_line_links(task_vault):
    priority_id = "week-2026-W28-p1"
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        f"- [ ] Legacy linked task [{priority_id}] ^task-20260711-045\n",
        encoding="utf-8",
    )

    [task] = work_server.find_linked_tasks(priority_id)

    assert task["task_id"] == "task-20260711-045"
    assert "Legacy linked task" in task["title"]


def test_find_linked_tasks_does_not_match_priority_id_prefix(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Linked only to priority ten ^task-20260711-063\n"
        "\t- Pillar: Test Pillar | Priority: P1 | Weekly priority: "
        "[week-2026-W28-p10]\n",
        encoding="utf-8",
    )

    assert work_server.find_linked_tasks("week-2026-W28-p1") == []
    assert len(work_server.find_linked_tasks("week-2026-W28-p10")) == 1


def test_nested_task_does_not_inherit_parent_metadata(task_vault):
    priority_id = "week-2026-W28-p1"
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Parent launch task ^task-20260711-064\n"
        "    - [ ] Nested checklist task ^task-20260711-065\n"
        f"    - Pillar: Test Pillar | Priority: P1 | Weekly priority: [{priority_id}]\n",
        encoding="utf-8",
    )

    linked = work_server.find_linked_tasks(priority_id)

    assert [task["task_id"] for task in linked] == ["task-20260711-064"]
    tasks = work_server.parse_tasks_file(task_vault["tasks"])
    assert next(task for task in tasks if task["task_id"] == "task-20260711-065")[
        "priority"
    ] == "P2"


def test_related_tasks_table_uses_metadata_priority_and_pillar_key(task_vault):
    person_path = "05-Areas/People/External/Jane_Doe.md"
    person_file = task_vault["root"] / person_path
    person_file.parent.mkdir(parents=True)
    person_file.write_text("# Jane Doe\n", encoding="utf-8")
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] **Prepare renewal evidence for Jane** | "
        f"{person_path} ^task-20260711-046\n"
        "\t- Pillar: Test Pillar | Priority: P1\n",
        encoding="utf-8",
    )

    tasks = work_server.find_tasks_for_page(person_path)
    sync_result = work_server.sync_task_refs_for_page(person_path)

    assert tasks[0]["priority"] == "P1"
    assert tasks[0]["pillar"] == "pillar_1"
    assert sync_result["success"] is True
    assert "| P1 |" in person_file.read_text(encoding="utf-8")


def test_create_task_schema_adds_owned_fields_without_source():
    tools = asyncio.run(work_server.handle_list_tools())
    create_tool = next(tool for tool in tools if tool.name == "create_task")
    properties = create_tool.inputSchema["properties"]

    assert {"due", "project", "goal", "on_duplicate"} <= properties.keys()
    assert "source" not in properties
    assert properties["on_duplicate"]["enum"] == ["fail", "force"]
    assert properties["on_duplicate"]["default"] == "fail"


def test_process_inbox_with_dedup_classifies_without_creating_tasks(task_vault):
    tools = asyncio.run(work_server.handle_list_tools())
    inbox_tool = next(tool for tool in tools if tool.name == "process_inbox_with_dedup")
    assert "auto_create" not in inbox_tool.inputSchema["properties"]

    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Prepare quarterly customer renewal brief ^task-20260711-070\n",
        encoding="utf-8",
    )
    before = task_vault["tasks"].read_text(encoding="utf-8")

    result = _call_tool(
        "process_inbox_with_dedup",
        {
            "items": [
                "Prepare quarterly customer renewal brief",
                "Fix bug",
                "Draft customer onboarding plan for this week",
            ],
            "auto_create": True,
        },
    )

    assert [entry["item"] for entry in result["potential_duplicates"]] == [
        "Prepare quarterly customer renewal brief"
    ]
    assert [entry["item"] for entry in result["needs_clarification"]] == ["Fix bug"]
    assert result["new_tasks"] == [
        {
            "item": "Draft customer onboarding plan for this week",
            "suggested_pillar": "pillar_2",
            "suggested_priority": "P1",
            "ready_to_create": True,
        }
    ]
    assert result["summary"]["total_items"] == 3
    assert result["summary"]["new_tasks"] == 1
    assert result["summary"]["duplicates_found"] == 1
    assert result["summary"]["needs_clarification"] == 1
    assert "auto_created" not in result
    assert task_vault["tasks"].read_text(encoding="utf-8") == before


def test_create_task_writes_and_parses_due_project_and_goal(task_vault):
    project = task_vault["root"] / "04-Projects" / "Customer_Renewal.md"
    project.parent.mkdir(parents=True)
    project.write_text("# Customer Renewal\n", encoding="utf-8")
    goal_id = "Q3-2026-goal-2"
    task_vault["goals"].write_text(
        "# Quarterly Goals\n\n"
        f"### 1. Retain strategic accounts — **Test Pillar** ^{goal_id}\n",
        encoding="utf-8",
    )

    created = _call_tool(
        "create_task",
        {
            "title": "Assemble strategic account evidence",
            "pillar": "pillar_1",
            "priority": "P1",
            "due": "2026-07-18",
            "project": "04-Projects/Customer_Renewal.md",
            "goal": goal_id,
        },
    )

    assert created["success"] is True
    text = task_vault["tasks"].read_text(encoding="utf-8")
    assert (
        "\t- Pillar: Test Pillar | Priority: P1 | Due: 2026-07-18 | "
        "Project: 04-Projects/Customer_Renewal.md | Goal: Q3-2026-goal-2"
    ) in text
    task = next(
        item
        for item in work_server.parse_tasks_file(task_vault["tasks"])
        if item["task_id"] == created["task"]["task_id"]
    )
    assert (task["due"], task["project"], task["goal"]) == (
        "2026-07-18",
        "04-Projects/Customer_Renewal.md",
        goal_id,
    )


@pytest.mark.parametrize("due", ["18-07-2026", "2026/07/18", "2026-7-18"])
def test_create_task_rejects_non_iso_due_without_writing(task_vault, due):
    before = task_vault["tasks"].read_text(encoding="utf-8")

    result = _call_tool(
        "create_task",
        {
            "title": "Prepare dated evidence package",
            "pillar": "pillar_1",
            "due": due,
        },
    )

    assert result["success"] is False
    assert "YYYY-MM-DD" in result["error"]
    assert task_vault["tasks"].read_text(encoding="utf-8") == before


def test_create_task_rejects_missing_project_with_substring_matches(task_vault):
    projects_dir = task_vault["root"] / "04-Projects"
    projects_dir.mkdir()
    (projects_dir / "Customer_Renewal_2026.md").write_text("# Renewal\n", encoding="utf-8")
    before = task_vault["tasks"].read_text(encoding="utf-8")

    result = _call_tool(
        "create_task",
        {
            "title": "Prepare customer renewal materials",
            "pillar": "pillar_1",
            "project": "04-Projects/Customer_Renewal.md",
        },
    )

    assert result["success"] is False
    assert result["close_matches"] == ["04-Projects/Customer_Renewal_2026.md"]
    assert task_vault["tasks"].read_text(encoding="utf-8") == before


def test_create_task_rejects_existing_file_outside_projects(task_vault):
    outside = task_vault["root"] / "00-Inbox" / "Not_A_Project.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("# No\n", encoding="utf-8")
    before = task_vault["tasks"].read_text(encoding="utf-8")

    result = _call_tool(
        "create_task",
        {
            "title": "Prepare bounded project reference",
            "pillar": "pillar_1",
            "project": "00-Inbox/Not_A_Project.md",
        },
    )

    assert result["success"] is False
    assert "04-Projects/" in result["error"]
    assert task_vault["tasks"].read_text(encoding="utf-8") == before


def test_create_task_rejects_unknown_goal_and_lists_available_ids(task_vault):
    available_id = "Q3-2026-goal-2"
    task_vault["goals"].write_text(
        "# Quarterly Goals\n\n"
        f"### 1. Retain strategic accounts — **Test Pillar** ^{available_id}\n",
        encoding="utf-8",
    )
    before = task_vault["tasks"].read_text(encoding="utf-8")

    result = _call_tool(
        "create_task",
        {
            "title": "Prepare aligned evidence package",
            "pillar": "pillar_1",
            "goal": "Q3-2026-goal-999",
        },
    )

    assert result["success"] is False
    assert "Q3-2026-goal-999" in result["error"]
    assert available_id in result["error"]
    assert task_vault["tasks"].read_text(encoding="utf-8") == before


def test_optional_metadata_omission_keeps_existing_metadata_line(task_vault):
    created = _call_tool(
        "create_task",
        {
            "title": "Prepare byte stable metadata example",
            "pillar": "pillar_1",
            "priority": "P2",
        },
    )

    assert created["success"] is True
    lines = task_vault["tasks"].read_text(encoding="utf-8").splitlines()
    assert "\t- Pillar: Test Pillar | Priority: P2" in lines
    assert not any("Due:" in line or "Project:" in line or "Goal:" in line for line in lines)


def test_duplicate_defaults_to_fail_and_force_skips_only_similarity_gate(task_vault):
    arguments = {
        "title": "Prepare unique renewal decision record",
        "pillar": "pillar_1",
    }
    first = _call_tool("create_task", arguments)
    duplicate = _call_tool("create_task", arguments)
    forced = _call_tool("create_task", {**arguments, "on_duplicate": "force"})

    assert first["success"] is True
    assert duplicate["success"] is False
    assert "on_duplicate=force" in duplicate["suggestion"]
    assert forced["success"] is True


def test_duplicate_force_does_not_bypass_ambiguity(task_vault):
    result = _call_tool(
        "create_task",
        {
            "title": "Fix bug",
            "pillar": "pillar_1",
            "on_duplicate": "force",
        },
    )

    assert result["success"] is False
    assert result["error"] == "Task is too vague"


def test_first_duplicate_section_insert_preserves_every_original_byte(task_vault):
    before = (
        "# Tasks\n\n"
        "## Next Week\n"
        "- [ ] First existing task ^task-20260711-001\n\n"
        "## Archive\n"
        "Archive body\n\n"
        "## Next Week\n"
        "- [ ] Second existing task ^task-20260711-002\n"
        "TRAILING-SENTINEL\n"
    )
    task_vault["tasks"].write_text(before, encoding="utf-8")

    created = _call_tool(
        "create_task",
        {
            "title": "Insert without losing user data",
            "pillar": "pillar_1",
            "section": "Next Week",
        },
    )

    assert created["success"] is True
    task_id = created["task"]["task_id"]
    task_entry = (
        f"- [ ] **Insert without losing user data** ^{task_id}\n"
        "\t- Pillar: Test Pillar | Priority: P2"
    )
    after = task_vault["tasks"].read_text(encoding="utf-8")
    expected = before.replace(
        "## Next Week",
        f"## Next Week\n{task_entry}\n",
        1,
    )
    assert after == expected
    assert after.count("## Next Week") == 2
    assert after.endswith("TRAILING-SENTINEL\n")


@pytest.mark.parametrize(
    "task_line",
    [
        "- [x] **Finish launch report** ^task-20260711-047 ✅ 2026-07-10 08:30",
        "- [x] **Finish launch report** ✅ 2026-07-10 08:30 ^task-20260711-047",
    ],
    ids=["old-layout", "block-ref-safe-layout"],
)
def test_completion_normalizes_old_and_new_layouts_with_anchor_last(
    task_vault, monkeypatch, task_line
):
    task_vault["tasks"].write_text(f"# Tasks\n\n## Done\n{task_line}\n", encoding="utf-8")
    monkeypatch.setattr(work_server, "_tz_now", lambda: datetime(2026, 7, 11, 21, 15))

    result = work_server.update_task_status_everywhere(
        "task-20260711-047", completed=True
    )

    assert result["success"] is True
    assert result["title"] == "Finish launch report"
    completed_line = next(
        line
        for line in task_vault["tasks"].read_text(encoding="utf-8").splitlines()
        if "task-20260711-047" in line
    )
    assert completed_line == (
        "- [x] **Finish launch report** ✅ 2026-07-11 21:15 "
        "^task-20260711-047"
    )
    assert completed_line.count("✅") == 1
    [parsed] = work_server.parse_tasks_file(task_vault["tasks"])
    assert parsed["title"] == "Finish launch report"


@pytest.mark.parametrize(
    "task_line",
    [
        "- [x] Finish launch report ^task-20260711-048 ✅ 2026-07-10 08:30",
        "- [x] Finish launch report ✅ 2026-07-10 08:30 ^task-20260711-048",
    ],
)
def test_uncompletion_accepts_both_stored_completion_layouts(task_vault, task_line):
    task_vault["tasks"].write_text(f"# Tasks\n\n## Done\n{task_line}\n", encoding="utf-8")

    result = work_server.update_task_status_everywhere(
        "task-20260711-048", completed=False
    )

    assert result["success"] is True
    assert task_vault["tasks"].read_text(encoding="utf-8").splitlines()[-1] == (
        "- [ ] Finish launch report ^task-20260711-048"
    )


def test_priority_limit_error_names_occupying_tasks_and_new_enforcement(task_vault, monkeypatch):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Existing launch brief ^task-20260711-051\n"
        "\t- Pillar: Test Pillar | Priority: P1\n"
        "- [ ] Existing evidence review ^task-20260711-052\n"
        "\t- Pillar: Test Pillar | Priority: P1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(work_server, "PRIORITY_LIMITS", {"P0": 3, "P1": 2, "P2": 10})

    result = _call_tool(
        "create_task",
        {
            "title": "Prepare another planning record",
            "pillar": "pillar_1",
            "priority": "P1",
        },
    )

    assert result["success"] is False
    assert "Existing launch brief" in result["error"]
    assert "task-20260711-051" in result["error"]
    assert "Existing evidence review" in result["error"]
    assert "task-20260711-052" in result["error"]
    assert "newly enforced" in result["error"].lower()
    assert result["occupying_tasks"] == [
        {"title": "Existing launch brief", "task_id": "task-20260711-051"},
        {"title": "Existing evidence review", "task_id": "task-20260711-052"},
    ]


def test_python_meeting_cache_recurses_dated_folders_and_skips_queue(
    task_vault, monkeypatch
):
    day = date.today().isoformat()
    meetings_dir = task_vault["root"] / "00-Inbox" / "Meetings"
    dated_dir = meetings_dir / day
    dated_dir.mkdir(parents=True)
    (dated_dir / "customer-sync.md").write_text(
        f"---\ndate: {day}\nparticipants: [Jane Doe]\n---\n"
        "# Customer Sync\n\n## Decisions\n\n- Ship it\n\n"
        "## Action Items\n\n"
        "- [x] Close old loop ^task-20260711-061 ✅ 2026-07-10 08:30\n"
        "- [x] Close new loop ✅ 2026-07-10 08:30 ^task-20260711-062\n",
        encoding="utf-8",
    )
    external_file = task_vault["root"].parent / "external-secret-meeting.md"
    external_file.write_text(
        f"---\ndate: {day}\n---\n# External Secret Must Not Cache\n",
        encoding="utf-8",
    )
    (dated_dir / "external-secret-link.md").symlink_to(external_file)
    queue_dir = dated_dir / "queue"
    queue_dir.mkdir()
    (queue_dir / "must-not-cache.md").write_text(
        f"---\ndate: {day}\n---\n# Must Not Cache\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(work_server, "get_meetings_dir", lambda: meetings_dir)

    result = work_server.rebuild_meeting_cache_data()

    assert result["success"] is True
    assert result["processed"] == 1
    cache = json.loads(task_vault["cache"].read_text(encoding="utf-8"))
    assert [meeting["title"] for meeting in cache["meetings"]] == ["Customer Sync"]
    assert cache["meetings"][0]["source_file"] == (
        f"00-Inbox/Meetings/{day}/customer-sync.md"
    )
    assert cache["meetings"][0]["action_items"] == ["Close old loop", "Close new loop"]
