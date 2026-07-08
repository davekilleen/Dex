"""Cross-file task sync and parser coverage for work_server.

These functions rewrite multiple vault files in one operation (golden journey:
task creation/update -> task index integrity). A regression here silently
corrupts user data, so every mutation is exercised against a throwaway vault.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.mcp import work_server

TASK_ID = "task-20260601-001"


def _make_vault(tmp_path: Path) -> Path:
    """Build a minimal vault with a task referenced from a person page."""
    vault = tmp_path / "vault"
    (vault / "03-Tasks").mkdir(parents=True)
    (vault / "People/External").mkdir(parents=True)

    (vault / "03-Tasks/Tasks.md").write_text(
        "\n".join(
            [
                "# Tasks",
                "",
                "## P1 - Important (max 5)",
                f"- [ ] Send proposal to John Doe | People/External/John_Doe.md ^{TASK_ID}",
                "\t- Priority: P1",
                "- [x] Archive old quotes ^task-20260601-002",
                "",
            ]
        )
    )
    (vault / "People/External/John_Doe.md").write_text(
        "\n".join(
            [
                "# John Doe",
                "",
                "| Field | Value |",
                "|-------|-------|",
                "| **Company** | Acme Corp |",
                "| **Company Page** | People/Companies/Acme_Corp.md |",
                "| **Role** | VP of Operations |",
                "| **Email** | john@acme.com |",
                "",
                "**Last interaction:** 2026-05-20",
                "",
                f"- [ ] Send proposal to John Doe ^{TASK_ID}",
                "",
                "## Notes",
                "Prefers morning calls.",
                "",
            ]
        )
    )
    return vault


def _point_work_server_at(monkeypatch, vault: Path) -> None:
    monkeypatch.setattr(work_server, "BASE_DIR", vault)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: vault / "03-Tasks/Tasks.md")
    monkeypatch.setattr(work_server, "get_people_dir", lambda: vault / "People")


# ---------------------------------------------------------------------------
# Task ID parsing
# ---------------------------------------------------------------------------


def test_extract_task_id_parses_anchor():
    assert work_server.extract_task_id(f"- [ ] Do a thing ^{TASK_ID}") == TASK_ID


def test_extract_task_id_rejects_malformed_ids():
    assert work_server.extract_task_id("- [ ] No anchor here") is None
    assert work_server.extract_task_id("- [ ] Bad ^task-2026-001") is None


def test_find_task_by_id_locates_every_instance(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    _point_work_server_at(monkeypatch, vault)

    instances = work_server.find_task_by_id(TASK_ID)

    files = sorted(Path(i["file"]).name for i in instances)
    assert files == ["John_Doe.md", "Tasks.md"]
    assert all(not i["completed"] for i in instances)
    assert all("Send proposal" in i["title"] for i in instances)


# ---------------------------------------------------------------------------
# Cross-file status propagation
# ---------------------------------------------------------------------------


def test_update_task_status_everywhere_completes_all_instances(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    _point_work_server_at(monkeypatch, vault)

    result = work_server.update_task_status_everywhere(TASK_ID, completed=True)

    assert result["success"] is True
    assert result["instances_found"] == 2
    assert len(result["updated_files"]) == 2
    for name in ("03-Tasks/Tasks.md", "People/External/John_Doe.md"):
        content = (vault / name).read_text()
        line = next(ln for ln in content.split("\n") if TASK_ID in ln)
        assert line.strip().startswith("- [x]")
        assert re.search(r"✅ \d{4}-\d{2}-\d{2} \d{2}:\d{2}", line)


def test_update_task_status_everywhere_uncomplete_removes_timestamp(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    _point_work_server_at(monkeypatch, vault)
    work_server.update_task_status_everywhere(TASK_ID, completed=True)

    result = work_server.update_task_status_everywhere(TASK_ID, completed=False)

    assert result["success"] is True
    for name in ("03-Tasks/Tasks.md", "People/External/John_Doe.md"):
        line = next(
            ln for ln in (vault / name).read_text().split("\n") if TASK_ID in ln
        )
        assert line.strip().startswith("- [ ]")
        assert "✅" not in line


def test_update_task_status_everywhere_is_idempotent(tmp_path, monkeypatch):
    """Completing twice must not stack duplicate timestamps."""
    vault = _make_vault(tmp_path)
    _point_work_server_at(monkeypatch, vault)

    work_server.update_task_status_everywhere(TASK_ID, completed=True)
    work_server.update_task_status_everywhere(TASK_ID, completed=True)

    content = (vault / "03-Tasks/Tasks.md").read_text()
    line = next(ln for ln in content.split("\n") if TASK_ID in ln)
    assert line.count("✅") == 1


def test_update_task_status_everywhere_unknown_id_reports_error(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    _point_work_server_at(monkeypatch, vault)

    result = work_server.update_task_status_everywhere("task-20990101-999", completed=True)

    assert result["success"] is False
    assert "No task found" in result["error"]


# ---------------------------------------------------------------------------
# Related Tasks section sync
# ---------------------------------------------------------------------------


def test_extract_file_refs_from_task_finds_paths():
    line = f"- [ ] Send proposal | People/External/John_Doe.md and Projects/Acme.md ^{TASK_ID}"
    refs = work_server.extract_file_refs_from_task(line)
    assert "People/External/John_Doe.md" in refs
    assert "Projects/Acme.md" in refs


def test_find_tasks_for_page_matches_by_reference_and_name(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    _point_work_server_at(monkeypatch, vault)

    tasks = work_server.find_tasks_for_page("People/External/John_Doe.md")

    assert len(tasks) == 1
    assert tasks[0]["title"].startswith("Send proposal")
    assert tasks[0]["priority"] == "P1"
    assert tasks[0]["completed"] is False


def test_update_related_tasks_section_inserts_and_replaces(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    _point_work_server_at(monkeypatch, vault)
    tasks = work_server.find_tasks_for_page("People/External/John_Doe.md")

    assert work_server.update_related_tasks_section("People/External/John_Doe.md", tasks)
    content = (vault / "People/External/John_Doe.md").read_text()
    assert content.count("## Related Tasks") == 1
    assert "⏳" in content
    # Section is inserted before the first other ## section
    assert content.index("## Related Tasks") < content.index("## Notes")

    # Re-sync after completion must replace, not duplicate, the section
    work_server.update_task_status_everywhere(TASK_ID, completed=True)
    tasks = work_server.find_tasks_for_page("People/External/John_Doe.md")
    assert work_server.update_related_tasks_section("People/External/John_Doe.md", tasks)
    content = (vault / "People/External/John_Doe.md").read_text()
    assert content.count("## Related Tasks") == 1
    assert "✅" in content


def test_update_related_tasks_section_missing_page_returns_false(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    _point_work_server_at(monkeypatch, vault)

    assert work_server.update_related_tasks_section("People/External/Nobody.md", []) is False


def test_propagate_task_status_to_refs_updates_person_page(tmp_path, monkeypatch):
    """Golden journey: complete a task -> every referenced page reflects it."""
    vault = _make_vault(tmp_path)
    _point_work_server_at(monkeypatch, vault)
    work_server.update_task_status_everywhere(TASK_ID, completed=True)

    updated = work_server.propagate_task_status_to_refs("Send proposal to John Doe", completed=True)

    assert "People/External/John_Doe.md" in updated
    content = (vault / "People/External/John_Doe.md").read_text()
    assert "## Related Tasks" in content
    assert "| ✅ | Send proposal" in content


# ---------------------------------------------------------------------------
# Person / company page parsing
# ---------------------------------------------------------------------------


def test_parse_person_page_extracts_table_fields(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    person = work_server.parse_person_page(vault / "People/External/John_Doe.md")

    assert person["name"] == "John Doe"
    assert person["company"] == "Acme Corp"
    assert person["company_page"] == "People/Companies/Acme_Corp.md"
    assert person["role"] == "VP of Operations"
    assert person["email"] == "john@acme.com"
    assert person["last_interaction"] == "2026-05-20"


def test_parse_person_page_missing_file_returns_empty(tmp_path):
    assert work_server.parse_person_page(tmp_path / "ghost.md") == {}


def test_find_people_at_company_matches_by_name_and_page(tmp_path, monkeypatch):
    vault = _make_vault(tmp_path)
    _point_work_server_at(monkeypatch, vault)

    people = work_server.find_people_at_company("Acme Corp")

    assert [p["name"] for p in people] == ["John Doe"]
    assert work_server.find_people_at_company("Globex") == []


def test_get_company_domains_parses_comma_separated_list(tmp_path):
    company = tmp_path / "Acme_Corp.md"
    company.write_text("| **Domains** | acme.com, acme.io |\n")

    assert work_server.get_company_domains(company) == ["acme.com", "acme.io"]
    assert work_server.get_company_domains(tmp_path / "ghost.md") == []


# ---------------------------------------------------------------------------
# Quarterly goals
# ---------------------------------------------------------------------------

GOALS_MD = """---
quarter: Q3 2026
---
# Quarter Goals

