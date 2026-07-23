"""Golden journeys through the real onboarding and work MCP handlers."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from core.entity_engine import cooling
from core.entity_engine.contract import render_person_page
from core.lifecycle import service as lifecycle_service
from core.tests.test_adoption_messy_vault_journey import (
    _created_ancestors,
    _transaction_paths,
)
from core.tests.test_adoption_transaction import _setup as setup_adoption_release
from core.tests.test_lifecycle_bridge import _write_bridge_release
from core.tests.vault_observed_writes import assert_observed_writes, snapshot_vault
from core.utils import doctor
from core.utils.entity_pages import parse_entity_page

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_service_owned_repair_crosses_transaction_and_declares_every_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E5: Doctor's Tier-1 repair has no vault write outside its receipt."""
    vault = tmp_path / "repair-vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    context = doctor.DoctorContext(
        vault_root=vault,
        repo_root=vault,
        home=home,
        now=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )
    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)
    script = vault / ".scripts/repair-me.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o644)
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [script])

    receipts: list[dict[str, object]] = []
    real_execute = doctor.lifecycle_service._execute_approved_transaction

    def record_execute(*args, **kwargs):
        response = real_execute(*args, **kwargs)
        receipts.append(response["receipt"])
        return response

    monkeypatch.setattr(
        doctor.lifecycle_service,
        "_execute_approved_transaction",
        record_execute,
    )

    before = snapshot_vault(vault)
    actions, errors = doctor._apply_t1_heals(context)
    after = snapshot_vault(vault)

    assert errors == []
    assert "regenerated core/paths.json" in actions
    assert any("restored executable permission" in action for action in actions)
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["purpose"] == "doctor-tier-1"
    assert [entry["path"] for entry in receipt["files_written"]] == [
        ".scripts/repair-me.sh",
        "core/paths.json",
    ]
    assert receipt["transaction_id"]
    changed = assert_observed_writes(before, after, set(receipt["declared_paths"]))
    assert {".scripts/repair-me.sh", "core/paths.json"} <= changed
    assert any(path.startswith("System/.dex/tx/") for path in changed)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_fresh_install_bootstrap_is_provision_receipt_declared(tmp_path: Path) -> None:
    """E5: the legitimate pre-engine bootstrap is bounded by its contract receipt."""
    vault = tmp_path / "fresh-vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    (vault / ".scripts").mkdir()
    for source, relative in (
        (REPO_ROOT / "System/.mcp.json.example", "System/.mcp.json.example"),
        (
            REPO_ROOT / "System/user-profile-template.yaml",
            "System/user-profile-template.yaml",
        ),
        (REPO_ROOT / "core/paths.py", "core/paths.py"),
        (REPO_ROOT / "package.json", "package.json"),
        (REPO_ROOT / "CLAUDE.md", "CLAUDE.md"),
    ):
        shutil.copy2(source, vault / relative)
    profile = tmp_path / "fresh-profile.json"
    profile.write_text(
        json.dumps(
            {
                "name": "Fresh User",
                "work_email": "fresh@example.com",
                "pillars": [{"name": "Build"}],
            }
        ),
        encoding="utf-8",
    )

    before = snapshot_vault(vault)
    completed = subprocess.run(
        [
            "node",
            str(REPO_ROOT / "core/provision.cjs"),
            "--path",
            str(vault),
            "--profile",
            str(profile),
            "--json",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    receipt = summary["mutation_receipt"]
    assert receipt["executor"] == "provision-contract-bootstrap"
    assert receipt["lifecycle_transaction_id"] is None
    assert_observed_writes(before, snapshot_vault(vault), set(receipt["declared_paths"]))


def test_update_and_rollback_skills_are_service_renderers_without_raw_mutation() -> None:
    update = (REPO_ROOT / ".claude/skills/dex-update/SKILL.md").read_text(encoding="utf-8")
    rollback = (REPO_ROOT / ".claude/skills/dex-rollback/SKILL.md").read_text(
        encoding="utf-8"
    )

    for operation in (
        "build_inventory_and_plan",
        "build_and_preview_adoption",
        "execute_approved_adoption",
        "read_lifecycle_state",
    ):
        assert operation in update
    for operation in ("read_lifecycle_state", "rewind_adoption_by_receipt"):
        assert operation in rollback
    for instructions in (update, rollback):
        lowered = instructions.lower()
        for forbidden in (
            "cp -r",
            "sed -i",
            "git merge",
            "git reset",
            "shutil.copy",
            ".write_text(",
            ".write_bytes(",
        ):
            assert forbidden not in lowered


def test_upgrade_and_rollback_cross_frozen_service_with_receipt_only_writes(
    tmp_path: Path,
) -> None:
    """E5/E10: service adoption and rewind exactly match receipt-derived writes."""
    (tmp_path / "release-fixture").mkdir()
    release, _document, _catalog, _inventory, _plan, _loader = setup_adoption_release(
        tmp_path / "release-fixture",
        item_ids=("alpha",),
    )
    _write_bridge_release(release)
    vault = tmp_path / "installed-vault"
    shutil.copytree(release, vault)
    target = ".claude/skills/alpha/SKILL.md"
    (vault / target).unlink()

    inventory = lifecycle_service.build_inventory_and_plan(vault)
    assert inventory["plan"]["items"][0]["action"] == "adopt"

    before_upgrade = snapshot_vault(vault)
    preview = lifecycle_service.build_and_preview_adoption(vault, release, ("alpha",))
    executed = lifecycle_service.execute_approved_adoption(
        vault,
        release,
        preview["preview"],
        preview["approval_token"],
    )
    receipt = executed["receipt"]
    tx_id = receipt["transaction_id"]
    receipt_path = f"System/.dex/adoptions/{tx_id}.receipt.json"
    upgrade_declared = {
        target,
        receipt_path,
        "System/.dex/ledger/.write.lock",
        "System/.dex/ledger/events/00000001-install-registered.json",
        "System/.dex/ledger/events/00000002-adoption-recorded.json",
        "System/.dex/ledger/commitments/00000001.sha256",
        "System/.dex/ledger/commitments/00000002.sha256",
        "System/.dex/ledger/state.json",
    }
    upgrade_declared |= _transaction_paths(
        tx_id,
        writes_payload=True,
        snapshot_blob=False,
    )
    for path in tuple(upgrade_declared):
        upgrade_declared |= _created_ancestors(path, before_upgrade)
    assert_observed_writes(before_upgrade, snapshot_vault(vault), upgrade_declared)

    before_rollback = snapshot_vault(vault)
    rewound = lifecycle_service.rewind_adoption_by_receipt(
        vault,
        receipt,
        executed["rewind_acknowledgement_token"],
    )["rewind_receipt"]
    rewind_tx_id = rewound["rewind_transaction_id"]
    rollback_declared = {
        target,
        "System/.dex/ledger/events/00000003-rewind-recorded.json",
        "System/.dex/ledger/commitments/00000003.sha256",
        "System/.dex/ledger/state.json",
    }
    rollback_declared |= _transaction_paths(
        rewind_tx_id,
        writes_payload=False,
        snapshot_blob=True,
    )
    for path in tuple(rollback_declared):
        rollback_declared |= _created_ancestors(path, before_rollback)
    assert_observed_writes(before_rollback, snapshot_vault(vault), rollback_declared)
    assert not (vault / target).exists()

ONBOARDING_JOURNEY = r"""
import asyncio
import json

from core.mcp import onboarding_server as onboarding
from core.tests.vault_observed_writes import changed_vault_paths, snapshot_vault


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
        7: {
            "capabilities": {
                "career": True,
                "companies": True,
                "quarter_goals": True,
            }
        },
    }
    results["steps"] = [
        await call("validate_and_save_step", {"step_number": number, "step_data": data})
        for number, data in step_data.items()
    ]
    results["status"] = await call("get_onboarding_status")
    before_finalize = snapshot_vault(onboarding.BASE_DIR)
    results["finalize"] = await call("finalize_onboarding")
    results["finalize_observed"] = sorted(
        changed_vault_paths(before_finalize, snapshot_vault(onboarding.BASE_DIR))
    )
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
const fs = require('node:fs');
const path = require('node:path');
const { processEntityCreation } = require(
  path.join(process.env.DEX_REPO_ROOT, '.scripts/meeting-intel/lib/entity-creation.cjs'),
);

const attendee = { name: 'Jane Doe', email: 'jane@example.com', location: 'external' };
const meetings = [
  { id: 'golden-entity-1', createdAt: '2026-06-01T10:00:00Z', transcript: '', filteredAttendees: [attendee] },
  { id: 'golden-entity-2', createdAt: '2026-06-08T10:00:00Z', transcript: '', filteredAttendees: [attendee] },
];
const profile = { email_domain: 'dex.test', entity_creation: { mode: process.env.ENTITY_CREATION_MODE } };
const personPath = path.join(
  process.env.VAULT_PATH, '05-Areas', 'People', 'External', 'Jane_Doe.md',
);
const first = processEntityCreation(meetings, profile);
const personAfterFirst = fs.existsSync(personPath) ? fs.readFileSync(personPath, 'utf8') : null;
const second = processEntityCreation(meetings, profile);
const personAfterSecond = fs.existsSync(personPath) ? fs.readFileSync(personPath, 'utf8') : null;
console.log(JSON.stringify({ first, second, personAfterFirst, personAfterSecond }));
"""


def _copy_fixture_vault(fixture_vault: Path, tmp_path: Path, *, onboarding: bool = False) -> Path:
    vault = tmp_path / "vault"
    shutil.copytree(fixture_vault, vault)
    if onboarding:
        shutil.copy2(REPO_ROOT / "CLAUDE.md", vault / "CLAUDE.md")
        shutil.copy2(REPO_ROOT / "System" / ".mcp.json.example", vault / "System" / ".mcp.json.example")
        (vault / "core").mkdir(exist_ok=True)
        shutil.copy2(REPO_ROOT / "core" / "paths.py", vault / "core" / "paths.py")
        shutil.copy2(REPO_ROOT / "package.json", vault / "package.json")
        (vault / ".scripts").mkdir()
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
    # The bridge routes entity writes through the Python engine, which needs a
    # resolvable interpreter. A real vault carries its own .venv (the fixture's
    # work-mcp command points at {vault}/.venv/bin/python); the tmp copy has none,
    # so pin DEX_PYTHON to the interpreter running this suite (it has the deps).
    env["DEX_PYTHON"] = os.environ.get("DEX_PYTHON", sys.executable)
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
    # The entity fixture models an ACTIVE, already-onboarded vault; the marker
    # engages the legacy capability bridge (rooms keep their pre-rooms status
    # quo) that background company creation depends on.
    (vault / "System" / ".onboarding-complete").write_text("{}\n", encoding="utf-8")


def _write_synced_entity_meetings(vault: Path) -> None:
    for meeting_id, date in (("golden-entity-1", "2026-06-01"), ("golden-entity-2", "2026-06-08")):
        meeting_path = vault / "00-Inbox/Meetings" / date / f"{meeting_id}.md"
        meeting_path.parent.mkdir(parents=True, exist_ok=True)
        meeting_path.write_text(
            "---\n"
            f"date: {date}\n"
            "attendees:\n"
            "  - name: Jane Doe\n"
            "    email: jane@example.com\n"
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
    assert journey["finalize"]["data"]["executor"] == "core/provision.cjs"
    assert journey["finalize_observed"] == journey["finalize"]["data"]["receipt"][
        "mutation_receipt"
    ]["declared_paths"]

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
    assert person["emails"] == ["jane@example.com"]
    assert person["location"] == "external"
    assert person["quarantined"] is False
    assert person["touches"] == [
        {
            "ts": "2026-06-01",
            "type": "meeting",
            "direction": "none",
            "source": {
                "id": "golden-entity-1",
                "title": "Meeting 2026-06-01",
            },
        },
        {
            "ts": "2026-06-08",
            "type": "meeting",
            "direction": "none",
            "source": {
                "id": "golden-entity-2",
                "title": "Meeting 2026-06-08",
            },
        },
    ]
    assert all(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", touch["ts"])
        for touch in person["touches"]
    )
    assert person["last_touched"] == "2026-06-08"
    update_log = re.search(
        r"<!-- dex:auto:update-log -->\n(.*?)\n<!-- /dex:auto -->",
        journey["personAfterFirst"],
        re.DOTALL,
    )
    assert update_log is not None
    assert update_log.group(1).splitlines() == [
        "- 2026-06-01 — meeting · two-way — Meeting 2026-06-01 [golden-entity-1]",
        "- 2026-06-08 — meeting · two-way — Meeting 2026-06-08 [golden-entity-2]",
    ]
    assert journey["personAfterSecond"] == journey["personAfterFirst"]

    company = parse_entity_page(vault / "05-Areas/Companies/Example.md")
    assert company["domains"] == ["example.com"]
    assert company["quarantined"] is False

    zero_touch_path = vault / "05-Areas/People/External/Zero_Touch.md"
    zero_touch_path.write_text(
        render_person_page(
            "Zero Touch",
            emails=["zero@example.org"],
            location="external",
        ),
        encoding="utf-8",
    )
    cooling_result = cooling.cooling_report(
        vault,
        now=datetime(2027, 1, 1, tzinfo=timezone.utc),
        people_dir=vault / "05-Areas/People",
        companies_dir=vault / "05-Areas/Companies",
    )
    cold_names = {item["name"] for item in cooling_result["cold"]}
    assert "Jane Doe" in cold_names
    assert "Zero Touch" not in cold_names

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
