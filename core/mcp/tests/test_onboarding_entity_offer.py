"""Stage 4b onboarding entity-page offer tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from core.mcp import onboarding_server
from core.utils.entity_pages import render_person_page

REPO_ROOT = Path(__file__).resolve().parents[3]


def _meeting(
    meeting_id: str,
    date: str,
    *,
    transcript: bool = False,
    attendees: list[dict] | None = None,
) -> dict:
    return {
        "id": meeting_id,
        "createdAt": f"{date}T10:00:00Z",
        "hasTranscript": transcript,
        "filteredAttendees": attendees
        or [
            {
                "name": "Jane Doe",
                "email": "jane@acme.com",
                "location": "external",
            }
        ],
    }


def _profile(*, companies: bool = False, mode: str = "suggest") -> dict:
    return {
        "name": "Test User",
        "work_email": "owner@example.com",
        "email_domain": "example.com",
        "entity_creation": {"mode": mode},
        "capabilities": {"companies": {"enabled": companies}},
    }


def _configure_vault(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    companies: bool = False,
    finalized: bool = True,
) -> None:
    system = vault / "System"
    system.mkdir(parents=True)
    (system / "user-profile.yaml").write_text(
        yaml.safe_dump(_profile(companies=companies), sort_keys=False),
        encoding="utf-8",
    )
    marker = system / ".onboarding-complete"
    if finalized:
        marker.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(onboarding_server, "BASE_DIR", vault)
    monkeypatch.setattr(onboarding_server, "MARKER_FILE", marker)


def _prepare(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    meetings: list[dict],
    *,
    companies: bool = False,
) -> dict:
    _configure_vault(vault, monkeypatch, companies=companies)
    monkeypatch.setattr(
        onboarding_server,
        "_collect_entity_offer_meetings",
        lambda: meetings,
    )
    return onboarding_server.prepare_entity_page_offer()


def _suggestions(vault: Path) -> list[dict]:
    store = json.loads(
        (vault / "System/.dex/entity-suggestions.json").read_text(encoding="utf-8")
    )
    return store["suggestions"]


def test_entity_offer_tools_are_registered() -> None:
    tools = {
        tool.name: tool
        for tool in __import__("asyncio").run(onboarding_server.handle_list_tools())
    }

    assert "prepare_entity_page_offer" in tools
    assert "respond_to_entity_page_offer" in tools
    assert "set_entity_creation_default" in tools
    assert tools["respond_to_entity_page_offer"].inputSchema["properties"]["action"][
        "enum"
    ] == ["yes", "no", "never"]


def test_offer_is_refused_until_finalize_onboarding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_vault(tmp_path, monkeypatch, finalized=False)
    monkeypatch.setattr(onboarding_server, "_collect_entity_offer_meetings", lambda: [])

    with pytest.raises(RuntimeError, match="finalize_onboarding"):
        onboarding_server.prepare_entity_page_offer()


@pytest.mark.parametrize(
    ("meetings", "expected_reason"),
    [
        ([_meeting("one-off", "2026-07-20")], None),
        (
            [
                _meeting("same-week-1", "2026-07-20"),
                _meeting("same-week-2", "2026-07-21"),
            ],
            None,
        ),
        (
            [
                _meeting("two-weeks-1", "2026-07-13"),
                _meeting("two-weeks-2", "2026-07-20"),
            ],
            "Seen in 2 meetings across 2 weeks",
        ),
        (
            [
                _meeting("transcript-1", "2026-07-20", transcript=True),
                _meeting("transcript-2", "2026-07-21"),
            ],
            "Seen in 2 meetings across 1 week",
        ),
    ],
)
def test_offer_honours_the_entity_engine_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    meetings: list[dict],
    expected_reason: str | None,
) -> None:
    result = _prepare(tmp_path, monkeypatch, meetings)

    people = [
        suggestion
        for suggestion in result["suggestions"]
        if suggestion["kind"] == "person"
    ]
    if expected_reason is None:
        assert people == []
        assert result["offered"] is False
    else:
        assert people[0]["reason"] == expected_reason
        assert result["offered"] is True


def test_internal_only_meetings_do_not_qualify_anyone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    internal = [
        {
            "name": "John Doe",
            "email": "john@example.com",
            "location": "internal",
        }
    ]

    result = _prepare(
        tmp_path,
        monkeypatch,
        [
            _meeting("internal-1", "2026-07-13", attendees=internal),
            _meeting("internal-2", "2026-07-20", attendees=internal),
        ],
    )

    assert result == {
        "available": True,
        "offered": False,
        "suggestions": [],
    }


@pytest.mark.parametrize(
    ("action", "expected_status", "page_exists"),
    [
        ("yes", "accepted", True),
        ("no", "dismissed", False),
        ("never", "suppressed", False),
    ],
)
def test_yes_no_never_use_the_existing_suggestion_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    expected_status: str,
    page_exists: bool,
) -> None:
    prepared = _prepare(
        tmp_path,
        monkeypatch,
        [
            _meeting("offer-1", "2026-07-13"),
            _meeting("offer-2", "2026-07-20"),
        ],
    )
    suggestion_id = prepared["suggestions"][0]["id"]

    result = onboarding_server.respond_to_entity_page_offer(
        action,
        [suggestion_id],
    )

    assert result["action"] == action
    assert result["results"][0]["status"] == expected_status
    assert _suggestions(tmp_path)[0]["status"] == expected_status
    assert (
        tmp_path / "05-Areas/People/External/Jane_Doe.md"
    ).exists() is page_exists


def test_yes_treats_an_existing_identity_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = _prepare(
        tmp_path,
        monkeypatch,
        [
            _meeting("existing-1", "2026-07-13"),
            _meeting("existing-2", "2026-07-20"),
        ],
    )
    existing_page = tmp_path / "05-Areas/People/External/Renamed_Jane.md"
    existing_page.parent.mkdir(parents=True)
    existing_page.write_text(
        render_person_page(
            "Renamed Jane",
            emails=["jane@acme.com"],
            location="external",
        ),
        encoding="utf-8",
    )

    result = onboarding_server.respond_to_entity_page_offer(
        "yes",
        [prepared["suggestions"][0]["id"]],
    )

    accepted = result["results"][0]
    assert accepted["status"] == "accepted"
    assert accepted["created"] is False
    assert accepted["existing"] is True
    assert list((tmp_path / "05-Areas/People").rglob("*.md")) == [existing_page]


def test_company_suggestions_respect_the_room_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attendees = [
        {
            "name": "Jane Doe",
            "email": "jane@acme.com",
            "location": "external",
        },
        {
            "name": "John Doe",
            "email": "john@acme.com",
            "location": "external",
        },
    ]
    meetings = [
        _meeting("company-1", "2026-07-13", attendees=attendees),
        _meeting("company-2", "2026-07-20", attendees=attendees),
    ]

    off = _prepare(tmp_path / "off", monkeypatch, meetings, companies=False)
    on = _prepare(tmp_path / "on", monkeypatch, meetings, companies=True)

    assert all(item["kind"] == "person" for item in off["suggestions"])
    company = next(item for item in on["suggestions"] if item["kind"] == "company")
    assert company["domains"] == ["acme.com"]
    assert company["reason"] == "2 contacts across 2 meetings"
    assert not (tmp_path / "off/05-Areas/Companies").exists()


def test_single_contact_company_reason_is_plain_english(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _prepare(
        tmp_path,
        monkeypatch,
        [
            _meeting("company-single-1", "2026-07-13"),
            _meeting("company-single-2", "2026-07-20"),
        ],
        companies=True,
    )

    company = next(item for item in result["suggestions"] if item["kind"] == "company")
    assert company["reason"] == "1 contact across 2 meetings"


def test_default_answer_is_written_explicitly_through_the_lifecycle_door(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_vault(tmp_path, monkeypatch)
    profile_path = tmp_path / "System/user-profile.yaml"

    no = onboarding_server.set_entity_creation_default(automatic=False)
    after_no = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    yes = onboarding_server.set_entity_creation_default(automatic=True)
    after_yes = yaml.safe_load(profile_path.read_text(encoding="utf-8"))

    assert no["mode"] == "suggest"
    assert after_no["entity_creation"] == {"mode": "suggest"}
    assert yes["mode"] == "auto"
    assert yes["lifecycle_receipt"]["purpose"] == "entity-creation-mode"
    assert after_yes["entity_creation"] == {"mode": "auto"}


def test_background_engine_adopts_an_onboarding_page_without_a_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    meetings = [
        _meeting("adopt-1", "2026-07-13"),
        _meeting("adopt-2", "2026-07-20"),
    ]
    prepared = _prepare(tmp_path, monkeypatch, meetings)
    onboarding_server.respond_to_entity_page_offer(
        "yes",
        [prepared["suggestions"][0]["id"]],
    )

    contacts_path = tmp_path / "System/.dex/contacts.json"
    contacts = json.loads(contacts_path.read_text(encoding="utf-8"))
    contact = next(iter(contacts["contacts"].values()))
    contact["state"] = "active"
    contact["page_path"] = None
    contacts_path.write_text(json.dumps(contacts), encoding="utf-8")

    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the entity adoption check")
    source = """
const path = require('node:path');
const { processEntityCreation } = require(
  path.join(process.env.DEX_REPO_ROOT, '.scripts/meeting-intel/lib/entity-creation.cjs')
);
const meetings = JSON.parse(process.env.DEX_TEST_MEETINGS);
const profile = JSON.parse(process.env.DEX_TEST_PROFILE);
console.log(JSON.stringify(processEntityCreation(meetings, profile)));
"""
    completed = subprocess.run(
        [node, "-e", source],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "VAULT_PATH": str(tmp_path),
            "CLAUDE_PROJECT_DIR": str(tmp_path),
            "DEX_REPO_ROOT": str(REPO_ROOT),
            "DEX_PYTHON": sys.executable,
            "DEX_TEST_MEETINGS": json.dumps(meetings),
            "DEX_TEST_PROFILE": json.dumps(_profile(mode="auto")),
        },
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    background = json.loads(completed.stdout)
    person_pages = list((tmp_path / "05-Areas/People").rglob("*.md"))

    assert len(background["created"]) == 1
    assert background["created"][0]["adopted"] is True
    assert background["created"][0]["created"] is False
    assert len(person_pages) == 1