### 1. Advance Tier-1 pipeline — **pillar_1** ^Q3-2026-goal-1
**What success looks like:**
Three Tier-1 deals in quoting stage.

- [x] Complete discovery calls
- [ ] Send first quotes

**Progress:** 40%
**Skills developing:** Negotiation, Forecasting
**Impact level:** high

### 2. Untracked goal — **pillar_2**
**Progress:** 0%
"""


def test_parse_quarterly_goals_extracts_full_goal(tmp_path):
    goals_file = tmp_path / "Quarter_Goals.md"
    goals_file.write_text(GOALS_MD)

    goals = work_server.parse_quarterly_goals(goals_file)

    assert len(goals) == 2
    first = goals[0]
    assert first["goal_id"] == "Q3-2026-goal-1"
    assert first["title"] == "Advance Tier-1 pipeline"
    assert first["pillar"] == "pillar_1"
    assert first["progress"] == 40
    assert first["quarter"] == "Q3 2026"
    assert first["success_criteria"] == "Three Tier-1 deals in quoting stage."
    assert [m["completed"] for m in first["milestones"]] == [True, False]
    assert first["skills_developed"] == ["Negotiation", "Forecasting"]
    assert first["impact_level"] == "high"
    assert goals[1]["goal_id"] is None


def test_parse_quarterly_goals_missing_file_returns_empty(tmp_path):
    assert work_server.parse_quarterly_goals(tmp_path / "ghost.md") == []


def test_extract_goal_id():
    assert work_server.extract_goal_id("### 1. Foo — **p** ^Q3-2026-goal-2") == "Q3-2026-goal-2"
    assert work_server.extract_goal_id("no goal here") is None


def test_generate_goal_id_increments_within_quarter():
    existing = [{"goal_id": "Q3-2026-goal-1"}, {"goal_id": "Q3-2026-goal-4"}, {"goal_id": "Q2-2026-goal-9"}]
    assert work_server.generate_goal_id("Q3 2026", existing) == "Q3-2026-goal-5"
    assert work_server.generate_goal_id("Q1 2027", []) == "Q1-2027-goal-1"


def test_calculate_goal_progress_from_linked_priorities(tmp_path, monkeypatch):
    priorities_file = tmp_path / "Week_Priorities.md"
    priorities_file.write_text(
        "\n".join(
            [
                "# Week Priorities",
                "- [x] **Run discovery calls** — Q3-2026-goal-1 ^priority-1",
                "- [ ] **Draft quotes** — Q3-2026-goal-1 ^priority-2",
            ]
        )
    )
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: priorities_file)

    result = work_server.calculate_goal_progress("Q3-2026-goal-1")

    assert result["total_priorities"] == 2
    assert result["completed_priorities"] == 1
    assert result["progress"] == 50

    assert work_server.calculate_goal_progress("Q3-2026-goal-99")["calculation_method"] == "no_linked_priorities"


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


def test_guess_priority_keyword_tiers():
    assert work_server.guess_priority("Send contract ASAP") == "P0"
    assert work_server.guess_priority("Follow up on the demo deadline") == "P1"
    assert work_server.guess_priority("Someday explore a newsletter") == "P3"
    assert work_server.guess_priority("Prepare partner sync notes") == "P2"


def test_priority_from_section_headers():
    assert work_server.priority_from_section("P0 - Urgent") == "P0"
    assert work_server.priority_from_section("Important this week") == "P1"
    assert work_server.priority_from_section("P3 - Backlog") == "P3"
    assert work_server.priority_from_section("Later") is None
    assert work_server.priority_from_section(None) is None


def test_is_ambiguous_flags_vague_items():
    assert work_server.is_ambiguous("fix bug") is True
    assert work_server.is_ambiguous("follow up") is True
    assert work_server.is_ambiguous("Prepare Q3 pricing proposal for Acme renewal") is False
