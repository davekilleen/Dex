from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from core.mcp import work_server


def _decode_tool_result(result):
    return json.loads(result[0].text)


def test_parse_tasks_file_reads_priority_from_section_header(tmp_path):
    tasks_file = tmp_path / "Tasks.md"
    tasks_file.write_text(
        "\n".join(
            [
                "# Tasks",
                "",
                "## P1 - Important (max 5)",
                "- [ ] Meeting with Nina Carpanini ^task-20260507-001",
                "",
                "## P3 - Backlog",
                "- [ ] Clean CRM records ^task-20260507-002",
                "",
                "## Later",
                "- [ ] Urgent customer response ^task-20260507-003",
            ]
        )
    )

    tasks = work_server.parse_tasks_file(tasks_file)

    assert [task["priority"] for task in tasks] == ["P1", "P3", "P0"]


def test_create_task_priority_limit_ignores_week_priority_source(tmp_path, monkeypatch):
    tasks_file = tmp_path / "Tasks.md"
    week_priorities_file = tmp_path / "Week_Priorities.md"
    tasks_file.write_text(
        "\n".join(
            [
                "# Tasks",
                "",
                "## P2 - Normal (max 10)",
                "- [ ] Existing canonical backlog item ^task-20260507-001",
                "",
            ]
        )
    )
    week_priorities_file.write_text(
        "\n".join(
            [
                "# Week Priorities",
                "",
                "## P2 - Normal (max 10)",
                *[
                    f"- [ ] Stale planning artifact {index:02d} ^task-202604{index:02d}-001"
                    for index in range(1, 11)
                ],
                "",
            ]
        )
    )

    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: week_priorities_file)
    monkeypatch.setattr(
        work_server,
        "PILLARS",
        {"pillar_1": {"name": "Pillar 1", "description": "", "keywords": []}},
    )
    monkeypatch.setattr(work_server, "PRIORITY_LIMITS", {"P0": 3, "P1": 5, "P2": 10})
    monkeypatch.setattr(work_server, "HAS_QMD", False)
    monkeypatch.setattr(work_server, "generate_task_id", lambda: "task-20260507-999")
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *args, **kwargs: None)

    result = asyncio.run(
        work_server.handle_call_tool(
            "create_task",
            {
                "title": "Prepare pricing rollout notes for Acme launch",
                "pillar": "pillar_1",
                "priority": "P2",
                "section": "P2 - Normal (max 10)",
            },
        )
    )

    payload = _decode_tool_result(result)

    assert payload["success"] is True
    assert "Prepare pricing rollout notes for Acme launch" in tasks_file.read_text()


def test_create_task_source_is_rendered_and_round_trips(tmp_path, monkeypatch):
    tasks_file = tmp_path / "03-Tasks" / "Tasks.md"
    meeting = tmp_path / "00-Inbox" / "Meetings" / "2026-07-10-roadmap.md"
    tasks_file.parent.mkdir(parents=True)
    meeting.parent.mkdir(parents=True)
    tasks_file.write_text("# Tasks\n")
    meeting.write_text("# Roadmap\n")

    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: tmp_path / "missing.md")
    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        work_server,
        "PILLARS",
        {"pillar_1": {"name": "Pillar 1", "description": "", "keywords": []}},
    )
    monkeypatch.setattr(work_server, "PRIORITY_LIMITS", {"P0": 3, "P1": 5, "P2": 10})
    monkeypatch.setattr(work_server, "HAS_QMD", False)
    monkeypatch.setattr(work_server, "generate_task_id", lambda: "task-20260711-001")
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *args, **kwargs: None)

    source = "00-Inbox/Meetings/2026-07-10-roadmap.md"
    result = asyncio.run(
        work_server.handle_call_tool(
            "create_task",
            {
                "title": "Prepare roadmap decisions for leadership review",
                "pillar": "pillar_1",
                "source": source,
            },
        )
    )
    payload = _decode_tool_result(result)
    task_text = tasks_file.read_text()

    assert payload["success"] is True
    assert payload["task"]["source"] == source
    assert source in task_text
    parsed = work_server.parse_tasks_file(tasks_file)
    assert len(parsed) == 1
    assert source in parsed[0]["raw_title"]
    assert source in work_server.extract_file_refs_from_task(task_text)
    assert "Prepare roadmap decisions" in meeting.read_text()

    tools = asyncio.run(work_server.handle_list_tools())
    create_task_tool = next(tool for tool in tools if tool.name == "create_task")
    assert create_task_tool.inputSchema["properties"]["source"]["type"] == "string"


def test_lookup_person_rebuilds_when_people_tree_is_newer(tmp_path, monkeypatch):
    people_dir = tmp_path / "05-Areas" / "People"
    person = people_dir / "Internal" / "Alice_Smith.md"
    index_file = tmp_path / "System" / "People_Index.json"
    person.parent.mkdir(parents=True)
    person.write_text("# Alice Smith\n")

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "PEOPLE_INDEX_FILE", index_file)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: people_dir)

    work_server.build_people_index_data()
    first_built_at = json.loads(index_file.read_text())["built_at"]
    future = work_server.datetime.fromisoformat(first_built_at).timestamp() + 2
    person.write_text("# Alice Smith\n\n## Notes\n\nUpdated.\n")
    os.utime(person, (future, future))

    work_server.lookup_person_data("Alice Smith")
    rebuilt_at = json.loads(index_file.read_text())["built_at"]

    assert rebuilt_at > first_built_at


