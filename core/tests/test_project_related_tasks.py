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


def test_new_project_page_does_not_write_an_empty_related_tasks_section() -> None:
    text = generate_project_page("Launch", description="Ship the launch.")
    assert "## Related Tasks" not in text
    assert "No linked tasks yet" not in text
    assert text.index("# Launch") < text.index("## Status")
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


def test_refresh_keeps_the_blank_line_and_never_deletes_the_next_section(
    vault: Path,
) -> None:
    _write_profile(vault, True)
    project = vault / "04-Projects" / "Alpha.md"
    original = (
        "# Project Alpha\n\n"
        "Intro.\n\n"
        "## Background\n\n"
        "Para.\n\n"
        "## Verdict\n\n"
        "Text.\n\n"
        "## Next steps\n\n"
        "- step\n"
    )
    project.write_text(original, encoding="utf-8")
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Ship Alpha",
            task_id="task-20261027-001",
            project="04-Projects/Alpha.md",
        ),
        encoding="utf-8",
    )

    first = project_related_tasks.sync_project_page(vault, "04-Projects/Alpha.md")
    second = project_related_tasks.sync_project_page(vault, "04-Projects/Alpha.md")
    third = project_related_tasks.sync_project_page(vault, "04-Projects/Alpha.md")
    text = project.read_text(encoding="utf-8")

    assert first["success"] is True
    assert first["changed"] is True
    assert second["changed"] is False
    assert third["changed"] is False
    assert "Ship Alpha" in text
    for heading in ("## Background", "## Verdict", "## Next steps"):
        assert f"\n{heading}\n" in text
        assert not any(
            line.endswith(heading) and not line.startswith("##")
            for line in text.splitlines()
        )
    assert "Para." in text
    assert "Text." in text
    assert "- step" in text


def test_glued_heading_is_repaired_and_the_following_section_is_kept(
    vault: Path,
) -> None:
    _write_profile(vault, True)
    project = vault / "04-Projects" / "Launch.md"
    project.write_text(
        "# Launch\n\n"
        "## Related Tasks\n\n"
        "*No linked tasks yet. Link a task to this project from the "
        "main task list.*## Background\n\n"
        "Keep this paragraph.\n\n"
        "## Verdict\n\n"
        "Still here.\n",
        encoding="utf-8",
    )

    result = project_related_tasks.repair_glued_headings_in_vault(vault)
    text = project.read_text(encoding="utf-8")

    assert result["count"] == 1
    assert "04-Projects/Launch.md" in result["repaired"]
    assert "*## Background" not in text
    assert "\n## Background\n" in text
    assert "Keep this paragraph." in text
    assert "\n## Verdict\n" in text
    assert "Still here." in text

    project_related_tasks.sync_project_page(vault, "04-Projects/Launch.md")
    refreshed = project.read_text(encoding="utf-8")
    assert "Keep this paragraph." in refreshed
    assert "Still here." in refreshed
    assert "*## Background" not in refreshed


def _placeholder_block() -> str:
    return (
        f"## {project_related_tasks.SECTION_HEADING}\n\n"
        f"{project_related_tasks.OPEN_FIRST_LINE}\n\n"
        f"{project_related_tasks.PLACEHOLDER_LINE}\n\n"
    )


def _snapshot_project_markdown(vault: Path) -> dict[str, bytes]:
    projects = vault / "04-Projects"
    return {
        path.relative_to(vault).as_posix(): path.read_bytes()
        for path in projects.rglob("*.md")
        if path.is_file() and not path.is_symlink()
    }


def _write_mixed_projects(vault: Path) -> dict[str, Path]:
    projects = vault / "04-Projects"
    files = {}
    files["launch"] = projects / "Launch.md"
    files["launch"].write_text(
        "# Launch\n\nOverview of the launch.\n\n## Status\n\nPlanning.\n",
        encoding="utf-8",
    )
    files["readme"] = projects / "README.md"
    files["readme"].write_text("# Projects\n\nIndex of projects.\n", encoding="utf-8")
    alpha = projects / "Alpha"
    alpha.mkdir()
    files["alpha"] = alpha / "Alpha.md"
    files["alpha"].write_text("# Alpha\n\n## Status\n\nActive.\n", encoding="utf-8")
    files["decision"] = alpha / "decision-log.md"
    files["decision"].write_text("# Decision log\n\nA decision.\n", encoding="utf-8")
    research = alpha / "research"
    research.mkdir()
    files["interview"] = research / "interview.md"
    files["interview"].write_text("# Interview\n\nNotes.\n", encoding="utf-8")
    beta = projects / "Beta"
    beta.mkdir()
    files["beta"] = beta / "README.md"
    files["beta"].write_text("# Beta\n\nMain page.\n", encoding="utf-8")
    gamma = projects / "Gamma"
    gamma.mkdir()
    files["gamma"] = gamma / "notes.md"
    files["gamma"].write_text(
        "---\ntype: project\n---\n# Gamma notes\n\n## Status\n\nDraft.\n",
        encoding="utf-8",
    )
    delta = projects / "Delta"
    delta.mkdir()
    files["delta"] = delta / "brief.md"
    files["delta"].write_text("# Delta brief\n\n## Status\n\nDraft.\n", encoding="utf-8")
    return files


