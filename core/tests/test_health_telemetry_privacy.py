"""Hard privacy acceptance tests for anonymous fleet-health verdicts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.mcp import analytics_helper
from core.utils import health_telemetry

EXPECTED_FIELDS = {
    "schema_version",
    "event",
    "counts",
    "worst_journey_id",
    "dex_version",
    "channel",
    "telemetry_id",
}


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "package.json").write_text('{"version":"1.56.0"}\n', encoding="utf-8")
    return repo


def _report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "summary": {"ok": 2, "broken": 1, "unknown": 1, "off": 1},
        "journeys": [
            {
                "id": "task_lifecycle",
                "verdict": "BROKEN",
                "detail": "/vault/03-Tasks/Secret Client.md failed",
                "duration_ms": 1,
            },
            {
                "id": "mcp_startup",
                "verdict": "UNKNOWN",
                "detail": "private integration name",
                "duration_ms": 1,
            },
        ],
    }


def _write_usage(vault: Path, content: str | None) -> None:
    system = vault / "System"
    system.mkdir(parents=True)
    if content is not None:
        (system / "usage_log.md").write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    "usage_content",
    [
        "**Health telemetry:** opted-out\n",
        "**Health telemetry:** pending\n",
        None,
    ],
    ids=["opted-out", "pending", "missing"],
)
def test_without_explicit_opt_in_post_is_never_called_but_attempt_is_logged(
    tmp_path: Path,
    usage_content: str | None,
) -> None:
    vault = tmp_path / "vault"
    _write_usage(vault, usage_content)
    post_calls = 0

    def forbidden_post(*_args, **_kwargs):
        nonlocal post_calls
        post_calls += 1
        pytest.fail("POST must not be called without explicit health-telemetry opt-in")

    result = health_telemetry.send_smoke_verdict(
        _report(),
        vault_root=vault,
        repo_root=_repo(tmp_path),
        transport_getter=lambda: pytest.fail("transport must not be resolved without opt-in"),
        post=forbidden_post,
    )

    assert post_calls == 0
    assert result == {"sent": False, "reason": "health_telemetry_not_opted_in"}
    record = json.loads((vault / "System/.dex/health-telemetry-log.jsonl").read_text())
    assert record["sent"] is False
    assert record["payload"]["telemetry_id"] is None
    assert not (vault / "System/.dex/telemetry-id").exists()


@pytest.mark.parametrize(
    "malformed",
    [
        "**Health telemetry:** yes\n",
        "**Health telemetry:** OPTED-IN\n",
        "**Health telemetry:** opted-in trailing-text\n",
        "**Health telemetry:** opted-in\n**Health telemetry:** opted-out\n",
        b"\xff\xfe",
    ],
)
def test_malformed_usage_log_fails_closed_and_never_posts(tmp_path: Path, malformed: str | bytes) -> None:
    vault = tmp_path / "vault"
    _write_usage(vault, "")
    usage_log = vault / "System/usage_log.md"
    if isinstance(malformed, bytes):
        usage_log.write_bytes(malformed)
    else:
        usage_log.write_text(malformed, encoding="utf-8")

    result = health_telemetry.send_smoke_verdict(
        _report(),
        vault_root=vault,
        repo_root=_repo(tmp_path),
        transport_getter=lambda: pytest.fail("malformed consent must fail closed before transport"),
        post=lambda *_args, **_kwargs: pytest.fail("malformed consent must never POST"),
    )

    assert result["sent"] is False
    assert health_telemetry.read_health_consent(vault) == "pending"
    assert (vault / "System/.dex/health-telemetry-log.jsonl").is_file()


def test_opted_in_wire_dict_is_exactly_counts_only_and_uses_separate_stable_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    _write_usage(vault, "**Health telemetry:** opted-in\n")
    (vault / "System/user-profile.yaml").write_text(
        "analytics:\n  visitor_id: analytics-visitor-123\n  account_id: analytics-account-456\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))
    posted: list[dict[str, object]] = []

    class Response:
        status_code = 200

    def capture_post(_endpoint, *, json, headers, timeout):
        posted.append(json)
        return Response()

    kwargs = {
        "vault_root": vault,
        "repo_root": _repo(tmp_path),
        "transport_getter": lambda: {
            "configured": True,
            "endpoint": "https://telemetry.invalid/verdict",
            "headers": {"Content-Type": "application/json"},
        },
        "post": capture_post,
    }
    health_telemetry.send_smoke_verdict(_report(), **kwargs)
    health_telemetry.send_smoke_verdict(_report(), **kwargs)

    assert len(posted) == 2
    payload = posted[0]
    assert set(payload) == EXPECTED_FIELDS
    assert payload == {
        "schema_version": 1,
        "event": "smoke_verdict",
        "counts": {"ok": 2, "broken": 1, "unknown": 1, "off": 1},
        "worst_journey_id": "task_lifecycle",
        "dex_version": "1.56.0",
        "channel": "stable",
        "telemetry_id": payload["telemetry_id"],
    }
    assert posted[1]["telemetry_id"] == payload["telemetry_id"]
    visitor = analytics_helper.get_visitor_info()
    assert payload["telemetry_id"] != visitor["visitor_id"]
    assert payload["telemetry_id"] != visitor["account_id"]

    encoded = json.dumps(payload)
    for forbidden in (
        "role",
        "company_size",
        "journey_stage",
        "visitorId",
        "accountId",
        "analytics-visitor-123",
        "analytics-account-456",
        "Secret Client.md",
        "/vault/03-Tasks",
        "private integration name",
    ):
        assert forbidden not in encoded


def test_dedicated_sender_never_references_analytics_event_enrichment() -> None:
    source = Path(health_telemetry.__file__).read_text(encoding="utf-8")

    assert "fire_event" not in source
    assert "calculate_journey_metadata" not in source
    assert "get_visitor_info" not in source
