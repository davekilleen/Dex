from __future__ import annotations

import asyncio
import json
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