def test_iter_project_pages_returns_only_real_project_pages(vault: Path) -> None:
    _write_mixed_projects(vault)
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Write the delta brief",
            task_id="task-20261117-001",
            project="04-Projects/Delta/brief.md",
        ),
        encoding="utf-8",
    )

    pages = {
        path.split("/", 1)[1]
        for path in project_related_tasks.iter_project_pages(vault)
    }

    assert pages == {
        "Launch.md",
        "Alpha/Alpha.md",
        "Beta/README.md",
        "Gamma/notes.md",
        "Delta/brief.md",
    }


def test_opting_in_with_zero_linked_tasks_leaves_files_byte_identical(
    vault: Path,
) -> None:
    _write_mixed_projects(vault)
    before = _snapshot_project_markdown(vault)

    result = project_related_tasks.set_preference(vault, True)

    assert result["status"] == "on"
    assert _snapshot_project_markdown(vault) == before


def test_linked_tasks_change_only_that_project_page_and_keep_the_next_heading(
    vault: Path,
) -> None:
    files = _write_mixed_projects(vault)
    _write_profile(vault, True)
    before = _snapshot_project_markdown(vault)
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Call the sponsor",
            task_id="task-20261117-001",
            project="04-Projects/Launch.md",
        )
        + _task_line(
            "Ship the checklist",
            task_id="task-20261117-002",
            project="04-Projects/Launch.md",
        ),
        encoding="utf-8",
    )

    project_related_tasks.refresh_all_project_pages(vault)
    after = _snapshot_project_markdown(vault)
    text = files["launch"].read_text(encoding="utf-8")

    changed = {path for path, payload in after.items() if payload != before[path]}
    assert changed == {"04-Projects/Launch.md"}
    assert "Call the sponsor" in text
    assert "Ship the checklist" in text
    assert "\n## Status\n" in text
    assert not any(
        line.endswith("## Status") and not line.startswith("##")
        for line in text.splitlines()
    )


def test_unlinking_tasks_removes_the_section_and_restores_original_bytes(
    vault: Path,
) -> None:
    files = _write_mixed_projects(vault)
    _write_profile(vault, True)
    original = files["launch"].read_bytes()
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Call the sponsor",
            task_id="task-20261117-001",
            project="04-Projects/Launch.md",
        )
        + _task_line(
            "Ship the checklist",
            task_id="task-20261117-002",
            project="04-Projects/Launch.md",
        ),
        encoding="utf-8",
    )
    project_related_tasks.sync_project_page(vault, "04-Projects/Launch.md")
    assert "## Related Tasks" in files["launch"].read_text(encoding="utf-8")

    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n",
        encoding="utf-8",
    )
    project_related_tasks.sync_project_page(vault, "04-Projects/Launch.md")

    assert files["launch"].read_bytes() == original
    assert "## Related Tasks" not in files["launch"].read_text(encoding="utf-8")


