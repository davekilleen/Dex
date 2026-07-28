"""Tests for the onboarding MCP server."""

import asyncio
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

# core/mcp/tests -> repo root (for `core.paths`) and core/mcp (for the module).
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core" / "mcp"))

import onboarding_server  # noqa: E402

from core.mcp import work_server  # noqa: E402


def _decode_tool_result(result) -> dict:
    return json.loads(result[0].text)


@pytest.fixture
def mixed_calendar_events():
    return [
        {
            "title": "Customer review",
            "start": datetime(2026, 7, 27, 9, 0),
            "end": datetime(2026, 7, 27, 10, 30),
            "duration_minutes": 90,
            "attendees": [
                {"name": "Jane", "email": "jane@acme.com"},
                {"name": "John", "email": "john@example.com"},
            ],
        },
        {
            "title": "Plan today with Dex",
            "start": datetime(2026, 7, 27, 10, 30),
            "end": datetime(2026, 7, 27, 11, 0),
            "duration_minutes": 30,
            "calendar_name": "Personal",
            "notes": "Added by Dex · delete the Dex calendar to stop these",
            "attendees": [],
        },
        {
            "title": "Out of office",
            "start": date(2026, 7, 28),
            "end": date(2026, 7, 29),
            "duration_minutes": 24 * 60,
            "attendees": [
                {"name": "Jane", "email": "jane@acme.com"},
            ],
        },
        {
            "title": "Holiday",
            "start": "2026-07-29T00:00:00+01:00",
            "end": "2026-07-30T00:00:00+01:00",
            "duration_minutes": 24 * 60,
            "all_day": True,
            "attendees": [
                {"name": "John", "email": "john@example.com"},
            ],
        },
    ]


@pytest.fixture
def pillar_evidence_events():
    return [
        {
            "title": "Weekly planning",
            "provider_event_id": "weekly-planning-2026-07-27",
            "provider_series_id": "weekly-planning",
            "start": datetime(2026, 7, 27, 9, 0),
            "end": datetime(2026, 7, 27, 10, 0),
            "attendees": [
                {
                    "name": "Jane",
                    "email": "jane@acme.com",
                    "is_current_user": True,
                },
                {"name": "John", "email": "john@acme.com"},
            ],
        },
        {
            "title": "Customer review",
            "provider_event_id": "customer-review-2026-07-27",
            "provider_series_id": "customer-review",
            "start": datetime(2026, 7, 27, 11, 0),
            "end": datetime(2026, 7, 27, 12, 30),
            "attendees": [
                {
                    "name": "Jane",
                    "email": "jane@acme.com",
                    "is_current_user": True,
                },
                {"name": "John", "email": "john@example.com"},
            ],
        },
        {
            "title": "Weekly planning",
            "provider_event_id": "weekly-planning-2026-07-28",
            "provider_series_id": "weekly-planning",
            "start": datetime(2026, 7, 28, 9, 0),
            "end": datetime(2026, 7, 28, 10, 0),
            "attendees": [
                {
                    "name": "Jane",
                    "email": "jane@acme.com",
                    "is_current_user": True,
                },
                {"name": "John", "email": "john@acme.com"},
            ],
        },
        {
            "title": "Holiday",
            "provider_event_id": "holiday-2026-07-29",
            "provider_series_id": "holiday",
            "start": datetime(2026, 7, 29, 0, 0),
            "end": datetime(2026, 7, 30, 0, 0),
            "all_day": True,
            "attendees": [
                {"name": "John", "email": "john@example.com"},
            ],
        },
    ]


