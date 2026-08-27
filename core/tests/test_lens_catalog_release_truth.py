"""Release-truth checks for catalogue availability claims."""

from __future__ import annotations

import json
from pathlib import Path

from core.lens_catalog_discovery import discover_active_skills, discover_system_engines

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "core/lens-catalog/registry.json"


def test_held_connect_doorway_is_not_shipped_as_active() -> None:
    active_ids = {item.capability_id for item in discover_active_skills(REPO_ROOT)}
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry_ids = {entry["id"] for entry in registry["entries"]}
    engines = {item.capability_id: item for item in discover_system_engines(REPO_ROOT)}

    assert not (REPO_ROOT / ".claude/skills/connect/SKILL.md").exists()
    assert "connect" not in active_ids
    assert "connect" not in registry_ids
    connection_manager = engines["connection-manager-engine"]
    assert connection_manager.availability == "parked"
    assert connection_manager.source_paths
    assert all(".test." not in Path(path).name for path in connection_manager.source_paths)