def test_check_priority_limits_uses_canonical_backlog_counts(tmp_path, monkeypatch):
    tasks_file = tmp_path / "Tasks.md"
    week_priorities_file = tmp_path / "Week_Priorities.md"
    tasks_file.write_text(
        "\n".join(
            [
                "# Tasks",
                "",
                "## P2 - Normal (max 10)",
                "- [ ] Existing canonical backlog item ^task-20260507-001",
                "",
            ]
        )
    )
    week_priorities_file.write_text(
        "\n".join(
            [
                "# Week Priorities",
                "",
                "## P2 - Normal (max 10)",
                *[
                    f"- [ ] Stale planning artifact {index:02d} ^task-202604{index:02d}-001"
                    for index in range(1, 12)
                ],
                "",
            ]
        )
    )

    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: week_priorities_file)
    monkeypatch.setattr(work_server, "PRIORITY_LIMITS", {"P0": 3, "P1": 5, "P2": 10})

    result = asyncio.run(work_server.handle_call_tool("check_priority_limits", {}))
    payload = _decode_tool_result(result)

    assert payload["priority_counts"] == {"P2": 1}
    assert payload["alerts"] == []
    assert payload["balanced"] is True


def test_update_task_status_everywhere_reports_partial_write_failure(tmp_path, monkeypatch):
    task_id = "task-20260711-001"
    first_successful_file = tmp_path / "Tasks.md"
    failed_file = tmp_path / "Meeting.md"
    second_successful_file = tmp_path / "Person.md"
    task_line = f"- [ ] Ship audited fixes ^{task_id}"
    first_successful_file.write_text(task_line)
    failed_file.write_text(task_line)
    second_successful_file.write_text(task_line)

    monkeypatch.setattr(
        work_server,
        "find_task_by_id",
        lambda _task_id: [
            {
                "file": str(first_successful_file),
                "line_number": 1,
                "title": "Ship audited fixes",
            },
            {
                "file": str(failed_file),
                "line_number": 1,
                "title": "Ship audited fixes",
            },
            {
                "file": str(second_successful_file),
                "line_number": 1,
                "title": "Ship audited fixes",
            },
        ],
    )

    original_write_text = Path.write_text

    def fail_one_write(path, content, *args, **kwargs):
        if path == failed_file:
            raise OSError("disk full")
        return original_write_text(path, content, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_one_write)

    result = work_server.update_task_status_everywhere(task_id, completed=True)

    assert result["success"] is False
    assert result["failed_files"] == [
        {"file": str(failed_file), "error": "disk full"}
    ]
    assert result["updated_files"] == [
        {"file": str(first_successful_file), "line": 1},
        {"file": str(second_successful_file), "line": 1},
    ]
    assert result["instances_found"] == 3
    assert result["error"] == (
        f"task updated in 2 of 3 locations; failures: {failed_file}: disk full"
    )


def test_update_task_status_tool_surfaces_title_match_write_failure(monkeypatch):
    failure = {
        "success": False,
        "task_id": "task-20260711-001",
        "title": "Ship audited fixes",
        "status": "completed",
        "completed_at": "2026-07-11 12:00",
        "updated_files": [{"file": "/vault/Tasks.md", "line": 1}],
        "instances_found": 2,
        "failed_files": [{"file": "/vault/Meeting.md", "error": "disk full"}],
        "error": (
            "task updated in 1 of 2 locations; failures: "
            "/vault/Meeting.md: disk full"
        ),
    }
    monkeypatch.setattr(
        work_server,
        "get_all_tasks",
        lambda: [
            {
                "title": "Ship audited fixes",
                "task_id": "task-20260711-001",
            }
        ],
    )
    monkeypatch.setattr(
        work_server,
        "update_task_status_everywhere",
        lambda _task_id, _completed: failure.copy(),
    )

    def fail_if_propagated(*_args, **_kwargs):
        raise AssertionError("related task sync must not run after a failed write")

    monkeypatch.setattr(
        work_server,
        "propagate_task_status_to_refs",
        fail_if_propagated,
    )

    payload = _decode_tool_result(
        asyncio.run(
            work_server.handle_call_tool(
                "update_task_status",
                {"task_title": "audited fixes", "status": "d"},
            )
        )
    )

    assert payload == failure


def test_load_pillars_coerces_non_string_keywords(tmp_path, monkeypatch):
    """A YAML keyword like `1:1` parses as an int (base-60); guess_pillar must not crash."""
    pillars_file = tmp_path / "pillars.yaml"
    pillars_file.write_text(
        "pillars:\n"
        "  - id: sales\n"
        "    name: Sales\n"
        "    keywords:\n"
        "      - 1:1\n"
        "      - pipeline\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(work_server, "get_pillars_file", lambda: pillars_file)

    pillars = work_server.load_pillars_from_yaml()

    assert pillars["sales"]["keywords"] == ["61", "pipeline"]
    # guess_pillar iterates `keyword in text` over module-level PILLARS — the
    # int-coerced keyword must not raise a TypeError on `61 in "..."`.
    monkeypatch.setattr(work_server, "PILLARS", pillars)
    assert work_server.guess_pillar("let's sync on the pipeline") == "sales"


def test_empty_keywords_does_not_discard_all_pillars(tmp_path, monkeypatch):
    """A present-but-empty `keywords:` parses as None; it must load that pillar
    with no keywords, not raise and fall back to DEFAULT_PILLARS (wiping the
    user's real pillars)."""
    pillars_file = tmp_path / "pillars.yaml"
    pillars_file.write_text(
        "pillars:\n"
        "  - id: sales\n"
        "    name: Sales\n"
        "    keywords:\n"
        "  - id: product\n"
        "    name: Product\n"
        "    keywords:\n"
        "      - roadmap\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(work_server, "get_pillars_file", lambda: pillars_file)

    pillars = work_server.load_pillars_from_yaml()

    assert set(pillars) == {"sales", "product"}
    assert pillars["sales"]["keywords"] == []
    assert pillars["product"]["keywords"] == ["roadmap"]