class TestFirstWeekAnalysis:
    def test_tool_is_registered(self):
        tools = asyncio.run(onboarding_server.handle_list_tools())

        assert "run_first_week_analysis" in {tool.name for tool in tools}

    def test_returns_structured_result(
        self,
        tmp_path,
        monkeypatch,
        mixed_calendar_events,
    ):
        system = tmp_path / "System"
        system.mkdir()
        (system / "user-profile.yaml").write_text(
            "role: Founder\n"
            "email_domain: acme.com\n"
            "pillars:\n"
            "  - name: Product\n"
            "  - name: Customers\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)

        def calendar_events():
            return mixed_calendar_events

        monkeypatch.setattr(
            onboarding_server,
            "get_calendar_events_for_week",
            calendar_events,
        )
        monkeypatch.setattr(
            onboarding_server,
            "get_recent_granola_meetings",
            lambda days=7: [],
        )

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool("run_first_week_analysis", {})
            )
        )

        assert payload["success"] is True
        analysis = payload["data"]
        assert set(analysis) == {
            "available",
            "meeting_count",
            "meeting_hours",
            "one_on_one_count",
            "busiest_day",
            "top_contacts",
            "unique_people_count",
            "external_company_count",
            "recent_meeting_count",
            "pillar_evidence",
            "draft_weekly_plan",
        }
        assert analysis["available"] is True
        assert analysis["meeting_count"] == 1
        assert analysis["meeting_hours"] == 1.5
        assert analysis["one_on_one_count"] == 1
        assert analysis["busiest_day"] == {"day": "Monday", "count": 1}
        assert analysis["top_contacts"] == [
            {"name": "Jane", "email": "jane@acme.com", "meeting_count": 1},
            {"name": "John", "email": "john@example.com", "meeting_count": 1},
        ]
        assert analysis["unique_people_count"] == 2
        assert analysis["external_company_count"] == 1
        assert analysis["recent_meeting_count"] == 0
        assert "You have **1 meetings** scheduled this week." in analysis[
            "draft_weekly_plan"
        ]
        assert "Out of office" not in analysis["draft_weekly_plan"]
        assert "Holiday" not in analysis["draft_weekly_plan"]

    def test_reports_unavailable_without_fabricated_numbers(self, monkeypatch):
        def unavailable_calendar():
            raise RuntimeError("Calendar permission denied")

        monkeypatch.setattr(
            onboarding_server,
            "get_calendar_events_for_week",
            unavailable_calendar,
        )

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool("run_first_week_analysis", {})
            )
        )

        assert payload == {
            "success": True,
            "data": {
                "available": False,
                "reason": "Calendar permission denied",
            },
        }

    def test_zero_meetings_is_available(self, tmp_path, monkeypatch):
        system = tmp_path / "System"
        system.mkdir()
        (system / "user-profile.yaml").write_text(
            "role: Founder\nemail_domain: acme.com\npillars: []\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)

        def no_calendar_events():
            return []

        monkeypatch.setattr(
            onboarding_server,
            "get_calendar_events_for_week",
            no_calendar_events,
        )
        monkeypatch.setattr(
            onboarding_server,
            "get_recent_granola_meetings",
            lambda days=7: [],
        )

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool("run_first_week_analysis", {})
            )
        )

        assert payload["success"] is True
        analysis = payload["data"]
        assert analysis["available"] is True
        assert analysis["meeting_count"] == 0
        assert analysis["meeting_hours"] == 0.0
        assert analysis["one_on_one_count"] == 0
        assert analysis["busiest_day"] == {"day": "", "count": 0}
        assert analysis["top_contacts"] == []
        assert "You have **0 meetings** scheduled this week." in analysis[
            "draft_weekly_plan"
        ]

    def test_all_day_events_contribute_zero_hours_and_are_not_meetings(
        self,
        mixed_calendar_events,
    ):
        analysis = onboarding_server.analyze_calendar_events(mixed_calendar_events)

        assert analysis["total_meetings"] == 1
        assert analysis["meeting_hours"] == 1.5
        assert analysis["one_on_ones"] == 1
        assert analysis["busiest_day"] == "Monday"
        assert analysis["busiest_day_count"] == 1

    def test_capacity_hours_exclude_all_day_events(
        self,
        mixed_calendar_events,
    ):
        capacity = work_server.analyze_day_capacity(
            mixed_calendar_events,
            date(2026, 7, 27),
        )

        assert capacity["meeting_count"] == 1
        assert capacity["meeting_hours"] == 1.5

    def test_pillar_evidence_uses_only_timed_calendar_events(
        self,
        tmp_path,
        monkeypatch,
        pillar_evidence_events,
    ):
        system = tmp_path / "System"
        system.mkdir()
        (system / "user-profile.yaml").write_text(
            "role: Founder\nemail_domain: acme.com\npillars: []\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
        monkeypatch.setattr(
            onboarding_server,
            "SESSION_FILE",
            system / ".onboarding-session.json",
        )
        monkeypatch.setattr(
            onboarding_server,
            "get_calendar_events_for_week",
            lambda: pillar_evidence_events,
        )
        monkeypatch.setattr(
            onboarding_server,
            "get_recent_granola_meetings",
            lambda days=7: [],
        )

        analysis = onboarding_server.run_first_week_analysis()

        assert analysis["meeting_count"] == 3
        assert analysis["meeting_hours"] == 3.5
        assert analysis["pillar_evidence"] == {
            "recurring_commitments": [
                {
                    "title": "Weekly planning",
                    "meeting_count": 2,
                    "meeting_hours": 2.0,
                }
            ],
            "internal_external_split": {
                "internal_meeting_count": 2,
                "external_meeting_count": 1,
                "unknown_meeting_count": 0,
            },
            "observations": [
                "Monday is your busiest day, with 2 timed meetings.",
                "3 of your 3 timed meetings are 1:1s.",
            ],
        }
        assert "Holiday" not in json.dumps(analysis["pillar_evidence"])
        assert "24" not in json.dumps(analysis["pillar_evidence"])

    def test_analysis_context_uses_active_onboarding_session_before_finalize(
        self,
        tmp_path,
        monkeypatch,
    ):
        system = tmp_path / "System"
        system.mkdir()
        session_file = system / ".onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        session = onboarding_server.create_new_session()
        session["data"] = {
            "email_domain": "acme.com",
            "calendar": {"work_calendar": "jane@acme.com"},
        }
        onboarding_server.save_session(session)

        assert onboarding_server._load_first_week_profile() == session["data"]


class TestIdentityDerivation:
    @pytest.mark.parametrize(
        ("address", "expected"),
        (
            (
                "jane.smith@example.com",
                {"name": "Jane", "domain": "example.com"},
            ),
            ("js@example.com", {"name": None, "domain": "example.com"}),
            ("info@example.com", {"name": None, "domain": "example.com"}),
            ("j.smith@example.com", {"name": None, "domain": "example.com"}),
            ("jane@acme.com", {"name": "Jane", "domain": "acme.com"}),
        ),
    )
    def test_derives_only_confident_identity_guesses(self, address, expected):
        assert onboarding_server.derive_identity_from_email(address) == expected

    @pytest.mark.parametrize(
        "address",
        ("", "not-an-email", "jane@@example.com", "@example.com", "jane@example"),
    )
    def test_rejects_malformed_addresses(self, address):
        assert onboarding_server.derive_identity_from_email(address) == {
            "name": None,
            "domain": None,
        }

    def test_calendar_save_returns_identity_for_confirmation(
        self, tmp_path, monkeypatch
    ):
        from core.mcp import calendar_server

        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        monkeypatch.setattr(
            calendar_server,
            "_get_calendar_list_result",
            lambda: {
                "success": True,
                "calendars": ["jane.smith@example.com"],
                "count": 1,
            },
        )
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "save_calendar_selection",
                    {
                        "work_calendar": "jane.smith@example.com",
                        "work_email": "jane.smith@example.com",
                        "calendar_count": 1,
                    },
                )
            )
        )

        assert payload["success"] is True
        assert payload["data"]["derived_identity"] == {
            "name": "Jane",
            "domain": "example.com",
        }


