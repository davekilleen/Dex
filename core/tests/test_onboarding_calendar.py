from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
import yaml

from core.mcp import calendar_server, onboarding_server

REPO_ROOT = Path(__file__).resolve().parents[2]


def _decode_tool_result(result):
    return json.loads(result[0].text)


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    return _decode_tool_result(
        asyncio.run(onboarding_server.handle_call_tool(name, arguments or {}))
    )


@pytest.fixture
def onboarding_vault(tmp_path, monkeypatch) -> Path:
    vault = tmp_path / "vault"
    system_dir = vault / "System"
    system_dir.mkdir(parents=True)

    profile_template = system_dir / "user-profile-template.yaml"
    shutil.copy2(REPO_ROOT / "System" / "user-profile-template.yaml", profile_template)

    monkeypatch.setattr(onboarding_server, "BASE_DIR", vault)
    monkeypatch.setattr(
        onboarding_server,
        "SESSION_FILE",
        system_dir / ".onboarding-session.json",
    )
    monkeypatch.setattr(
        onboarding_server,
        "USER_PROFILE_FILE",
        system_dir / "user-profile.yaml",
    )
    monkeypatch.setattr(onboarding_server, "USER_PROFILE_TEMPLATE", profile_template)
    return vault


def _start_session() -> None:
    result = _call_tool("start_onboarding_session", {"force_new": True})
    assert result["success"] is True


def test_save_calendar_selection_stores_valid_live_calendar(
    onboarding_vault,
    monkeypatch,
):
    monkeypatch.setattr(
        calendar_server,
        "_get_calendar_list_result",
        lambda: {
            "success": True,
            "calendars": ["Home", "dave@dex.ai"],
            "count": 2,
        },
    )
    _start_session()

    result = _call_tool(
        "save_calendar_selection",
        {
            "work_calendar": "dave@dex.ai",
            "work_email": "dave@dex.ai",
            "calendar_count": 2,
        },
    )

    assert result["success"] is True
    session = onboarding_server.load_session()
    assert session["data"]["work_email"] == "dave@dex.ai"
    assert session["data"]["calendar"] == {
        "work_calendar": "dave@dex.ai",
        "calendar_count": 2,
        "lazy_load": True,
    }


def test_save_calendar_selection_rejects_name_missing_from_live_calendars(
    onboarding_vault,
    monkeypatch,
):
    available = ["Home", "Team Calendar"]
    monkeypatch.setattr(
        calendar_server,
        "_get_calendar_list_result",
        lambda: {"success": True, "calendars": available, "count": len(available)},
    )
    _start_session()

    result = _call_tool(
        "save_calendar_selection",
        {"work_calendar": "Guessed Work", "calendar_count": 2},
    )

    assert result["success"] is False
    assert all(name in result["error"] for name in available)
    assert "calendar" not in onboarding_server.load_session()["data"]


@pytest.mark.parametrize("failure_mode", ["raises", "returns_failure"])
def test_save_calendar_selection_accepts_value_when_live_list_is_unavailable(
    onboarding_vault,
    monkeypatch,
    failure_mode,
):
    if failure_mode == "raises":
        def unavailable_calendar_list():
            raise RuntimeError("Calendar permission denied")
    else:
        def unavailable_calendar_list():
            return {"success": False, "error": "Calendar permission denied"}

    monkeypatch.setattr(
        calendar_server,
        "_get_calendar_list_result",
        unavailable_calendar_list,
    )
    _start_session()

    result = _call_tool(
        "save_calendar_selection",
        {"work_calendar": "Team Calendar", "calendar_count": 3},
    )

    assert result["success"] is True
    assert "couldn't verify against your live calendars" in result["message"].lower()
    assert onboarding_server.load_session()["data"]["calendar"] == {
        "work_calendar": "Team Calendar",
        "calendar_count": 3,
        "lazy_load": True,
    }


def test_save_calendar_selection_marks_permissions_pending_when_skipped(
    onboarding_vault,
    monkeypatch,
):
    def fail_if_called():
        raise AssertionError("skip should not list calendars")

    monkeypatch.setattr(calendar_server, "_get_calendar_list_result", fail_if_called)
    _start_session()

    result = _call_tool("save_calendar_selection", {"skipped": True})

    assert result["success"] is True
    assert "/dex-doctor" in result["message"]
    assert onboarding_server.load_session()["data"]["calendar"] == {
        "permissions_pending": True,
    }


