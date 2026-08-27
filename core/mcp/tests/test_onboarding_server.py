"""Tests for the onboarding MCP server."""

import asyncio
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

# core/mcp/tests -> repo root (for `core.paths`) and core/mcp (for the module).
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "core" / "mcp"))

import onboarding_server  # noqa: E402

from core.mcp import work_server  # noqa: E402


def _decode_tool_result(result) -> dict:
    return json.loads(result[0].text)


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    return _decode_tool_result(
        asyncio.run(onboarding_server.handle_call_tool(name, arguments or {}))
    )


VALID_STEP_DATA = {
    1: {"name": "Jane"},
    2: {"role_number": 1},
    3: {"company": "Acme", "company_size": "startup"},
    4: {"email_domain": "acme.com"},
    5: {"pillars": ["Build", "Learn"]},
    6: {"communication": {}},
    7: {"working_week": {"days": ["monday"]}},
}


def _start_session_before_step(step_number: int) -> None:
    onboarding_server.save_session(onboarding_server.create_new_session())
    skipped = _call_tool("save_calendar_selection", {"skipped": True})
    assert skipped["success"] is True, skipped
    for prior_step in range(1, step_number):
        payload = _call_tool(
            "validate_and_save_step",
            {
                "step_number": prior_step,
                "step_data": VALID_STEP_DATA[prior_step],
            },
        )
        assert payload["success"] is True, payload


def _prepare_finalize_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    system = tmp_path / "System"
    system.mkdir()
    shutil.copy(
        REPO_ROOT / "System/user-profile-template.yaml",
        system / "user-profile-template.yaml",
    )
    shutil.copy(
        REPO_ROOT / "System/.mcp.json.example",
        system / ".mcp.json.example",
    )
    (tmp_path / "core").mkdir()
    shutil.copy(REPO_ROOT / "core/paths.py", tmp_path / "core/paths.py")
    (tmp_path / ".scripts").mkdir()
    shutil.copy(REPO_ROOT / "package.json", tmp_path / "package.json")
    shutil.copy(REPO_ROOT / "CLAUDE.md", tmp_path / "CLAUDE.md")
    monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        onboarding_server,
        "MARKER_FILE",
        system / ".onboarding-complete",
    )
    monkeypatch.setattr(
        onboarding_server,
        "MCP_CONFIG_EXAMPLE",
        system / ".mcp.json.example",
    )
    monkeypatch.setattr(
        onboarding_server,
        "SESSION_FILE",
        system / ".onboarding-session.json",
    )
    return system / ".onboarding-session.json"


def test_confirmed_context_tools_preview_then_apply_without_creating_a_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    system = vault / "System"
    system.mkdir(parents=True)
    (system / "user-profile.yaml").write_text("name: Example User\n", encoding="utf-8")
    (system / ".onboarding-complete").write_text("{}\n", encoding="utf-8")
    session_file = system / ".onboarding-session.json"
    monkeypatch.setattr(onboarding_server, "BASE_DIR", vault)
    monkeypatch.setattr(onboarding_server, "MARKER_FILE", system / ".onboarding-complete")
    monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)

    previewed = _call_tool(
        "preview_confirmed_onboarding_context",
        {
            "working_context": {"role_focus": "Lead product work", "key_people": []},
            "calendar_source": {"provider": "apple", "work_calendar": "Work"},
        },
    )

    assert previewed["success"] is True
    assert not session_file.exists()
    assert "working_context" not in (system / "user-profile.yaml").read_text(encoding="utf-8")

    applied = _call_tool(
        "apply_confirmed_onboarding_context",
        {
            "preview": previewed["data"]["preview"],
            "approval_token": previewed["data"]["approval_token"],
        },
    )

    assert applied["success"] is True
    profile = yaml.safe_load((system / "user-profile.yaml").read_text(encoding="utf-8"))
    assert profile["calendar"] == {"provider": "apple", "work_calendar": "Work"}
    assert profile["working_context"]["role_focus"] == "Lead product work"
    assert not session_file.exists()