class TestRoleStep:
    def test_role_areas_cover_all_existing_role_numbers_once(self):
        mapped_numbers = [
            role_number
            for role_numbers in onboarding_server.ROLE_AREAS.values()
            for role_number in role_numbers
        ]

        assert len(onboarding_server.ROLE_AREAS) == 8
        assert list(onboarding_server.ROLES) == list(range(1, 32))
        assert sorted(mapped_numbers) == list(onboarding_server.ROLES)
        assert len(mapped_numbers) == len(set(mapped_numbers))

        role_step = (
            REPO_ROOT / ".claude/flows/onboarding.md"
        ).read_text(encoding="utf-8").split("## Step 2:", 1)[1].split(
            "## Step 3:", 1
        )[0]
        documented_numbers = []
        for area, role_numbers in onboarding_server.ROLE_AREAS.items():
            area_line = next(
                line
                for line in role_step.splitlines()
                if line.startswith(f"- **{area}:**")
            )
            documented_area_numbers = [
                int(number) for number in re.findall(r"`(\d+)`", area_line)
            ]
            assert documented_area_numbers == list(role_numbers)
            documented_numbers.extend(documented_area_numbers)

        assert sorted(documented_numbers) == list(onboarding_server.ROLES)
        assert len(documented_numbers) == len(set(documented_numbers))
        for role_number, (label, _) in onboarding_server.ROLES.items():
            assert role_step.count(f"`{role_number}` {label}") == 1

    @pytest.mark.parametrize("role_number", (1, 31))
    def test_numbered_role_contract_is_unchanged(
        self,
        tmp_path,
        monkeypatch,
        role_number,
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 2,
                        "step_data": {"role_number": role_number},
                    },
                )
            )
        )

        expected_role, expected_group = onboarding_server.ROLES[role_number]
        assert payload["success"] is True
        assert onboarding_server.load_session()["data"] == {
            "role": expected_role,
            "role_group": expected_group,
        }

    def test_custom_role_contract_is_unchanged(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 2,
                        "step_data": {
                            "role": "Researcher",
                            "role_group": "Custom",
                        },
                    },
                )
            )
        )

        assert payload["success"] is True
        assert onboarding_server.load_session()["data"] == {
            "role": "Researcher",
            "role_group": "Custom",
        }


