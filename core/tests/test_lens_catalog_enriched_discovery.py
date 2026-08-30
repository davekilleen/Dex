"""Repository discovery gates for the enriched Dex Lens preview."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.lens_catalog_discovery import (
    LensDiscoveryError,
    _automation_cadence,
    discover_mcp_server_source,
    discover_mcp_servers,
    discover_scheduled_automations,
    discover_system_engines,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ENRICHED_REGISTRY = REPO_ROOT / "core/lens-catalog/enriched-registry.json"


def _write_mcp_server(root: Path, *, duplicate_server: bool = False) -> Path:
    path = root / "core/mcp/example_server.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    second_server = 'shadow = Server("dex-example")\n' if duplicate_server else ""
    path.write_text(
        "from mcp.server import Server\n"
        "from mcp.types import Tool\n\n"
        'server = Server("dex-example")\n'
        f"{second_server}"
        "@server.list_tools()\n"
        "async def list_tools():\n"
        '    return [Tool(name="example_tool", description="Example.", inputSchema={})]\n',
        encoding="utf-8",
    )
    return path


def test_discovers_every_core_and_integration_mcp_server() -> None:
    servers = discover_mcp_servers(REPO_ROOT)

    assert len(servers) == 11
    assert sum(server.tool_count for server in servers) == 151
    assert {server.server_name: server.tool_count for server in servers} == {
        "dex-analytics": 4,
        "dex-calendar-mcp": 15,
        "dex-career-mcp": 8,
        "dex-customization-migration-mcp": 7,
        "dex-granola-mcp": 6,
        "dex-improvements-mcp": 9,
        "dex-onboarding-mcp": 17,
        "dex-pipedrive-mcp": 15,
        "dex-resume-mcp": 12,
        "dex-session-memory": 8,
        "dex-work-mcp": 50,
    }
    assert all(server.capability_id == server.server_name for server in servers)
    assert all(server.source_path.endswith("_server.py") for server in servers)
    assert all(1 <= len(server.example_tools) <= 5 for server in servers)
    assert all(tuple(sorted(server.example_tools)) == server.example_tools for server in servers)
    pipedrive = next(server for server in servers if server.server_name == "dex-pipedrive-mcp")
    assert pipedrive.source_path == "core/integrations/pipedrive/pipedrive_server.py"


def test_mcp_discovery_rejects_untracked_source(tmp_path: Path) -> None:
    source = _write_mcp_server(tmp_path)
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)

    with pytest.raises(LensDiscoveryError, match="not tracked"):
        discover_mcp_server_source(tmp_path, source)


def test_mcp_discovery_rejects_symlinked_parent(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    source = _write_mcp_server(real.parent)
    source.rename(real / source.name)
    source.parent.rmdir()
    source.parent.symlink_to(real, target_is_directory=True)

    with pytest.raises(LensDiscoveryError, match="symlink"):
        discover_mcp_server_source(tmp_path, source.parent / source.name)


def test_mcp_discovery_rejects_duplicate_literal_server_declarations(tmp_path: Path) -> None:
    source = _write_mcp_server(tmp_path, duplicate_server=True)

    with pytest.raises(LensDiscoveryError, match="exactly one literal Server name"):
        discover_mcp_server_source(tmp_path, source)


def test_discovers_four_plists_and_daily_backup_scheduler() -> None:
    automations = discover_scheduled_automations(REPO_ROOT)

    assert [(item.capability_id, item.cadence) for item in automations] == [
        ("dex-changelog-checker", "every 6 hours; also at load"),
        ("dex-learning-review", "daily at 17:00"),
        ("dex-meeting-intel", "every 30 minutes; also at load"),
        ("dex-smoke-nightly", "daily at 03:15"),
        ("dex-vault-backup", "daily at a user-selected time"),
    ]
    assert all(item.source_paths for item in automations)
    assert all(item.installer_path for item in automations)
    assert all(item.program_target for item in automations)


@pytest.mark.parametrize(
    "calendar",
    [
        {"Hour": 24, "Minute": 0},
        {"Hour": 12, "Minute": 60},
        {"Hour": 12, "Minute": 0, "Weekday": 1},
    ],
)
def test_automation_cadence_rejects_invalid_or_nondaily_calendar_fields(
    calendar: dict[str, int],
) -> None:
    with pytest.raises(LensDiscoveryError, match="unsupported cadence"):
        _automation_cadence({"StartCalendarInterval": calendar}, source="invalid.plist")


def test_discovers_five_reviewed_system_engine_groups() -> None:
    engines = discover_system_engines(REPO_ROOT)

    assert [engine.capability_id for engine in engines] == [
        "connection-manager-engine",
        "entity-temperature-engine",
        "proactive-promise-engine",
        "ritual-intelligence-engine",
        "session-hook-orchestration",
    ]
    assert next(item for item in engines if item.capability_id == "ritual-intelligence-engine").availability == "parked"
    assert all(engine.component_count == len(engine.source_paths) > 0 for engine in engines)
    assert all(1 <= len(engine.example_components) <= 5 for engine in engines)
    hooks = next(item for item in engines if item.capability_id == "session-hook-orchestration")
    assert all(not path.startswith(".claude/hooks/tests/") for path in hooks.source_paths)
    temperature = next(item for item in engines if item.capability_id == "entity-temperature-engine")
    assert "core/entity_engine/temperature.py" in temperature.source_paths
    assert "core/entity_engine/cooling.py" in temperature.source_paths


def test_enriched_registry_exactly_annotates_every_non_skill_candidate() -> None:
    registry = json.loads(ENRICHED_REGISTRY.read_text(encoding="utf-8"))
    entries = registry["entries"]
    discovered = {
        "mcp-server": {item.capability_id for item in discover_mcp_servers(REPO_ROOT)},
        "scheduled-automation": {item.capability_id for item in discover_scheduled_automations(REPO_ROOT)},
        "system-engine": {item.capability_id for item in discover_system_engines(REPO_ROOT)},
    }

    assert registry["registry_version"] == 1
    assert len(entries) == 21
    assert len({entry["id"] for entry in entries}) == 21
    for capability_class, expected_ids in discovered.items():
        assert {entry["id"] for entry in entries if entry["capability_class"] == capability_class} == expected_ids
    assert all(entry["impact_tier"] in {"core", "high", "medium", "niche"} for entry in entries)
    assert all(entry["availability"] in {"active", "parked"} for entry in entries)
