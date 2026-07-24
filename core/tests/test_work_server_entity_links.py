"""Regression coverage for entity-resolved task creation and source stamping."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from core.mcp import work_server
from core.utils.entity_pages import render_company_page, render_person_page

TEST_PILLARS = {
    "pillar_1": {
        "name": "Test Pillar",
        "description": "Neutral test work",
        "keywords": ["test"],
    },
    "pillar_2": {
        "name": "Customer Growth",
        "description": "Customer work",
        "keywords": ["customer"],
    },
}


def _decode_tool_result(result) -> dict:
    return json.loads(result[0].text)


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    return _decode_tool_result(
        asyncio.run(work_server.handle_call_tool(name, arguments or {}))
    )


@pytest.fixture
def entity_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    original_root = work_server.BASE_DIR
    tasks_file = tmp_path / work_server.TASKS_FILE.relative_to(original_root)
    priorities_file = tmp_path / work_server.WEEK_PRIORITIES_FILE.relative_to(original_root)
    goals_file = tmp_path / work_server.QUARTER_GOALS_FILE.relative_to(original_root)
    people_dir = tmp_path / work_server.PEOPLE_DIR.relative_to(original_root)
    companies_dir = tmp_path / work_server.COMPANIES_DIR.relative_to(original_root)
    meetings_dir = tmp_path / work_server.MEETINGS_DIR.relative_to(original_root)
    people_index = tmp_path / work_server.PEOPLE_INDEX_FILE.relative_to(original_root)
    company_index = tmp_path / work_server.COMPANY_INDEX_FILE.relative_to(original_root)

    for directory in (
        tasks_file.parent,
        priorities_file.parent,
        goals_file.parent,
        people_dir,
        companies_dir,
        meetings_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    tasks_file.write_text("# Tasks\n\n## Next Week\n", encoding="utf-8")

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: priorities_file)
    monkeypatch.setattr(work_server, "get_people_dir", lambda: people_dir)
    monkeypatch.setattr(work_server, "get_companies_dir", lambda: companies_dir)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals_file)
    monkeypatch.setattr(work_server, "PEOPLE_INDEX_FILE", people_index)
    monkeypatch.setattr(work_server, "COMPANY_INDEX_FILE", company_index)
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    monkeypatch.setattr(
        work_server,
        "PRIORITY_LIMITS",
        {"P0": 20, "P1": 20, "P2": 20},
    )
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(work_server, "refresh_search_index", lambda: None)

    next_id = 100

    def generate_task_id() -> str:
        nonlocal next_id
        next_id += 1
        return f"task-20260712-{next_id:03d}"

    monkeypatch.setattr(work_server, "generate_task_id", generate_task_id)

    return {
        "root": tmp_path,
        "tasks": tasks_file,
        "priorities": priorities_file,
        "goals": goals_file,
        "people": people_dir,
        "companies": companies_dir,
        "meetings": meetings_dir,
    }


def _vault_relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _write_person(
    entity_vault: dict[str, Path],
    folder: str,
    filename: str,
    name: str,
) -> Path:
    person = entity_vault["people"] / folder / filename
    person.parent.mkdir(parents=True, exist_ok=True)
    person.write_text(render_person_page(name), encoding="utf-8")
    return person


def _write_company(
    entity_vault: dict[str, Path],
    filename: str,
    name: str,
    domains: list[str] | None = None,
) -> Path:
    company = entity_vault["companies"] / filename
    company.parent.mkdir(parents=True, exist_ok=True)
    company.write_text(
        render_company_page(name, domains=domains),
        encoding="utf-8",
    )
    return company


def _write_goals(entity_vault: dict[str, Path], body: str) -> None:
    entity_vault["goals"].write_text(
        f"# Quarterly Goals\n\n{body}",
        encoding="utf-8",
    )


def test_stamped_meeting_task_completion_updates_backlog_and_source(entity_vault):
    source_line = "- [ ] Send the renewal brief - by Friday"
    meeting = entity_vault["meetings"] / "2026-07-12-renewal.md"
    meeting.write_text(f"# Renewal\n\n### For Me\n{source_line}\n", encoding="utf-8")
    source = _vault_relative(meeting, entity_vault["root"])

    created = _call_tool(
        "create_task",
        {
            "title": "Send the renewal brief by Friday",
            "pillar": "pillar_1",
            "source": source,
            "stamp_source_line": source_line,
        },
    )
    task_id = created["task"]["task_id"]

    assert created["stamp"] == {"attempted": True, "stamped": True}
    assert f"{source_line} ^{task_id}" in meeting.read_text(encoding="utf-8")

    updated = _call_tool(
        "update_task_status",
        {"task_id": task_id, "status": "d"},
    )

    assert updated["success"] is True
    assert "- [x] **Send the renewal brief by Friday**" in entity_vault[
        "tasks"
    ].read_text(encoding="utf-8")
    assert "- [x] Send the renewal brief - by Friday" in meeting.read_text(
        encoding="utf-8"
    )


def test_create_task_rejects_dead_person_path_with_close_matches(entity_vault):
    existing = _write_person(
        entity_vault,
        "External",
        "Alice_Smith.md",
        "Alice Smith",
    )
    missing = existing.with_name("Alice.md")
    given = _vault_relative(missing, entity_vault["root"])
    before = entity_vault["tasks"].read_text(encoding="utf-8")

    result = _call_tool(
        "create_task",
        {
            "title": "Prepare the customer briefing for Alice",
            "pillar": "pillar_1",
            "people": [given],
        },
    )

    assert result["success"] is False
    assert result["close_matches"] == [
        _vault_relative(existing, entity_vault["root"])
    ]
    assert entity_vault["tasks"].read_text(encoding="utf-8") == before


def test_create_task_stamps_the_only_exact_source_line(entity_vault):
    source_line = "- [ ] Share the decision log - by Monday"
    meeting = entity_vault["meetings"] / "2026-07-12-decisions.md"
    meeting.write_text(
        f"# Decisions\n\n### For Me\n  {source_line}  \n",
        encoding="utf-8",
    )

    created = _call_tool(
        "create_task",
        {
            "title": "Share the decision log by Monday",
            "pillar": "pillar_1",
            "source": _vault_relative(meeting, entity_vault["root"]),
            "stamp_source_line": source_line,
        },
    )

    task_id = created["task"]["task_id"]
    stamped_line = next(
        line for line in meeting.read_text(encoding="utf-8").splitlines() if task_id in line
    )
    assert created["stamp"] == {"attempted": True, "stamped": True}
    assert stamped_line == f"  {source_line}   ^{task_id}"
    assert stamped_line.endswith(f"^{task_id}")


def test_create_task_stamp_is_idempotent_when_line_is_already_anchored(entity_vault):
    source_line = "- [ ] Send revised commercial terms - by Tuesday"
    meeting = entity_vault["meetings"] / "2026-07-12-commercial.md"
    meeting.write_text(f"# Commercial\n\n### For Me\n{source_line}\n", encoding="utf-8")
    source = _vault_relative(meeting, entity_vault["root"])
    arguments = {
        "title": "Send revised commercial terms by Tuesday",
        "pillar": "pillar_1",
        "source": source,
        "stamp_source_line": source_line,
    }

    first = _call_tool("create_task", arguments)
    first_task_id = first["task"]["task_id"]
    anchored_line = next(
        line
        for line in meeting.read_text(encoding="utf-8").splitlines()
        if first_task_id in line
    )
    second = _call_tool(
        "create_task",
        {
            **arguments,
            "stamp_source_line": anchored_line,
            "on_duplicate": "force",
        },
    )

    assert second["success"] is True
    assert second["stamp"] == {
        "attempted": True,
        "stamped": False,
        "reason": "already_anchored",
    }
    assert meeting.read_text(encoding="utf-8").count(f"^{first_task_id}") == 1
    assert f"^{second['task']['task_id']}" not in anchored_line


def test_create_task_reports_zero_stamp_matches_without_failing_creation(entity_vault):
    meeting = entity_vault["meetings"] / "2026-07-12-zero-match.md"
    meeting.write_text(
        "# Follow-up\n\n### For Me\n- [ ] Send the actual follow-up\n",
        encoding="utf-8",
    )

    created = _call_tool(
        "create_task",
        {
            "title": "Send the missing follow-up note",
            "pillar": "pillar_1",
            "source": _vault_relative(meeting, entity_vault["root"]),
            "stamp_source_line": "- [ ] Send a different follow-up",
        },
    )

    assert created["success"] is True
    assert created["stamp"] == {
        "attempted": True,
        "stamped": False,
        "reason": "no_match",
        "match_count": 0,
    }
    assert f"^{created['task']['task_id']}" not in meeting.read_text(encoding="utf-8")


def test_create_task_reports_multiple_stamp_matches_without_guessing(entity_vault):
    source_line = "- [ ] Confirm the launch owner"
    meeting = entity_vault["meetings"] / "2026-07-12-two-matches.md"
    meeting.write_text(
        f"# Launch\n\n### For Me\n{source_line}\n{source_line}\n",
        encoding="utf-8",
    )

    created = _call_tool(
        "create_task",
        {
            "title": "Confirm the launch owner today",
            "pillar": "pillar_1",
            "source": _vault_relative(meeting, entity_vault["root"]),
            "stamp_source_line": source_line,
        },
    )

    assert created["success"] is True
    assert created["stamp"] == {
        "attempted": True,
        "stamped": False,
        "reason": "multiple_matches",
        "match_count": 2,
    }
    assert f"^{created['task']['task_id']}" not in meeting.read_text(encoding="utf-8")


def test_create_task_schema_exposes_exact_source_line_stamp():
    tools = asyncio.run(work_server.handle_list_tools())
    create_task = next(tool for tool in tools if tool.name == "create_task")

    assert create_task.inputSchema["properties"]["stamp_source_line"]["type"] == "string"


def test_create_task_keeps_existing_person_path_and_reports_resolution(entity_vault):
    person = _write_person(
        entity_vault,
        "External",
        "Priya_Shah.md",
        "Priya Shah",
    )
    given = _vault_relative(person, entity_vault["root"])

    created = _call_tool(
        "create_task",
        {
            "title": "Prepare the launch briefing with Priya",
            "pillar": "pillar_1",
            "people": [given],
        },
    )

    assert created["success"] is True
    assert created["links"]["people"] == [
        {"given": given, "resolved_path": given, "how": "path"}
    ]
    assert created["task"]["people"] == [given]
    assert given in entity_vault["tasks"].read_text(encoding="utf-8")


def test_create_task_resolves_unambiguous_bare_person_name(entity_vault):
    person = _write_person(
        entity_vault,
        "Internal",
        "Alice_Smith.md",
        "Alice Smith",
    )
    resolved_path = _vault_relative(person, entity_vault["root"])

    created = _call_tool(
        "create_task",
        {
            "title": "Draft the onboarding plan with Alice",
            "pillar": "pillar_1",
            "people": ["Alice"],
        },
    )

    assert created["success"] is True
    assert created["links"]["people"] == [
        {
            "given": "Alice",
            "resolved_path": resolved_path,
            "how": "first_name",
        }
    ]
    assert created["task"]["people"] == [resolved_path]


def test_create_task_rejects_ambiguous_person_and_lists_every_candidate(entity_vault):
    first = _write_person(
        entity_vault,
        "External",
        "Jessica_Jolly.md",
        "Jessica Jolly",
    )
    second = _write_person(
        entity_vault,
        "Internal",
        "Jessica_Jones.md",
        "Jessica Jones",
    )
    before = entity_vault["tasks"].read_text(encoding="utf-8")

    result = _call_tool(
        "create_task",
        {
            "title": "Prepare the account follow-up with Jessica",
            "pillar": "pillar_1",
            "people": ["Jessica"],
        },
    )

    assert result["success"] is False
    assert result["candidates"] == sorted(
        [
            _vault_relative(first, entity_vault["root"]),
            _vault_relative(second, entity_vault["root"]),
        ]
    )
    assert entity_vault["tasks"].read_text(encoding="utf-8") == before


def test_create_task_resolves_account_by_domain(entity_vault):
    company = _write_company(
        entity_vault,
        "Acme_Corporation.md",
        "Acme Corporation",
        domains=["acme.com"],
    )
    resolved_path = _vault_relative(company, entity_vault["root"])

    created = _call_tool(
        "create_task",
        {
            "title": "Prepare the Acme renewal proposal",
            "pillar": "pillar_1",
            "account": "https://www.acme.com/pricing",
        },
    )

    assert created["success"] is True
    assert created["links"]["account"] == {
        "given": "https://www.acme.com/pricing",
        "resolved_path": resolved_path,
        "how": "domain",
    }
    assert created["task"]["account"] == resolved_path
    assert resolved_path in entity_vault["tasks"].read_text(encoding="utf-8")


def test_create_task_strong_goal_inference_uses_title_and_context(entity_vault):
    goal_id = "Q3-2026-goal-1"
    _write_goals(
        entity_vault,
        "### 1. Launch retention analytics dashboard — **pillar_1** "
        f"^{goal_id}\n\n"
        "- [ ] Launch retention analytics dashboard\n",
    )

    created = _call_tool(
        "create_task",
        {
            "title": "Prepare the leadership decision packet",
            "context": "Launch retention analytics dashboard",
            "pillar": "pillar_1",
        },
    )

    assert created["success"] is True
    assert created["task"]["goal"] == goal_id
    assert created["task"]["goal_tentative"] is False
    assert created["links"]["goal"]["goal_id"] == goal_id
    assert created["links"]["goal"]["confidence"] == "strong"
    assert f"Goal: {goal_id}" in entity_vault["tasks"].read_text(encoding="utf-8")
    assert f"Goal: {goal_id} (?)" not in entity_vault["tasks"].read_text(
        encoding="utf-8"
    )


def test_create_task_weak_goal_inference_marks_and_round_trips_tentative(entity_vault):
    goal_id = "Q3-2026-goal-2"
    _write_goals(
        entity_vault,
        f"### 1. Expand strategic account retention — **pillar_1** ^{goal_id}\n",
    )

    created = _call_tool(
        "create_task",
        {
            "title": "Draft the onboarding workshop agenda",
            "pillar": "pillar_1",
        },
    )

    assert created["success"] is True
    assert created["task"]["goal"] == goal_id
    assert created["task"]["goal_tentative"] is True
    assert created["links"]["tentative"]["goal_id"] == goal_id
    assert created["links"]["tentative"]["confidence"] == "weak"
    assert f"Goal: {goal_id} (?)" in entity_vault["tasks"].read_text(
        encoding="utf-8"
    )

    task = next(
        task
        for task in work_server.parse_tasks_file(entity_vault["tasks"])
        if task["task_id"] == created["task"]["task_id"]
    )
    assert task["goal"] == goal_id
    assert task["goal_tentative"] is True


def test_create_task_none_goal_inference_writes_no_goal(entity_vault):
    _write_goals(
        entity_vault,
        "### 1. Expand strategic account retention — **pillar_2** "
        "^Q3-2026-goal-3\n",
    )

    created = _call_tool(
        "create_task",
        {
            "title": "Draft the internal platform migration runbook",
            "pillar": "pillar_1",
        },
    )

    assert created["success"] is True
    assert created["task"]["goal"] is None
    assert created["task"]["goal_tentative"] is False
    assert created["links"]["goal"] is None
    assert created["links"]["tentative"] is None
    assert "Goal:" not in entity_vault["tasks"].read_text(encoding="utf-8")


def test_create_task_explicit_goal_is_never_second_guessed(entity_vault, monkeypatch):
    explicit_goal = "Q3-2026-goal-4"
    _write_goals(
        entity_vault,
        f"### 1. Keep the supplied goal — **pillar_2** ^{explicit_goal}\n",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("explicit goals must bypass inference")

    monkeypatch.setattr(work_server, "infer_goal_link", fail_if_called)

    created = _call_tool(
        "create_task",
        {
            "title": "Prepare an unrelated leadership briefing",
            "pillar": "pillar_1",
            "goal": explicit_goal,
        },
    )

    assert created["success"] is True
    assert created["task"]["goal"] == explicit_goal
    assert created["task"]["goal_tentative"] is False
    assert created["links"]["goal"] == {
        "goal_id": explicit_goal,
        "how": "explicit",
        "tentative": False,
    }
    assert f"Goal: {explicit_goal} (?)" not in entity_vault["tasks"].read_text(
        encoding="utf-8"
    )


def test_work_mcp_confirm_and_dismiss_relationship_use_engine_path(
    entity_vault,
    monkeypatch,
) -> None:
    person = entity_vault["people"] / "External" / "Related.md"
    person.parent.mkdir(parents=True, exist_ok=True)
    person.write_text(
        "---\n"
        "type: person\n"
        "name: Related Person\n"
        "relationships:\n"
        "- type: works_at\n"
        "  target: '[[Acme]]'\n"
        "  status: suggested\n"
        "  source: {kind: domain-match, id: acme.test}\n"
        "  date: '2026-07-23'\n"
        "dex_pinned: {relationships: user}\n"
        "dex_last_written:\n"
        "  relationships:\n"
        "  - type: works_at\n"
        "    target: '[[Acme]]'\n"
        "    status: suggested\n"
        "    source: {kind: domain-match, id: acme.test}\n"
        "    date: '2026-07-23'\n"
        "---\n"
        "# Related Person\n",
        encoding="utf-8",
    )
    relative = _vault_relative(person, entity_vault["root"])
    monkeypatch.setattr(work_server, "_tz_today", lambda: date(2026, 7, 24))

    tools = {
        tool.name: tool
        for tool in asyncio.run(work_server.handle_list_tools())
    }
    assert tools["confirm_relationship"].inputSchema["required"] == [
        "page",
        "edge_key",
    ]
    assert tools["dismiss_relationship"].inputSchema["required"] == [
        "page",
        "edge_key",
    ]

    confirmed = _call_tool(
        "confirm_relationship",
        {"page": relative, "edge_key": "works_at::[[acme]]"},
    )
    assert confirmed["success"] is True
    parsed = work_server.parse_entity_page(person)
    assert parsed["relationships"][0]["status"] == "confirmed"

    dismissed = _call_tool(
        "dismiss_relationship",
        {"page": relative, "edge_key": "works_at::[[acme]]"},
    )
    assert dismissed["success"] is True
    parsed = work_server.parse_entity_page(person)
    assert parsed["relationships"] == []
    frontmatter = yaml.safe_load(person.read_text(encoding="utf-8").split("---", 2)[1])
    assert frontmatter["dex_dismissed_relationships"] == [
        {"key": "works_at::[[acme]]", "date": "2026-07-24"}
    ]
