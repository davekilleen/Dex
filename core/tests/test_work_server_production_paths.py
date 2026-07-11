"""Regression tests for production task-server execution paths."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from core.mcp import work_server


REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_TITLE = "Draft production path regression note"


def _copy_fixture_vault(fixture_vault: Path, tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    shutil.copytree(fixture_vault, vault)
    (vault / "System" / "pillars.yaml").write_text(
        "pillars:\n"
        "  - id: pillar_1\n"
        "    name: Test Pillar\n"
        "    description: For production-path tests\n"
        "    keywords: [test]\n",
        encoding="utf-8",
    )
    return vault


async def _create_task_over_production_stdio(vault: Path):
    server = StdioServerParameters(
        command=sys.executable,
        args=["core/mcp/work_server.py"],
        env={"VAULT_PATH": str(vault)},
        cwd=REPO_ROOT,
    )

    async with asyncio.timeout(30):
        async with stdio_client(server) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=30),
            ) as session:
                await session.initialize()
                return await session.call_tool(
                    "create_task",
                    {
                        "title": TASK_TITLE,
                        "pillar": "pillar_1",
                        "priority": "P2",
                    },
                )


def _decode_handler_result(result) -> dict:
    return json.loads(result[0].text)


def test_create_task_succeeds_over_production_stdio(fixture_vault: Path, tmp_path: Path):
    vault = _copy_fixture_vault(fixture_vault, tmp_path)

    result = asyncio.run(_create_task_over_production_stdio(vault))

    assert result.isError is False, result.content
    payload = json.loads(result.content[0].text)
    assert payload["success"] is True

    tasks_text = (vault / "03-Tasks" / "Tasks.md").read_text(encoding="utf-8")
    assert TASK_TITLE in tasks_text
    assert re.search(r"\^task-\d{8}-\d{3}", tasks_text)


def test_task_lifecycle_succeeds_in_process_without_qmd_patching(tmp_path: Path, monkeypatch):
    tasks_file = tmp_path / "03-Tasks" / "Tasks.md"
    week_priorities_file = tmp_path / "02-Week_Priorities" / "Week_Priorities.md"
    tasks_file.parent.mkdir(parents=True)
    tasks_file.write_text("# Tasks\n", encoding="utf-8")

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(
        work_server,
        "get_week_priorities_file",
        lambda: week_priorities_file,
    )
    monkeypatch.setattr(
        work_server,
        "PILLARS",
        {
            "pillar_1": {
                "name": "Test Pillar",
                "description": "For production-path tests",
                "keywords": ["test"],
            }
        },
    )

    created = _decode_handler_result(
        asyncio.run(
            work_server.handle_call_tool(
                "create_task",
                {
                    "title": TASK_TITLE,
                    "pillar": "pillar_1",
                    "priority": "P2",
                },
            )
        )
    )
    assert created["success"] is True
    task_id = created["task"]["task_id"]

    listed = _decode_handler_result(
        asyncio.run(work_server.handle_call_tool("list_tasks", {}))
    )
    assert any(
        task["task_id"] == task_id and task["title"] == TASK_TITLE
        for task in listed["tasks"]
    )

    updated = _decode_handler_result(
        asyncio.run(
            work_server.handle_call_tool(
                "update_task_status",
                {"task_id": task_id, "status": "d"},
            )
        )
    )
    assert updated["success"] is True

    task_line = next(
        line
        for line in tasks_file.read_text(encoding="utf-8").splitlines()
        if f"^{task_id}" in line
    )
    assert task_line.startswith("- [x]")
    assert f"^{task_id}" in task_line
