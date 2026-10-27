"""DEX-194: Related tasks on project pages."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from core import project_related_tasks
from core.mcp import work_server
from core.utils.page_generators import generate_project_page

TEST_PILLARS = {
    "pillar_1": {
        "name": "Test Pillar",
        "description": "Neutral test work",
        "keywords": ["test"],
    },
}


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    return json.loads(
        asyncio.run(work_server.handle_call_tool(name, arguments or {}))[0].text
    )


def _write_profile(vault: Path, enabled: bool | None) -> None:
    path = vault / "System" / "user-profile.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if enabled is None:
        path.write_text("name: Test\n", encoding="utf-8")
        return
    path.write_text(
        "name: Test\nproject_related_tasks:\n"
        f"  enabled: {'true' if enabled else 'false'}\n",
        encoding="utf-8",
    )


def _task_line(
    title: str,
    *,
    task_id: str,
    project: str | None = None,
    completed: bool = False,
    done_at: str | None = None,
    extra_title: str = "",
    priority: str = "P2",
) -> str:
    mark = "x" if completed else " "
    stamp = f" ✅ {done_at}" if completed and done_at else ""
    line = f"- [{mark}] **{title}**{extra_title}{stamp} ^{task_id}\n"
    meta = f"\t- Pillar: Test Pillar | Priority: {priority}"
    if project:
        meta += f" | Project: {project}"
    return line + meta + "\n"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tasks = tmp_path / "03-Tasks" / "Tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("# Tasks\n\n## Next Week\n", encoding="utf-8")
    (tmp_path / "04-Projects").mkdir()
    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks)
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    return tmp_path


def test_template_starts_new_installs_on() -> None:
    root = Path(__file__).resolve().parents[2]
    profile = yaml.safe_load(
        (root / "System" / "user-profile-template.yaml").read_text(encoding="utf-8")
    )
    assert profile["project_related_tasks"]["enabled"] is True


def test_missing_profile_key_is_an_ask_and_does_not_write(vault: Path) -> None:
    project = vault / "04-Projects" / "Launch.md"
    project.write_text("# Launch\n\n## Status\n\nPlanning.\n", encoding="utf-8")
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Ship the launch checklist",
            task_id="task-20261027-001",
            project="04-Projects/Launch.md",
        ),
        encoding="utf-8",
    )

    result = project_related_tasks.sync_project_page(vault, "04-Projects/Launch.md")

    assert result["status"] == "needs_opt_in"
    assert "Turn it on?" in result["ask"]
    assert "## Related Tasks" not in project.read_text(encoding="utf-8")


def test_disabled_preference_does_not_write(vault: Path) -> None:
    _write_profile(vault, False)
    project = vault / "04-Projects" / "Launch.md"
    project.write_text("# Launch\n\n## Status\n\nPlanning.\n", encoding="utf-8")
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Ship the launch checklist",
            task_id="task-20261027-001",
            project="04-Projects/Launch.md",
        ),
        encoding="utf-8",
    )

    result = project_related_tasks.sync_project_page(vault, "04-Projects/Launch.md")

    assert result["status"] == "off"
    assert "## Related Tasks" not in project.read_text(encoding="utf-8")


def test_explicit_project_link_writes_open_then_recent_done(vault: Path) -> None:
    _write_profile(vault, True)
    project = vault / "04-Projects" / "Launch.md"
    project.write_text("# Launch\n\nOverview of the launch.\n\n## Status\n\nPlanning.\n", encoding="utf-8")
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Call the sponsor",
            task_id="task-20261027-002",
            project="04-Projects/Launch.md",
            priority="P1",
        )
        + _task_line(
            "Older leftover",
            task_id="task-20261001-001",
            project="04-Projects/Launch.md",
            completed=True,
            done_at="2026-10-01 09:00",
        )
        + _task_line(
            "Kickoff deck",
            task_id="task-20261020-003",
            project="04-Projects/Launch.md",
            completed=True,
            done_at="2026-10-20 14:35",
        )
        + _task_line(
            "Name coincidence only",
            task_id="task-20261027-099",
        ),
        encoding="utf-8",
    )

    result = project_related_tasks.sync_project_page(vault, "04-Projects/Launch.md")
    text = project.read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["open_count"] == 1
    assert result["done_count"] == 2
    assert text.index("## Related Tasks") < text.index("## Status")
    assert "[Call the sponsor](03-Tasks/Tasks.md#^task-20261027-002)" in text
    assert text.index("Call the sponsor") < text.index("### Recently done")
    assert text.index("Kickoff deck") < text.index("Older leftover")
    assert "Name coincidence only" not in text
    assert "- [ ]" not in text
    assert "- [x]" not in text
    assert "Ship the launch checklist body" not in text


def test_name_coincidence_and_other_project_are_ignored(vault: Path) -> None:
    _write_profile(vault, True)
    project = vault / "04-Projects" / "Launch.md"
    other = vault / "04-Projects" / "Other.md"
    project.write_text("# Launch\n\n## Notes\n", encoding="utf-8")
    other.write_text("# Other\n\n## Notes\n", encoding="utf-8")
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line("Talk about Launch tomorrow", task_id="task-20261027-010")
        + _task_line(
            "Work the other project",
            task_id="task-20261027-011",
            project="04-Projects/Other.md",
        )
        + _task_line(
            "Linked by wikilink",
            task_id="task-20261027-012",
            extra_title=" | [[04-Projects/Launch]]",
        ),
        encoding="utf-8",
    )

    project_related_tasks.sync_project_page(vault, "04-Projects/Launch.md")
    text = project.read_text(encoding="utf-8")

    assert "Linked by wikilink" in text
    assert "Talk about Launch tomorrow" not in text
    assert "Work the other project" not in text


def test_project_name_in_metadata_is_an_explicit_link(vault: Path) -> None:
    _write_profile(vault, True)
    project = vault / "04-Projects" / "Customer_Renewal.md"
    project.write_text("# Customer Renewal\n\n## Status\n\n", encoding="utf-8")
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Write the renewal brief",
            task_id="task-20261027-020",
            project="Customer Renewal",
        )
        + _task_line(
            "Mention Customer Renewal in passing",
            task_id="task-20261027-021",
        )
        + _task_line(
            "Linked by short wikilink",
            task_id="task-20261027-022",
            extra_title=" | [[Customer_Renewal]]",
        ),
        encoding="utf-8",
    )

    project_related_tasks.sync_project_page(
        vault, "04-Projects/Customer_Renewal.md"
    )
    text = project.read_text(encoding="utf-8")

    assert "Write the renewal brief" in text
    assert "Linked by short wikilink" in text
    assert "Mention Customer Renewal in passing" not in text


def test_recently_done_keeps_only_three(vault: Path) -> None:
    _write_profile(vault, True)
    project = vault / "04-Projects" / "Launch.md"
    project.write_text("# Launch\n", encoding="utf-8")
    body = "# Tasks\n\n## Next Week\n"
    for index, day in enumerate(("01", "02", "03", "04"), start=1):
        body += _task_line(
            f"Done {day}",
            task_id=f"task-202610{day}-00{index}",
            project="04-Projects/Launch.md",
            completed=True,
            done_at=f"2026-10-{day} 12:00",
        )
    (vault / "03-Tasks" / "Tasks.md").write_text(body, encoding="utf-8")

    project_related_tasks.sync_project_page(vault, "04-Projects/Launch.md")
    text = project.read_text(encoding="utf-8")

    assert "Done 04" in text
    assert "Done 03" in text
    assert "Done 02" in text
    assert "Done 01" not in text


def test_opting_in_writes_the_section_and_does_not_rewrite_unrelated_profile(
    vault: Path,
) -> None:
    profile = vault / "System" / "user-profile.yaml"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        "name: Test\ncommunication:\n  formality: casual\n",
        encoding="utf-8",
    )
    project = vault / "04-Projects" / "Launch.md"
    project.write_text("# Launch\n\n## Status\n\n", encoding="utf-8")
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Ship it",
            task_id="task-20261027-001",
            project="04-Projects/Launch.md",
        ),
        encoding="utf-8",
    )

    result = project_related_tasks.set_preference(vault, True)
    text = project.read_text(encoding="utf-8")
    saved = profile.read_text(encoding="utf-8")

    assert result["status"] == "on"
    assert "Ship it" in text
    assert "formality: casual" in saved
    assert "enabled: true" in saved


def test_daily_refresh_runs_once_per_day(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_profile(vault, True)
    project = vault / "04-Projects" / "Launch.md"
    project.write_text("# Launch\n\n## Status\n\n", encoding="utf-8")
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Hand-edited link",
            task_id="task-20261027-001",
            project="04-Projects/Launch.md",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(project_related_tasks, "_today", lambda _vault: date(2026, 10, 27))

    first = project_related_tasks.maybe_daily_refresh(vault)
    second = project_related_tasks.maybe_daily_refresh(vault)

    assert first["ran"] is True
    assert "Hand-edited link" in project.read_text(encoding="utf-8")
    assert second["ran"] is False
    assert second["reason"] == "already_today"


def test_new_project_page_puts_related_tasks_near_the_top() -> None:
    text = generate_project_page("Launch", description="Ship the launch.")
    assert text.index("## Related Tasks") < text.index("## Status")
    assert "- [ ]" not in text


def test_create_task_refreshes_when_enabled_and_asks_when_missing(vault: Path) -> None:
    project = vault / "04-Projects" / "Customer_Renewal.md"
    project.write_text("# Customer Renewal\n\n## Status\n\n", encoding="utf-8")

    asked = _call_tool(
        "create_task",
        {
            "title": "Assemble strategic account evidence",
            "pillar": "pillar_1",
            "project": "04-Projects/Customer_Renewal.md",
        },
    )
    assert asked["success"] is True
    assert asked["project_related_tasks"]["status"] == "needs_opt_in"
    assert "## Related Tasks" not in project.read_text(encoding="utf-8")

    _write_profile(vault, True)
    created = _call_tool(
        "create_task",
        {
            "title": "Write the customer renewal brief",
            "pillar": "pillar_1",
            "project": "04-Projects/Customer_Renewal.md",
        },
    )
    text = project.read_text(encoding="utf-8")
    assert created["project_related_tasks"]["status"] == "on"
    assert "Write the customer renewal brief" in text
    assert "- [ ]" not in text.split("## Related Tasks", 1)[1].split("## Status", 1)[0]


def test_completing_a_task_moves_it_under_recently_done(vault: Path) -> None:
    _write_profile(vault, True)
    project = vault / "04-Projects" / "Launch.md"
    project.write_text("# Launch\n\n## Status\n\n", encoding="utf-8")
    created = _call_tool(
        "create_task",
        {
            "title": "Send the recap",
            "pillar": "pillar_1",
            "project": "04-Projects/Launch.md",
        },
    )
    task_id = created["task"]["task_id"]
    assert "Send the recap" in project.read_text(encoding="utf-8")
    assert "### Recently done" not in project.read_text(encoding="utf-8")

    updated = _call_tool("update_task_status", {"task_id": task_id, "status": "d"})
    text = project.read_text(encoding="utf-8")

    assert updated["project_related_tasks"]["status"] == "on"
    assert "### Recently done" in text
    assert f"[Send the recap](03-Tasks/Tasks.md#^{task_id})" in text
    related = text.split("## Related Tasks", 1)[1].split("## Status", 1)[0]
    assert "- [x]" not in related
    assert "- [ ]" not in related


def test_mcp_tools_are_registered() -> None:
    tools = {tool.name for tool in asyncio.run(work_server.handle_list_tools())}
    assert "set_project_related_tasks" in tools
    assert "refresh_project_related_tasks" in tools