class TestEmailDomainStep:
    @pytest.mark.parametrize(
        ("entered_domain", "normalized_domain"),
        (
            ("@acme.com", "acme.com"),
            ("jane@acme.com", "acme.com"),
            ("acme.com, @acme.io", "acme.com, acme.io"),
        ),
    )
    def test_normalizes_and_saves_email_domains(
        self, tmp_path, monkeypatch, entered_domain, normalized_domain
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 4,
                        "step_data": {"email_domain": entered_domain},
                    },
                )
            )
        )

        assert payload["success"] is True
        assert payload["data"]["email_domain"] == normalized_domain
        assert onboarding_server.load_session()["data"]["email_domain"] == normalized_domain

    def test_explicit_no_company_domain_completes_step_and_allows_finalize(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 4,
                        "step_data": {
                            "email_domain": "",
                            "no_company_domain": True,
                        },
                    },
                )
            )
        )

        assert payload["success"] is True
        session = onboarding_server.load_session()
        assert session["data"]["email_domain"] == ""
        assert 4 in session["completed_steps"]

        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7]
        session["data"]["working_week"] = {
            "days": ["monday", "tuesday", "wednesday", "thursday", "friday"]
        }
        onboarding_server.save_session(session)
        finalized = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "finalize_onboarding", {"dry_run": True}
                )
            )
        )

        assert finalized["success"] is True
        assert finalized["data"]["preview_user_profile"]["email_domain"] == ""

    def test_rejects_plain_empty_domain_with_explicit_opt_out_guidance(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {"step_number": 4, "step_data": {"email_domain": ""}},
                )
            )
        )

        assert payload["success"] is False
        assert "no_company_domain" in f"{payload['error']} {payload['suggestion']}"


class TestPillarStep:
    def test_requires_at_least_two_pillars(self):
        assert onboarding_server.validate_pillars(["Product"]) == (
            False,
            "Need at least 2 pillars",
        )

    def test_more_than_three_pillars_still_warns(self):
        valid, warning = onboarding_server.validate_pillars(
            ["Product", "Customers", "Team", "Operations"]
        )

        assert valid is True
        assert warning == "Warning: 4 pillars provided. 2-3 is recommended for focus."


