"""Golden user-journey continuity tests."""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import yaml


def _copy_fixture_vault(fixture_vault: Path, tmp_path: Path) -> Path:
    target = tmp_path / "vault"
    shutil.copytree(fixture_vault, target)
    return target


def test_golden_journey_onboarding_to_week_review(fixture_vault: Path, tmp_path: Path):
    vault = _copy_fixture_vault(fixture_vault, tmp_path)

    # 1) Onboarding baseline
    profile = yaml.safe_load((vault / "System/user-profile.yaml").read_text(encoding="utf-8"))
    pillars = yaml.safe_load((vault / "System/pillars.yaml").read_text(encoding="utf-8"))
    assert profile["name"] == "Test User"
    assert "pillars" in pillars

    # 2) Task creation
    task_id = "task-golden-001"
    tasks_file = vault / "03-Tasks/Tasks.md"
    task_line = f"- [ ] Prepare partner sync ({task_id}) #P1\\n"
    tasks_file.write_text(tasks_file.read_text(encoding="utf-8") + task_line, encoding="utf-8")

    # 3) Meeting sync
    today = date.today().isoformat()
    meeting_file = vault / "00-Inbox/Meetings" / f"{today}-partner-sync.md"
    meeting_file.write_text(
        "\\n".join(
            [
                f"# Partner Sync — {today}",
                "",
                f"- Follow-up task: {task_id}",
                "- Attendee: Alice Smith",
            ]
        ),
        encoding="utf-8",
    )

    # 4) Daily plan
    daily_plan = vault / "00-Inbox/Daily_Plans" / f"{today}.md"
    daily_plan.write_text(
        "\\n".join(
            [
                f"# Daily Plan — {today}",
                "",
                "## Must-do",
                f"- Finish: {task_id}",
                f"- Review notes: [[Meetings/{today}-partner-sync]]",
            ]
        ),
        encoding="utf-8",
    )

    # 5) Week review
    week_review = vault / "02-Week_Priorities" / "Week_Review.md"
    week_review.write_text(
        "\\n".join(
            [
                "# Week Review",
                "",
                f"- Closed loop from meeting to execution: {task_id}",
                f"- Source meeting: {meeting_file.name}",
            ]
        ),
        encoding="utf-8",
    )

    # Continuity assertions
    tasks_content = tasks_file.read_text(encoding="utf-8")
    meeting_content = meeting_file.read_text(encoding="utf-8")
    daily_content = daily_plan.read_text(encoding="utf-8")
    review_content = week_review.read_text(encoding="utf-8")

    assert task_id in tasks_content
    assert task_id in meeting_content
    assert task_id in daily_content
    assert task_id in review_content
    assert meeting_file.name in review_content