def test_save_calendar_selection_clears_old_email_for_non_email_calendar(
    onboarding_vault,
    monkeypatch,
):
    monkeypatch.setattr(
        calendar_server,
        "_get_calendar_list_result",
        lambda: {
            "success": True,
            "calendars": ["dave@dex.ai", "Team Calendar"],
            "count": 2,
        },
    )
    _start_session()
    first_result = _call_tool(
        "save_calendar_selection",
        {
            "work_calendar": "dave@dex.ai",
            "work_email": "dave@dex.ai",
            "calendar_count": 2,
        },
    )
    assert first_result["success"] is True

    second_result = _call_tool(
        "save_calendar_selection",
        {"work_calendar": "Team Calendar", "calendar_count": 2},
    )

    assert second_result["success"] is True
    assert "work_email" not in onboarding_server.load_session()["data"]


def test_save_calendar_selection_clears_old_email_when_skipped(
    onboarding_vault,
    monkeypatch,
):
    monkeypatch.setattr(
        calendar_server,
        "_get_calendar_list_result",
        lambda: {
            "success": True,
            "calendars": ["dave@dex.ai"],
            "count": 1,
        },
    )
    _start_session()
    first_result = _call_tool(
        "save_calendar_selection",
        {
            "work_calendar": "dave@dex.ai",
            "work_email": "dave@dex.ai",
            "calendar_count": 1,
        },
    )
    assert first_result["success"] is True

    skipped_result = _call_tool("save_calendar_selection", {"skipped": True})

    assert skipped_result["success"] is True
    assert "work_email" not in onboarding_server.load_session()["data"]


def test_save_calendar_selection_requires_calendar_name(onboarding_vault):
    _start_session()

    result = _call_tool("save_calendar_selection")

    assert result["success"] is False
    assert "work_calendar" in result["error"]


def test_save_calendar_selection_is_registered():
    tools = asyncio.run(onboarding_server.handle_list_tools())

    assert "save_calendar_selection" in {tool.name for tool in tools}


def test_create_user_profile_writes_calendar_selection(onboarding_vault):
    session = onboarding_server.create_new_session()
    session["data"] = {
        "work_email": "dave@dex.ai",
        "calendar": {
            "work_calendar": "dave@dex.ai",
            "calendar_count": 4,
            "lazy_load": True,
        },
    }

    assert onboarding_server.create_user_profile(session) is True

    profile = yaml.safe_load(
        (onboarding_vault / "System" / "user-profile.yaml").read_text()
    )
    assert profile["work_email"] == "dave@dex.ai"
    assert profile["calendar"] == {
        "work_calendar": "dave@dex.ai",
        "calendar_count": 4,
        "lazy_load": True,
    }


def test_create_user_profile_writes_pending_calendar_permissions(onboarding_vault):
    session = onboarding_server.create_new_session()
    session["data"] = {"calendar": {"permissions_pending": True}}

    assert onboarding_server.create_user_profile(session) is True

    profile = yaml.safe_load(
        (onboarding_vault / "System" / "user-profile.yaml").read_text()
    )
    assert profile["calendar"] == {"permissions_pending": True}


def test_finalize_dry_run_previews_calendar_selection(onboarding_vault):
    session = onboarding_server.create_new_session()
    session["completed_steps"] = [1, 2, 3, 4, 5, 6]
    session["data"] = {
        "name": "Dave",
        "role": "Founder",
        "email_domain": "dex.ai",
        "pillars": ["Product", "Customers"],
        "work_email": "dave@dex.ai",
        "calendar": {
            "work_calendar": "dave@dex.ai",
            "calendar_count": 2,
            "lazy_load": True,
        },
    }
    assert onboarding_server.save_session(session) is True

    result = _call_tool("finalize_onboarding", {"dry_run": True})

    assert result["success"] is True
    assert result["data"]["preview_user_profile"]["work_email"] == "dave@dex.ai"
    assert result["data"]["preview_user_profile"]["calendar"] == {
        "work_calendar": "dave@dex.ai",
        "calendar_count": 2,
        "lazy_load": True,
    }
