"""Behavioral coverage for blocked/started statuses, orphan detection, and
provisional quarterly-goal recovery."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.mcp import work_server

TEST_PILLARS = {
    "pillar_1": {
        "name": "Test Pillar",
        "description": "Neutral test work",
        "keywords": ["test"],
    },
}


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    result = asyncio.run(work_server.handle_call_tool(name, arguments or {}))
    return json.loads(result[0].text)


@pytest.fixture
def task_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    tasks_file = tmp_path / "03-Tasks" / "Tasks.md"
    priorities_file = tmp_path / "02-Week_Priorities" / "Week_Priorities.md"
    goals_file = tmp_path / "01-Quarter_Goals" / "Quarter_Goals.md"
    tasks_file.parent.mkdir(parents=True)
    priorities_file.parent.mkdir(parents=True)
    goals_file.parent.mkdir(parents=True)
    tasks_file.write_text("# Tasks\n\n## Next Week\n", encoding="utf-8")

    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks_file)
    monkeypatch.setattr(work_server, "get_week_priorities_file", lambda: priorities_file)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals_file)
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)
    monkeypatch.setattr(
        work_server,
        "PRIORITY_LIMITS",
        {"P0": 20, "P1": 20, "P2": 20},
    )
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(work_server, "refresh_search_index", lambda: None)

    next_id = 80

    def generate_task_id() -> str:
        nonlocal next_id
        next_id += 1
        return f"task-20260903-{next_id:03d}"

    monkeypatch.setattr(work_server, "generate_task_id", generate_task_id)

    return {
        "root": tmp_path,
        "tasks": tasks_file,
        "priorities": priorities_file,
        "goals": goals_file,
    }


def test_get_blocked_tasks_returns_status_b_tasks_and_dedupes_keyword_matches(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [b] Ship integration handoff notes ^task-20260903-050\n"
        "- [b] Blocked on legal review of contract ^task-20260903-051\n"
        "- [ ] Waiting on vendor pricing sheet ^task-20260903-052\n"
        "- [ ] Draft launch summary email ^task-20260903-053\n",
        encoding="utf-8",
    )

    result = _call_tool("get_blocked_tasks")

    by_id = {task["task_id"]: task for task in result["blocked_tasks"]}
    assert result["count"] == 3
    assert by_id["task-20260903-050"]["blocked_signal"] == "status"
    # A status-blocked task with a keyword title appears exactly once.
    assert by_id["task-20260903-051"]["blocked_signal"] == "status"
    assert by_id["task-20260903-052"]["blocked_signal"] == "title_keyword"
    assert "task-20260903-053" not in by_id


def test_started_status_round_trips_through_write_and_parse(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Prepare renewal talking points ^task-20260903-060\n",
        encoding="utf-8",
    )

    started = _call_tool(
        "update_task_status",
        {"task_id": "task-20260903-060", "status": "s"},
    )

    assert started["success"] is True
    content = task_vault["tasks"].read_text(encoding="utf-8")
    assert "- [/] Prepare renewal talking points ^task-20260903-060" in content

    [task] = work_server.parse_tasks_file(task_vault["tasks"])
    assert task["status"] == "s"
    assert task["completed"] is False

    completed = _call_tool(
        "update_task_status",
        {"task_id": "task-20260903-060", "status": "d"},
    )

    assert completed["success"] is True
    [task] = work_server.parse_tasks_file(task_vault["tasks"])
    assert task["status"] == "d"


def test_legacy_s_checkbox_is_read_as_started_without_migration(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [s] Legacy started task ^task-20260903-061\n",
        encoding="utf-8",
    )

    [task] = work_server.parse_tasks_file(task_vault["tasks"])

    assert task["status"] == "s"
    assert work_server.find_task_by_id("task-20260903-061")


def test_check_goal_alignment_reports_tasks_without_goal_or_weekly_priority(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Orphaned launch checklist item ^task-20260903-070\n"
        "- [ ] Goal-linked migration task ^task-20260903-071\n"
        "\t- Pillar: Test Pillar | Priority: P1 | Goal: Q3-2026-goal-1\n"
        "- [ ] Priority-linked rollout task ^task-20260903-072\n"
        "\t- Weekly priority: [week-2026-W36-p1]\n",
        encoding="utf-8",
    )

    result = _call_tool("check_goal_alignment")

    orphans = result["tasks_without_priority"]
    assert orphans["count"] == 1
    assert orphans["items"][0]["task_id"] == "task-20260903-070"
    assert any("neither" in rec for rec in result["recommendations"])


FREEFORM_GOALS = (
    "# Quarter Goals\n\n"
    "## 🎯 This Quarter\n\n"
    "1. Launch the partner portal beta\n"
    "2. Cut onboarding time in half\n"
)


def test_lenient_parse_recovers_freeform_list_as_provisional_goals(task_vault):
    task_vault["goals"].write_text(FREEFORM_GOALS, encoding="utf-8")

    goals = work_server.parse_quarterly_goals(task_vault["goals"])

    assert [goal["title"] for goal in goals] == [
        "Launch the partner portal beta",
        "Cut onboarding time in half",
    ]
    assert all(goal["provisional"] for goal in goals)
    assert all(goal["goal_id"] for goal in goals)

    payload = _call_tool("get_quarterly_goals")
    assert payload["provisional_count"] == 2
    assert "provisional" in payload["provisional_note"]


def test_seed_placeholder_numbered_list_recovers_nothing(task_vault):
    task_vault["goals"].write_text(
        "# Quarter Goals\n\n## 🎯 This Quarter\n\n1.\n2.\n3.\n",
        encoding="utf-8",
    )

    assert work_server.parse_quarterly_goals(task_vault["goals"]) == []


def test_infer_goal_link_refuses_to_auto_link_against_provisional_goals(task_vault):
    task_vault["goals"].write_text(FREEFORM_GOALS, encoding="utf-8")
    goals = work_server.parse_quarterly_goals(task_vault["goals"])

    # An exact-title match would score 'strong' against a structured goal.
    candidates = work_server.infer_goal_link(
        "Launch the partner portal beta", "", goals
    )

    assert candidates
    assert all(candidate["confidence"] == "none" for candidate in candidates)
    assert all(candidate.get("provisional") for candidate in candidates)


def test_create_task_never_links_to_provisional_goals(task_vault):
    task_vault["goals"].write_text(FREEFORM_GOALS, encoding="utf-8")

    created = _call_tool(
        "create_task",
        {
            "title": "Launch the partner portal beta rollout checklist",
            "pillar": "pillar_1",
            "priority": "P2",
        },
    )

    assert created["success"] is True
    assert created["task"]["goal"] is None
    assert "Goal:" not in task_vault["tasks"].read_text(encoding="utf-8")

    provisional_id = work_server.parse_quarterly_goals(task_vault["goals"])[0]["goal_id"]
    refused = _call_tool(
        "create_task",
        {
            "title": "Draft partner portal launch communications plan",
            "pillar": "pillar_1",
            "goal": provisional_id,
        },
    )

    assert refused["success"] is False
    assert "structuring" in refused.get("note", "")


CANONICAL_SECTIONS = (
    "# Tasks\n\n"
    "## This Week\n\n"
    "## P0 - Urgent (max 3)\n\n"
    "## P1 - Important (max 5)\n\n"
    "## P2 - Normal (max 10)\n\n"
    "## P3 - Backlog\n"
)


def test_create_task_defaults_to_matching_priority_section(task_vault):
    task_vault["tasks"].write_text(CANONICAL_SECTIONS, encoding="utf-8")

    created = _call_tool(
        "create_task",
        {
            "title": "Draft neutral launch briefing document",
            "pillar": "pillar_1",
            "priority": "P1",
        },
    )

    assert created["success"] is True
    assert created["task"]["section"] == "P1 - Important (max 5)"
    content = task_vault["tasks"].read_text(encoding="utf-8")
    p1_section = content.split("## P1 - Important (max 5)", 1)[1].split("## P2", 1)[0]
    assert "Draft neutral launch briefing document" in p1_section
    # No duplicate section was injected.
    assert content.count("## P1 - Important (max 5)") == 1


def test_create_task_falls_back_to_next_week_without_priority_sections(task_vault):
    created = _call_tool(
        "create_task",
        {
            "title": "Draft neutral launch briefing document",
            "pillar": "pillar_1",
            "priority": "P1",
        },
    )

    assert created["success"] is True
    assert created["task"]["section"] == "Next Week"
    assert "## Next Week" in task_vault["tasks"].read_text(encoding="utf-8")


def test_explicit_section_argument_still_wins(task_vault):
    task_vault["tasks"].write_text(CANONICAL_SECTIONS, encoding="utf-8")

    created = _call_tool(
        "create_task",
        {
            "title": "Draft neutral launch briefing document",
            "pillar": "pillar_1",
            "priority": "P1",
            "section": "This Week",
        },
    )

    assert created["success"] is True
    assert created["task"]["section"] == "This Week"

# ---------------------------------------------------------------------------
# Goal-backlog readers: list_tasks filters, get_goal_backlog, next-up ordering
# ---------------------------------------------------------------------------

from datetime import date  # noqa: E402

STRUCTURED_GOALS = (
    "---\n"
    "quarter: Q3 2026\n"
    "---\n\n"
    "# Quarter Goals\n\n"
    "### 1. Expand aurora coverage — **Other Pillar** ^Q3-2026-goal-1\n"
    "**Progress:** 0% 🔴\n\n"
    "### 2. Modernize ledger tooling — **Other Pillar** ^Q3-2026-goal-2\n"
    "**Progress:** 0% 🔴\n"
)

BACKLOG_TASKS = (
    "# Tasks\n\n"
    "## P1 - Important (max 5)\n"
    "- [ ] Aurora rollout step one ^task-20260601-001\n"
    "\t- Pillar: Test Pillar | Priority: P1 | Goal: Q3-2026-goal-1\n"
    "- [ ] Aurora rollout step two ^task-20260901-002\n"
    "\t- Pillar: Test Pillar | Priority: P0 | Goal: Q3-2026-goal-1\n"
    "- [ ] Aurora rollout step three ^task-20260901-003\n"
    "\t- Pillar: Test Pillar | Priority: P2 | Goal: Q3-2026-goal-1 | Next up: 1\n"
    "- [ ] Aurora rollout step four ^task-20260902-010\n"
    "\t- Pillar: Test Pillar | Priority: P1 | Goal: Q3-2026-goal-1\n"
    "- [ ] Ledger follow-through item ^task-20260901-004\n"
    "\t- Pillar: Test Pillar | Priority: P2 | Goal: Q3-2026-goal-2 (?)\n"
    "- [ ] Pillar only item ^task-20260901-005\n"
    "\t- Pillar: Test Pillar | Priority: P2\n"
    "- [ ] Zqx orphan item ^task-20260901-006\n"
    "- [ ] Project scoped item ^task-20260901-007\n"
    "\t- Pillar: Test Pillar | Priority: P2 | Project: 04-Projects/Aurora.md\n"
    "- [ ] Weekly linked item ^task-20260901-008\n"
    "\t- Pillar: Test Pillar | Priority: P2 | Weekly priority: [week-2026-W36-p1]\n"
    "- [x] Done goal item ✅ 2026-09-01 10:00 ^task-20260801-009\n"
    "\t- Pillar: Test Pillar | Priority: P2 | Goal: Q3-2026-goal-1\n"
)


@pytest.fixture
def backlog_vault(task_vault, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    task_vault["goals"].write_text(STRUCTURED_GOALS, encoding="utf-8")
    task_vault["tasks"].write_text(BACKLOG_TASKS, encoding="utf-8")
    # Staleness assertions must not rot as real time passes.
    monkeypatch.setattr(work_server, "_tz_today", lambda: date(2026, 9, 3))
    return task_vault


def _ids(tasks: list[dict]) -> list[str]:
    return [task.get("task_id") or task.get("id") for task in tasks]


def test_list_tasks_goal_filter_matches_linked_tasks(backlog_vault):
    result = _call_tool("list_tasks", {"goal": "Q3-2026-goal-1"})

    assert sorted(_ids(result["tasks"])) == [
        "task-20260601-001",
        "task-20260901-002",
        "task-20260901-003",
        "task-20260902-010",
    ]


def test_list_tasks_goal_none_returns_open_tasks_without_goal_link(backlog_vault):
    result = _call_tool("list_tasks", {"goal": "none"})

    assert sorted(_ids(result["tasks"])) == [
        "task-20260901-005",
        "task-20260901-006",
        "task-20260901-007",
        "task-20260901-008",
    ]


def test_list_tasks_goal_tentative_returns_only_unconfirmed_links(backlog_vault):
    result = _call_tool("list_tasks", {"goal": "tentative"})

    assert _ids(result["tasks"]) == ["task-20260901-004"]
    assert result["tasks"][0]["goal"] == "Q3-2026-goal-2"
    assert result["tasks"][0]["goal_tentative"] is True


def test_list_tasks_project_filter_ignores_md_suffix(backlog_vault):
    with_suffix = _call_tool("list_tasks", {"project": "04-Projects/Aurora.md"})
    without_suffix = _call_tool("list_tasks", {"project": "04-Projects/Aurora"})

    assert _ids(with_suffix["tasks"]) == ["task-20260901-007"]
    assert _ids(without_suffix["tasks"]) == ["task-20260901-007"]


def test_list_tasks_weekly_priority_filter(backlog_vault):
    result = _call_tool("list_tasks", {"weekly_priority": "week-2026-W36-p1"})

    assert _ids(result["tasks"]) == ["task-20260901-008"]


def test_list_tasks_goal_filter_composes_with_priority_filter(backlog_vault):
    result = _call_tool(
        "list_tasks", {"goal": "Q3-2026-goal-1", "priority": "P1"}
    )

    assert sorted(_ids(result["tasks"])) == [
        "task-20260601-001",
        "task-20260902-010",
    ]


def test_get_goal_backlog_groups_goal_then_pillar_then_orphaned(backlog_vault):
    result = _call_tool("get_goal_backlog", {"goal_id": "all"})

    groups_by_goal = {group["goal_id"]: group for group in result["goal_groups"]}
    goal_1 = groups_by_goal["Q3-2026-goal-1"]
    goal_2 = groups_by_goal["Q3-2026-goal-2"]

    # Open tasks only; the done task never appears.
    assert goal_1["count"] == 4
    assert "task-20260801-009" not in [task["id"] for task in goal_1["tasks"]]
    assert goal_1["goal_title"] == "Expand aurora coverage"

    # Tentative links stay in their goal's group, flagged for grooming.
    assert goal_2["count"] == 1
    assert goal_2["tasks"][0]["tentative"] is True

    [pillar_group] = result["pillar_groups"]
    assert pillar_group["pillar"] == "pillar_1"
    assert sorted(task["id"] for task in pillar_group["tasks"]) == [
        "task-20260901-005",
        "task-20260901-007",
        "task-20260901-008",
    ]

    assert [task["id"] for task in result["orphaned"]["tasks"]] == [
        "task-20260901-006"
    ]
    assert result["open_task_count"] == 9


def test_get_goal_backlog_orders_next_up_then_priority_then_age(backlog_vault):
    result = _call_tool("get_goal_backlog", {"goal_id": "Q3-2026-goal-1"})

    [group] = result["goal_groups"]
    assert [task["id"] for task in group["tasks"]] == [
        "task-20260901-003",  # next_up beats priority
        "task-20260901-002",  # P0 beats P1
        "task-20260601-001",  # older P1 beats newer P1
        "task-20260902-010",
    ]
    # A specific goal request returns only that group.
    assert result["pillar_groups"] == []
    assert result["orphaned"] is None


def test_get_goal_backlog_reports_staleness(backlog_vault):
    result = _call_tool("get_goal_backlog", {"goal_id": "Q3-2026-goal-1"})

    [group] = result["goal_groups"]
    by_id = {task["id"]: task for task in group["tasks"]}
    assert by_id["task-20260601-001"]["staleness_days"] == 94
    assert by_id["task-20260901-002"]["staleness_days"] == 2
    assert group["stale_count"] == 1
    assert result["stale_after_days"] == 21


def test_get_goal_backlog_rejects_unknown_goal(backlog_vault):
    result = _call_tool("get_goal_backlog", {"goal_id": "Q3-2026-goal-9"})

    assert result["success"] is False
    assert "Q3-2026-goal-1" in result["error"]


def test_get_goal_backlog_marks_provisional_goal_groups(task_vault):
    task_vault["goals"].write_text(FREEFORM_GOALS, encoding="utf-8")
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Zqx unlinked item ^task-20260901-030\n",
        encoding="utf-8",
    )

    result = _call_tool("get_goal_backlog", {"goal_id": "all"})

    assert result["provisional_count"] == 2
    assert "provisional" in result["provisional_note"]
    for group in result["goal_groups"]:
        assert group["provisional"] is True
        assert group["count"] == 0
        assert "cannot link" in group["note"]


def test_get_goal_backlog_surfaces_tasks_linked_to_missing_goals(backlog_vault):
    backlog_vault["goals"].write_text("# Quarter Goals\n", encoding="utf-8")

    result = _call_tool("get_goal_backlog", {"goal_id": "all"})

    groups_by_goal = {group["goal_id"]: group for group in result["goal_groups"]}
    assert groups_by_goal["Q3-2026-goal-1"]["goal_missing"] is True
    assert groups_by_goal["Q3-2026-goal-1"]["count"] == 4


def test_create_task_writes_next_up_and_it_round_trips(backlog_vault):
    created = _call_tool(
        "create_task",
        {
            "title": "Zqx sequencing candidate",
            "pillar": "pillar_1",
            "priority": "P2",
            "next_up": 2,
        },
    )

    assert created["success"] is True
    assert created["task"]["next_up"] == 2
    assert "| Next up: 2" in backlog_vault["tasks"].read_text(encoding="utf-8")

    task = next(
        t for t in work_server.parse_tasks_file(backlog_vault["tasks"])
        if t["task_id"] == created["task"]["task_id"]
    )
    assert task["next_up"] == 2


def test_create_task_rejects_non_positive_next_up(backlog_vault):
    result = _call_tool(
        "create_task",
        {
            "title": "Zqx sequencing candidate",
            "pillar": "pillar_1",
            "next_up": 0,
        },
    )

    assert result["success"] is False
    assert "next_up" in result["error"]


def test_set_task_next_up_add_update_clear_round_trip(task_vault):
    original = (
        "# Tasks\n\n## Next Week\n"
        "- [ ] Keep everything else intact ^task-20260901-020\n"
        "\t- some freeform context bullet\n"
        "\t- Pillar: Test Pillar | Priority: P2 | Goal: Q3-2026-goal-1\n"
        "- [ ] Neighbor task stays put ^task-20260901-021\n"
    )
    task_vault["tasks"].write_text(original, encoding="utf-8")

    added = _call_tool(
        "set_task_next_up", {"task_id": "task-20260901-020", "next_up": 3}
    )
    assert added["success"] is True
    assert added["next_up"] == 3
    assert added["previous_next_up"] is None

    after_add = task_vault["tasks"].read_text(encoding="utf-8")
    assert "\t- Next up: 3\n" in after_add
    # Everything that existed before is still there verbatim.
    for line in original.rstrip("\n").split("\n"):
        assert line in after_add
    [task_020] = [
        t for t in work_server.parse_tasks_file(task_vault["tasks"])
        if t["task_id"] == "task-20260901-020"
    ]
    assert task_020["next_up"] == 3
    assert task_020["goal"] == "Q3-2026-goal-1"

    updated = _call_tool(
        "set_task_next_up", {"task_id": "task-20260901-020", "next_up": 1}
    )
    assert updated["success"] is True
    assert updated["previous_next_up"] == 3
    [task_020] = [
        t for t in work_server.parse_tasks_file(task_vault["tasks"])
        if t["task_id"] == "task-20260901-020"
    ]
    assert task_020["next_up"] == 1

    cleared = _call_tool(
        "set_task_next_up", {"task_id": "task-20260901-020", "next_up": None}
    )
    assert cleared["success"] is True
    assert cleared["previous_next_up"] == 1
    assert task_vault["tasks"].read_text(encoding="utf-8") == original


def test_set_task_next_up_updates_inline_metadata_field_surgically(task_vault):
    task_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Inline ordered task ^task-20260901-022\n"
        "\t- Pillar: Test Pillar | Priority: P2 | Next up: 4\n",
        encoding="utf-8",
    )

    updated = _call_tool(
        "set_task_next_up", {"task_id": "task-20260901-022", "next_up": 2}
    )

    assert updated["success"] is True
    assert updated["previous_next_up"] == 4
    content = task_vault["tasks"].read_text(encoding="utf-8")
    assert "\t- Pillar: Test Pillar | Priority: P2 | Next up: 2\n" in content

    cleared = _call_tool(
        "set_task_next_up", {"task_id": "task-20260901-022"}
    )
    assert cleared["success"] is True
    content = task_vault["tasks"].read_text(encoding="utf-8")
    assert "Next up" not in content
    assert "\t- Pillar: Test Pillar | Priority: P2\n" in content


def test_set_task_next_up_clearing_when_unset_changes_nothing(task_vault):
    original = (
        "# Tasks\n\n## Next Week\n"
        "- [ ] Never ordered task ^task-20260901-023\n"
    )
    task_vault["tasks"].write_text(original, encoding="utf-8")

    cleared = _call_tool(
        "set_task_next_up", {"task_id": "task-20260901-023", "next_up": None}
    )

    assert cleared["success"] is True
    assert cleared["changed"] is False
    assert task_vault["tasks"].read_text(encoding="utf-8") == original


def test_set_task_next_up_unknown_task_errors(task_vault):
    result = _call_tool(
        "set_task_next_up", {"task_id": "task-20260901-099", "next_up": 1}
    )

    assert result["success"] is False
    assert result["error"] == "task not found"


def test_calculate_goal_progress_reports_task_counts(backlog_vault):
    progress = work_server.calculate_goal_progress("Q3-2026-goal-1")

    assert progress["open_tasks"] == 4
    assert progress["done_tasks"] == 1
    # The percentage formula is untouched: still priorities-only.
    assert progress["progress"] == 0
    assert progress["calculation_method"] == "no_linked_priorities"


def test_weekly_planning_context_surfaces_open_counts_and_top_next_up(backlog_vault):
    backlog_vault["tasks"].write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] Aurora queue slot one ^task-20260901-040\n"
        "\t- Pillar: Test Pillar | Priority: P2 | Goal: Q3-2026-goal-1 | Next up: 1\n"
        "- [ ] Aurora queue slot two ^task-20260901-041\n"
        "\t- Pillar: Test Pillar | Priority: P2 | Goal: Q3-2026-goal-1 | Next up: 2\n"
        "- [ ] Aurora queue slot three ^task-20260901-042\n"
        "\t- Pillar: Test Pillar | Priority: P2 | Goal: Q3-2026-goal-1 | Next up: 3\n"
        "- [ ] Aurora queue slot four ^task-20260901-043\n"
        "\t- Pillar: Test Pillar | Priority: P2 | Goal: Q3-2026-goal-1 | Next up: 4\n"
        "- [ ] Aurora unordered extra ^task-20260901-044\n"
        "\t- Pillar: Test Pillar | Priority: P2 | Goal: Q3-2026-goal-1\n",
        encoding="utf-8",
    )

    result = _call_tool("get_weekly_planning_context", {})

    goal_1 = next(
        g for g in result["goal_health"] if g["goal_id"] == "Q3-2026-goal-1"
    )
    assert goal_1["open_task_count"] == 5
    assert [t["task_id"] for t in goal_1["next_up_tasks"]] == [
        "task-20260901-040",
        "task-20260901-041",
        "task-20260901-042",
    ]

    goal_2 = next(
        g for g in result["goal_health"] if g["goal_id"] == "Q3-2026-goal-2"
    )
    assert goal_2["open_task_count"] == 0
    assert goal_2["next_up_tasks"] == []
