"""Golden journeys through the real onboarding and work MCP handlers."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core.utils.entity_pages import parse_entity_page

REPO_ROOT = Path(__file__).resolve().parents[2]

ONBOARDING_JOURNEY = r"""
import asyncio
import json

from core.mcp import onboarding_server as onboarding


def decode(contents):
    return json.loads(contents[0].text)


async def call(name, arguments=None):
    return decode(await onboarding.handle_call_tool(name, arguments or {}))


async def main():
    results = {}
    results["start"] = await call("start_onboarding_session", {"force_new": True})
    results["resume"] = await call("start_onboarding_session")

    onboarding.check_python_packages = lambda: {
        "mcp": {"installed": True},
        "yaml": {"installed": True},
        "aiohttp": {"installed": True},
    }
    onboarding.check_calendar_app = lambda: {"available": True}
    onboarding.check_granola = lambda: {"available": True}
    results["dependencies"] = await call("verify_dependencies")

    step_data = {
        1: {"name": "Golden User"},
        2: {"role_number": 1},
        3: {"company": "Golden Co", "company_size": "startup"},
        4: {"email_domain": "golden.example"},
        5: {"pillars": ["Customer", "Product"]},
        6: {
            "communication": {
                "formality": "professional_casual",
                "directness": "balanced",
                "career_level": "leadership",
            },
            "obsidian_mode": False,
        },
    }
    results["steps"] = [
        await call("validate_and_save_step", {"step_number": number, "step_data": data})
        for number, data in step_data.items()
    ]
    results["status"] = await call("get_onboarding_status")
    results["finalize"] = await call("finalize_onboarding")
    print(json.dumps(results))


asyncio.run(main())
"""

TASK_JOURNEY = r"""
import asyncio
import json
from pathlib import Path

from core.mcp import work_server as work


def decode(contents):
    return json.loads(contents[0].text)


async def call(name, arguments=None):
    return decode(await work.handle_call_tool(name, arguments or {}))


async def main():
    work.HAS_QMD = False
    work.is_qmd_available = lambda: False
    work.refresh_search_index = lambda: None
    work._fire_analytics_event = lambda *_args, **_kwargs: {"fired": False}

    title = "Prepare golden customer renewal brief"
    person_path = "05-Areas/People/Internal/Alice_Smith"
    person_file = work.BASE_DIR / f"{person_path}.md"
    tasks_file = work.BASE_DIR / "03-Tasks" / "Tasks.md"

    initial_summary = await call("get_work_summary")
    created = await call(
        "create_task",
        {
            "title": title,
            "pillar": "pillar_1",
            "priority": "P2",
            "section": "Next Week",
            "context": "Use the latest customer evidence.",
            "people": [person_path],
        },
    )
    created_summary = await call("get_work_summary")
    person_after_create = person_file.read_text(encoding="utf-8")
    tasks_after_create = tasks_file.read_text(encoding="utf-8")

    updated = await call(
        "update_task_status",
        {"task_id": created["task"]["task_id"], "status": "d"},
    )
    completed_summary = await call("get_work_summary")
    week_progress = await call("get_week_progress")

    print(
        json.dumps(
            {
                "title": title,
                "person_path": person_path,
                "initial_summary": initial_summary,
                "created": created,
                "created_summary": created_summary,
                "person_after_create": person_after_create,
                "tasks_after_create": tasks_after_create,
                "updated": updated,
                "completed_summary": completed_summary,
                "week_progress": week_progress,
                "person_after_complete": person_file.read_text(encoding="utf-8"),
                "tasks_after_complete": tasks_file.read_text(encoding="utf-8"),
            }
        )
    )


asyncio.run(main())
"""

ENTITY_CREATION_JOURNEY = r"""
const path = require('node:path');
const { processEntityCreation } = require(
  path.join(process.env.DEX_REPO_ROOT, '.scripts/meeting-intel/lib/entity-creation.cjs'),
);

