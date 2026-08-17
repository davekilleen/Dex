"""Proof that named product events fire only at real completion points."""

from __future__ import annotations

import ast
import asyncio
import json
import subprocess
from collections import Counter
from pathlib import Path

from core.analytics_events import SAFE_ANALYTICS_EVENT_NAMES
from core.mcp import (
    analytics_helper,
    analytics_server,
    career_server,
    dex_improvements_server,
    onboarding_server,
    resume_server,
    work_server,
)
from core.mcp.analytics_receipts import surface_analytics_attempt

REPO_ROOT = Path(__file__).resolve().parents[2]
MEETING_SKILL = REPO_ROOT / ".claude/skills/process-meetings/SKILL.md"
AGENT_MEETING_SKILL = REPO_ROOT / ".agents/skills/process-meetings/SKILL.md"
ONBOARDING_FLOW = REPO_ROOT / ".claude/flows/onboarding.md"
ANALYTICS_CALLER_EVENTS = {
    "core/mcp/work_server.py": Counter(
        {
            "task_created": 1,
            "task_completed": 3,
            "person_page_created": 1,
            "skill_rated": 1,
        }
    ),
    "core/mcp/onboarding_server.py": Counter({"onboarding_completed": 1}),
    "core/mcp/career_server.py": Counter(
        {
            "career_evidence_scanned": 1,
            "career_coverage_analyzed": 2,
            "promotion_readiness_checked": 1,
        }
    ),
    "core/mcp/resume_server.py": Counter({"resume_compiled": 1}),
    "core/mcp/dex_improvements_server.py": Counter({"idea_captured": 1, "idea_implemented": 1}),
}


def _decode_tool_result(result) -> dict[str, object]:
    return json.loads(result[0].text)


def _ready_onboarding_session() -> dict[str, object]:
    return {
        "completed_steps": list(onboarding_server.REQUIRED_ONBOARDING_STEPS),
        "data": {"email_domain": "example.test"},
    }


def test_every_python_analytics_caller_uses_the_safe_receipt_surface() -> None:
    for relative, expected_events in ANALYTICS_CALLER_EVENTS.items():
        module = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
        direct_calls = [
            call
            for call in ast.walk(module)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_fire_analytics_event"
        ]
        surface_events = Counter(
            ast.literal_eval(call.args[2])
            for call in ast.walk(module)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "surface_analytics_attempt"
        )

        assert direct_calls == []
        assert surface_events == expected_events


def test_shared_receipt_surface_hides_call_errors_and_preserves_the_result() -> None:
    result: dict[str, object] = {"success": True, "title": "Kept intact"}

    def fail_delivery(*_args, **_kwargs):
        raise RuntimeError("private relay token must not reach the caller")

    receipt_failure = surface_analytics_attempt(
        result,
        fail_delivery,
        "task_created",
    )

    assert receipt_failure == {
        "written": False,
        "reason": "receipt_write_failed",
    }
    assert result == {
        "success": True,
        "title": "Kept intact",
        "analytics_receipt": receipt_failure,
    }
    assert "private relay token" not in json.dumps(result, sort_keys=True)


def test_every_required_server_imports_the_shared_analytics_helper() -> None:
    for server in (
        work_server,
        onboarding_server,
        career_server,
        resume_server,
        dex_improvements_server,
    ):
        assert server.HAS_ANALYTICS is True
        assert server._fire_analytics_event is analytics_helper.fire_event


def test_work_server_package_import_uses_the_shared_receipt_helper() -> None:
    assert work_server.HAS_ANALYTICS is True
    assert work_server._fire_analytics_event is analytics_helper.fire_event


def test_unavailable_analytics_helpers_return_only_fixed_receipt_status() -> None:
    expected = {
        "fired": False,
        "receipt_written": False,
        "receipt_reason": "receipt_write_failed",
    }

    assert onboarding_server._analytics_helper_unavailable_result() == expected
    assert work_server._analytics_helper_unavailable_result() == expected


def test_onboarding_completion_event_follows_successful_finalization(monkeypatch) -> None:
    events: list[tuple[str, object]] = []
    session = _ready_onboarding_session()
    monkeypatch.setattr(onboarding_server, "load_session", lambda: session)
    monkeypatch.setattr(onboarding_server, "_calendar_addressed", lambda _session: True)
    monkeypatch.setattr(
        onboarding_server,
        "_finalize_through_provisioner",
        lambda _session: {"folders_created": [], "files_created": []},
    )
    monkeypatch.setattr(
        onboarding_server,
        "_fire_analytics_event",
        lambda event_name, properties=None: events.append((event_name, properties)),
        raising=False,
    )

    payload = _decode_tool_result(asyncio.run(onboarding_server.handle_call_tool("finalize_onboarding", {})))

    assert payload["success"] is True
    assert events == [("onboarding_completed", None)]


def test_onboarding_completion_surfaces_a_safe_receipt_write_failure(monkeypatch) -> None:
    session = _ready_onboarding_session()
    monkeypatch.setattr(onboarding_server, "load_session", lambda: session)
    monkeypatch.setattr(onboarding_server, "_calendar_addressed", lambda _session: True)
    monkeypatch.setattr(
        onboarding_server,
        "_finalize_through_provisioner",
        lambda _session: {"folders_created": [], "files_created": []},
    )
    monkeypatch.setattr(
        onboarding_server,
        "_fire_analytics_event",
        lambda *_args, **_kwargs: {
            "fired": False,
            "reason": "analytics_disabled",
            "receipt_written": False,
            "receipt_reason": "receipt_write_failed",
        },
    )

    payload = _decode_tool_result(asyncio.run(onboarding_server.handle_call_tool("finalize_onboarding", {})))

    assert payload["success"] is True
    assert payload["analytics_receipt"] == {
        "written": False,
        "reason": "receipt_write_failed",
    }
    assert "analytics_disabled" not in json.dumps(payload, sort_keys=True)


