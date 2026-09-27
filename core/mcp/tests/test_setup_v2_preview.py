"""No-write /setup-v2 preview — existing vault stays byte-identical."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from core.mcp import onboarding_server
from core.onboarding.preview_sandbox import (
    PREFIX,
    PreviewWriteRefused,
    assert_preview_write_allowed,
    begin_preview,
    discard_preview,
    is_preview_active,
    leftover_preview_dirs,
    preview_sandbox_root,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _decode_tool_result(result) -> dict:
    return json.loads(result[0].text)


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    return _decode_tool_result(
        asyncio.run(onboarding_server.handle_call_tool(name, arguments or {}))
    )


def _file_mode(path: Path) -> int:
    return path.lstat().st_mode & 0o777


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int]]:
    """Hash every path, bytes, and mode, plus the directory listing."""
    snapshot: dict[str, tuple[str, int]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        mode = _file_mode(path)
        if path.is_symlink():
            snapshot[relative] = (f"link->{os.readlink(path)}", mode)
        elif path.is_dir():
            snapshot[relative] = ("dir", mode)
        elif path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            snapshot[relative] = (digest, mode)
        else:
            snapshot[relative] = (f"other:{stat.S_IFMT(path.lstat().st_mode)}", mode)
    snapshot["."] = ("dir", _file_mode(root))
    snapshot["__listing__"] = (
        hashlib.sha256(
            "\n".join(sorted(snapshot)).encode("utf-8")
        ).hexdigest(),
        0,
    )
    return snapshot


def _point_server_at(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    system = vault / "System"
    monkeypatch.setattr(onboarding_server, "BASE_DIR", vault)
    monkeypatch.setattr(onboarding_server, "SESSION_FILE", system / ".onboarding-session.json")
    monkeypatch.setattr(onboarding_server, "MARKER_FILE", system / ".onboarding-complete")
    monkeypatch.setattr(
        onboarding_server,
        "MCP_CONFIG_EXAMPLE",
        system / ".mcp.json.example",
    )


def _existing_vault(root: Path) -> Path:
    """Realistic already-set-up Dex: settings, people, config, work files."""
    vault = root / "existing-vault"
    system = vault / "System"
    people_internal = vault / "05-Areas" / "People" / "Internal"
    people_external = vault / "05-Areas" / "People" / "External"
    for folder in (
        system / "integrations",
        people_internal,
        people_external,
        vault / "03-Tasks",
        vault / "01-Quarter_Goals",
        vault / "02-Week_Priorities",
        vault / "04-Projects",
        vault / "00-Inbox" / "Meetings",
    ):
        folder.mkdir(parents=True)

    (system / "user-profile.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "Jane Doe",
                "role": "Product lead",
                "company": "Example Co",
                "company_size": "startup",
                "email_domain": "example.com",
                "work_email": "jane@example.com",
                "entity_creation": {"mode": "suggest"},
                "capabilities": {
                    "career": {"enabled": True},
                    "companies": {"enabled": True},
                    "quarter_goals": {"enabled": True},
                },
                "communication": {
                    "formality": "professional_casual",
                    "directness": "balanced",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (system / "pillars.yaml").write_text(
        yaml.safe_dump(
            {
                "pillars": [
                    {
                        "id": "retention",
                        "name": "Customer retention",
                        "description": "Keep the accounts that already trust us",
                        "keywords": ["renewal", "health"],
                    },
                    {
                        "id": "product",
                        "name": "Product strategy",
                        "description": "Ship the shared inbox",
                        "keywords": ["inbox", "roadmap"],
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (system / "integrations" / "config.yaml").write_text(
        "todoist:\n  enabled: false\n",
        encoding="utf-8",
    )
    (system / ".mcp.json.example").write_text("{}\n", encoding="utf-8")
    (system / ".onboarding-complete").write_text(
        json.dumps(
            {
                "completed": True,
                "completed_at": "2026-03-01T12:00:00.000Z",
                "user_name": "Jane Doe",
                "role": "Product lead",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (people_internal / "Sam_Lee.md").write_text(
        "# Sam Lee\n\nRole: Engineering\nCompany: Northwind\n",
        encoding="utf-8",
    )
    (people_external / "Riley_Chen.md").write_text(
        "# Riley Chen\n\nRole: Design partner\nCompany: Contoso\n",
        encoding="utf-8",
    )
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "- [ ] Review renewal notes ^task-20260301-001\n",
        encoding="utf-8",
    )
    (vault / "01-Quarter_Goals" / "Quarter_Goals.md").write_text(
        "# Quarter goals\n\n- Shared inbox live\n",
        encoding="utf-8",
    )
    (vault / "02-Week_Priorities" / "Week_Priorities.md").write_text(
        "# This week\n\n- Prep Riley review\n",
        encoding="utf-8",
    )
    (vault / "04-Projects" / "Shared_Inbox.md").write_text(
        "# Shared Inbox\n\nStatus: in flight\n",
        encoding="utf-8",
    )
    (vault / "00-Inbox" / "Meetings" / "2026-03-02 - Design partner.md").write_text(
        "# Design partner\n\nFollow up with Riley.\n",
        encoding="utf-8",
    )
    (vault / "CLAUDE.md").write_text("# Dex\n\nExisting workspace.\n", encoding="utf-8")
    (vault / ".mcp.json").write_text("{}\n", encoding="utf-8")
    return vault


def _isolated_home(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = root / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    (home / ".config").mkdir(parents=True)
    (home / ".claude").mkdir(parents=True)
    (home / "Library" / "LaunchAgents" / "keep.plist").write_text(
        "existing\n",
        encoding="utf-8",
    )
    (home / ".config" / "dex-keep").write_text("keep\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    return home


def _run_preview_journey() -> dict[str, object]:
    """Full first-hour tool path, including connection, sync, and discard."""
    started = _call_tool("start_onboarding_session", {"preview": True})
    assert started["success"] is True, started
    assert started["data"]["preview"] is True
    sandbox = Path(started["data"]["sandbox"])
    assert sandbox.is_dir()
    assert sandbox.name.startswith(PREFIX)

    calendar = _call_tool("save_calendar_selection", {"skipped": True})
    assert calendar["success"] is True, calendar

    harness = _call_tool(
        "save_harness_selection",
        {"harnesses": ["cursor"], "confirmed": True},
    )
    assert harness["success"] is True, harness

    steps = (
        (1, {"name": "Alex Rivera"}),
        (2, {"role": "Product Manager", "role_group": "product"}),
        (3, {"company": "Northwind", "company_size": "startup"}),
        (4, {"email_domain": "example.com"}),
        (5, {"pillars": ["Customer retention", "Product strategy"]}),
        (6, {"communication": {}}),
        (
            7,
            {
                "working_week": {
                    "days": [
                        "monday",
                        "tuesday",
                        "wednesday",
                        "thursday",
                        "friday",
                    ]
                }
            },
        ),
    )
    for number, data in steps:
        saved = _call_tool(
            "validate_and_save_step",
            {"step_number": number, "step_data": data},
        )
        assert saved["success"] is True, saved

    assert _call_tool("save_source_doc_note", {"status": "skipped"})["success"] is True
    assert _call_tool("save_meeting_source", {"primary": "none"})["success"] is True

    finalized = _call_tool("finalize_onboarding", {})
    assert finalized["success"] is True, finalized

    analysis = _call_tool(
        "run_first_week_analysis",
        {
            "v2": True,
            "events": [
                {
                    "title": "1:1 with Sam",
                    "start": datetime(2026, 9, 29, 10, 0).isoformat(),
                    "end": datetime(2026, 9, 29, 10, 30).isoformat(),
                    "attendees": [],
                }
            ],
        },
    )
    assert analysis["success"] is True, analysis

    context = _call_tool(
        "preview_confirmed_onboarding_context",
        {
            "working_context": {
                "role_focus": "Ship the shared inbox",
                "key_people": [],
            },
            "calendar_source": {"provider": "none"},
        },
    )
    assert context["success"] is True, context
    applied = _call_tool(
        "apply_confirmed_onboarding_context",
        {
            "preview": context["data"]["preview"],
            "approval_token": context["data"]["approval_token"],
        },
    )
    assert applied["success"] is True, applied

    calendar_nudge = _call_tool("generate_nudge_calendar", {})
    assert calendar_nudge["success"] is True, calendar_nudge

    connection = _call_tool("preview_connection_step", {"kind": "notes"})
    assert connection["success"] is True, connection
    assert connection["data"]["noop"] is True
    assert connection["data"]["installed"] is False

    sync = _call_tool("preview_sync_install", {"kind": "launch-agent"})
    assert sync["success"] is True, sync
    assert sync["data"]["noop"] is True
    assert sync["data"]["installed"] is False

    offer = _call_tool("prepare_entity_page_offer", {"v2_window": True})
    assert offer["success"] is True, offer
    if offer["data"].get("suggestions"):
        declined = _call_tool(
            "respond_to_entity_page_offer",
            {
                "action": "no",
                "suggestion_ids": [offer["data"]["suggestions"][0]["id"]],
                "v2_window": True,
            },
        )
        assert declined["success"] is True, declined

    discarded = _call_tool("discard_preview_session", {})
    assert discarded["success"] is True, discarded
    assert discarded["data"]["nothing_saved"] is True
    assert discarded["data"]["sandbox_gone"] is True
    return {"sandbox": sandbox, "discarded": discarded}


def test_preview_tools_are_registered() -> None:
    tools = {
        tool.name: tool
        for tool in asyncio.run(onboarding_server.handle_list_tools())
    }
    assert "preview" in tools["start_onboarding_session"].inputSchema["properties"]
    assert tools["start_onboarding_session"].inputSchema["properties"]["preview"].get(
        "default"
    ) is False
    assert "discard_preview_session" in tools
    assert "preview_connection_step" in tools
    assert "preview_sync_install" in tools


def test_existing_vault_offers_preview_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _existing_vault(tmp_path)
    home = _isolated_home(tmp_path, monkeypatch)
    _point_server_at(vault, monkeypatch)
    before_vault = _tree_snapshot(vault)
    before_home = _tree_snapshot(home)

    offered = _call_tool("start_onboarding_session", {"v2": True})
    assert offered["success"] is True, offered
    assert offered["data"]["existing_vault"] is True
    assert offered["data"]["offer_preview"] is True
    assert offered["data"]["attached"] is False
    assert is_preview_active() is False
    assert _tree_snapshot(vault) == before_vault
    assert _tree_snapshot(home) == before_home
    assert leftover_preview_dirs() == []


def test_preview_journey_leaves_existing_vault_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _existing_vault(tmp_path)
    home = _isolated_home(tmp_path, monkeypatch)
    _point_server_at(vault, monkeypatch)
    before_vault = _tree_snapshot(vault)
    before_home = _tree_snapshot(home)

    try:
        result = _run_preview_journey()
    finally:
        if is_preview_active():
            discard_preview()

    assert not result["sandbox"].exists()
    assert leftover_preview_dirs() == []
    assert is_preview_active() is False
    assert preview_sandbox_root() is None
    assert _tree_snapshot(vault) == before_vault
    assert _tree_snapshot(home) == before_home
    assert onboarding_server.BASE_DIR == vault
    assert onboarding_server.MARKER_FILE == vault / "System" / ".onboarding-complete"


def test_preview_refuses_writes_outside_the_temp_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _existing_vault(tmp_path)
    home = _isolated_home(tmp_path, monkeypatch)
    _point_server_at(vault, monkeypatch)
    before_vault = _tree_snapshot(vault)
    before_home = _tree_snapshot(home)

    sandbox = begin_preview(vault)
    try:
        outside = home / "Library" / "LaunchAgents" / "sneak.plist"
        with pytest.raises(PreviewWriteRefused, match="outside sandbox"):
            outside.write_text("nope\n", encoding="utf-8")
        with pytest.raises(PreviewWriteRefused, match="outside sandbox"):
            (vault / "System" / "user-profile.yaml").write_text(
                "name: hacked\n",
                encoding="utf-8",
            )
        with pytest.raises(PreviewWriteRefused, match="outside sandbox"):
            assert_preview_write_allowed(tmp_path / "escape.txt")
        with pytest.raises(PreviewWriteRefused, match="subprocess"):
            import subprocess

            subprocess.run(["launchctl", "load", str(outside)], check=False)
        (sandbox / "ok.txt").write_text("sandbox only\n", encoding="utf-8")
    finally:
        discard_preview()

    assert not sandbox.exists()
    assert _tree_snapshot(vault) == before_vault
    assert _tree_snapshot(home) == before_home


def test_stale_preview_dirs_are_wiped_on_next_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _existing_vault(tmp_path)
    _isolated_home(tmp_path, monkeypatch)
    leftover = Path(tempfile.gettempdir()) / f"{PREFIX}stale-test"
    leftover.mkdir(parents=True, exist_ok=True)
    (leftover / "dirt.txt").write_text("old\n", encoding="utf-8")
    sandbox = begin_preview(vault)
    try:
        assert leftover.exists() is False
        assert sandbox.is_dir()
    finally:
        discard_preview()
    assert leftover.exists() is False
    assert sandbox.exists() is False