const attendee = { name: 'Jane Doe', email: 'jane@acme.com', location: 'external' };
const meetings = [
  { id: 'golden-entity-1', createdAt: '2026-06-01T10:00:00Z', transcript: '', filteredAttendees: [attendee] },
  { id: 'golden-entity-2', createdAt: '2026-06-08T10:00:00Z', transcript: '', filteredAttendees: [attendee] },
];
const profile = { email_domain: 'dex.test', entity_creation: { mode: process.env.ENTITY_CREATION_MODE } };
const first = processEntityCreation(meetings, profile);
const second = processEntityCreation(meetings, profile);
console.log(JSON.stringify({ first, second }));
"""


def _copy_fixture_vault(fixture_vault: Path, tmp_path: Path, *, onboarding: bool = False) -> Path:
    vault = tmp_path / "vault"
    shutil.copytree(fixture_vault, vault)
    if onboarding:
        shutil.copy2(REPO_ROOT / "CLAUDE.md", vault / "CLAUDE.md")
        shutil.copy2(REPO_ROOT / "System" / ".mcp.json.example", vault / "System" / ".mcp.json.example")
    return vault


def _run_journey(vault: Path, source: str) -> dict:
    env = os.environ.copy()
    env["VAULT_PATH"] = str(vault)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def _run_entity_creation_journey(vault: Path, mode: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the entity-engine golden journey")
    env = os.environ.copy()
    env["VAULT_PATH"] = str(vault)
    # CLAUDE_PROJECT_DIR outranks VAULT_PATH in paths.cjs; an inherited value
    # (e.g. from a Claude Code shell) would silently point the engine at a
    # different vault, so pin it to the journey vault explicitly.
    env["CLAUDE_PROJECT_DIR"] = str(vault)
    env["DEX_REPO_ROOT"] = str(REPO_ROOT)
    env["ENTITY_CREATION_MODE"] = mode
    result = subprocess.run(
        [node, "-e", ENTITY_CREATION_JOURNEY],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def _write_entity_profile(vault: Path, mode: str) -> None:
    profile_path = vault / "System/user-profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    profile["email_domain"] = "dex.test"
    profile["entity_creation"] = {"mode": mode}
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")


def _write_synced_entity_meetings(vault: Path) -> None:
    for meeting_id, date in (("golden-entity-1", "2026-06-01"), ("golden-entity-2", "2026-06-08")):
        meeting_path = vault / "00-Inbox/Meetings" / date / f"{meeting_id}.md"
        meeting_path.parent.mkdir(parents=True, exist_ok=True)
        meeting_path.write_text(
            "---\n"
            f"date: {date}\n"
            "attendees:\n"
            "  - name: Jane Doe\n"
            "    email: jane@acme.com\n"
            "    location: external\n"
            "---\n"
            f"# Entity journey {date}\n",
            encoding="utf-8",
        )


def test_golden_onboarding_drives_state_machine_to_real_vault(fixture_vault: Path, tmp_path: Path):
    vault = _copy_fixture_vault(fixture_vault, tmp_path, onboarding=True)

    journey = _run_journey(vault, ONBOARDING_JOURNEY)

    assert journey["start"]["success"] is True
    assert journey["resume"]["success"] is True
    assert journey["start"]["data"]["started_at"] == journey["resume"]["data"]["started_at"]
    assert journey["resume"]["data"]["completed_steps"] == []
    assert "Resuming onboarding session" in journey["resume"]["message"]
    assert journey["dependencies"]["data"]["all_required_installed"] is True
    assert all(step["success"] for step in journey["steps"])
    assert journey["status"]["data"]["progress_percent"] == 100.0
    assert journey["status"]["data"]["ready_to_finalize"] is True
    assert journey["finalize"]["success"] is True
    assert journey["finalize"]["data"]["errors"] == []

    for directory in (
        "00-Inbox",
        "01-Quarter_Goals",
        "02-Week_Priorities",
        "03-Tasks",
        "04-Projects",
        "05-Areas",
        "06-Resources",
        "07-Archives",
        "System",
    ):
        assert (vault / directory).is_dir(), directory
    assert (vault / "03-Tasks/Tasks.md").is_file()
    assert (vault / "02-Week_Priorities/Week_Priorities.md").is_file()

    profile = yaml.safe_load((vault / "System/user-profile.yaml").read_text(encoding="utf-8"))
    assert profile["name"] == "Golden User"
    assert profile["role"] == "Product Manager"
    assert profile["company"] == "Golden Co"
    assert profile["company_size"] == "startup"
    assert profile["email_domain"] == "golden.example"
    assert profile["communication"]["career_level"] == "leadership"

    pillars = yaml.safe_load((vault / "System/pillars.yaml").read_text(encoding="utf-8"))
    assert [pillar["name"] for pillar in pillars["pillars"]] == ["Customer", "Product"]

    root_config = vault / ".mcp.json"
    config_text = root_config.read_text(encoding="utf-8")
    config = json.loads(config_text)
    assert "{{" not in config_text
    assert config["mcpServers"]["work-mcp"]["command"] == f"{vault}/.venv/bin/python"
    assert config["mcpServers"]["work-mcp"]["args"] == [f"{vault}/core/mcp/work_server.py"]
    assert config["mcpServers"]["work-mcp"]["env"]["VAULT_PATH"] == str(vault)
    assert not (vault / "System/.mcp.json").exists()
    assert (vault / "System/.onboarding-complete").is_file()
    assert not (vault / "System/.onboarding-session.json").exists()


def test_golden_task_lifecycle_propagates_and_rolls_up(fixture_vault: Path, tmp_path: Path):
    vault = _copy_fixture_vault(fixture_vault, tmp_path)

    journey = _run_journey(vault, TASK_JOURNEY)

    created = journey["created"]
    updated = journey["updated"]
    title = journey["title"]
    task_id = created["task"]["task_id"]
    assert created["success"] is True
    assert re.fullmatch(r"task-\d{8}-\d{3}", task_id)
    assert journey["person_path"] in created["synced_pages"]
    assert f"^{task_id}" in journey["tasks_after_create"]
    assert f"| ⏳ | {title} | P2 |" in journey["person_after_create"]

    assert updated["success"] is True
    assert updated["status"] == "completed"
    assert updated["instances_found"] == 1
    assert f"{journey['person_path']}.md" in updated["related_tasks_synced"]
    assert len(updated["updated_files"]) == 1
    completed_line = next(
        line for line in journey["tasks_after_complete"].splitlines() if f"^{task_id}" in line
    )
    assert completed_line.startswith("- [x]")
    assert completed_line.index(updated["completed_at"]) < completed_line.index(f"^{task_id}")
    assert f"| ✅ | {title} | P2 |" in journey["person_after_complete"]

    initial_active = journey["initial_summary"]["daily_summary"]["total_tasks"]
    created_active = journey["created_summary"]["daily_summary"]["total_tasks"]
    completed_active = journey["completed_summary"]["daily_summary"]["total_tasks"]
    assert created_active == initial_active + 1
    assert completed_active == initial_active
    assert journey["week_progress"]["tasks_completed_this_week"] == 1


def test_golden_entity_creation_auto_is_idempotent_and_verifies(
    fixture_vault: Path, tmp_path: Path
):
    vault = _copy_fixture_vault(fixture_vault, tmp_path)
    _write_entity_profile(vault, "auto")
    _write_synced_entity_meetings(vault)

    journey = _run_entity_creation_journey(vault, "auto")

    assert len(journey["first"]["created"]) == 1
    assert len(journey["first"]["companies_created"]) == 1
    assert journey["second"]["created"] == []
    assert journey["second"]["companies_created"] == []

    person = parse_entity_page(vault / "05-Areas/People/External/Jane_Doe.md")
    assert person["emails"] == ["jane@acme.com"]
    assert person["location"] == "external"
    assert person["quarantined"] is False

    company = parse_entity_page(vault / "05-Areas/Companies/Acme.md")
    assert company["domains"] == ["acme.com"]
    assert company["quarantined"] is False

    verification = subprocess.run(
        [shutil.which("node"), ".scripts/meeting-intel/verify-entities.cjs", "--days", "3650"],
        cwd=REPO_ROOT,
        env={**os.environ, "VAULT_PATH": str(vault)},
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert verification.returncode == 0, verification.stderr
    assert "0 unresolved" in verification.stdout


def test_golden_entity_creation_suggests_without_pages(fixture_vault: Path, tmp_path: Path):
    vault = _copy_fixture_vault(fixture_vault, tmp_path)
    _write_entity_profile(vault, "suggest")

    journey = _run_entity_creation_journey(vault, "suggest")

    assert journey["first"]["created"] == []
    assert journey["first"]["companies_created"] == []
    assert not (vault / "05-Areas/People/External/Jane_Doe.md").exists()
    assert not (vault / "05-Areas/Companies/Acme.md").exists()

    suggestions = json.loads(
        (vault / "System/.dex/entity-suggestions.json").read_text(encoding="utf-8")
    )["suggestions"]
    assert any(item["kind"] == "person" and item["name"] == "Jane Doe" for item in suggestions)
