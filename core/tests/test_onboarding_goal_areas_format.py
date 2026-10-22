"""DEX-250: first-time setup must write goal areas that quarterly goals accept.

Onboarding used to save focus areas as a list of names (or objects with only a
name). The goals feature required ``{id, name}`` and rejected those files, so
goals broke immediately after setup. Existing vaults still have the older shape.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from core.mcp import work_server
from core.tests.test_provision_parity import _prepare_provision_vault, _run_provision
from core.utils.validators import normalize_pillar, validate_pillars_config


def _create_goal(title: str, pillar: str) -> dict:
    result = asyncio.run(
        work_server.handle_call_tool(
            "create_quarterly_goal",
            {
                "title": title,
                "pillar": pillar,
                "success_criteria": "The goal is usable after setup",
                "quarter": "Q4 2026",
            },
        )
    )
    return json.loads(result[0].text)


def _point_work_server_at(
    vault: Path, monkeypatch: pytest.MonkeyPatch, *, pillars_file: Path
) -> None:
    goals = vault / "01-Quarter_Goals" / "Quarter_Goals.md"
    goals.parent.mkdir(parents=True, exist_ok=True)
    profile = vault / "System" / "user-profile.yaml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    if not profile.exists():
        profile.write_text(
            "capabilities:\n  quarter_goals:\n    enabled: true\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(work_server, "BASE_DIR", vault)
    monkeypatch.setattr(work_server, "PILLARS_FILE", pillars_file)
    monkeypatch.setattr(work_server, "get_pillars_file", lambda: pillars_file)
    monkeypatch.setattr(work_server, "QUARTER_GOALS_FILE", goals)
    monkeypatch.setattr(work_server, "USER_PROFILE_FILE", profile)
    monkeypatch.setattr(work_server, "_tz_today", lambda: date(2026, 10, 2))
    monkeypatch.setattr(
        work_server, "_tz_now", lambda: datetime(2026, 10, 2, 9, 15)
    )
    monkeypatch.setattr(work_server, "_fire_analytics_event", lambda *a, **k: None)
    monkeypatch.setattr(work_server, "refresh_search_index", lambda: None)
    monkeypatch.setattr(work_server, "_PILLARS_SIGNATURE", ("stale", 0, 0))
    monkeypatch.setattr(work_server, "PILLARS", work_server.DEFAULT_PILLARS.copy())


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_fresh_setup_goal_areas_are_accepted_by_create_quarterly_goal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = _prepare_provision_vault(tmp_path)
    overlay = tmp_path / "setup-profile.json"
    overlay.write_text(
        json.dumps(
            {
                "name": "Setup User",
                "role": "Founder",
                "email_domain": "example.com",
                "pillars": [{"name": "Ship", "description": ""}, {"name": "Learn Fast"}],
            }
        ),
        encoding="utf-8",
    )

    _run_provision(vault, "--onboard", "--profile", str(overlay))

    pillars_doc = yaml.safe_load(
        (vault / "System/pillars.yaml").read_text(encoding="utf-8")
    )
    assert validate_pillars_config(pillars_doc) == []
    assert pillars_doc["pillars"] == [
        {"id": "ship", "name": "Ship", "description": ""},
        {"id": "learn-fast", "name": "Learn Fast", "description": ""},
    ]
    profile = yaml.safe_load(
        (vault / "System/user-profile.yaml").read_text(encoding="utf-8")
    )
    assert profile["pillars"] == [
        {"id": "ship", "name": "Ship", "description": ""},
        {"id": "learn-fast", "name": "Learn Fast", "description": ""},
    ]

    _point_work_server_at(
        vault, monkeypatch, pillars_file=vault / "System" / "pillars.yaml"
    )

    by_id = _create_goal("Land the first release", "ship")
    by_name = _create_goal("Run the learning loop", "Learn Fast")

    assert by_id["success"] is True, by_id
    assert by_name["success"] is True, by_name
    written = (vault / "01-Quarter_Goals/Quarter_Goals.md").read_text(encoding="utf-8")
    assert "### 1. Land the first release — **Ship** ^Q4-2026-goal-1" in written
    assert "### 2. Run the learning loop — **Learn Fast** ^Q4-2026-goal-2" in written


def test_old_format_string_goal_areas_are_accepted_by_create_quarterly_goal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "old-vault"
    pillars_file = vault / "System" / "pillars.yaml"
    pillars_file.parent.mkdir(parents=True)
    # The shape first-time setup used to write, and that existing users still have.
    pillars_file.write_text("pillars:\n  - Ship\n  - Learn Fast\n", encoding="utf-8")

    assert validate_pillars_config(
        yaml.safe_load(pillars_file.read_text(encoding="utf-8"))
    ) == []
    assert normalize_pillar("Ship") == {
        "id": "ship",
        "name": "Ship",
        "description": "",
        "keywords": [],
    }

    _point_work_server_at(vault, monkeypatch, pillars_file=pillars_file)

    loaded = work_server.load_pillars_from_yaml()
    assert set(loaded) == {"ship", "learn-fast"}
    assert loaded["learn-fast"]["name"] == "Learn Fast"

    result = _create_goal("Keep an older setup working", "Learn Fast")

    assert result["success"] is True, result
    written = (vault / "01-Quarter_Goals/Quarter_Goals.md").read_text(encoding="utf-8")
    assert (
        "### 1. Keep an older setup working — **Learn Fast** ^Q4-2026-goal-1"
        in written
    )


def test_old_format_name_only_objects_are_accepted_by_create_quarterly_goal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "old-object-vault"
    pillars_file = vault / "System" / "pillars.yaml"
    pillars_file.parent.mkdir(parents=True)
    pillars_file.write_text(
        "pillars:\n  - name: Ship\n    description: ''\n  - name: Learn Fast\n",
        encoding="utf-8",
    )

    _point_work_server_at(vault, monkeypatch, pillars_file=pillars_file)

    result = _create_goal("Name-only objects still work", "ship")

    assert result["success"] is True, result
    assert work_server.resolve_pillar_id("Learn Fast") == "learn-fast"