def test_confirmed_context_tools_do_not_change_an_existing_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    system = vault / "System"
    system.mkdir(parents=True)
    (system / "user-profile.yaml").write_text("name: Example User\n", encoding="utf-8")
    (system / ".onboarding-complete").write_text("{}\n", encoding="utf-8")
    session_file = system / ".onboarding-session.json"
    session_file.write_text('{"keep": "exactly"}\n', encoding="utf-8")
    original_session = session_file.read_bytes()
    monkeypatch.setattr(onboarding_server, "BASE_DIR", vault)
    monkeypatch.setattr(onboarding_server, "MARKER_FILE", system / ".onboarding-complete")
    monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)

    previewed = _call_tool(
        "preview_confirmed_onboarding_context",
        {
            "working_context": {"role_focus": "Lead product work", "key_people": []},
            "calendar_source": {"provider": "none"},
        },
    )
    applied = _call_tool(
        "apply_confirmed_onboarding_context",
        {
            "preview": previewed["data"]["preview"],
            "approval_token": previewed["data"]["approval_token"],
        },
    )

    assert previewed["success"] is True
    assert applied["success"] is True
    assert session_file.read_bytes() == original_session


def test_apply_confirmed_context_refuses_a_missing_token_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    system = vault / "System"
    system.mkdir(parents=True)
    profile = system / "user-profile.yaml"
    profile.write_text("name: Example User\n", encoding="utf-8")
    (system / ".onboarding-complete").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(onboarding_server, "BASE_DIR", vault)
    monkeypatch.setattr(onboarding_server, "MARKER_FILE", system / ".onboarding-complete")
    monkeypatch.setattr(onboarding_server, "SESSION_FILE", system / ".onboarding-session.json")
    previewed = _call_tool(
        "preview_confirmed_onboarding_context",
        {
            "working_context": {"role_focus": "Lead product work", "key_people": []},
            "calendar_source": {"provider": "none"},
        },
    )
    original_profile = profile.read_bytes()

    applied = _call_tool(
        "apply_confirmed_onboarding_context",
        {"preview": previewed["data"]["preview"]},
    )

    assert applied["success"] is False
    assert profile.read_bytes() == original_profile


def test_onboarding_flow_requires_context_preview_and_explicit_approval() -> None:
    flow = (REPO_ROOT / ".claude/flows/onboarding.md").read_text(encoding="utf-8")
    confirmation = flow.split("### Confirm working context and calendar", 1)[1].split(
        "### Automatic First-Week Reveal",
        1,
    )[0]

    assert "working_context" in confirmation
    assert "calendar_source" in confirmation
    assert "preview_confirmed_onboarding_context" in confirmation
    assert "apply_confirmed_onboarding_context" in confirmation
    assert "explicit Yes" in confirmation
    assert confirmation.index("preview_confirmed_onboarding_context") < confirmation.index(
        "explicit Yes"
    )
    assert confirmation.index("explicit Yes") < confirmation.index(
        "apply_confirmed_onboarding_context"
    )


def test_onboarding_flow_previews_and_confirms_multi_harness_selection() -> None:
    flow = (REPO_ROOT / ".claude/flows/onboarding.md").read_text(encoding="utf-8")
    selection = flow.split("### Choose where Dex should work", 1)[1].split(
        "### Question UI detection",
        1,
    )[0]

    assert "inspect_harnesses" in selection
    assert "save_harness_selection" in selection
    assert "Allow multiple choices" in selection
    assert "automatic" in selection
    assert "on demand" in selection
    assert "guided" in selection
    assert "unavailable" in selection
    assert selection.index("capability preview") < selection.index("confirmed=true")


