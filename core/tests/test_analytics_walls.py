"""WO-057 walls: planted canaries must never leave the public download path."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from core.analytics_events import CAREER_GRADE_EVENT_NAMES
from core.analytics_walls import (
    ANALYTICS_ACCOUNT_SCOPE,
    ANALYTICS_INSTALL_ID_RELATIVE,
    WALL_CAREER,
    WALL_CONTENT,
    WALL_IDENTITY,
    WALL_USAGE_PATTERN,
)
from core.mcp import analytics_helper
from core.lifecycle import service as lifecycle_service

# Planted canaries — each wall test asserts these strings never appear on the wire.
CANARY_VAULT_TEXT = "WO057-CANARY-VAULT-TEXT the Q3 pipeline is slipping"
CANARY_FILENAME = "WO057-CANARY-FILE Secret_Client.md"
CANARY_PATH = "05-Areas/Career/WO057-CANARY-PATH.md"
CANARY_ASK = "WO057-CANARY-ASK why did my promotion stall"
CANARY_TRANSCRIPT = "WO057-CANARY-TRANSCRIPT she said I am not ready"
CANARY_USAGE = "WO057-CANARY-USAGE career coaching completed"
CANARY_NAME = "Ada Lovelace"
CANARY_EMAIL = "ada@example.com"
CANARY_RECORD_KEY = "record_key_wo057_canary"
CANARY_LEDGER_ID = "12345678-1234-4678-9234-567812345678"

FEEDBACK_SKILL = Path(__file__).resolve().parents[2] / ".claude/skills/feedback/SKILL.md"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    return vault


def _write_profile(vault: Path, body: str) -> None:
    (vault / "System" / "user-profile.yaml").write_text(body, encoding="utf-8")


def _write_usage(vault: Path, body: str) -> None:
    (vault / "System" / "usage_log.md").write_text(body, encoding="utf-8")


def _capture_posts(monkeypatch) -> list[dict[str, object]]:
    posted: list[dict[str, object]] = []

    def post(_url, *, json, **_kwargs):
        posted.append(json)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(analytics_helper, "HAS_REQUESTS", True)
    monkeypatch.setattr(
        analytics_helper,
        "get_analytics_transport",
        lambda: {
            "configured": True,
            "mode": "proxy",
            "endpoint": "https://private.example.test/track",
            "headers": {"Authorization": "Bearer never-store-this"},
        },
    )
    monkeypatch.setattr(analytics_helper, "requests", SimpleNamespace(post=post), raising=False)
    return posted


def _assert_canaries_absent(*blobs: object) -> None:
    serialized = json.dumps(blobs, sort_keys=True, default=str)
    for canary in (
        CANARY_VAULT_TEXT,
        CANARY_FILENAME,
        CANARY_PATH,
        CANARY_ASK,
        CANARY_TRANSCRIPT,
        CANARY_USAGE,
        CANARY_NAME,
        CANARY_EMAIL,
        CANARY_RECORD_KEY,
        CANARY_LEDGER_ID,
        "never-store-this",
        "Secret_Client",
    ):
        assert canary not in serialized


def test_settings_off_switch_is_zero_egress(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    _write_profile(vault, "analytics:\n  enabled: false\n")
    _write_usage(vault, "**Consent decision:** opted-in\n")
    posted = _capture_posts(monkeypatch)

    result = analytics_helper.fire_event(
        "task_created",
        {"count": 1, "notes": CANARY_VAULT_TEXT},
    )

    assert analytics_helper.is_analytics_enabled() is False
    assert result["fired"] is False
    assert result["reason"] == "analytics_disabled"
    assert posted == []
    _assert_canaries_absent(result)


def test_usage_log_opted_out_is_also_zero_egress(tmp_path: Path, monkeypatch) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    _write_profile(vault, "analytics:\n  enabled: true\n")
    _write_usage(vault, "**Consent decision:** opted-out\n")
    posted = _capture_posts(monkeypatch)

    result = analytics_helper.fire_event("task_created")

    assert analytics_helper.is_analytics_enabled() is False
    assert result["fired"] is False
    assert result["reason"] == "analytics_disabled"
    assert posted == []


def test_default_on_when_settings_and_consent_are_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posted = _capture_posts(monkeypatch)

    assert analytics_helper.is_analytics_enabled() is True
    result = analytics_helper.fire_event("task_created")

    assert result["fired"] is True
    assert len(posted) == 1
    payload = posted[0]
    uuid.UUID(payload["visitorId"])
    assert payload["accountId"] == ANALYTICS_ACCOUNT_SCOPE
    assert payload["event"] == "task_created"
    assert "journey_stage" not in payload["properties"]
    assert "role" not in payload["properties"]
    assert (vault / ANALYTICS_INSTALL_ID_RELATIVE).is_file()


def test_wall_no_content_planted_canaries_never_leave(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posted = _capture_posts(monkeypatch)
    plants = (
        {"notes": CANARY_VAULT_TEXT},
        {"filename": CANARY_FILENAME},
        {"path": CANARY_PATH},
        {"ask": CANARY_ASK},
        {"transcript": CANARY_TRANSCRIPT},
        {"conversation": CANARY_ASK},
    )

    for properties in plants:
        result = analytics_helper.fire_event("task_created", properties)
        assert result["fired"] is False
        assert result["reason"] == WALL_CONTENT
        _assert_canaries_absent(result)

    assert posted == []


def test_wall_no_guide_coach_usage_log_planted_canary_never_leaves(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    _write_usage(
        vault,
        "- [x] Career coaching (`/career-coach`)\n"
        f"- [x] {CANARY_USAGE}\n"
        "**Setup date:** 2026-01-01\n",
    )
    posted = _capture_posts(monkeypatch)

    result = analytics_helper.fire_event(
        "task_created",
        {
            "journey_stage": "power_user",
            "feature_adoption_score": 55,
            "most_active_area": "career",
            "days_since_setup": 400,
        },
    )

    assert result["fired"] is False
    assert result["reason"] == WALL_USAGE_PATTERN
    assert posted == []
    _assert_canaries_absent(result)

    safe = analytics_helper.fire_event("task_created")
    assert safe["fired"] is True
    assert len(posted) == 1
    serialized = json.dumps(posted[0], sort_keys=True)
    for forbidden in (
        "journey_stage",
        "feature_adoption_score",
        "most_active_area",
        "days_since_setup",
        CANARY_USAGE,
        "career coaching",
        "power_user",
    ):
        assert forbidden not in serialized


def test_wall_no_identity_beyond_install_scoped_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    _write_profile(
        vault,
        "name: Ada Lovelace\n"
        f"email_domain: example.com\n"
        f"work_email: {CANARY_EMAIL}\n"
        "analytics:\n"
        "  enabled: true\n"
        "  visitor_id: analytics-visitor-from-profile\n"
        "  account_id: analytics-account-from-profile\n",
    )
    (vault / "System" / ".dex" / "ledger").mkdir(parents=True)
    (vault / "System" / ".dex" / "telemetry-id").write_text(
        CANARY_LEDGER_ID + "\n",
        encoding="utf-8",
    )
    posted = _capture_posts(monkeypatch)

    blocked = analytics_helper.fire_event(
        "task_created",
        {
            "visitor_id": CANARY_NAME,
            "record_key": CANARY_RECORD_KEY,
            "install_id": CANARY_LEDGER_ID,
            "email": CANARY_EMAIL,
        },
    )
    assert blocked["fired"] is False
    assert blocked["reason"] == WALL_IDENTITY
    assert posted == []

    sent = analytics_helper.fire_event("task_created")
    assert sent["fired"] is True
    payload = posted[0]
    visitor = uuid.UUID(payload["visitorId"])
    assert str(visitor) != CANARY_LEDGER_ID
    assert payload["accountId"] == ANALYTICS_ACCOUNT_SCOPE
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        CANARY_NAME,
        CANARY_EMAIL,
        CANARY_RECORD_KEY,
        CANARY_LEDGER_ID,
        "analytics-visitor-from-profile",
        "analytics-account-from-profile",
        "example.com",
        "Ada",
    ):
        assert forbidden not in serialized
    assert analytics_helper.get_visitor_info()["visitor_id"] == str(visitor)
    assert analytics_helper.get_visitor_info()["account_id"] == ANALYTICS_ACCOUNT_SCOPE


def test_wall_career_grade_surfaces_emit_nothing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = _vault(tmp_path)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posted = _capture_posts(monkeypatch)

    for event_name in sorted(CAREER_GRADE_EVENT_NAMES):
        result = analytics_helper.fire_event(
            event_name,
            {"path": CANARY_PATH, "output": CANARY_ASK},
        )
        assert result["fired"] is False
        assert result["reason"] == WALL_CAREER
        _assert_canaries_absent(result)

    assert posted == []
    assert not (vault / ANALYTICS_INSTALL_ID_RELATIVE).exists()


def test_disclosure_stays_founder_yes_and_is_not_invented_in_core() -> None:
    """Founder-yes disclosure is not invented here as shipped onboarding copy."""
    core_sources = (
        REPO_ROOT / "core/analytics_walls.py",
        REPO_ROOT / "core/mcp/analytics_helper.py",
        REPO_ROOT / "core/mcp/analytics_server.py",
        REPO_ROOT / "core/analytics_events.py",
    )
    invented = (
        "One last thing: Dex collects anonymous feature usage data",
        "Say: \"One last thing",
        "[founder-yes]",
    )
    for path in core_sources:
        text = path.read_text(encoding="utf-8")
        for fragment in invented:
            assert fragment not in text, path.name


def test_bug_reports_still_wait_for_an_explicit_yes() -> None:
    skill = FEEDBACK_SKILL.read_text(encoding="utf-8")
    assert "always-review" in skill
    assert "wait for a clear yes" in skill
    assert "The first report is always reviewed" in skill
    assert "fire_event" not in skill
    assert "track_event" not in skill


def test_receipt_reasons_include_the_four_walls() -> None:
    reasons = lifecycle_service._ANALYTICS_RECEIPT_REASONS
    assert WALL_CONTENT in reasons
    assert WALL_USAGE_PATTERN in reasons
    assert WALL_IDENTITY in reasons
    assert WALL_CAREER in reasons
