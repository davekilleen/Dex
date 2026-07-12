"""Contract tests for feature availability responses."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from core.mcp import (
    analytics_server,
    calendar_server,
    career_server,
    granola_server,
    resume_server,
)
from core.utils import feature_status as feature_status_module


@pytest.mark.parametrize(
    ("state", "expected_success"),
    [
        ("ok", True),
        ("off", False),
        ("not_installed", False),
        ("broken", False),
        ("unknown", False),
    ],
)
def test_feature_status_derives_success_from_state(state, expected_success):
    result = feature_status_module.feature_status(
        "Example feature",
        state,
        "Example status",
    )

    assert result["success"] is expected_success
    assert result["feature"] == "Example feature"
    assert result["feature_status"] == state
    assert result["user_message"] == "Example status"


def test_feature_status_rejects_invalid_state():
    with pytest.raises(ValueError):
        feature_status_module.feature_status(
            "Example feature",
            "disabled",
            "Example status",
        )


def test_feature_status_passes_through_extra_keys():
    result = feature_status_module.feature_status(
        "Example feature",
        "off",
        "Example status",
        connected=False,
        message="Legacy message",
    )

    assert result["connected"] is False
    assert result["message"] == "Legacy message"


def test_feature_status_includes_detail_only_when_given():
    without_detail = feature_status_module.feature_status(
        "Example feature",
        "off",
        "Example status",
    )
    with_detail = feature_status_module.feature_status(
        "Example feature",
        "broken",
        "Example status",
        detail="Diagnostic detail",
    )

    assert "detail" not in without_detail
    assert with_detail["detail"] == "Diagnostic detail"


def _decode_tool_result(result):
    return json.loads(result[0].text)


def test_granola_without_api_key_reports_off_and_preserves_legacy_keys(monkeypatch):
    monkeypatch.setattr(granola_server, "get_api_key", lambda: None)

    payload = _decode_tool_result(
        asyncio.run(granola_server.handle_call_tool("granola_check_available", {}))
    )

    assert payload["feature"] == "Granola meeting sync"
    assert payload["feature_status"] == "off"
    assert payload["user_message"] == granola_server.NOT_CONNECTED_MESSAGE
    assert payload["success"] is False
    assert payload["connected"] is False
    assert payload["message"] == granola_server.NOT_CONNECTED_MESSAGE


def test_calendar_eventkit_permission_failure_reports_broken_and_preserves_error(
    monkeypatch,
):
    error = "Calendar permission denied"

    def deny_calendar(script_name, operation, *args):
        assert script_name == "calendar_eventkit.py"
        assert operation == "list"
        return False, error

    monkeypatch.setattr(calendar_server, "run_shell_script", deny_calendar)

    payload = _decode_tool_result(
        asyncio.run(
            calendar_server._handle_call_tool_inner("calendar_list_calendars", {})
        )
    )

    assert payload["feature"] == "Calendar access"
    assert payload["feature_status"] == "broken"
    assert payload["user_message"] == error
    assert payload["success"] is False
    assert payload["error"] == error


@pytest.mark.parametrize(
    ("success", "output", "expected_message"),
    [
        (False, "Reminders permission denied", "Reminders permission denied"),
        (True, "not valid JSON", "JSON parse error:"),
    ],
)
def test_reminders_failures_report_broken_and_preserve_error(
    monkeypatch,
    success,
    output,
    expected_message,
):
    monkeypatch.setattr(
        calendar_server,
        "run_shell_script",
        lambda *_args: (success, output),
    )

    payload = _decode_tool_result(
        asyncio.run(
            calendar_server._handle_call_tool_inner("reminders_list_items", {})
        )
    )

    assert payload["feature"] == "Reminders access"
    assert payload["feature_status"] == "broken"
    assert expected_message in payload["user_message"]
    assert payload["success"] is False
    assert payload["error"] == payload["user_message"]


def test_missing_career_folder_reports_off_and_preserves_setup_guidance(
    monkeypatch,
    tmp_path,
):
    career_dir = tmp_path / "vault" / "05-Areas" / "Career"
    evidence_dir = career_dir / "Evidence"
    monkeypatch.setattr(career_server, "CAREER_DIR", career_dir)
    monkeypatch.setattr(career_server, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(career_server, "LADDER_FILE", career_dir / "Career_Ladder.md")

    payload = _decode_tool_result(
        asyncio.run(career_server.handle_call_tool("scan_evidence", {}))
    )

    assert payload["feature"] == "Career evidence"
    assert payload["feature_status"] == "off"
    assert payload["user_message"] == payload["error"]
    assert payload["success"] is False
    assert payload["error"] == f"Evidence directory not found: {evidence_dir}"
    assert payload["note"] == "Run /career-setup to initialize your career system"
    assert not career_dir.exists()


def test_missing_career_ladder_reports_off_and_preserves_setup_guidance(
    monkeypatch,
    tmp_path,
):
    evidence_dir = tmp_path / "Career" / "Evidence"
    evidence_dir.mkdir(parents=True)
    ladder_file = tmp_path / "Career" / "Career_Ladder.md"
    monkeypatch.setattr(career_server, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(career_server, "LADDER_FILE", ladder_file)

    payload = _decode_tool_result(
        asyncio.run(career_server.handle_call_tool("analyze_coverage", {}))
    )

    assert payload["feature"] == "Career ladder"
    assert payload["feature_status"] == "off"
    assert payload["user_message"] == payload["error"]
    assert payload["success"] is False
    assert payload["error"] == "Career ladder file not found"
    assert payload["note"] == "Run /career-setup to create your career ladder"


def test_existing_unreadable_career_ladder_reports_broken(monkeypatch, tmp_path):
    ladder_file = tmp_path / "Career_Ladder.md"
    ladder_file.write_text("not a valid ladder")
    monkeypatch.setattr(career_server, "LADDER_FILE", ladder_file)
    monkeypatch.setattr(
        career_server,
        "parse_ladder_file",
        lambda _path: {"error": "Could not parse career ladder"},
    )

    payload = _decode_tool_result(
        asyncio.run(career_server.handle_call_tool("parse_ladder", {}))
    )

    assert payload["feature"] == "Career ladder"
    assert payload["feature_status"] == "broken"
    assert payload["user_message"] == "Could not parse career ladder"
    assert payload["success"] is False
    assert payload["error"] == "Could not parse career ladder"


def test_career_ladder_without_competencies_reports_broken(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "Career" / "Evidence"
    evidence_dir.mkdir(parents=True)
    ladder_file = tmp_path / "Career" / "Career_Ladder.md"
    ladder_file.write_text("# Career ladder")
    ladder_data = {"competencies": [], "competency_count": 0}
    monkeypatch.setattr(career_server, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(career_server, "LADDER_FILE", ladder_file)
    monkeypatch.setattr(career_server, "parse_ladder_file", lambda _path: ladder_data)

    payload = _decode_tool_result(
        asyncio.run(career_server.handle_call_tool("analyze_coverage", {}))
    )

    assert payload["feature"] == "Career ladder"
    assert payload["feature_status"] == "broken"
    assert payload["user_message"] == payload["error"]
    assert payload["success"] is False
    assert payload["error"] == "Failed to parse career ladder or no competencies found"
    assert payload["ladder_data"] == ladder_data


def test_resume_missing_career_evidence_reports_off_and_preserves_keys(
    monkeypatch,
    tmp_path,
):
    role = resume_server.Role(
        role_id="role-1",
        title="Product lead",
        company="Dex",
        start_date="2025-01",
        end_date="present",
        responsibilities="Lead product work",
    )
    session = resume_server.ResumeSession(
        session_id="session-1",
        created_at="2026-07-11T00:00:00",
        last_modified="2026-07-11T00:00:00",
        phase=resume_server.PhaseEnum.ROLES,
        approach="from_scratch",
        roles=[role],
    )
    monkeypatch.setattr(resume_server, "sessions", {session.session_id: session})
    monkeypatch.setattr(resume_server, "EVIDENCE_DIR", tmp_path / "Career" / "Evidence")

    payload = _decode_tool_result(
        asyncio.run(
            resume_server.handle_pull_career_evidence(
                {"session_id": session.session_id, "role_id": role.role_id}
            )
        )
    )

    assert payload["feature"] == "Career evidence"
    assert payload["feature_status"] == "off"
    assert payload["user_message"] == payload["error"]
    assert payload["success"] is False
    assert payload["error"] == "Career Evidence directory not found"
    assert payload["note"] == "Run /career-setup to initialize career system"


def test_analytics_missing_requests_reports_not_installed_and_preserves_error(
    monkeypatch,
):
    monkeypatch.setattr(analytics_server, "HAS_REQUESTS", False)

    payload = _decode_tool_result(
        asyncio.run(analytics_server._call_tool_inner("test_connection", {}))
    )

    assert payload["feature"] == "Usage analytics"
    assert payload["feature_status"] == "not_installed"
    assert payload["user_message"] == payload["error"]
    assert payload["success"] is False
    assert payload["error"] == "requests library not installed. Run: pip install requests"


def test_analytics_http_failure_reports_broken_and_preserves_transport_keys(
    monkeypatch,
):
    monkeypatch.setattr(analytics_server, "HAS_REQUESTS", True)
    monkeypatch.setattr(
        analytics_server,
        "get_analytics_transport",
        lambda: {
            "configured": True,
            "mode": "proxy",
            "endpoint": "https://analytics.example.test",
            "headers": {},
        },
    )
    monkeypatch.setattr(
        analytics_server,
        "get_visitor_info",
        lambda: {"visitor_id": "visitor-123", "account_id": "account-123"},
    )
    monkeypatch.setattr(
        analytics_server.requests,
        "post",
        lambda *args, **kwargs: SimpleNamespace(status_code=503, text="unavailable"),
    )

    payload = _decode_tool_result(
        asyncio.run(analytics_server._call_tool_inner("test_connection", {}))
    )

    assert payload["feature"] == "Usage analytics"
    assert payload["feature_status"] == "broken"
    assert payload["user_message"] == "Analytics connection failed (HTTP 503)."
    assert payload["success"] is False
    assert payload["status"] == 503
    assert payload["transport_mode"] == "proxy"
    assert payload["transport_endpoint"] == "https://analytics.example.test"
    assert payload["body"] == "unavailable"


def test_analytics_request_exception_reports_broken_and_preserves_error(monkeypatch):
    monkeypatch.setattr(analytics_server, "HAS_REQUESTS", True)
    monkeypatch.setattr(
        analytics_server,
        "get_analytics_transport",
        lambda: {
            "configured": True,
            "mode": "proxy",
            "endpoint": "https://analytics.example.test",
            "headers": {},
        },
    )
    monkeypatch.setattr(
        analytics_server,
        "get_visitor_info",
        lambda: {"visitor_id": "visitor-123", "account_id": "account-123"},
    )

    def raise_network_error(*_args, **_kwargs):
        raise OSError("network unavailable")

    monkeypatch.setattr(analytics_server.requests, "post", raise_network_error)

    payload = _decode_tool_result(
        asyncio.run(analytics_server._call_tool_inner("test_connection", {}))
    )

    assert payload["feature"] == "Usage analytics"
    assert payload["feature_status"] == "broken"
    assert payload["user_message"] == "network unavailable"
    assert payload["success"] is False
    assert payload["error"] == "network unavailable"
