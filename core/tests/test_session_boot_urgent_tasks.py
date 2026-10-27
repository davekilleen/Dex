from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from core.context import session_boot
from core.context.session_boot import build_session_boot
from core.mcp import work_server

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "session_boot_urgent_tasks.md"
TODAY = date(2026, 10, 27)

SUB_BULLET_P0 = "- [ ] Sign the vendor contract ^task-20261020-001"
KEYWORD_FALLBACK = "- [ ] Reply to legal today ^task-20261020-003"
SECTION_P0 = "- [ ] Fix the checkout outage ^task-20261020-005"
DUE_TODAY = "- [ ] Send the renewal quote ^task-20261020-008"
OVERDUE = "- [ ] File the expense report ^task-20261020-009"

NOT_URGENT = (
    "Draft the board memo for urgent review",
    "Tidy the shared drive",
    "Ship the hotfix",
    "Prepare the quarterly review",
    "Book the offsite venue",
    "Update the pricing page",
    "Explore a partner program",
    "**Task title**",
)


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "03-Tasks").mkdir(parents=True)
    shutil.copyfile(FIXTURE, vault / "03-Tasks" / "Tasks.md")
    return vault


@pytest.fixture
def unlimited(monkeypatch):
    monkeypatch.setattr(session_boot, "URGENT_LIMIT", 100)


def test_urgent_tasks_read_core_task_format(tmp_path: Path, unlimited) -> None:
    urgent = build_session_boot(_vault(tmp_path), today=TODAY)["urgent_tasks"]

    assert urgent == [SUB_BULLET_P0, KEYWORD_FALLBACK, SECTION_P0, DUE_TODAY, OVERDUE]


def test_non_urgent_tasks_stay_out(tmp_path: Path, unlimited) -> None:
    urgent = "\n".join(build_session_boot(_vault(tmp_path), today=TODAY)["urgent_tasks"])

    for title in NOT_URGENT:
        assert title not in urgent


def test_due_tasks_drop_out_before_their_date(tmp_path: Path, unlimited) -> None:
    urgent = build_session_boot(_vault(tmp_path), today=date(2026, 10, 19))["urgent_tasks"]

    assert DUE_TODAY not in urgent
    assert OVERDUE not in urgent
    assert SECTION_P0 in urgent


def test_session_start_text_shows_core_format_urgent_tasks(tmp_path: Path) -> None:
    payload = build_session_boot(_vault(tmp_path), today=TODAY)

    assert payload["urgent_tasks"] == [SUB_BULLET_P0, KEYWORD_FALLBACK, SECTION_P0]
    assert "--- Urgent Tasks ---" in payload["injected_text"]
    assert "Sign the vendor contract" in payload["injected_text"]


def test_urgent_tasks_match_work_server_parser(tmp_path: Path, unlimited) -> None:
    vault = _vault(tmp_path)
    tasks = work_server.parse_tasks_file(vault / "03-Tasks" / "Tasks.md")
    expected = {
        task["title"]
        for task in tasks
        if task["status"] == "n"
        and (task["priority"] == "P0" or (task["due"] and date.fromisoformat(task["due"]) <= TODAY))
    }

    urgent = build_session_boot(vault, today=TODAY)["urgent_tasks"]

    assert {work_server._task_title_from_line(line) for line in urgent} == expected
