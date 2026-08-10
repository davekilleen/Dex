"""Task IDs past 999: generation, parsing, and boundary-safe matching.

Field report (Martin, 2026-08-10): the ID sequence regex matched exactly three
digits, so once a vault reached task 999 the observed maximum froze there and
every new task was assigned 1000 — colliding forever. A plain substring test
in find_task_by_id compounded it: task-...-100 matched inside task-...-1000.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.mcp import work_server


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "03-Tasks").mkdir(parents=True)
    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    return tmp_path


def _write_tasks(vault: Path, ids: list[str]) -> Path:
    tasks = vault / "03-Tasks" / "Tasks.md"
    lines = ["# Tasks", ""]
    lines.extend(f"- [ ] Task number {task_id} ^{task_id}" for task_id in ids)
    tasks.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tasks


def test_generation_rolls_past_999_without_colliding(vault: Path) -> None:
    _write_tasks(vault, [f"task-20260810-{n:03d}" for n in (1, 998, 999)])

    first = work_server.generate_task_id()
    assert first.endswith("-1000")

    _write_tasks(vault, ["task-20260810-999", "task-20260810-1000"])
    second = work_server.generate_task_id()
    assert second.endswith("-1001")


def test_extract_task_id_reads_four_digit_ids() -> None:
    line = "- [ ] The thousandth task ^task-20260810-1000"
    assert work_server.extract_task_id(line) == "task-20260810-1000"


def test_find_task_by_id_never_matches_a_longer_id(vault: Path) -> None:
    _write_tasks(vault, ["task-20260810-100", "task-20260810-1000"])

    short = work_server.find_task_by_id("task-20260810-100")
    long = work_server.find_task_by_id("task-20260810-1000")

    assert [i["line_content"] for i in short] == [
        "- [ ] Task number task-20260810-100 ^task-20260810-100"
    ]
    assert [i["line_content"] for i in long] == [
        "- [ ] Task number task-20260810-1000 ^task-20260810-1000"
    ]
