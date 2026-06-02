from __future__ import annotations

import asyncio
import json

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