def test_cleanup_restores_exact_placeholders_and_reports_user_edited_blocks(
    vault: Path,
) -> None:
    files = _write_mixed_projects(vault)
    original_decision = files["decision"].read_bytes()
    original_readme = files["readme"].read_bytes()
    files["decision"].write_text(
        files["decision"].read_text(encoding="utf-8").rstrip()
        + "\n\n"
        + _placeholder_block(),
        encoding="utf-8",
    )
    files["readme"].write_text(
        files["readme"].read_text(encoding="utf-8").rstrip()
        + "\n\n"
        + _placeholder_block(),
        encoding="utf-8",
    )
    interview_with_user_line = (
        files["interview"].read_text(encoding="utf-8").rstrip()
        + "\n\n"
        + _placeholder_block().rstrip()
        + "\n\nKeep this interview note.\n"
    )
    files["interview"].write_text(interview_with_user_line, encoding="utf-8")
    interview_bytes = files["interview"].read_bytes()

    first = project_related_tasks.cleanup_placeholder_sections(vault)
    second = project_related_tasks.cleanup_placeholder_sections(vault)

    assert files["decision"].read_bytes() == original_decision
    assert files["readme"].read_bytes() == original_readme
    assert files["interview"].read_bytes() == interview_bytes
    assert "04-Projects/Alpha/decision-log.md" in first["cleaned"]
    assert "04-Projects/README.md" in first["cleaned"]
    assert "04-Projects/Alpha/research/interview.md" in first["reported"]
    assert first["count"] == 2
    assert first["backup_dir"]
    backup = vault / first["backup_dir"]
    manifest_path = backup / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["files"]}
    assert paths == {
        "04-Projects/Alpha/decision-log.md",
        "04-Projects/README.md",
    }
    for item in manifest["files"]:
        assert item["sha256_before"]
        assert item["sha256_after"]
        assert item["sha256_before"] != item["sha256_after"]
        assert (backup / item["path"]).is_file()
    stamp = vault / "System" / ".dex" / "project-related-tasks-cleanup.json"
    assert stamp.is_file()
    assert second["status"] == "already_done"
    assert second["count"] == 0
    assert files["decision"].read_bytes() == original_decision
    assert files["readme"].read_bytes() == original_readme
    assert files["interview"].read_bytes() == interview_bytes


def test_refresh_of_a_non_project_file_is_skipped(vault: Path) -> None:
    files = _write_mixed_projects(vault)
    _write_profile(vault, True)
    original = files["decision"].read_bytes()

    result = project_related_tasks.sync_project_page(
        vault, "04-Projects/Alpha/decision-log.md"
    )

    assert result["success"] is True
    assert result["status"] == "skipped"
    assert result["reason"] == "not_a_project_page"
    assert files["decision"].read_bytes() == original


def test_turning_the_feature_off_removes_sections_and_writes_backups(
    vault: Path,
) -> None:
    files = _write_mixed_projects(vault)
    _write_profile(vault, True)
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n## Next Week\n"
        + _task_line(
            "Call the sponsor",
            task_id="task-20261117-001",
            project="04-Projects/Launch.md",
        ),
        encoding="utf-8",
    )
    project_related_tasks.sync_project_page(vault, "04-Projects/Launch.md")
    assert "## Related Tasks" in files["launch"].read_text(encoding="utf-8")
    files["readme"].write_text(
        files["readme"].read_text(encoding="utf-8").rstrip()
        + "\n\n"
        + _placeholder_block(),
        encoding="utf-8",
    )

    result = project_related_tasks.set_preference(vault, False)
    removed = result["removed"]

    assert result["status"] == "off"
    assert "## Related Tasks" not in files["launch"].read_text(encoding="utf-8")
    assert "## Related Tasks" not in files["readme"].read_text(encoding="utf-8")
    assert "04-Projects/Launch.md" in removed["changed"]
    assert "04-Projects/README.md" in removed["changed"]
    assert removed["backup_dir"]
    backup = vault / removed["backup_dir"]
    assert (backup / "manifest.json").is_file()
    assert (backup / "04-Projects" / "Launch.md").is_file()


def test_glue_repair_leaves_a_reference_doc_without_a_section_alone(
    vault: Path,
) -> None:
    files = _write_mixed_projects(vault)
    original = "See foo## Bar in the research notes.\n"
    files["interview"].write_text(original, encoding="utf-8")
    before = files["interview"].read_bytes()

    result = project_related_tasks.repair_glued_headings_in_vault(vault)

    assert files["interview"].read_bytes() == before
    assert "04-Projects/Alpha/research/interview.md" not in result.get("repaired", [])
    assert original in files["interview"].read_text(encoding="utf-8")


def test_empty_render_section_does_not_include_the_placeholder() -> None:
    assert project_related_tasks.render_section([], []) == ""
    assert "No linked tasks yet" not in project_related_tasks.render_section([], [])


def test_daily_refresh_cleans_placeholders_even_when_the_feature_is_off(
    vault: Path,
) -> None:
    files = _write_mixed_projects(vault)
    _write_profile(vault, False)
    original = files["readme"].read_bytes()
    files["readme"].write_text(
        files["readme"].read_text(encoding="utf-8").rstrip()
        + "\n\n"
        + _placeholder_block(),
        encoding="utf-8",
    )

    result = project_related_tasks.maybe_daily_refresh(vault)

    assert files["readme"].read_bytes() == original
    assert result["cleanup"]["count"] == 1
    assert "04-Projects/README.md" in result["cleanup"]["cleaned"]
