"""Opt-in /setup-v2 onboarding MCP — shipped defaults stay unchanged."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from core.lifecycle import service
from core.mcp import onboarding_server
from core.mcp.tests.test_onboarding_entity_offer import (
    _configure_vault,
    _meeting,
    _prepare,
)
from core.tests.test_onboarding_context_lifecycle import _vault
from core.transaction.engine import PlanRejected

REPO_ROOT = Path(__file__).resolve().parents[3]


def _decode_tool_result(result) -> dict:
    return json.loads(result[0].text)


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    return _decode_tool_result(
        asyncio.run(onboarding_server.handle_call_tool(name, arguments or {}))
    )


def _timed_week_events() -> list[dict]:
    return [
        {
            "title": "1:1 with Sam",
            "start": datetime(2026, 7, 28, 10, 0),
            "end": datetime(2026, 7, 28, 10, 30),
            "attendees": [
                {"name": "Alex", "email": "alex@acme.com", "is_current_user": True},
                {"name": "Sam", "email": "sam@acme.com"},
            ],
        },
        {
            "title": "Out of office",
            "start": datetime(2026, 7, 29, 0, 0),
            "end": datetime(2026, 7, 30, 0, 0),
            "all_day": True,
            "attendees": [],
        },
    ]


def _session_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    system = tmp_path / "System"
    system.mkdir(parents=True)
    session_file = system / ".onboarding-session.json"
    monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
    monkeypatch.setattr(onboarding_server, "MARKER_FILE", system / ".onboarding-complete")
    return tmp_path


def test_v2_tools_are_registered() -> None:
    tools = {
        tool.name: tool
        for tool in asyncio.run(onboarding_server.handle_list_tools())
    }
    assert "save_meeting_source" in tools
    assert "save_source_doc_note" in tools
    start = tools["start_onboarding_session"].inputSchema["properties"]
    assert "v2" in start
    assert start["v2"].get("default") is False
    prepare = tools["prepare_entity_page_offer"].inputSchema["properties"]
    assert prepare["v2_window"].get("default") is False
    respond = tools["respond_to_entity_page_offer"].inputSchema["properties"]
    assert respond["v2_window"].get("default") is False
    assert respond["suggestion_ids"]["maxItems"] == 5


def test_default_start_session_has_no_v2_journey(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_vault(tmp_path, monkeypatch)
    payload = _call_tool("start_onboarding_session", {"force_new": True})
    assert payload["success"] is True
    assert payload["data"].get("journey") is None
    session = onboarding_server.create_new_session()
    assert "journey" not in session


def test_v2_clean_first_run_and_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_vault(tmp_path, monkeypatch)
    created = _call_tool("start_onboarding_session", {"v2": True})
    assert created["success"] is True
    assert created["data"]["journey"] == "v2"
    first_started = created["data"]["started_at"]

    resumed = _call_tool("start_onboarding_session", {"v2": True})
    assert resumed["success"] is True
    assert resumed["data"]["journey"] == "v2"
    assert resumed["data"]["started_at"] == first_started
    assert "Resuming" in resumed["message"]


def test_v2_does_not_attach_to_mid_shipped_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_vault(tmp_path, monkeypatch)
    shipped = _call_tool("start_onboarding_session", {"force_new": True})
    assert shipped["data"].get("journey") is None

    blocked = _call_tool("start_onboarding_session", {"v2": True})
    assert blocked["success"] is True
    assert blocked["data"]["attached"] is False
    assert blocked["data"]["blocked"] == "shipped_setup_in_progress"
    leftover = onboarding_server.load_session()
    assert leftover.get("journey") is None


def test_shortest_path_saves_skips_and_does_not_leak_into_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_vault(tmp_path, monkeypatch)
    _call_tool("start_onboarding_session", {"v2": True})
    skipped = _call_tool("save_calendar_selection", {"skipped": True})
    assert skipped["success"] is True
    notes = _call_tool("save_meeting_source", {"primary": "none"})
    assert notes["success"] is True
    assert notes["data"] == {"primary": "none"}
    doc = _call_tool("save_source_doc_note", {"status": "skipped"})
    assert doc["success"] is True
    assert doc["data"]["status"] == "skipped"

    session = onboarding_server.load_session()
    assert session["data"]["meeting_source"]["primary"] == "none"
    assert session["data"]["source_doc"]["status"] == "skipped"
    approved = onboarding_server._approved_profile_session_data(session)
    assert "meeting_source" not in approved
    assert "source_doc" not in approved


def test_meeting_source_connected_and_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_vault(tmp_path, monkeypatch)
    _call_tool("start_onboarding_session", {"v2": True})
    granola = _call_tool("save_meeting_source", {"primary": "granola"})
    assert granola["success"] is True
    none = _call_tool("save_meeting_source", {"primary": "none"})
    assert none["success"] is True
    refused = _call_tool("save_meeting_source", {"primary": "fireflies"})
    assert refused["success"] is False


def test_source_doc_supplied_is_session_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_vault(tmp_path, monkeypatch)
    _call_tool("start_onboarding_session", {"v2": True})
    supplied = _call_tool(
        "save_source_doc_note",
        {"status": "supplied", "kind": "review"},
    )
    assert supplied["success"] is True
    session = onboarding_server.load_session()
    assert session["data"]["source_doc"] == {"status": "supplied", "kind": "review"}
    assert "review text" not in json.dumps(session)


def test_inferred_identity_is_not_saved_until_the_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_vault(tmp_path, monkeypatch)
    _call_tool("start_onboarding_session", {"v2": True})
    _call_tool("save_calendar_selection", {"skipped": True})
    session = onboarding_server.load_session()
    assert "name" not in session["data"]
    saved = _call_tool(
        "validate_and_save_step",
        {"step_number": 1, "step_data": {"name": "Alex Rivera"}},
    )
    assert saved["success"] is True
    corrected = _call_tool(
        "validate_and_save_step",
        {"step_number": 1, "step_data": {"name": "Alex R."}},
    )
    assert corrected["success"] is True
    assert onboarding_server.load_session()["data"]["name"] == "Alex R."


def test_default_first_week_analysis_keys_stay_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = tmp_path / "System"
    system.mkdir()
    (system / "user-profile.yaml").write_text(
        "role: Founder\nemail_domain: acme.com\npillars:\n  - name: Product\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        onboarding_server,
        "get_calendar_events_for_week",
        _timed_week_events,
    )
    monkeypatch.setattr(
        onboarding_server,
        "get_recent_granola_meetings",
        lambda days=7: [],
    )
    payload = _decode_tool_result(
        asyncio.run(onboarding_server.handle_call_tool("run_first_week_analysis", {}))
    )
    assert "next_working_day" not in payload["data"]


def test_host_events_analysis_is_non_blocking_and_adds_next_working_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system = tmp_path / "System"
    system.mkdir()
    (system / "user-profile.yaml").write_text(
        "role: Founder\nemail_domain: acme.com\npillars: []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        onboarding_server,
        "get_recent_granola_meetings",
        lambda days=7: [],
    )

    def boom():
        raise AssertionError("host events must not read the stored calendar")

    monkeypatch.setattr(onboarding_server, "get_calendar_events_for_week", boom)
    monkeypatch.setattr(onboarding_server, "date", date)
    analysis = onboarding_server.run_first_week_analysis(
        events=_timed_week_events(),
        v2=True,
    )
    assert analysis["available"] is True
    assert analysis["meeting_count"] == 1
    assert "next_working_day" in analysis
    assert analysis["next_working_day"]["weekday"]
    assert analysis["next_working_day"]["date"]
    assert "," in analysis["next_working_day"]["label"]


def test_next_working_day_skips_all_day_ooo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(onboarding_server, "date", date)
    class _Today(date):
        @classmethod
        def today(cls):
            return date(2026, 7, 27)

    monkeypatch.setattr(onboarding_server, "date", _Today)
    events = [
        {
            "title": "Out of office",
            "start": datetime(2026, 7, 28, 0, 0),
            "end": datetime(2026, 7, 29, 0, 0),
            "all_day": True,
            "attendees": [],
        }
    ]
    monkeypatch.setattr(
        onboarding_server,
        "get_recent_granola_meetings",
        lambda days=7: [],
    )
    system = tmp_path / "System"
    system.mkdir()
    (system / "user-profile.yaml").write_text(
        "role: Founder\nemail_domain: acme.com\npillars: []\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
    analysis = onboarding_server.run_first_week_analysis(events=events, v2=True)
    assert analysis["next_working_day"]["date"] == "2026-07-29"
    assert analysis["next_working_day"]["label"] == "Wednesday, 29 July"


def test_default_entity_offer_still_caps_at_five(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meetings = []
    for index in range(8):
        attendee = [{
            "name": f"Person {index}",
            "email": f"p{index}@acme.com",
            "location": "external",
        }]
        meetings.extend(
            [
                _meeting(f"w1-{index}", "2026-07-13", attendees=attendee),
                _meeting(f"w2-{index}", "2026-07-20", attendees=attendee),
            ]
        )
    default = _prepare(tmp_path / "default", monkeypatch, meetings)
    assert len(default["suggestions"]) == 5

    _configure_vault(tmp_path / "v2", monkeypatch)
    monkeypatch.setattr(
        onboarding_server,
        "_collect_entity_offer_meetings",
        lambda: meetings,
    )
    widened = onboarding_server.prepare_entity_page_offer(v2_window=True)
    assert len(widened["suggestions"]) > 5
    assert len(widened["suggestions"]) <= 25


def test_entity_creation_accepted_and_declined_on_v2_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meetings = [
        _meeting("offer-1", "2026-07-13"),
        _meeting("offer-2", "2026-07-20"),
    ]
    prepared = _prepare(tmp_path / "yes", monkeypatch, meetings)
    suggestion_id = prepared["suggestions"][0]["id"]
    accepted = onboarding_server.respond_to_entity_page_offer(
        "yes",
        [suggestion_id],
        v2_window=True,
    )
    assert accepted["action"] == "yes"
    assert accepted["results"][0]["status"] == "accepted"

    declined_prep = _prepare(tmp_path / "no", monkeypatch, meetings)
    declined = onboarding_server.respond_to_entity_page_offer(
        "no",
        [declined_prep["suggestions"][0]["id"]],
        v2_window=True,
    )
    assert declined["results"][0]["status"] == "dismissed"
    assert not (tmp_path / "no/05-Areas/People/External/Jane_Doe.md").exists()


def test_v2_session_still_requires_harness_and_strips_session_only_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_vault(tmp_path, monkeypatch)
    session = onboarding_server.create_new_session(v2=True)
    session["calendar_addressed"] = True
    session["harness_setup"] = {
        "detected": ["codex"],
        "selected": ["codex"],
        "confirmed": False,
    }
    session["completed_steps"] = list(range(1, 8))
    session["data"] = {
        "name": "Alex",
        "role": "Product Manager",
        "role_group": "product",
        "company": "Northwind",
        "company_size": "startup",
        "email_domain": "northwind.example",
        "pillars": ["Retention"],
        "communication": {},
        "working_week": {"days": ["monday", "tuesday", "wednesday", "thursday", "friday"]},
        "meeting_source": {"primary": "none"},
        "source_doc": {"status": "skipped"},
    }
    onboarding_server.save_session(session)
    refused = _call_tool("finalize_onboarding", {"dry_run": True})
    assert refused["success"] is False
    assert "confirm where Dex should work" in refused["error"]

    session["harness_setup"]["confirmed"] = True
    approved = onboarding_server._approved_profile_session_data(session)
    assert "meeting_source" not in approved
    assert "source_doc" not in approved
    assert approved["name"] == "Alex"
    assert approved["email_domain"] == "northwind.example"


def test_v2_does_not_widen_google_persist(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    with pytest.raises(PlanRejected, match="Apple Calendar or no calendar"):
        service.build_and_preview_onboarding_context(
            vault,
            working_context={"role_focus": "Lead product work", "key_people": []},
            calendar_source={"provider": "google", "calendar_id": "primary"},
        )


def test_reset_and_change_job_still_use_shipped_start() -> None:
    reset = (REPO_ROOT / ".claude/skills/reset/SKILL.md").read_text(encoding="utf-8")
    change_job = (REPO_ROOT / ".claude/skills/change-job/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "v2=true" not in reset
    assert "v2=true" not in change_job
    assert "start_onboarding_session(force_new=True)" in reset or "force_new" in reset