class TestWorkingWeekStep:
    def test_saves_days_in_the_profile_parsers_normalized_shape(
        self,
        tmp_path,
        monkeypatch,
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 7,
                        "step_data": {
                            "working_week": {
                                "days": ["Sunday", "MON", "sun", 2, "not-a-day"]
                            }
                        },
                    },
                )
            )
        )

        assert payload["success"] is True
        assert payload["data"]["working_week"] == {
            "days": ["sunday", "monday", "wednesday"]
        }
        session = onboarding_server.load_session()
        assert session["data"]["working_week"] == {
            "days": ["sunday", "monday", "wednesday"]
        }
        assert 7 in session["completed_steps"]
        assert session["current_step"] == 8

    @pytest.mark.parametrize("submitted_days", ([], ["not-a-day", 9, True]))
    def test_rejects_a_working_week_without_any_valid_days(
        self,
        tmp_path,
        monkeypatch,
        submitted_days,
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 7,
                        "step_data": {"working_week": {"days": submitted_days}},
                    },
                )
            )
        )

        assert payload["success"] is False
        assert payload["field"] == "working_week.days"
        assert "at least one day" in payload["suggestion"].lower()
        assert 7 not in onboarding_server.load_session()["completed_steps"]

    def test_progress_counts_the_new_required_step_and_keeps_rooms_optional(
        self,
        tmp_path,
        monkeypatch,
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6]
        onboarding_server.save_session(session)

        incomplete = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool("get_onboarding_status", {})
            )
        )

        assert onboarding_server.ONBOARDING_STEPS == 8
        assert incomplete["data"]["missing_steps"] == [7]
        assert incomplete["data"]["missing_step_names"] == ["Working Week"]
        assert incomplete["data"]["progress_percent"] == 85.7
        assert incomplete["data"]["ready_to_finalize"] is False

        session["completed_steps"].append(7)
        onboarding_server.save_session(session)
        complete = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool("get_onboarding_status", {})
            )
        )

        assert complete["data"]["progress_percent"] == 100.0
        assert complete["data"]["ready_to_finalize"] is True