def test_failed_onboarding_does_not_claim_completion(monkeypatch) -> None:
    events: list[tuple[str, object]] = []
    session = _ready_onboarding_session()
    monkeypatch.setattr(onboarding_server, "load_session", lambda: session)
    monkeypatch.setattr(onboarding_server, "_calendar_addressed", lambda _session: True)

    def fail_finalization(_session):
        raise RuntimeError("provisioning failed")

    monkeypatch.setattr(onboarding_server, "_finalize_through_provisioner", fail_finalization)
    monkeypatch.setattr(
        onboarding_server,
        "_fire_analytics_event",
        lambda event_name, properties=None: events.append((event_name, properties)),
        raising=False,
    )

    payload = _decode_tool_result(asyncio.run(onboarding_server.handle_call_tool("finalize_onboarding", {})))

    assert payload["success"] is False
    assert events == []


def test_person_page_event_follows_a_real_created_page(monkeypatch) -> None:
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(
        work_server,
        "create_person_data",
        lambda **_kwargs: {
            "success": True,
            "path": "05-Areas/People/External/Example.md",
            "location": "external",
            "created": True,
        },
    )
    monkeypatch.setattr(
        work_server,
        "_fire_analytics_event",
        lambda event_name, properties=None: events.append((event_name, properties)),
    )

    payload = _decode_tool_result(asyncio.run(work_server.handle_call_tool("create_person", {"name": "Example"})))

    assert payload["success"] is True
    assert events == [("person_page_created", None)]


def test_person_page_creation_surfaces_a_safe_receipt_write_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        work_server,
        "create_person_data",
        lambda **_kwargs: {
            "success": True,
            "path": "05-Areas/People/External/Example.md",
            "location": "external",
            "created": True,
        },
    )
    monkeypatch.setattr(
        work_server,
        "_fire_analytics_event",
        lambda *_args, **_kwargs: {
            "fired": False,
            "reason": "analytics_disabled",
            "receipt_written": False,
            "receipt_reason": "receipt_write_failed",
        },
    )

    payload = _decode_tool_result(asyncio.run(work_server.handle_call_tool("create_person", {"name": "Example"})))

    assert payload["success"] is True
    assert payload["analytics_receipt"] == {
        "written": False,
        "reason": "receipt_write_failed",
    }
    assert "analytics_disabled" not in json.dumps(payload, sort_keys=True)


def test_failed_person_creation_does_not_claim_a_page(monkeypatch) -> None:
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(
        work_server,
        "create_person_data",
        lambda **_kwargs: {"success": False, "error": "already exists"},
    )
    monkeypatch.setattr(
        work_server,
        "_fire_analytics_event",
        lambda event_name, properties=None: events.append((event_name, properties)),
    )

    payload = _decode_tool_result(asyncio.run(work_server.handle_call_tool("create_person", {"name": "Example"})))

    assert payload["success"] is False
    assert events == []


def test_meeting_skill_uses_the_declared_singular_event_name() -> None:
    for skill_path in (MEETING_SKILL, AGENT_MEETING_SKILL):
        skill = skill_path.read_text(encoding="utf-8")

        assert "event_name `meeting_processed`" in skill
        assert "meetings_processed" not in skill


def test_onboarding_never_treats_a_default_as_analytics_consent() -> None:
    flow = ONBOARDING_FLOW.read_text(encoding="utf-8")

    assert "### Analytics Notice (Inform, Don't Ask):" in flow
    assert "Consent decision: opted-in" in flow
    assert "enabled: true" in flow
    assert "analytics_consent_given" not in flow


def test_no_tracked_source_declares_the_retired_consent_event() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    offenders = []
    for relative in tracked:
        path = Path(relative)
        if "tests" in path.parts:
            continue
        source = REPO_ROOT / path
        if "analytics_consent_given" in source.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(relative)

    assert offenders == []
    assert not hasattr(analytics_helper.Events, "ANALYTICS_CONSENT_GIVEN")


def test_every_named_shipped_skill_event_is_explicitly_allowlisted() -> None:
    # The reference checklist deliberately contains placeholders; only shipped
    # skill instructions name events that the MCP may accept at runtime.
    documented: set[str] = set()
    for skill_root in (
        REPO_ROOT / ".claude" / "skills",
        REPO_ROOT / ".agents" / "skills",
    ):
        for skill in skill_root.rglob("*.md"):
            text = skill.read_text(encoding="utf-8")
            for marker in ("event_name `", "fire_event('"):
                for fragment in text.split(marker)[1:]:
                    event_name = fragment.split("`", 1)[0].split("'", 1)[0]
                    if event_name:
                        documented.add(event_name)

    assert documented <= SAFE_ANALYTICS_EVENT_NAMES


def test_track_event_tool_advertises_only_an_allowlisted_example() -> None:
    tools = asyncio.run(analytics_server.list_tools())
    track_event = next(tool for tool in tools if tool.name == "track_event")
    event_description = track_event.inputSchema["properties"]["event_name"]["description"]

    assert "task_completed" in event_description
    assert "skill_invoked" not in event_description
