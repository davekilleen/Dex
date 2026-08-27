"""Lab / preview onboarding tools: identity batch, Google calendar, meeting source."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core" / "mcp"))

import onboarding_server  # noqa: E402


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    return json.loads(
        asyncio.run(onboarding_server.handle_call_tool(name, arguments or {}))[0].text
    )


@pytest.fixture
def lab_session(tmp_path, monkeypatch):
    session_file = tmp_path / "System" / ".onboarding-session.json"
    session_file.parent.mkdir(parents=True)
    monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
    monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
    return tmp_path


def test_lab_session_allows_name_before_calendar(lab_session) -> None:
    started = _call_tool("start_onboarding_session", {"force_new": True, "lab": True})
    assert started["success"] is True
    assert started["data"]["lab"] is True

    named = _call_tool(
        "validate_and_save_step",
        {"step_number": 1, "step_data": {"name": "Doireann Marron"}},
    )
    assert named["success"] is True


def test_shipped_session_still_requires_calendar_before_name(lab_session) -> None:
    _call_tool("start_onboarding_session", {"force_new": True})
    named = _call_tool(
        "validate_and_save_step",
        {"step_number": 1, "step_data": {"name": "Doireann Marron"}},
    )
    assert named["success"] is False


def test_save_identity_confirm_batches_name_company_and_domain(lab_session) -> None:
    _call_tool("start_onboarding_session", {"force_new": True, "lab": True})
    payload = _call_tool(
        "save_identity_confirm",
        {
            "name": "Doireann Marron",
            "company": "Pendo",
            "company_size": "enterprise",
            "email_domain": "pendo.io",
            "work_email": "doireann.marron@pendo.io",
        },
    )
    assert payload["success"] is True
    session = onboarding_server.load_session()
    assert session["data"]["name"] == "Doireann Marron"
    assert session["data"]["email_domain"] == "pendo.io"
    assert session["data"]["work_email"] == "doireann.marron@pendo.io"
    assert sorted(session["completed_steps"]) == [1, 3, 4]


def test_save_calendar_selection_returns_google_without_storing_it(lab_session) -> None:
    _call_tool("start_onboarding_session", {"force_new": True, "lab": True})
    payload = _call_tool(
        "save_calendar_selection",
        {"provider": "google", "account": "doireann.marron@pendo.io"},
    )
    assert payload["success"] is True
    assert payload["data"]["calendar_source"] == {
        "provider": "google",
        "account": "doireann.marron@pendo.io",
    }
    session = onboarding_server.load_session()
    assert session["calendar_addressed"] is True
    assert "calendar_source" not in session["data"]
    assert "work_email" not in session["data"]


def test_save_meeting_source_stays_on_session(lab_session) -> None:
    _call_tool("start_onboarding_session", {"force_new": True, "lab": True})
    payload = _call_tool(
        "save_meeting_source",
        {"primary": "granola", "notes_folder": ""},
    )
    assert payload["success"] is True
    session = onboarding_server.load_session()
    assert session["data"]["meeting_sources"] == {
        "primary": "granola",
        "notes_folder": "",
    }


def test_save_entity_creation_preference_stays_on_session(lab_session) -> None:
    _call_tool("start_onboarding_session", {"force_new": True, "lab": True})
    payload = _call_tool(
        "save_entity_creation_preference",
        {"automatic": True},
    )
    assert payload["success"] is True
    session = onboarding_server.load_session()
    assert session["data"]["entity_creation_automatic"] is True


def test_first_week_analysis_accepts_host_fetched_events(lab_session, monkeypatch) -> None:
    def boom():
        raise AssertionError("must not read Calendar.app when events are passed")

    monkeypatch.setattr(onboarding_server, "get_calendar_events_for_week", boom)
    granola_days = []

    def capture_granola(days=7):
        granola_days.append(days)
        return []

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 27, 12, 0)

    monkeypatch.setattr(onboarding_server, "datetime", FrozenDateTime)
    monkeypatch.setattr(onboarding_server, "get_recent_granola_meetings", capture_granola)
    (lab_session / "System" / "user-profile.yaml").write_text(
        "role: Customer Engineer\nemail_domain: pendo.io\npillars:\n  - name: Retention\n",
        encoding="utf-8",
    )

    payload = _call_tool(
        "run_first_week_analysis",
        {
            "events": [
                {
                    "title": "Caerus expansion",
                    "start": datetime(2026, 8, 27, 10, 0),
                    "end": datetime(2026, 8, 27, 11, 0),
                    "duration_minutes": 60,
                    "attendees": [
                        {
                            "name": "Doireann Marron",
                            "email": "doireann.marron@pendo.io",
                        }
                    ],
                },
                {
                    "title": "Doireann / Alex 1:1",
                    "start": datetime(2026, 8, 13, 15, 0),
                    "end": datetime(2026, 8, 13, 15, 30),
                    "duration_minutes": 30,
                    "attendees": [
                        {
                            "name": "Doireann Marron",
                            "email": "doireann.marron@pendo.io",
                            "is_current_user": True,
                        },
                        {"name": "Alex Rivera", "email": "alex.rivera@pendo.io"},
                    ],
                },
                {
                    "title": "Doireann / Alex 1:1",
                    "start": datetime(2026, 8, 20, 15, 0),
                    "end": datetime(2026, 8, 20, 15, 30),
                    "duration_minutes": 30,
                    "attendees": [
                        {
                            "name": "Doireann Marron",
                            "email": "doireann.marron@pendo.io",
                            "is_current_user": True,
                        },
                        {"name": "Alex Rivera", "email": "alex.rivera@pendo.io"},
                    ],
                },
            ]
        },
    )
    assert payload["success"] is True
    assert payload["data"]["available"] is True
    assert payload["data"]["meeting_count"] == 1
    assert granola_days == [21]
    cadence = payload["data"]["cadence"]
    assert cadence["window_days"] == 21
    assert cadence["meeting_count"] == 3
    assert cadence["recurring"][0]["title"] == "Doireann / Alex 1:1"
    assert cadence["recurring"][0]["count"] == 2
    assert cadence["likely_manager"]["name"] == "Alex Rivera"
    assert "ask, do not assume" in cadence["likely_manager"]["guess"]


def test_parse_provisioner_receipt_reads_json_wrapped_in_node_noise() -> None:
    receipt = onboarding_server._parse_provisioner_receipt(
        "npm warn old lockfile\n{\"ok\": true, \"created\": []}\n",
        "",
        lab=True,
    )
    assert receipt["ok"] is True


def test_parse_provisioner_receipt_lab_missing_helper_is_honest() -> None:
    with pytest.raises(RuntimeError, match="practice folder is missing a helper"):
        onboarding_server._parse_provisioner_receipt(
            "",
            "Error: Cannot find module 'js-yaml'",
            lab=True,
        )


def test_lab_tools_are_registered() -> None:
    names = {tool.name for tool in asyncio.run(onboarding_server.handle_list_tools())}
    assert "save_identity_confirm" in names
    assert "save_meeting_source" in names
    assert "save_entity_creation_preference" in names
