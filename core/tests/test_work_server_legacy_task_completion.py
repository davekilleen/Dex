"""Regression coverage for completing ID-less tasks without corrupting Tasks.md."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.mcp import work_server


def _complete_legacy_task(task_title: str) -> dict:
    result = asyncio.run(
        work_server.handle_call_tool(
            "update_task_status",
            {"task_title": task_title, "status": "d"},
        )
    )
    return json.loads(result[0].text)


@pytest.fixture
def tasks_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "03-Tasks" / "Tasks.md"
    path.parent.mkdir(parents=True)

    monkeypatch.setattr(work_server, "get_tasks_file", lambda: path)
    monkeypatch.setattr(
        work_server,
        "get_week_priorities_file",
        lambda: tmp_path / "02-Week_Priorities" / "Week_Priorities.md",
    )
    monkeypatch.setattr(
        work_server,
        "PILLARS",
        {
            "operations": {
                "name": "Operations",
                "description": "Operational work",
                "keywords": ["operations"],
            }
        },
    )
    monkeypatch.setattr(
        work_server, "propagate_task_status_to_refs", lambda *_args: []
    )
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *_args: None)
    return path


def test_legacy_completion_changes_only_the_exact_task_line(tasks_file: Path):
    before = (
        "# Tasks\n\n"
        "## P1 - Important\n"
        "- [ ] Prepare renewal review\n"
        "  - Pillar: Operations | Priority: P1\n"
        "- [ ] Prepare renewal review notes\n\n"
        "## P2 - Normal\n"
        "- [ ] Follow up after prepare renewal review\n"
        "- [x] Already completed item\n\n"
        "## Notes\n"
        "The phrase Prepare renewal review appears here too.\n"
    )
    tasks_file.write_text(before, encoding="utf-8")

    result = _complete_legacy_task("Prepare renewal review notes")

    assert result["success"] is True
    assert result["task"] == "Prepare renewal review notes"
    assert result["new_status"] == "done"
    assert tasks_file.read_bytes() == (
        "# Tasks\n\n"
        "## P1 - Important\n"
        "- [ ] Prepare renewal review\n"
        "  - Pillar: Operations | Priority: P1\n"
        "- [x] Prepare renewal review notes\n\n"
        "## P2 - Normal\n"
        "- [ ] Follow up after prepare renewal review\n"
        "- [x] Already completed item\n\n"
        "## Notes\n"
        "The phrase Prepare renewal review appears here too.\n"
    ).encode()


def test_legacy_completion_prefers_exact_title_over_earlier_substring_match(
    tasks_file: Path,
):
    before = (
        "# Tasks\n\n"
        "## P1 - Important\n"
        "- [ ] Prepare launch notes for the board\n"
        "- [ ] Prepare launch notes\n"
        "- [ ] Prepare launch note\n"
    )
    tasks_file.write_text(before, encoding="utf-8")

    result = _complete_legacy_task("Prepare launch notes")

    assert result["task"] == "Prepare launch notes"
    assert tasks_file.read_bytes() == before.replace(
        "- [ ] Prepare launch notes\n",
        "- [x] Prepare launch notes\n",
    ).encode()


def test_legacy_completion_skips_completed_duplicate_and_completes_open_copy(
    tasks_file: Path,
):
    before = (
        "# Tasks\n\n"
        "## Completed\n"
        "- [x] Send customer update\n\n"
        "## Next\n"
        "- [ ] Send customer update\n"
        "- [ ] Send customer update summary\n"
    )
    tasks_file.write_text(before, encoding="utf-8")

    result = _complete_legacy_task("Send customer update")

    assert result["success"] is True
    assert tasks_file.read_bytes() == (
        "# Tasks\n\n"
        "## Completed\n"
        "- [x] Send customer update\n\n"
        "## Next\n"
        "- [x] Send customer update\n"
        "- [ ] Send customer update summary\n"
    ).encode()


def test_legacy_completion_preserves_crlf_bytes_outside_target_line(tasks_file: Path):
    before = (
        b"# Tasks\r\n\r\n"
        b"## Next\r\n"
        b"- [ ] Complete migration checklist\r\n"
        b"- [ ] Leave this task untouched\r\n"
        b"\r\n## Notes\r\n"
        b"Do not rewrite these line endings.\r\n"
    )
    tasks_file.write_bytes(before)

    result = _complete_legacy_task("Complete migration checklist")

    assert result["success"] is True
    assert tasks_file.read_bytes() == before.replace(
        b"- [ ] Complete migration checklist\r\n",
        b"- [x] Complete migration checklist\r\n",
    )


def test_legacy_completion_does_not_rewrite_checkbox_syntax_inside_title(
    tasks_file: Path,
):
    before = (
        "# Tasks\n\n"
        "## Next\n"
        "- [ ] Document the literal - [ ] checkbox syntax\n"
        "- [ ] Other task\n"
    )
    tasks_file.write_text(before, encoding="utf-8")

    result = _complete_legacy_task("Document the literal - [ ] checkbox syntax")

    assert result["success"] is True
    assert tasks_file.read_bytes() == (
        "# Tasks\n\n"
        "## Next\n"
        "- [x] Document the literal - [ ] checkbox syntax\n"
        "- [ ] Other task\n"
    ).encode()