class TestCapabilityStep:
    def test_tool_schema_includes_the_eighth_capability_step(self):
        tools = asyncio.run(onboarding_server.handle_list_tools())
        validate = next(tool for tool in tools if tool.name == "validate_and_save_step")

        assert validate.inputSchema["properties"]["step_number"]["maximum"] == 8

    def test_saves_explicit_room_answers(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 8,
                        "step_data": {
                            "capabilities": {
                                "career": True,
                                "companies": False,
                                "quarter_goals": True,
                            }
                        },
                    },
                )
            )
        )

        assert payload["success"] is True
        session = onboarding_server.load_session()
        assert session["data"]["capabilities"] == {
            "career": True,
            "companies": False,
            "quarter_goals": True,
        }
        assert 8 in session["completed_steps"]
        assert session["current_step"] == 9

    def test_omitted_room_answers_use_contract_defaults(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 8,
                        "step_data": {"capabilities": {"career": True}},
                    },
                )
            )
        )

        assert payload["success"] is True
        assert onboarding_server.load_session()["data"]["capabilities"] == {
            "career": True,
            "companies": True,
            "quarter_goals": False,
        }

    def test_rejects_non_boolean_room_answers(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 8,
                        "step_data": {
                            "capabilities": {
                                "career": "yes",
                                "companies": False,
                                "quarter_goals": False,
                            }
                        },
                    },
                )
            )
        )

        assert payload["success"] is False
        assert payload["field"] == "capabilities.career"

    def test_rejects_unknown_room_answers(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "validate_and_save_step",
                    {
                        "step_number": 8,
                        "step_data": {"capabilities": {"careeer": True}},
                    },
                )
            )
        )

        assert payload["success"] is False
        assert payload["field"] == "capabilities.careeer"

    def test_dry_run_includes_only_selected_room_folders(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7, 8]
        session["current_step"] = 9
        session["data"] = {
            "name": "Test User",
            "role": "Founder",
            "company_size": "startup",
            "email_domain": "example.test",
            "pillars": ["Build", "Learn"],
            "communication": {},
            "working_week": {
                "days": ["sunday", "monday", "tuesday", "wednesday", "thursday"]
            },
            "capabilities": {
                "career": True,
                "companies": False,
                "quarter_goals": False,
            },
        }
        onboarding_server.save_session(session)

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "finalize_onboarding", {"dry_run": True}
                )
            )
        )

        preview = payload["data"]
        assert "05-Areas/Career" in preview["would_create_folders"]
        assert "05-Areas/Companies" not in preview["would_create_folders"]
        assert "01-Quarter_Goals" not in preview["would_create_folders"]
        assert preview["preview_user_profile"]["capabilities"] == {
            "career": {"enabled": True},
            "companies": {"enabled": False},
            "quarter_goals": {"enabled": False},
        }
        assert preview["preview_user_profile"]["working_week"] == {
            "days": ["sunday", "monday", "tuesday", "wednesday", "thursday"]
        }

    def test_dry_run_uses_contract_defaults_when_capabilities_are_omitted(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7]
        session["current_step"] = 8
        session["data"] = {
            "name": "Test User",
            "role": "Founder",
            "company_size": "startup",
            "email_domain": "example.test",
            "pillars": ["Build", "Learn"],
            "communication": {},
        }
        onboarding_server.save_session(session)

        payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "finalize_onboarding", {"dry_run": True}
                )
            )
        )

        preview = payload["data"]
        assert "05-Areas/Companies" in preview["would_create_folders"]
        assert preview["preview_user_profile"]["capabilities"]["companies"] == {
            "enabled": True
        }

    def test_finalize_provisions_only_selected_room_assets(self, tmp_path, monkeypatch):
        system = tmp_path / "System"
        system.mkdir()
        template = system / "user-profile-template.yaml"
        shutil.copy(REPO_ROOT / "System/user-profile-template.yaml", template)
        shutil.copytree(
            REPO_ROOT / ".claude/skills/_available/capabilities",
            tmp_path / ".claude/skills/_available/capabilities",
        )
        (tmp_path / "core").mkdir()
        shutil.copy(REPO_ROOT / "core/paths.py", tmp_path / "core/paths.py")
        (tmp_path / ".scripts").mkdir()
        mcp_example = system / ".mcp.json.example"
        mcp_example.write_text('{"mcpServers": {}}\n', encoding="utf-8")
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("## User Profile\n\n---\n", encoding="utf-8")

        paths = {
            "BASE_DIR": tmp_path,
            "SESSION_FILE": system / ".onboarding-session.json",
            "MCP_CONFIG_EXAMPLE": mcp_example,
            "MARKER_FILE": system / ".onboarding-complete",
        }
        for name, value in paths.items():
            monkeypatch.setattr(onboarding_server, name, value)

        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7, 8]
        session["current_step"] = 9
        session["data"] = {
            "name": "Test User",
            "role": "Founder",
            "role_group": "leadership",
            "company_size": "startup",
            "email_domain": "example.com",
            "pillars": ["Build", "Learn"],
            "communication": {},
            "working_week": {
                "days": ["sunday", "monday", "tuesday", "wednesday", "thursday"]
            },
            "capabilities": {
                "career": True,
                "companies": False,
                "quarter_goals": False,
            },
        }
        onboarding_server.save_session(session)

        payload = _decode_tool_result(
            asyncio.run(onboarding_server.handle_call_tool("finalize_onboarding", {}))
        )

        assert payload["success"] is True, payload
        assert (tmp_path / "05-Areas/Career/Evidence/README.md").is_file()
        assert (tmp_path / ".claude/skills/career-setup/SKILL.md").is_file()
        assert not (tmp_path / "05-Areas/Companies").exists()
        assert not (tmp_path / "01-Quarter_Goals").exists()
        assert (tmp_path / "03-Tasks/Tasks.md").is_file()
        assert (tmp_path / "05-Areas/People/Internal").is_dir()
        profile = (tmp_path / "System/user-profile.yaml").read_text(encoding="utf-8")
        assert "working_week:" in profile
        assert "days:" in profile
        assert "sunday" in profile
        assert not paths["SESSION_FILE"].exists()