class _FakeHarnessProfile:
    def __init__(self, profile_id: str, *, pre_tool: str = "unavailable"):
        self.id = profile_id
        self._payload = {
            "id": profile_id,
            "display_name": profile_id.replace("-", " ").title(),
            "capabilities": [
                {"id": "vault", "mode": "automatic"},
                {"id": "mcp", "mode": "on_demand"},
                {"id": "pre-tool", "mode": pre_tool},
            ],
        }

    def to_dict(self):
        return dict(self._payload)

    def capability_rows(self):
        return list(self._payload["capabilities"])


class TestHarnessSelection:
    def test_preview_includes_live_pi_and_bb_limits(self):
        from core.harnesses.registry import get_profile

        inspected = onboarding_server.inspect_harnesses(["pi", "bb"])

        assert inspected["selected"] == ["bb", "pi"]
        by_id = {row["id"]: row for row in inspected["profiles"]}
        assert by_id["pi"]["limitations"] == list(get_profile("pi").limitations)
        assert by_id["bb"]["limitations"] == list(get_profile("bb").limitations)
        assert "mcp" in " ".join(by_id["pi"]["limitations"]).lower()
        assert "macos" in " ".join(by_id["bb"]["limitations"]).lower()

    def test_preview_includes_live_chatgpt_work_web_limit(self):
        from core.harnesses.registry import get_profile

        inspected = onboarding_server.inspect_harnesses(["chatgpt-work"])

        assert inspected["selected"] == ["chatgpt-work"]
        by_id = {row["id"]: row for row in inspected["profiles"]}
        assert by_id["chatgpt-work"]["limitations"] == list(get_profile("chatgpt-work").limitations)
        joined = " ".join(by_id["chatgpt-work"]["limitations"]).lower()
        assert "web" in joined
        assert "https" in joined

    def test_inspection_supplies_existing_home_path_evidence(self, monkeypatch):
        evidence = (Path("/fixture/.codex"), Path("/fixture/.pi"))
        captured = []
        monkeypatch.setattr(
            onboarding_server.harness_registry,
            "standard_detection_paths",
            lambda: evidence,
            raising=False,
        )
        monkeypatch.setattr(
            onboarding_server.harness_registry,
            "detect_harnesses",
            lambda **kwargs: captured.append(kwargs) or (),
        )

        inspected = onboarding_server.inspect_harnesses()

        assert inspected["detected"] == []
        assert captured == [{"paths": evidence}]

    def test_start_detects_harnesses_without_confirming_for_the_user(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        monkeypatch.setattr(
            onboarding_server.harness_registry,
            "detect_harnesses",
            lambda **_kwargs: (
                _FakeHarnessProfile("codex", pre_tool="automatic"),
                _FakeHarnessProfile("pi"),
            ),
        )

        payload = _call_tool("start_onboarding_session", {"force_new": True})

        setup = payload["data"]["harness_setup"]
        assert setup == {
            "detected": ["codex", "pi"],
            "selected": ["codex", "pi"],
            "confirmed": False,
        }
        assert payload["data"]["harness_capabilities"][0]["id"] == "codex"

    def test_selection_supports_multiple_harnesses_and_requires_confirmation(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        profiles = {
            "codex": _FakeHarnessProfile("codex", pre_tool="automatic"),
            "pi": _FakeHarnessProfile("pi"),
        }
        monkeypatch.setattr(
            onboarding_server.harness_registry,
            "get_profile",
            profiles.__getitem__,
        )
        onboarding_server.save_session(onboarding_server.create_new_session())

        refused = _call_tool(
            "save_harness_selection",
            {"harnesses": ["codex", "pi"], "confirmed": False},
        )
        accepted = _call_tool(
            "save_harness_selection",
            {"harnesses": ["codex", "pi"], "confirmed": True},
        )

        assert refused["success"] is False
        assert accepted["success"] is True
        assert onboarding_server.load_session()["harness_setup"] == {
            "detected": [],
            "selected": ["codex", "pi"],
            "confirmed": True,
        }
        assert accepted["data"]["profiles"][0]["capabilities"][2] == {
            "id": "pre-tool",
            "mode": "automatic",
        }

    def test_completed_vault_can_record_selection_without_restarting_onboarding(
        self, tmp_path, monkeypatch
    ):
        system = tmp_path / "System"
        system.mkdir()
        marker = system / ".onboarding-complete"
        marker.write_text("{}\n", encoding="utf-8")
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
        monkeypatch.setattr(onboarding_server, "MARKER_FILE", marker)
        monkeypatch.setattr(
            onboarding_server,
            "SESSION_FILE",
            system / ".onboarding-session.json",
        )
        onboarding_server.SESSION_FILE.write_text(
            json.dumps(onboarding_server.create_new_session()),
            encoding="utf-8",
        )
        original_session = onboarding_server.SESSION_FILE.read_bytes()
        profiles = {
            "codex": _FakeHarnessProfile("codex", pre_tool="automatic"),
            "pi": _FakeHarnessProfile("pi"),
        }
        monkeypatch.setattr(
            onboarding_server.harness_registry,
            "get_profile",
            profiles.__getitem__,
        )
        monkeypatch.setattr(
            onboarding_server.harness_registry,
            "detect_harnesses",
            lambda **_kwargs: (_FakeHarnessProfile("codex"),),
        )
        calls = []

        def record(selected, detected, *, source, dry_run):
            calls.append((selected, detected, source, dry_run))
            return {
                "ok": True,
                "mutation_receipt": {
                    "declared_paths": ["System/.dex/harness-profile.json"]
                },
            }

        monkeypatch.setattr(
            onboarding_server,
            "_run_harness_receipt_provisioner",
            record,
            raising=False,
        )

        accepted = _call_tool(
            "save_harness_selection",
            {"harnesses": ["codex", "pi"], "confirmed": True},
        )

        assert accepted["success"] is True
        assert calls == [(["codex", "pi"], ["codex"], "user-confirmed", False)]
        assert accepted["data"]["receipt"]["ok"] is True
        assert onboarding_server.SESSION_FILE.read_bytes() == original_session

    def test_selection_rejects_unknown_and_duplicate_harnesses(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        monkeypatch.setattr(
            onboarding_server.harness_registry,
            "get_profile",
            lambda profile_id: (
                _FakeHarnessProfile(profile_id)
                if profile_id == "codex"
                else (_ for _ in ()).throw(KeyError(profile_id))
            ),
        )
        onboarding_server.save_session(onboarding_server.create_new_session())

        duplicate = _call_tool(
            "save_harness_selection",
            {"harnesses": ["codex", "codex"], "confirmed": True},
        )
        unknown = _call_tool(
            "save_harness_selection",
            {"harnesses": ["magic-agent"], "confirmed": True},
        )

        assert duplicate["success"] is False
        assert "duplicate" in duplicate["error"].lower()
        assert unknown["success"] is False
        assert "unknown" in unknown["error"].lower()

    def test_tool_catalog_exposes_inspection_and_selection(self):
        tools = asyncio.run(onboarding_server.handle_list_tools())
        by_name = {tool.name: tool for tool in tools}

        assert "inspect_harnesses" in by_name
        assert "save_harness_selection" in by_name
        assert by_name["save_harness_selection"].inputSchema["required"] == [
            "harnesses",
            "confirmed",
        ]

    def test_new_portable_session_cannot_finalize_before_harness_confirmation(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
        monkeypatch.setattr(
            onboarding_server.harness_registry,
            "detect_harnesses",
            lambda **_kwargs: (_FakeHarnessProfile("codex"),),
        )
        _call_tool("start_onboarding_session", {"force_new": True})
        session = onboarding_server.load_session()
        session["completed_steps"] = list(onboarding_server.REQUIRED_ONBOARDING_STEPS)
        session["calendar_addressed"] = True
        session["data"] = {
            "name": "Jane",
            "role": "Founder",
            "company_size": "startup",
            "email_domain": "acme.com",
            "pillars": ["Build", "Learn"],
            "communication": {},
            "working_week": {"days": ["monday"]},
        }
        onboarding_server.save_session(session)

        status = _call_tool("get_onboarding_status")
        finalized = _call_tool("finalize_onboarding", {"dry_run": True})

        assert status["data"]["harness_selection_confirmed"] is False
        assert status["data"]["ready_to_finalize"] is False
        assert finalized["success"] is False
        assert "confirm where Dex should work" in finalized["error"]

    def test_unconfirmed_detection_is_not_approved_for_provisioning(self):
        session = onboarding_server.create_new_session()
        session["harness_setup"] = {
            "detected": ["codex"],
            "selected": ["codex"],
            "confirmed": False,
        }

        assert "harnesses" not in onboarding_server._approved_profile_session_data(session)

        session["harness_setup"]["confirmed"] = True
        approved = onboarding_server._approved_profile_session_data(session)
        assert approved["harnesses"] == ["codex"]
        assert approved["harness_source"] == "user-confirmed"


class TestStepOrdering:
    def test_rejects_out_of_order_step_with_next_expected_step(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        _start_session_before_step(2)

        payload = _call_tool(
            "validate_and_save_step",
            {
                "step_number": 3,
                "step_data": {"company": "Acme", "company_size": "startup"},
            },
        )

        assert payload["success"] is False
        assert payload["error"] == (
            "Complete step 2 (role) first — steps run in order."
        )

    def test_rejects_step_1_until_calendar_is_addressed(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        payload = _call_tool(
            "validate_and_save_step",
            {"step_number": 1, "step_data": {"name": "Jane"}},
        )

        assert payload["success"] is False
        assert payload["error"] == (
            "Connect the calendar first (or skip it explicitly with "
            "save_calendar_selection(skipped=true)) — setup opens with the calendar."
        )

    def test_accepts_step_1_after_calendar_is_explicitly_skipped(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        onboarding_server.save_session(onboarding_server.create_new_session())

        skipped = _call_tool("save_calendar_selection", {"skipped": True})
        payload = _call_tool(
            "validate_and_save_step",
            {"step_number": 1, "step_data": {"name": "Jane"}},
        )

        assert skipped["success"] is True
        assert payload["success"] is True

    def test_allows_correction_of_an_already_completed_step(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        session = onboarding_server.create_new_session()
        session["completed_steps"] = [2]
        session["data"] = {
            "calendar": {"permissions_pending": True},
            "role": "Product Manager",
            "role_group": "product",
        }
        onboarding_server.save_session(session)

        payload = _call_tool(
            "validate_and_save_step",
            {
                "step_number": 2,
                "step_data": {"role": "Researcher", "role_group": "Custom"},
            },
        )

        assert payload["success"] is True
        assert onboarding_server.load_session()["data"]["role"] == "Researcher"

    def test_optional_step_8_does_not_block_finalization(
        self, tmp_path, monkeypatch
    ):
        _prepare_finalize_vault(tmp_path, monkeypatch)
        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7]
        session["data"] = {
            "calendar": {"permissions_pending": True},
            "name": "Jane",
            "role": "Founder",
            "company_size": "startup",
            "email_domain": "acme.com",
            "pillars": ["Build", "Learn"],
            "communication": {},
            "working_week": {"days": ["monday"]},
        }
        onboarding_server.save_session(session)

        payload = _call_tool("finalize_onboarding", {"dry_run": True})

        assert payload["success"] is True

    def test_finalize_rejects_session_without_calendar_addressed(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        monkeypatch.setattr(onboarding_server, "BASE_DIR", tmp_path)
        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7]
        session["data"] = {
            "name": "Jane",
            "role": "Founder",
            "company_size": "startup",
            "email_domain": "acme.com",
            "pillars": ["Build", "Learn"],
            "communication": {},
            "working_week": {"days": ["monday"]},
        }
        onboarding_server.save_session(session)

        payload = _call_tool("finalize_onboarding", {"dry_run": True})

        assert payload["success"] is False
        assert payload["error"] == (
            "Connect the calendar first (or skip it explicitly with "
            "save_calendar_selection(skipped=true)) — setup opens with the calendar."
        )

    def test_status_is_not_ready_without_calendar_addressed(
        self, tmp_path, monkeypatch
    ):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7]
        onboarding_server.save_session(session)

        payload = _call_tool("get_onboarding_status")

        assert payload["success"] is True
        assert payload["data"]["missing_steps"] == []
        assert payload["data"]["progress_percent"] == 100.0
        assert payload["data"]["calendar_addressed"] is False
        assert payload["data"]["ready_to_finalize"] is False


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
        _start_session_before_step(2)

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
        session_data = onboarding_server.load_session()["data"]
        assert session_data["role"] == expected_role
        assert session_data["role_group"] == expected_group

    def test_custom_role_contract_is_unchanged(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        _start_session_before_step(2)

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
        session_data = onboarding_server.load_session()["data"]
        assert session_data["role"] == "Researcher"
        assert session_data["role_group"] == "Custom"


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
        _start_session_before_step(4)

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
        _prepare_finalize_vault(tmp_path, monkeypatch)
        _start_session_before_step(4)

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
        _start_session_before_step(4)

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
        _start_session_before_step(7)

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
        _start_session_before_step(7)

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
        session["data"]["calendar"] = {"permissions_pending": True}
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
        _start_session_before_step(8)

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
        _start_session_before_step(8)

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
            "quarter_goals": True,
        }

    def test_rejects_non_boolean_room_answers(self, tmp_path, monkeypatch):
        session_file = tmp_path / "System/.onboarding-session.json"
        monkeypatch.setattr(onboarding_server, "SESSION_FILE", session_file)
        _start_session_before_step(8)

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
        _start_session_before_step(8)

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
        _prepare_finalize_vault(tmp_path, monkeypatch)
        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7, 8]
        session["current_step"] = 9
        session["data"] = {
            "calendar": {"permissions_pending": True},
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
        assert "05-Areas/People/Internal" not in preview["would_create_folders"]
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
        _prepare_finalize_vault(tmp_path, monkeypatch)
        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7]
        session["current_step"] = 8
        session["data"] = {
            "calendar": {"permissions_pending": True},
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
        assert "05-Areas/Career" in preview["would_create_folders"]
        assert "05-Areas/Companies" in preview["would_create_folders"]
        assert "01-Quarter_Goals" in preview["would_create_folders"]
        assert preview["preview_user_profile"]["capabilities"] == {
            "career": {"enabled": True},
            "companies": {"enabled": True},
            "quarter_goals": {"enabled": True},
        }

    def test_onboarding_step_8_asks_nothing_now_that_every_room_is_on(self):
        """All three rooms default on, so step 8 has no question left to ask.

        It states what the user is getting and moves on. The step must not put a
        yes/no choice to someone whose answer is always yes, and must not force
        an answer — an unanswered step 8 is what lets finalization fill every
        room from the shipped defaults.
        """
        flow = (REPO_ROOT / ".claude/flows/onboarding.md").read_text(encoding="utf-8")
        step = flow.split("## Step 8:", 1)[1].split("## Step 9:", 1)[0]

        assert '"options"' not in step
        assert "Recommended" not in step
        assert "**Do not ask a question here.**" in step
        assert "Do not call `validate_and_save_step` for step 8." in step
        for room in ("Companies", "Career", "Quarter Goals"):
            assert room in step

    def test_finalize_with_default_answers_provisions_protected_room_seeds(
        self, tmp_path, monkeypatch
    ):
        system = tmp_path / "System"
        system.mkdir()
        shutil.copy(
            REPO_ROOT / "System/user-profile-template.yaml",
            system / "user-profile-template.yaml",
        )
        shutil.copytree(
            REPO_ROOT / ".claude/skills/_available/capabilities",
            tmp_path / ".claude/skills/_available/capabilities",
        )
        (tmp_path / "core").mkdir()
        shutil.copy(REPO_ROOT / "core/paths.py", tmp_path / "core/paths.py")
        (tmp_path / ".scripts").mkdir()
        mcp_example = system / ".mcp.json.example"
        mcp_example.write_text('{"mcpServers": {}}\n', encoding="utf-8")
        (tmp_path / "CLAUDE.md").write_text(
            "## User Profile\n\n---\n",
            encoding="utf-8",
        )

        paths = {
            "BASE_DIR": tmp_path,
            "SESSION_FILE": system / ".onboarding-session.json",
            "MCP_CONFIG_EXAMPLE": mcp_example,
            "MARKER_FILE": system / ".onboarding-complete",
        }
        for name, value in paths.items():
            monkeypatch.setattr(onboarding_server, name, value)

        session = onboarding_server.create_new_session()
        session["completed_steps"] = [1, 2, 3, 4, 5, 6, 7]
        session["current_step"] = 8
        session["data"] = {
            "calendar": {"permissions_pending": True},
            "name": "Default User",
            "role": "Founder",
            "role_group": "leadership",
            "company_size": "startup",
            "email_domain": "example.com",
            "pillars": ["Build", "Learn"],
            "communication": {},
            "working_week": {
                "days": ["monday", "tuesday", "wednesday", "thursday", "friday"]
            },
        }
        onboarding_server.save_session(session)

        payload = _decode_tool_result(
            asyncio.run(onboarding_server.handle_call_tool("finalize_onboarding", {}))
        )

        assert payload["success"] is True, payload
        assert (tmp_path / "05-Areas/Career/Evidence/README.md").is_file()
        assert (tmp_path / "01-Quarter_Goals/Quarter_Goals.md").is_file()
        profile = yaml.safe_load(
            (tmp_path / "System/user-profile.yaml").read_text(encoding="utf-8")
        )
        assert profile["capabilities"] == {
            "career": {"enabled": True},
            "companies": {"enabled": True},
            "quarter_goals": {"enabled": True},
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
            "calendar": {"permissions_pending": True},
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

        preview_payload = _decode_tool_result(
            asyncio.run(
                onboarding_server.handle_call_tool(
                    "finalize_onboarding", {"dry_run": True}
                )
            )
        )
        assert preview_payload["success"] is True, preview_payload
        preview = preview_payload["data"]
        assert "01-Quarter_Goals" not in preview["would_create_folders"]
        assert "05-Areas/People/Internal" not in preview["would_create_folders"]
        assert paths["SESSION_FILE"].is_file()
        assert not paths["MARKER_FILE"].exists()
        assert not (tmp_path / "System/user-profile.yaml").exists()
        assert not (tmp_path / "05-Areas/Career").exists()
        assert not (tmp_path / "System/.dex/tx").exists()

        payload = _decode_tool_result(
            asyncio.run(onboarding_server.handle_call_tool("finalize_onboarding", {}))
        )

        assert payload["success"] is True, payload
        assert (tmp_path / "05-Areas/Career/Evidence/README.md").is_file()
        assert (tmp_path / ".claude/skills/career-setup/SKILL.md").is_file()
        assert not (tmp_path / "05-Areas/Companies").exists()
        # Disabled rooms and genuinely empty spine folders stay absent. Parent
        # directories are created only for files in the durable transaction.
        assert not (tmp_path / "01-Quarter_Goals").exists()
        assert not (tmp_path / ".claude/skills/quarter-plan").exists()
        assert not (tmp_path / ".claude/skills/quarter-review").exists()
        assert (tmp_path / "03-Tasks/Tasks.md").is_file()
        assert not (tmp_path / "05-Areas/People/Internal").exists()
        profile = (tmp_path / "System/user-profile.yaml").read_text(encoding="utf-8")
        assert "working_week:" in profile
        assert "days:" in profile
        assert "sunday" in profile
        assert not paths["SESSION_FILE"].exists()
        assert preview["provision_receipt"]["created"] == payload["data"]["receipt"][
            "created"
        ]
